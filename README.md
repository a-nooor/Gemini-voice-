# local-agent

Local automation agent for this Windows machine. It stays on 127.0.0.1.

## What it does

- Hold **F9** (or the dashboard button) to talk. Release to run.
- Speech-to-text and command handling go through the Gemini API. The dashboard model list defaults to Auto: 3.7 Flash, then 3.6, then 3.5. Each try stops after 22 seconds. A voice reply is spoken, including a short failure if Gemini does not answer.
- Replies are spoken with the Windows voice (pyttsx3).
- Gmail: read, create a draft, send only after **Approve send** on the dashboard.
- Drafts and sends are limited to `email_allowlist` in `config.json` (default `wissam@sundaymedia.me`).
- Page checks and the monitor list report HTTP status. Chromium is used when Playwright can launch it.
- Dashboard: http://127.0.0.1:8765

## Run

```powershell
cd C:\Users\Alaa\Documents\githup\localvscode\local-agent
.\setup.ps1
.\run.ps1
```

## Secrets

` .credentials.md` (gitignored):

- Service Gemini → Password = API key. Restart after saving.

Gmail:

- Download an OAuth desktop client JSON from Google Cloud.
- Save it as `secrets/client_secret.json`.
- Open the dashboard and click **Connect Gmail**. Sign in in the browser window that opens.

## This session — 2026-09-28

**Problem:** No local agent. Desktop folder only had maintenance scripts.

**Method:** FastAPI on localhost, one process for hotkey, microphone, Gemini, Gmail, monitors, and the dashboard. Send is a separate approved action so the model cannot send mail.

**Worked:** `setup.ps1` finished (packages + Chromium). `run.py` is serving http://127.0.0.1:8765. Typed `status` produced: "Gemini API key is missing. Monitors: Agent health: 200". F9 hook armed. Windows speech engine initialized. Hold-to-talk logged "No microphone is visible to Windows."

**Did not:** Gemini was not called. No Gmail OAuth file. Needs your verification that you hear the spoken reply and that a real sentence transcribes.

**Mic:** After the plug-in, Windows shows `Microphone (High Definition Audio Device)`. The default input opened and returned samples. Agent restarted so the dashboard can use it.

**Next:** Hold F9 and speak. Add `secrets/client_secret.json` and connect Gmail from the dashboard.
