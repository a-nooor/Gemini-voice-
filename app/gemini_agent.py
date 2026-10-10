from app.browser_mon import browse, refresh_monitors
from app.config import gemini_key
from app.gemini_retry import generate, make_client
from app.gmail_svc import create_draft, list_unread, read_message
from app.policy import PolicyError
from app.status import hub

SYSTEM = """You are the local automation agent on this Windows machine.
You read Gmail, create drafts, and check web pages when the user asks.
Rules:
- Never send mail. Creating a draft only queues it for dashboard approval.
- Drafts may go only to the configured allowlist. If asked to write anyone else, refuse.
- Do not invent inbox contents or page contents. If a tool fails, say so.
- Keep the spoken reply to a few sentences.
"""


async def run_command(text: str) -> str:
    if not gemini_key():
        return await _offline(text)
    from google.genai import types

    client = make_client()
    declarations = [
        _fn(
            "gmail_list_unread",
            "List recent unread Gmail messages.",
            {"max_results": {"type": "integer"}},
        ),
        _fn(
            "gmail_read",
            "Read one Gmail message by id.",
            {"message_id": {"type": "string"}},
            ["message_id"],
        ),
        _fn(
            "gmail_create_draft",
            "Create a Gmail draft. Does not send.",
            {
                "to": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
            },
            ["to", "subject", "body"],
        ),
        _fn(
            "browser_check",
            "Open an http or https URL and return status, title, and a short excerpt.",
            {"url": {"type": "string"}},
            ["url"],
        ),
        _fn("refresh_monitors", "Refresh the configured application monitors.", {}),
    ]
    tool = types.Tool(function_declarations=declarations)
    contents = [types.Content(role="user", parts=[types.Part.from_text(text=text)])]
    gen_config = types.GenerateContentConfig(
        system_instruction=SYSTEM,
        tools=[tool],
        temperature=0.2,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    for _round in range(4):
        response = await generate(client, contents=contents, gen_config=gen_config)
        calls = _function_calls(response)
        if not calls:
            return _response_text(response) or "I have nothing to add."
        content = response.candidates[0].content if response.candidates else None
        if content is None:
            return _response_text(response) or "Gemini returned no content."
        contents.append(content)
        parts = []
        for call in calls:
            result = await _dispatch(call.name, dict(call.args or {}))
            hub.note(f"Tool {call.name}")
            parts.append(types.Part.from_function_response(name=call.name, response=result))
        contents.append(types.Content(role="user", parts=parts))
        hub.set_state("thinking")
    return "Stopped after too many tool steps."


async def _offline(text: str) -> str:
    lowered = text.lower()
    if "monitor" in lowered or "status" in lowered:
        rows = await refresh_monitors()
        if not rows:
            return "No monitors configured. Gemini API key is also missing."
        bits = [f"{row['name']}: {row.get('status', 0)}" for row in rows]
        return "Gemini API key is missing. Monitors: " + "; ".join(bits)
    return "Gemini API key is missing. Add it under Service: Gemini in local-agent/.credentials.md and restart."


async def _dispatch(name: str, args: dict) -> dict:
    try:
        if name == "gmail_list_unread":
            hub.set_state("gmail", "list unread")
            return list_unread(int(args.get("max_results") or 5))
        if name == "gmail_read":
            hub.set_state("gmail", "read")
            return read_message(str(args.get("message_id", "")))
        if name == "gmail_create_draft":
            hub.set_state("gmail", "draft")
            return create_draft(str(args.get("to", "")), str(args.get("subject", "")), str(args.get("body", "")))
        if name == "browser_check":
            return await browse(str(args.get("url", "")))
        if name == "refresh_monitors":
            rows = await refresh_monitors()
            return {"monitors": rows}
        return {"error": f"Unknown tool {name}"}
    except PolicyError as exc:
        return {"error": str(exc)}
    except Exception as exc:
        hub.note(f"{name} failed: {exc}", "error")
        return {"error": str(exc)}


def _fn(name: str, description: str, properties: dict, required: list | None = None):
    from google.genai import types

    schema = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return types.FunctionDeclaration(
        name=name,
        description=description,
        parameters_json_schema=schema,
    )


def _function_calls(response):
    calls = []
    for candidate in response.candidates or []:
        content = getattr(candidate, "content", None)
        if not content:
            continue
        for part in content.parts or []:
            call = getattr(part, "function_call", None)
            if call and getattr(call, "name", None):
                calls.append(call)
    return calls


def _response_text(response) -> str:
    chunks = []
    for candidate in response.candidates or []:
        content = getattr(candidate, "content", None)
        if not content:
            continue
        for part in content.parts or []:
            text = getattr(part, "text", None)
            if text:
                chunks.append(text)
    return "\n".join(chunks).strip()
