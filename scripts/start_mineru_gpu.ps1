$ErrorActionPreference = "Stop"
$env:CUDA_VISIBLE_DEVICES = "0"
$env:MINERU_DEVICE_MODE = "cuda"
$env:MINERU_VIRTUAL_VRAM_SIZE = "3"
$env:MINERU_MAX_CONCURRENT_REQUESTS = "1"
$env:MINERU_API_MAX_CONCURRENT_REQUESTS = "1"
$env:MINERU_MODEL_SOURCE = "modelscope"
$python = Join-Path $PSScriptRoot "..\.venv-mineru\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "MinerU environment is missing. Run scripts\setup_mineru_gpu.ps1 first."
}
& $python (Join-Path $PSScriptRoot "mineru_gpu_service.py") --host 127.0.0.1 --port 18010

