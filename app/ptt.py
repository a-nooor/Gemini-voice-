from pynput import keyboard

SPECIAL = {
    "f8": keyboard.Key.f8,
    "f9": keyboard.Key.f9,
    "f10": keyboard.Key.f10,
    "ctrl_r": keyboard.Key.ctrl_r,
    "shift_r": keyboard.Key.shift_r,
    "pause": keyboard.Key.pause,
}


def _matches(key, name: str) -> bool:
    expected = SPECIAL.get(name)
    if expected is not None:
        return key == expected
    return getattr(key, "char", None) == name


class PttListener:
    def __init__(self, key_name: str, on_down, on_up) -> None:
        self.key_name = key_name.lower()
        self.on_down = on_down
        self.on_up = on_up
        self.held = False
        self.listener = None
        self.last_error = ""

    def start(self) -> bool:
        try:
            self.listener = keyboard.Listener(on_press=self._press, on_release=self._release)
            self.listener.start()
            return True
        except Exception as exc:
            self.last_error = str(exc)
            return False

    def stop(self) -> None:
        if self.listener is not None:
            self.listener.stop()

    def _press(self, key) -> None:
        if self.held or not _matches(key, self.key_name):
            return
        self.held = True
        self.on_down()

    def _release(self, key) -> None:
        if not self.held or not _matches(key, self.key_name):
            return
        self.held = False
        self.on_up()
