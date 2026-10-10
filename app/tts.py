import queue
import threading

from app.config import config
from app.status import hub


class Speaker:
    def __init__(self) -> None:
        self._queue: queue.Queue = queue.Queue()
        self.available = False
        self.last_error = ""
        self.ready = threading.Event()
        self._thread = threading.Thread(target=self._run, name="tts", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        engine = None
        try:
            import pyttsx3

            engine = pyttsx3.init()
            engine.setProperty("rate", int(config().get("tts_rate", 175)))
            self.available = True
        except Exception as exc:
            self.last_error = str(exc)
            self.available = False
        self.ready.set()
        while True:
            item = self._queue.get()
            if item is None:
                break
            text, done = item
            try:
                if engine is None:
                    import pyttsx3

                    engine = pyttsx3.init()
                    engine.setProperty("rate", int(config().get("tts_rate", 175)))
                    self.available = True
                engine.say(text)
                engine.runAndWait()
            except Exception as exc:
                self.available = False
                self.last_error = str(exc)
                engine = None
                hub.note(f"Speech output failed: {exc}", "error")
            finally:
                done.set()

    def say(self, text: str) -> threading.Event:
        done = threading.Event()
        cleaned = " ".join(text.split())
        if not cleaned:
            done.set()
            return done
        self._queue.put((cleaned[:800], done))
        return done

    def close(self) -> None:
        self._queue.put(None)
