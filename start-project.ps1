<#
.SYNOPSIS
    Startup script for QA Automation Operator project.
.DESCRIPTION
    Launches the application via Docker Compose, Uvicorn API server, or CLI mode.
.PARAMETER Mode
    Specify how to start the project: 'docker' (default), 'local' (FastAPI via Uvicorn), or 'cli' (CLI run with sample data).
#>

param (
    [ValidateSet('docker', 'local', 'cli')]
    [string]$Mode = 'docker'
)

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "      QA Automation Operator            " -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# Ensure virtual environment is active if running local or cli
if ($Mode -ne 'docker') {
    if (Test-Path ".\venv\Scripts\Activate.ps1") {
        Write-Host "[+] Activating Python virtual environment..." -ForegroundColor Yellow
        . .\venv\Scripts\Activate.ps1
    }
}

switch ($Mode) {
    'docker' {
        Write-Host "[+] Starting containers via Docker Compose..." -ForegroundColor Green
        docker compose up -d
        if ($LASTEXITCODE -eq 0) {
            Write-Host ""
            Write-Host "[OK] Services started successfully!" -ForegroundColor Green
            Write-Host "    - Swagger API Docs: http://localhost:8000/docs" -ForegroundColor DarkGreen
            Write-Host "    - ReDoc API Docs:   http://localhost:8000/redoc" -ForegroundColor DarkGreen
            Write-Host ""
            Write-Host "Opening application in browser..." -ForegroundColor Yellow
            Start-Process "http://localhost:8000/docs"
            Write-Host ""
            Write-Host "To view API logs: docker compose logs -f api" -ForegroundColor Gray
            Write-Host "To stop services: docker compose down" -ForegroundColor Gray
        } else {
            Write-Host "[!] Docker Compose failed to start." -ForegroundColor Red
        }
    }
    'local' {
        Write-Host "[+] Starting FastAPI server locally on http://localhost:8000..." -ForegroundColor Green
        Write-Host "    - Press Ctrl+C to stop the server." -ForegroundColor Gray
        Start-Process "http://localhost:8000/docs"
        uvicorn src.api.app:app --reload --host 127.0.0.1 --port 8000
    }
    'cli' {
        Write-Host "[+] Executing CLI analysis on sample data..." -ForegroundColor Green
        python main.py --input sample_data/test_results.csv
        if (Test-Path "reports\qa_report_build_245.html") {
            Write-Host ""
            Write-Host "Dashboard:" -ForegroundColor Cyan
            Write-Host "  reports\qa_report_build_245.html" -ForegroundColor DarkCyan
            Write-Host ""
            Write-Host "Open with:" -ForegroundColor Cyan
            Write-Host "  start reports\qa_report_build_245.html" -ForegroundColor DarkCyan
            Write-Host ""
            Write-Host "[+] Opening generated HTML report in browser..." -ForegroundColor Green
            Start-Process "reports\qa_report_build_245.html"
        }
    }
}
