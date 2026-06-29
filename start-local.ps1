# Start Politrade locally (Windows)
Set-Location $PSScriptRoot
if (-not (Test-Path .venv)) {
    python -m venv .venv
    .\.venv\Scripts\pip install -e ".[dev]"
}
if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
    Write-Host "Created .env — edit wallet keys or use /wallet in the UI"
}
if (-not (Test-Path data)) { New-Item -ItemType Directory -Path data | Out-Null }
Write-Host "Open http://localhost:8000 (login: admin / see DASHBOARD_PASSWORD in .env)"
.\.venv\Scripts\politrade-web.exe
