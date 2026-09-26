$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

Write-Host '=== NOTE HRM Auto Register - Build EXE ===' -ForegroundColor Cyan

# Windows cannot replace the EXE while the application is still running.
$runningApp = Get-Process -Name 'NOTE_HRM_Auto_Register' -ErrorAction SilentlyContinue
if ($runningApp) {
    throw 'NOTE_HRM_Auto_Register.exe is still running. In the app, click DUNG and close the window; then run build.ps1 again.'
}

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw 'Python launcher (py) was not found. Install Python 3.11 or 3.12 x64, then reopen CMD.'
}

if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    & py -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python environment.' }
}

$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$pyinstaller = Join-Path $PSScriptRoot '.venv\Scripts\pyinstaller.exe'
if (-not $env:LOCALAPPDATA) { throw 'LOCALAPPDATA is not set.' }
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $env:LOCALAPPDATA 'ms-playwright'

& $python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw 'pip upgrade failed.' }
& $python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& $python -m playwright install chromium
if ($LASTEXITCODE -ne 0) { throw 'Chromium installation failed.' }
& $python -m pip install pyinstaller
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller installation failed.' }

if (Test-Path -LiteralPath 'build') { Remove-Item -LiteralPath 'build' -Recurse -Force }
if (Test-Path -LiteralPath 'dist') {
    try {
        Remove-Item -LiteralPath 'dist' -Recurse -Force -ErrorAction Stop
    } catch {
        throw 'Cannot replace dist\NOTE_HRM_Auto_Register.exe. Close the app and any program using this file, then run build.ps1 again.'
    }
}

& $pyinstaller --noconfirm --clean --onefile --windowed --name NOTE_HRM_Auto_Register main.py
if ($LASTEXITCODE -ne 0) { throw 'EXE build failed.' }

$exe = Join-Path $PSScriptRoot 'dist\NOTE_HRM_Auto_Register.exe'
if (-not (Test-Path -LiteralPath $exe)) { throw 'Build finished without creating the EXE.' }

Write-Host ('Build complete: ' + $exe) -ForegroundColor Green
Write-Host ('Chromium installed in: ' + $env:PLAYWRIGHT_BROWSERS_PATH)
Write-Host 'On another computer, install Chromium with the matching Playwright version.'
