param(
    [string]$BackendUrl = 'http://127.0.0.1:8765',
    [int]$Port = 5173
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$frontendPath = Join-Path $projectRoot 'frontend'
if (-not (Test-Path -LiteralPath (Join-Path $frontendPath 'node_modules'))) {
    throw 'Frontend dependencies are missing. Run npm ci --no-audit --no-fund inside frontend first.'
}
$env:RELAY_API_URL = $BackendUrl
Push-Location $frontendPath
try {
    & npm run dev -- --port $Port
    if ($LASTEXITCODE -ne 0) { throw "Frontend exited with code $LASTEXITCODE" }
} finally {
    Pop-Location
}
