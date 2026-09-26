$ErrorActionPreference = "Stop"
if (-not (Test-Path ".venv")) {
    py -m venv .venv
}
& ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt
& ".\.venv\Scripts\python.exe" -m playwright install chromium
& ".\.venv\Scripts\python.exe" main.py
