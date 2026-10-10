import asyncio
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.audio_io import Recorder
from app.browser_mon import playwright_installed, refresh_monitors
from app.config import CLIENT_SECRET_PATH, config, gemini_key, load_config, public_settings, set_gemini_model
from app.gmail_svc import (
    approve_send,
    connect_blocking,
    dismiss,
    pending_public,
    secret_present,
    token_present,
)
from app.orchestrator import Orchestrator
from app.policy import PolicyError
from app.ptt import PttListener
from app.status import hub
from app.tts import Speaker

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"

load_config()
recorder = Recorder()
speaker = Speaker()
orchestrator = Orchestrator(recorder, speaker)
ptt = PttListener(
    public_settings()["ptt_key"],
    lambda: None,
    lambda: None,
)

app = FastAPI(title="local-agent")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


def _allowed_origins() -> set[str]:
    port = public_settings()["port"]
    return {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}


def _origin_ok(origin: str | None) -> bool:
    return not origin or origin in _allowed_origins()


def capabilities() -> dict:
    return {
        "gemini": bool(gemini_key()),
        "mic": recorder.available,
        "mic_error": recorder.last_error,
        "tts": speaker.available,
        "tts_error": speaker.last_error,
        "ptt": ptt.listener is not None and ptt.last_error == "",
        "ptt_error": ptt.last_error,
        "gmail_secret": secret_present(),
        "gmail": token_present(),
        "browser": playwright_installed(),
        "client_secret_path": str(CLIENT_SECRET_PATH),
        **public_settings(),
    }


@app.middleware("http")
async def origin_gate(request, call_next):
    if request.url.path.startswith("/api") and request.method != "GET":
        if not _origin_ok(request.headers.get("origin")):
            return JSONResponse({"error": "blocked origin"}, status_code=403)
    return await call_next(request)


@app.on_event("startup")
async def startup() -> None:
    loop = asyncio.get_running_loop()
    hub.bind_loop(loop)
    await asyncio.to_thread(speaker.ready.wait, 8)

    def down() -> None:
        asyncio.run_coroutine_threadsafe(orchestrator.begin_ptt(), loop)

    def up() -> None:
        asyncio.run_coroutine_threadsafe(orchestrator.end_ptt(), loop)

    ptt.on_down = down
    ptt.on_up = up
    if ptt.start():
        hub.note(f"Push-to-talk armed on {public_settings()['ptt_key']}")
    else:
        hub.note(ptt.last_error or "Push-to-talk failed", "error")
    hub.set_capabilities(capabilities())
    hub.note("Agent idle")
    asyncio.create_task(_monitor_loop())


@app.on_event("shutdown")
async def shutdown() -> None:
    ptt.stop()
    speaker.close()


async def _monitor_loop() -> None:
    await asyncio.sleep(1)
    interval = max(10, int(config().get("monitor_interval_sec", 30)))
    while True:
        try:
            await refresh_monitors()
        except Exception as exc:
            hub.note(f"Monitor refresh failed: {exc}", "error")
        await asyncio.sleep(interval)


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
async def health():
    return {"ok": True, "service": "local-agent", "state": hub.state}


@app.get("/api/snapshot")
async def snapshot():
    hub.set_capabilities(capabilities())
    return hub.snapshot()


@app.post("/api/model")
async def choose_model(payload: dict):
    try:
        selected = set_gemini_model(str(payload.get("model", "")))
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    hub.note(f"Model set to {selected}")
    hub.set_capabilities(capabilities())
    return {"model": selected}


@app.post("/api/command")
async def command(payload: dict):
    text = str(payload.get("text", ""))
    asyncio.create_task(orchestrator.command(text))
    return {"accepted": True}


@app.post("/api/gmail/connect")
async def gmail_connect():
    message = await asyncio.to_thread(connect_blocking)
    hub.set_capabilities(capabilities())
    return {"message": message, "gmail": token_present()}


@app.post("/api/gmail/approve")
async def gmail_approve(payload: dict):
    draft_id = str(payload.get("draft_id", ""))
    try:
        result = await asyncio.to_thread(approve_send, draft_id)
    except PolicyError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        hub.note(str(exc), "error")
        return JSONResponse({"error": str(exc)}, status_code=400)
    return result


@app.post("/api/gmail/dismiss")
async def gmail_dismiss(payload: dict):
    dismiss(str(payload.get("draft_id", "")))
    return {"ok": True, "pending": pending_public()}


@app.post("/api/monitors/refresh")
async def monitors_refresh():
    rows = await refresh_monitors()
    return {"monitors": rows}


@app.websocket("/ws")
async def ws(socket: WebSocket):
    if not _origin_ok(socket.headers.get("origin")):
        await socket.close(code=1008)
        return
    await socket.accept()
    queue = hub.subscribe()
    hub.set_capabilities(capabilities())
    await socket.send_json(hub.snapshot())
    sender = asyncio.create_task(_pump(socket, queue))
    try:
        while True:
            message = await socket.receive_json()
            kind = message.get("type")
            if kind == "command":
                asyncio.create_task(orchestrator.command(str(message.get("text", ""))))
            elif kind == "ptt" and message.get("phase") == "down":
                asyncio.create_task(orchestrator.begin_ptt())
            elif kind == "ptt" and message.get("phase") == "up":
                asyncio.create_task(orchestrator.end_ptt())
    except WebSocketDisconnect:
        pass
    finally:
        sender.cancel()
        hub.unsubscribe(queue)


async def _pump(socket: WebSocket, queue: asyncio.Queue) -> None:
    while True:
        event = await queue.get()
        await socket.send_json(event)
