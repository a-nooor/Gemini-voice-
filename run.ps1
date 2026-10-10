$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Test-Path .\.venv\Scripts\python.exe)) {
  Write-Error "Run setup.ps1 first."
}
& .\.venv\Scripts\python.exe run.py
