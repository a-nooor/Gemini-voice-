import base64
from email.mime.text import MIMEText

from app.config import CLIENT_SECRET_PATH, GMAIL_TOKEN_PATH
from app.policy import PolicyError, no_copies, only_allowed_recipient
from app.status import hub

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.send",
]

_pending: dict[str, dict] = {}
_connect_lock_held = False


def secret_present() -> bool:
    return CLIENT_SECRET_PATH.exists()


def token_present() -> bool:
    return GMAIL_TOKEN_PATH.exists()


def _service():
    creds = _credentials()
    if creds is None:
        raise RuntimeError("Gmail is not connected. Put client_secret.json in secrets/ and use Connect Gmail.")
    from googleapiclient.discovery import build

    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _credentials():
    if not GMAIL_TOKEN_PATH.exists():
        return None
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    creds = Credentials.from_authorized_user_file(str(GMAIL_TOKEN_PATH), SCOPES)
    if creds.valid:
        return creds
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        GMAIL_TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
        return creds
    return None


def connect_blocking() -> str:
    global _connect_lock_held
    if _connect_lock_held:
        return "Gmail connect is already running."
    if not secret_present():
        return "Missing secrets/client_secret.json."
    _connect_lock_held = True
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow

        flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET_PATH), SCOPES)
        creds = flow.run_local_server(port=0, open_browser=True)
        GMAIL_TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
        hub.note("Gmail connected")
        return "Gmail connected."
    finally:
        _connect_lock_held = False


def pending_public() -> list[dict]:
    return list(_pending.values())


def list_unread(max_results: int = 5) -> dict:
    count = max(1, min(int(max_results or 5), 10))
    service = _service()
    listed = (
        service.users()
        .messages()
        .list(userId="me", q="is:unread", maxResults=count)
        .execute()
    )
    messages = []
    for item in listed.get("messages", []):
        full = (
            service.users()
            .messages()
            .get(userId="me", id=item["id"], format="metadata", metadataHeaders=["From", "Subject", "Date"])
            .execute()
        )
        headers = {h["name"].lower(): h["value"] for h in full.get("payload", {}).get("headers", [])}
        messages.append(
            {
                "id": item["id"],
                "from": headers.get("from", ""),
                "subject": headers.get("subject", ""),
                "date": headers.get("date", ""),
                "snippet": full.get("snippet", ""),
            }
        )
    hub.note(f"Gmail listed {len(messages)} unread")
    return {"messages": messages}


def read_message(message_id: str) -> dict:
    service = _service()
    full = service.users().messages().get(userId="me", id=message_id, format="full").execute()
    payload = full.get("payload", {})
    headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
    hub.note(f"Gmail read {headers.get('subject', message_id)[:80]}")
    return {
        "id": message_id,
        "from": headers.get("from", ""),
        "to": headers.get("to", ""),
        "subject": headers.get("subject", ""),
        "date": headers.get("date", ""),
        "body": _plain_body(payload)[:2000],
    }


def create_draft(to: str, subject: str, body: str) -> dict:
    address = only_allowed_recipient(to)
    no_copies("", "")
    if not subject.strip() or not body.strip():
        raise PolicyError("Subject and body are required.")
    mime = MIMEText(body, "plain", "utf-8")
    mime["To"] = address
    mime["Subject"] = subject.strip()
    raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()
    service = _service()
    draft = service.users().drafts().create(userId="me", body={"message": {"raw": raw}}).execute()
    draft_id = draft["id"]
    record = {
        "id": draft_id,
        "to": address,
        "subject": subject.strip(),
        "body": body[:500],
    }
    _pending[draft_id] = record
    hub.set_pending(pending_public())
    hub.note(f"Draft created for {address}: {subject.strip()[:80]}")
    return {"draft_id": draft_id, "to": address, "subject": subject.strip(), "needs_approval": True}


def approve_send(draft_id: str) -> dict:
    if draft_id not in _pending:
        raise PolicyError("That draft is not waiting for approval in this session.")
    service = _service()
    draft = service.users().drafts().get(userId="me", id=draft_id, format="full").execute()
    payload = draft.get("message", {}).get("payload", {})
    headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
    only_allowed_recipient(headers.get("to", ""))
    no_copies(headers.get("cc", ""), headers.get("bcc", ""))
    sent = service.users().drafts().send(userId="me", body={"id": draft_id}).execute()
    _pending.pop(draft_id, None)
    hub.set_pending(pending_public())
    hub.note(f"Sent draft {draft_id} to {headers.get('to', '')}")
    return {"sent": True, "id": sent.get("id", ""), "to": headers.get("to", "")}


def dismiss(draft_id: str) -> None:
    _pending.pop(draft_id, None)
    hub.set_pending(pending_public())
    hub.note(f"Dismissed draft {draft_id} from the dashboard. The Gmail draft was left in the mailbox.")


def _plain_body(payload: dict) -> str:
    mime = payload.get("mimeType", "")
    data = payload.get("body", {}).get("data")
    if mime == "text/plain" and data:
        return base64.urlsafe_b64decode(data.encode()).decode("utf-8", "replace")
    for part in payload.get("parts", []) or []:
        text = _plain_body(part)
        if text:
            return text
    return ""
