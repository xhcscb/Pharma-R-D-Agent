$ErrorActionPreference = "Stop"
$venvPath = Join-Path $PSScriptRoot "..\.venv-mineru"
if (-not (Test-Path $venvPath)) {
    $bootstrapPython = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
    if (-not (Test-Path $bootstrapPython)) {
        throw "Python 3.12 bootstrap environment was not found at .venv\Scripts\python.exe"
    }
    & $bootstrapPython -m venv $venvPath
}
$python = Join-Path $venvPath "Scripts\python.exe"
& $python -m pip install --upgrade "pip==26.0.1"
if ($LASTEXITCODE -ne 0) { throw "pip bootstrap failed with exit code $LASTEXITCODE" }
& $python -m pip install -r (Join-Path $PSScriptRoot "..\requirements-mineru-cu128.txt")
if ($LASTEXITCODE -ne 0) { throw "MinerU dependency installation failed with exit code $LASTEXITCODE" }
& $python -c "import importlib.metadata, torch; assert torch.cuda.is_available(); print({'mineru': importlib.metadata.version('mineru'), 'torch': torch.__version__, 'cuda': torch.version.cuda, 'device': torch.cuda.get_device_name(0), 'vram': torch.cuda.get_device_properties(0).total_memory})"
if ($LASTEXITCODE -ne 0) { throw "CUDA validation failed with exit code $LASTEXITCODE" }
