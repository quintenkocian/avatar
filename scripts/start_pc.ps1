# Avatar — build and run the single Docker container (Windows / PowerShell).
#
# Stops and removes any existing `avatar` container, rebuilds the image from the
# repo root, then runs it with the root .env on port 8000.
#
# Usage (from anywhere):  ./scripts/start_pc.ps1
$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot  = Split-Path -Parent $ScriptDir
Set-Location $RepoRoot

# Docker must be running. Run native probes with the error policy relaxed so a
# non-zero exit is handled via $LASTEXITCODE, not turned into a terminating error.
$ErrorActionPreference = 'Continue'
docker info 1> $null 2> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Docker does not appear to be running. Start Docker Desktop and try again." -ForegroundColor Red
    exit 1
}

# The container reads configuration from the root .env via --env-file.
if (-not (Test-Path (Join-Path $RepoRoot '.env'))) {
    Write-Error "No .env found at repo root. Copy the values from README.md 'Setup instructions' first."
    exit 1
}

Write-Host "Stopping any existing 'avatar' container..." -ForegroundColor Cyan
docker rm -f avatar 1> $null 2> $null   # no-op if it doesn't exist

Write-Host "Building image 'avatar'..." -ForegroundColor Cyan
docker build -t avatar .
if ($LASTEXITCODE -ne 0) { Write-Error "Docker build failed."; exit 1 }

Write-Host "Starting container 'avatar' on port 8000..." -ForegroundColor Cyan
docker run -d --name avatar --env-file .env -p 8000:8000 avatar
if ($LASTEXITCODE -ne 0) { Write-Error "Docker run failed."; exit 1 }

Write-Host ""
Write-Host "Avatar is running:" -ForegroundColor Green
Write-Host "  Visitor:  http://localhost:8000"
Write-Host "  Admin:    http://localhost:8000/admin"
Write-Host ""
Write-Host "Logs:  docker logs -f avatar"
Write-Host "Stop:  ./scripts/stop_pc.ps1"
