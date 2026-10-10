$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Test-Path .venv)) {
  py -3 -m venv .venv
}
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
try {
  & .\.venv\Scripts\python.exe -m playwright install chromium
} catch {
  Write-Warning "Chromium install failed. Page checks will use plain HTTP until playwright install chromium succeeds."
}
Write-Host "Setup finished."
