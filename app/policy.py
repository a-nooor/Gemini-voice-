from email.utils import parseaddr

from app.config import config


class PolicyError(Exception):
    pass


def allowlist() -> list[str]:
    return [item.strip().lower() for item in config().get("email_allowlist", []) if item.strip()]


def only_allowed_recipient(to_header: str) -> str:
    _name, address = parseaddr(to_header or "")
    address = address.strip().lower()
    if not address or "," in (to_header or "") or ";" in (to_header or ""):
        raise PolicyError("One recipient only.")
    allowed = allowlist()
    if address not in allowed:
        raise PolicyError(
            "Recipient is outside the allowlist. Drafts and sends stay limited to: "
            + ", ".join(allowed)
        )
    return address


def no_copies(cc: str, bcc: str) -> None:
    if (cc or "").strip() or (bcc or "").strip():
        raise PolicyError("Cc and Bcc are not allowed.")
