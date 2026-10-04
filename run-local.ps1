# Starts all five services locally, each in its own PowerShell window (no Docker, no make).
# Usage: .\run-local.ps1            (add -Ingest to rebuild the retrieval index first)
param([switch]$Ingest)

$root = $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"
$st = Join-Path $root ".venv\Scripts\streamlit.exe"

if ($Ingest -or -not (Test-Path (Join-Path $root ".index\chroma"))) {
    Write-Host "Building retrieval index..."
    & $py -m rag.ingestion.cli --rebuild
}

$services = @(
    @{ Name = "alarm-api";     Cmd = "& '$py' -m uvicorn alarm_api.main:app --host 0.0.0.0 --port 8000" },
    @{ Name = "ticketing-api"; Cmd = "& '$py' -m uvicorn ticketing_api.main:app --host 0.0.0.0 --port 8100" },
    @{ Name = "mcp";           Cmd = "& '$py' -m alarm_mcp" },
    @{ Name = "backend";       Cmd = "& '$py' -m uvicorn copilot.api.app:app --host 0.0.0.0 --port 8080" },
    @{ Name = "gui";           Cmd = "& '$st' run apps/frontend/gui/app.py" }
)

foreach ($s in $services) {
    $title = "`$Host.UI.RawUI.WindowTitle = '$($s.Name)'; Set-Location '$root'; $($s.Cmd)"
    Start-Process powershell -ArgumentList "-NoExit", "-Command", $title
    Start-Sleep -Seconds 3   # let each dependency come up before the next
}

Write-Host "Started. Open http://localhost:8501  (health: http://localhost:8080/health)"
