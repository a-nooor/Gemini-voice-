import asyncio

from app.audio_io import Recorder
from app.gemini_agent import run_command
from app.status import hub
from app.stt import transcribe
from app.tts import Speaker


class Orchestrator:
    def __init__(self, recorder: Recorder, speaker: Speaker) -> None:
        self.recorder = recorder
        self.speaker = speaker
        self.lock = asyncio.Lock()
        self.listening = False

    async def begin_ptt(self) -> None:
        if self.listening or self.lock.locked():
            hub.note("Still working. Wait for the reply.")
            return
        if not self.recorder.start():
            hub.set_state("error", "microphone")
            hub.note(self.recorder.last_error or "No microphone", "error")
            return
        self.listening = True
        hub.set_state("listening", self.recorder.input_name or "Release to send")
        hub.note(f"Listening on {self.recorder.input_name}")

    async def end_ptt(self) -> None:
        if not self.listening:
            return
        self.listening = False
        if self.lock.locked():
            await asyncio.to_thread(self.recorder.cancel)
            return
        async with self.lock:
            hub.set_state("transcribing")
            wav = await asyncio.to_thread(self.recorder.stop)
            if wav is None:
                hub.set_state("idle")
                hub.note("Ignored a very short press")
                return
            hub.note(f"Mic {self.recorder.input_name} peak {self.recorder.last_peak}")
            if self.recorder.last_peak < 250:
                await self.speak_only("The microphone was silent.")
                return
            try:
                text = await transcribe(wav)
            except Exception as exc:
                hub.set_state("error", "speech")
                hub.note(str(exc), "error")
                await self.speak_only(str(exc))
                return
            await self.execute(text, "voice")

    async def command(self, text: str) -> None:
        if self.lock.locked() or self.listening:
            hub.note("Still working. Wait for the reply.")
            return
        async with self.lock:
            await self.execute(text, "text")

    async def execute(self, text: str, source: str) -> None:
        cleaned = " ".join((text or "").split())
        hub.set_exchange(transcript=cleaned, reply="")
        if not cleaned:
            await self.speak_only("I didn't catch any words.")
            return
        hub.note(f"{source}: {cleaned[:180]}")
        hub.set_state("thinking")
        try:
            reply = await run_command(cleaned)
        except Exception as exc:
            reply = f"Failed: {exc}"
            hub.note(reply, "error")
        await self.speak_only(reply)

    async def speak_only(self, reply: str) -> None:
        hub.set_exchange(reply=reply)
        hub.set_state("speaking")
        done = self.speaker.say(reply)
        await asyncio.to_thread(done.wait, 120)
        if hub.state == "speaking":
            hub.set_state("idle")
