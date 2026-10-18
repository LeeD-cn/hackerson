param(
    [string]$Config = '.local/planning/settings.json',
    [int]$Port = 8765,
    [string]$Database = 'data/relay.db',
    [string]$BindAddress = '127.0.0.1',
    [string]$AdminTokenFile = ''
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$configPath = if ([IO.Path]::IsPathRooted($Config)) { $Config } else { Join-Path $projectRoot $Config }
if (-not (Test-Path -LiteralPath $configPath)) {
    throw 'Missing local config. Copy backend/planning.example.json to .local/planning/settings.json first.'
}
$settings = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
$keyPath = if ([IO.Path]::IsPathRooted($settings.api_key_file)) { $settings.api_key_file } else { Join-Path $projectRoot $settings.api_key_file }
if (-not (Test-Path -LiteralPath $keyPath)) {
    throw 'Missing local model key file. Create the configured api_key_file; do not commit it.'
}
$pythonPath = Join-Path $projectRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Project .venv is missing. Run scripts/setup.ps1 first.' }
$dbPath = if ([IO.Path]::IsPathRooted($Database)) { $Database } else { Join-Path $projectRoot $Database }
if ($AdminTokenFile) {
    $adminPath = if ([IO.Path]::IsPathRooted($AdminTokenFile)) { $AdminTokenFile } else { Join-Path $projectRoot $AdminTokenFile }
    $env:RELAY_ADMIN_TOKEN = (Get-Content -LiteralPath $adminPath -Raw -Encoding UTF8).Trim()
}
$env:RELAY_AI_BASE_URL = $settings.base_url
$env:RELAY_AI_MODEL = $settings.model
$env:RELAY_AI_API_KEY = $null
$env:RELAY_AI_API_KEY_FILE = $keyPath
$env:RELAY_AI_JSON_MODE = if ($settings.json_mode) { '1' } else { '0' }
$env:RELAY_AI_TIMEOUT_SECONDS = [string]$settings.timeout_seconds
Push-Location $projectRoot
try {
    & $pythonPath -m backend --host $BindAddress --port $Port --db $dbPath
    if ($LASTEXITCODE -ne 0) { throw "Backend exited with code $LASTEXITCODE" }
} finally {
    Pop-Location
}
