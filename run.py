from app.config import load_config

import uvicorn

if __name__ == "__main__":
    cfg = load_config()
    uvicorn.run("app.main:app", host=cfg.get("host", "127.0.0.1"), port=int(cfg.get("port", 8765)))
