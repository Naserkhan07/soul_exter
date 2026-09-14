# SOUL EXTER — one command to open the trading floor in your own browser (Windows).
#
#   .\scripts\run_local.ps1              # build the interface, serve UI + API on :8000
#   $env:PORT=9000; .\scripts\run_local.ps1
#   $env:DEV=1; .\scripts\run_local.ps1  # hot-reload dev server on :5173 + API on :8000
#
# If PowerShell blocks the script, run once:
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $repo
$port = if ($env:PORT) { $env:PORT } else { '8000' }

function Say($m) { Write-Host "> $m" -ForegroundColor Cyan }

if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw 'python not found' }
if (-not (Get-Command node   -ErrorAction SilentlyContinue)) { throw 'node not found (needed to build the interface)' }

Say 'installing backend dependencies'
python -m pip install -q -r backend/requirements.txt

Say 'installing interface dependencies'
Push-Location frontend; npm install --silent; Pop-Location

Say 'building the interface'
Push-Location frontend; npm run build; Pop-Location

if (Test-Path .env) {
  Say 'found .env - loading provider keys'
  Get-Content .env | ForEach-Object {
    if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') {
      [Environment]::SetEnvironmentVariable($matches[1], $matches[2].Trim('"').Trim("'"), 'Process')
    }
  }
}

if (-not $env:SOUL_EXTER_SETTINGS) { $env:SOUL_EXTER_SETTINGS = "$repo\soul_exter_settings.json" }

if ($env:DEV -eq '1') {
  Say "API on http://127.0.0.1:$port"
  $api = Start-Process -PassThru -NoNewWindow python `
    -ArgumentList '-m','uvicorn','soul_exter.api.server:app','--host','0.0.0.0','--port',$port `
    -WorkingDirectory "$repo\backend"
  Start-Sleep -Seconds 4
  Say 'interface (hot reload) ->  http://localhost:5173'
  Push-Location frontend; npm run dev -- --port 5173; Pop-Location
  Stop-Process -Id $api.Id -ErrorAction SilentlyContinue
} else {
  Say "floor ready ->  http://localhost:$port"
  Say 'press Ctrl+C to stop'
  Set-Location backend
  python -m uvicorn soul_exter.api.server:app --host 0.0.0.0 --port $port
}
