import asyncio
from collections import deque
from datetime import datetime, timezone


class Hub:
    def __init__(self) -> None:
        self.state = "idle"
        self.detail = ""
        self.last_transcript = ""
        self.last_reply = ""
        self.log: deque[dict] = deque(maxlen=200)
        self.pending: list[dict] = []
        self.monitors: list[dict] = []
        self.capabilities: dict = {}
        self._subscribers: set[asyncio.Queue] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def set_capabilities(self, caps: dict) -> None:
        self.capabilities = caps
        self.emit({"type": "capabilities", "capabilities": caps})

    def set_state(self, state: str, detail: str = "") -> None:
        self.state = state
        self.detail = detail
        self.emit({"type": "state", "state": state, "detail": detail})

    def note(self, message: str, level: str = "info") -> None:
        entry = {
            "time": datetime.now(timezone.utc).astimezone().strftime("%H:%M:%S"),
            "level": level,
            "message": message[:500],
        }
        self.log.append(entry)
        self.emit({"type": "log", "entry": entry})

    def set_exchange(self, transcript: str | None = None, reply: str | None = None) -> None:
        if transcript is not None:
            self.last_transcript = transcript
        if reply is not None:
            self.last_reply = reply
        self.emit(
            {
                "type": "exchange",
                "transcript": self.last_transcript,
                "reply": self.last_reply,
            }
        )

    def set_pending(self, pending: list[dict]) -> None:
        self.pending = pending
        self.emit({"type": "pending", "pending": pending})

    def set_monitors(self, monitors: list[dict]) -> None:
        self.monitors = monitors
        self.emit({"type": "monitors", "monitors": monitors})

    def snapshot(self) -> dict:
        return {
            "type": "snapshot",
            "state": self.state,
            "detail": self.detail,
            "log": list(self.log),
            "pending": self.pending,
            "monitors": self.monitors,
            "transcript": self.last_transcript,
            "reply": self.last_reply,
            "capabilities": self.capabilities,
        }

    def emit(self, event: dict) -> None:
        loop = self._loop
        if loop is None or not loop.is_running():
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            self._fanout(event)
        else:
            loop.call_soon_threadsafe(self._fanout, event)

    def _fanout(self, event: dict) -> None:
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)


hub = Hub()
