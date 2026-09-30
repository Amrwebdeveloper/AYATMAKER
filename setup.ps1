# Creates .venv, installs requirements and Playwright Chromium.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Test-Path .venv)) { python -m venv .venv }
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
& $py -m ensurepip --upgrade 2>$null
& $py -m pip install --upgrade pip
& $py -m pip install -r requirements.txt
& $py -m playwright install chromium
if (-not (Test-Path config.toml) -and -not $env:PEXELS_API_KEY) {
    Copy-Item config.example.toml config.toml
    Write-Host "Created config.toml - add your Pexels API key (or set PEXELS_API_KEY)."
}
Write-Host "Done. Try: .\.venv\Scripts\python -m ayatmaker.make --surah 1 --ayah 1-7 --reader alafasy --out output"
