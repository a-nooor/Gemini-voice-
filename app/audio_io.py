import threading
import time
import wave
from pathlib import Path

import numpy as np

from app.config import DATA_DIR

RATE = 16000


class Recorder:
    def __init__(self) -> None:
        self._frames: list[bytes] = []
        self._stream = None
        self._lock = threading.Lock()
        self._started = 0.0
        self.last_error = ""
        self.input_index: int | None = None
        self.input_name = ""
        self.last_peak = 0
        self.available = self._probe()

    def _candidates(self) -> list[tuple[int | None, str]]:
        import sounddevice as sd

        found: list[tuple[int, int, str]] = []
        devices = list(sd.query_devices())
        hosts = list(sd.query_hostapis())
        for index, device in enumerate(devices):
            if int(device["max_input_channels"]) <= 0:
                continue
            host = str(hosts[int(device["hostapi"])]["name"])
            name = str(device["name"])
            low_host = host.lower()
            low_name = name.lower()
            if "wdm-ks" in low_host:
                continue
            if "mapper" in low_name or "primary" in low_name:
                score = 50
            elif "mme" in low_host and "microphone" in low_name:
                score = 40
            elif "directsound" in low_host and "microphone" in low_name:
                score = 30
            elif "wasapi" in low_host:
                score = 5
            else:
                score = 20
            found.append((score, index, f"{name} ({host})"))
        found.sort(key=lambda item: (-item[0], item[1]))
        return [(None, "default input")] + [(index, label) for _score, index, label in found]

    def _probe(self) -> bool:
        try:
            return len(self._candidates()) > 1
        except Exception as exc:
            self.last_error = str(exc)
            return False

    def start(self) -> bool:
        with self._lock:
            if self._stream is not None:
                return True
            if not self.available:
                return False
            self._frames = []
            self.last_error = ""
            try:
                import sounddevice as sd

                def callback(indata, _frames, _time, status) -> None:
                    if status:
                        self.last_error = str(status)
                    self._frames.append(indata.copy().tobytes())

                opened = False
                for device, label in self._candidates():
                    stream = None
                    try:
                        stream = sd.InputStream(
                            device=device,
                            samplerate=RATE,
                            channels=1,
                            dtype="int16",
                            callback=callback,
                        )
                        stream.start()
                        self._stream = stream
                        self.input_index = device if isinstance(device, int) else None
                        self.input_name = label
                        self._started = time.monotonic()
                        opened = True
                        break
                    except Exception as exc:
                        self.last_error = str(exc)
                        if stream is not None:
                            try:
                                stream.close()
                            except Exception:
                                pass
                return opened
            except Exception as exc:
                self.last_error = str(exc)
                self._stream = None
                return False

    def stop(self) -> Path | None:
        with self._lock:
            stream = self._stream
            self._stream = None
            frames = self._frames
            self._frames = []
            started = self._started
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception as exc:
                self.last_error = str(exc)
        if not frames or (time.monotonic() - started) < 0.35:
            self.last_peak = 0
            return None
        raw = b"".join(frames)
        samples = np.frombuffer(raw, dtype=np.int16)
        self.last_peak = int(np.max(np.abs(samples))) if samples.size else 0
        path = DATA_DIR / "audio"
        path.mkdir(parents=True, exist_ok=True)
        wav_path = path / "last.wav"
        with wave.open(str(wav_path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(RATE)
            handle.writeframes(raw)
        return wav_path

    def cancel(self) -> None:
        self.stop()
