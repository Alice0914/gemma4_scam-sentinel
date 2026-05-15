# Scam Sentinel — end-to-end demo launcher
# Usage: .\run_demo.ps1
# Starts FastAPI backend (port 8000) and Next.js frontend (port 3000)

$ErrorActionPreference = "Stop"

Write-Host "=== Scam Sentinel Demo ===" -ForegroundColor Cyan

# 1. Check Ollama is running
Write-Host "`n[1/3] Checking Ollama..." -ForegroundColor Yellow
try {
    $null = Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -TimeoutSec 3
    Write-Host "  Ollama OK" -ForegroundColor Green
} catch {
    Write-Host "  ERROR: Ollama is not running. Start it with: ollama serve" -ForegroundColor Red
    exit 1
}

# 2. Start FastAPI backend
Write-Host "`n[2/3] Starting FastAPI backend on port 8000..." -ForegroundColor Yellow
$backend = Start-Process -FilePath "python" `
    -ArgumentList "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload" `
    -WorkingDirectory $PSScriptRoot `
    -PassThru -NoNewWindow
Write-Host "  Backend PID: $($backend.Id)" -ForegroundColor Green

Start-Sleep -Seconds 3

# 3. Start Next.js frontend
Write-Host "`n[3/3] Starting Next.js frontend on port 3000..." -ForegroundColor Yellow
$frontend = Start-Process -FilePath "npm" `
    -ArgumentList "run", "dev" `
    -WorkingDirectory "$PSScriptRoot\frontend" `
    -PassThru -NoNewWindow
Write-Host "  Frontend PID: $($frontend.Id)" -ForegroundColor Green

Write-Host "`n=== Demo running ===" -ForegroundColor Cyan
Write-Host "  Frontend: http://localhost:3000" -ForegroundColor White
Write-Host "  Backend:  http://localhost:8000/docs" -ForegroundColor White
Write-Host "`nPress Ctrl+C to stop both servers." -ForegroundColor Gray

try {
    Wait-Process -Id $backend.Id
} finally {
    if (-not $backend.HasExited) { $backend.Kill() }
    if (-not $frontend.HasExited) { $frontend.Kill() }
    Write-Host "`nStopped." -ForegroundColor Gray
}
