import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
CREDENTIALS_PATH = ROOT / ".credentials.md"
SECRETS_DIR = ROOT / "secrets"
DATA_DIR = ROOT / "data"
CLIENT_SECRET_PATH = SECRETS_DIR / "client_secret.json"
GMAIL_TOKEN_PATH = DATA_DIR / "gmail_token.json"

MODEL_CHOICES = (
    ("auto", "Auto"),
    ("gemini-3.6-flash", "3.6 Flash"),
    ("gemini-3.5-flash", "3.5 Flash"),
    ("gemini-3.7-flash", "3.7 Flash"),
    ("gemini-3.8-flash", "3.8 Flash"),
)
AUTO_MODELS = (
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.7-flash",
    "gemini-3.8-flash",
)

_config: dict | None = None
_gemini_key: str | None = None


def load_config() -> dict:
    global _config
    with CONFIG_PATH.open(encoding="utf-8") as handle:
        _config = json.load(handle)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    return _config


def config() -> dict:
    if _config is None:
        return load_config()
    return _config


def _parse_credentials(text: str) -> dict[str, dict]:
    blocks: list[dict] = []
    current: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            if current:
                blocks.append(current)
                current = {}
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        current[key.strip().lower()] = value.strip()
    if current:
        blocks.append(current)
    return {block.get("service", "").lower(): block for block in blocks}


def gemini_key() -> str:
    global _gemini_key
    if _gemini_key is not None:
        return _gemini_key
    env = os.environ.get("GEMINI_API_KEY", "").strip()
    if env:
        _gemini_key = env
        return _gemini_key
    if CREDENTIALS_PATH.exists():
        blocks = _parse_credentials(CREDENTIALS_PATH.read_text(encoding="utf-8"))
        _gemini_key = blocks.get("gemini", {}).get("password", "").strip()
    else:
        _gemini_key = ""
    return _gemini_key


def public_settings() -> dict:
    cfg = config()
    selected = cfg.get("gemini_model", "auto")
    if selected not in {item[0] for item in MODEL_CHOICES}:
        selected = "auto"
    return {
        "ptt_key": cfg.get("ptt_key", "f9"),
        "stt_engine": cfg.get("stt_engine", "gemini"),
        "gemini_model": selected,
        "model_choices": [{"id": item_id, "label": label} for item_id, label in MODEL_CHOICES],
        "email_allowlist": cfg.get("email_allowlist", []),
        "host": cfg.get("host", "127.0.0.1"),
        "port": int(cfg.get("port", 8765)),
    }


def set_gemini_model(name: str) -> str:
    allowed = {item[0] for item in MODEL_CHOICES}
    if name not in allowed:
        raise ValueError("Unknown model")
    cfg = config()
    cfg["gemini_model"] = name
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    return name
