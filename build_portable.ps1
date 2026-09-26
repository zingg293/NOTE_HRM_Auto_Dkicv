$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

Write-Host '=== Build portable NOTE HRM EXE (including Chromium) ===' -ForegroundColor Cyan

foreach ($file in @('main.py', 'notehrm_adapter.py', 'matcher.py', 'excel_reader.py', 'models.py', 'requirements.txt')) {
    if (-not (Test-Path -LiteralPath $file)) { throw "Missing source file: $file" }
}
if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw 'Python launcher py was not found. Install Python 3.12 x64 and reopen CMD.'
}

$python = Join-Path $PSScriptRoot '.venv_portable\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    & py -3.12 -m venv .venv_portable
    if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.12 x64 and retry.' }
}

& $python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw 'pip upgrade failed.' }
& $python -m pip install -r requirements.txt pyinstaller
if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }

# 0 installs the exact browser version next to the installed Playwright package.
$env:PLAYWRIGHT_BROWSERS_PATH = '0'
& $python -m playwright install chromium
if ($LASTEXITCODE -ne 0) { throw 'Chromium download failed.' }

$browserDir = (& $python -c "from pathlib import Path; import playwright; print(Path(playwright.__file__).parent / 'driver' / 'package' / '.local-browsers')").Trim()
if (-not (Test-Path -LiteralPath $browserDir)) {
    throw "Bundled Chromium directory does not exist: $browserDir"
}
$chrome = Get-ChildItem -LiteralPath $browserDir -Recurse -Filter chrome.exe -File -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $chrome) { throw 'Chromium chrome.exe is missing after installation.' }

$exe = Join-Path $PSScriptRoot 'dist_portable\NOTE_HRM_Auto_Register.exe'
if (Test-Path -LiteralPath $exe) {
    try {
        Remove-Item -LiteralPath $exe -Force -ErrorAction Stop
    } catch {
        throw 'Close the old EXE before rebuilding, then run build_portable.ps1 again.'
    }
}

& $python -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name NOTE_HRM_Auto_Register `
    --distpath dist_portable --workpath build_portable --specpath build_portable_spec `
    --add-data "${browserDir};playwright/driver/package/.local-browsers" main.py
if ($LASTEXITCODE -ne 0) { throw 'EXE build failed.' }
if (-not (Test-Path -LiteralPath $exe)) { throw 'Build ended without creating the EXE.' }

Write-Host ('Portable EXE created: ' + $exe) -ForegroundColor Green
Write-Host 'Copy just this EXE to another Windows x64 computer; select each Excel file inside the app.'
