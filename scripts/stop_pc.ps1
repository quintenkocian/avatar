# Avatar — stop and remove the running Docker container (Windows / PowerShell).
#
# Usage (from anywhere):  ./scripts/stop_pc.ps1
# Native probes run with the default 'Continue' policy so a non-zero exit is
# handled via $LASTEXITCODE rather than a terminating error.

# Docker must be running to talk to it.
docker info 1> $null 2> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Docker does not appear to be running. Start Docker Desktop and try again." -ForegroundColor Red
    exit 1
}

Write-Host "Stopping and removing 'avatar' container..." -ForegroundColor Cyan
docker rm -f avatar 1> $null 2> $null   # no-op if it doesn't exist

Write-Host "Stopped." -ForegroundColor Green
