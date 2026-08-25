$ErrorActionPreference = "Stop"
$projectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Application environment is missing. Create .venv first."
}
Set-Location $projectRoot
& $python -m pharma_data.orchestration.worker
