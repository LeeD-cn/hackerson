$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot

# Keep dependencies, package caches and temporary files under this checkout.
New-Item -ItemType Directory -Force -Path '.tmp', '.cache/pip', '.cache/npm' | Out-Null
$env:TEMP = Join-Path $projectRoot '.tmp'
$env:TMP = $env:TEMP
$env:PIP_CACHE_DIR = Join-Path $projectRoot '.cache/pip'
$env:npm_config_cache = Join-Path $projectRoot '.cache/npm'
$projectPython = Join-Path $projectRoot '.venv/Scripts/python.exe'

if (-not (Test-Path -LiteralPath $projectPython)) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create project virtual environment.' }
}

$requirementsFile = 'requirements.lock.txt'
if (-not (Test-Path -LiteralPath $requirementsFile)) { $requirementsFile = 'requirements.txt' }
& $projectPython -m pip install -r $requirementsFile
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& $projectPython -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Dependency consistency check failed.' }
Write-Host "Ready: $projectPython"
Write-Host 'No application server was started.'
