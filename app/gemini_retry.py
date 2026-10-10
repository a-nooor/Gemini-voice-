import asyncio

from app.config import AUTO_MODELS, config, gemini_key
from app.status import hub

REQUEST_TIMEOUT = 22


def make_client():
    from google import genai
    from google.genai import types

    return genai.Client(
        api_key=gemini_key(),
        http_options=types.HttpOptions(timeout=25000),
    )


def _thinking_rejected(exc: Exception) -> bool:
    text = str(exc).lower()
    return "thinking" in text and getattr(exc, "code", 400) in (400, 404)


def _retryable(exc: Exception) -> bool:
    if isinstance(exc, asyncio.TimeoutError):
        return True
    code = getattr(exc, "code", None)
    if code in (429, 500, 503):
        return True
    text = str(exc).lower()
    return "unavailable" in text or "resource_exhausted" in text or "timed out" in text or "timeout" in text


def chosen_models() -> list[str]:
    selected = config().get("gemini_model", "auto")
    if selected == "auto":
        return list(AUTO_MODELS)
    if selected in AUTO_MODELS:
        return [selected]
    return list(AUTO_MODELS)


async def generate(client, *, contents, gen_config=None):
    models = chosen_models()
    several = len(models) > 1
    last: Exception | None = None
    for model in models:
        tries = 1 if several else 2
        for attempt in range(tries):
            try:
                hub.note(f"Asking {model}")
                kwargs = {"model": model, "contents": contents}
                if gen_config is not None:
                    kwargs["config"] = gen_config
                return await asyncio.wait_for(
                    client.aio.models.generate_content(**kwargs),
                    timeout=REQUEST_TIMEOUT,
                )
            except Exception as exc:
                last = exc
                if gen_config is not None and _thinking_rejected(exc):
                    hub.note(f"{model} rejected the thinking setting")
                    gen_config = None
                    try:
                        return await asyncio.wait_for(
                            client.aio.models.generate_content(model=model, contents=contents),
                            timeout=REQUEST_TIMEOUT,
                        )
                    except Exception as retry_exc:
                        last = retry_exc
                        exc = retry_exc
                if not _retryable(exc):
                    raise
                hub.note(f"{model} did not answer: {str(exc).splitlines()[0][:160]}")
                if attempt < tries - 1:
                    await asyncio.sleep(2)
    raise RuntimeError("Gemini did not answer. Try again, or pick another model.") from last
