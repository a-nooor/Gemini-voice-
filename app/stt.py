from pathlib import Path

from app.config import config, gemini_key
from app.gemini_retry import generate, make_client
from app.status import hub


async def transcribe(wav_path: Path) -> str:
    engine = config().get("stt_engine", "gemini")
    if engine == "whisper":
        return await _whisper(wav_path)
    return await _gemini(wav_path)


async def _gemini(wav_path: Path) -> str:
    key = gemini_key()
    if not key:
        raise RuntimeError("Gemini API key is missing. Add it under Service: Gemini in .credentials.md.")
    from google.genai import types

    client = make_client()
    audio = wav_path.read_bytes()
    hub.note("Transcribing with Gemini")
    response = await generate(
        client,
        contents=[
            types.Part.from_bytes(data=audio, mime_type="audio/wav"),
            "Transcribe the speech exactly. Return only the words spoken. If there is no speech, return an empty string.",
        ],
        gen_config=types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(thinking_level="MINIMAL"),
        ),
    )
    return _spoken_text(response)


def _spoken_text(response) -> str:
    try:
        text = (response.text or "").strip()
        if text:
            return text
    except Exception:
        pass
    chunks = []
    for candidate in response.candidates or []:
        content = getattr(candidate, "content", None)
        if not content:
            continue
        for part in content.parts or []:
            if getattr(part, "thought", False):
                continue
            text = getattr(part, "text", None)
            if text:
                chunks.append(text)
    return "\n".join(chunks).strip()


async def _whisper(wav_path: Path) -> str:
    def run() -> str:
        from faster_whisper import WhisperModel

        model = WhisperModel("tiny", device="cpu", compute_type="int8")
        segments, _info = model.transcribe(str(wav_path))
        return " ".join(segment.text.strip() for segment in segments).strip()

    import asyncio

    hub.note("Transcribing with local Whisper")
    try:
        return await asyncio.to_thread(run)
    except ImportError as exc:
        raise RuntimeError("faster-whisper is not installed. Use stt_engine gemini or install faster-whisper.") from exc
