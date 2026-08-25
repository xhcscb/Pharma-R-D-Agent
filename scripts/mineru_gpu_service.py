"""Launch MinerU with a CUDA identity endpoint used by the data-layer gate."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

import torch
import uvicorn


def _prepare_fasttext_model_path() -> None:
    """Work around fastText's Windows inability to open non-ASCII paths."""
    import fast_langdetect.ft_detect.infer as language_infer

    source = Path(language_infer.LOCAL_SMALL_MODEL_PATH)
    cache_root = Path(
        os.getenv(
            "MINERU_FASTTEXT_CACHE",
            str(Path(tempfile.gettempdir()) / "mineru-fasttext"),
        )
    )
    cache_root.mkdir(parents=True, exist_ok=True)
    target = cache_root / source.name
    source_digest = hashlib.sha256(source.read_bytes()).digest()
    target_digest = hashlib.sha256(target.read_bytes()).digest() if target.exists() else None
    if target_digest != source_digest:
        shutil.copy2(source, target)
    language_infer.LOCAL_SMALL_MODEL_PATH = target


_prepare_fasttext_model_path()

from mineru.cli.fast_api import app  # noqa: E402


def _gpu_identity() -> dict[str, Any]:
    requested = os.getenv("MINERU_DEVICE_MODE", "cuda").casefold()
    cuda_available = torch.cuda.is_available()
    if requested.startswith("cuda") and not cuda_available:
        raise RuntimeError("MINERU_DEVICE_MODE=cuda but torch.cuda.is_available() is false")
    payload: dict[str, Any] = {
        "status": "ok",
        "device_mode": requested,
        "cuda_available": cuda_available,
        "torch_version": torch.__version__,
        "torch_cuda_version": torch.version.cuda,
        "mineru_version": importlib.metadata.version("mineru"),
    }
    if cuda_available:
        properties = torch.cuda.get_device_properties(0)
        virtual_gb = float(os.getenv("MINERU_VIRTUAL_VRAM_SIZE", "3"))
        total_bytes = int(properties.total_memory)
        fraction = min(virtual_gb * 1024**3 / max(total_bytes, 1), 0.95)
        torch.cuda.set_per_process_memory_fraction(fraction, 0)
        payload.update(
            {
                "device_index": 0,
                "device_name": torch.cuda.get_device_name(0),
                "total_vram_bytes": total_bytes,
                "virtual_vram_gb": virtual_gb,
                "memory_fraction": round(fraction, 6),
                "compute_capability": list(torch.cuda.get_device_capability(0)),
            }
        )
    return payload


GPU_IDENTITY = _gpu_identity()


@app.get("/gpu-health", include_in_schema=True)
def gpu_health() -> dict[str, Any]:
    return GPU_IDENTITY


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18010)
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("Local MinerU must listen on loopback; use a TLS/auth proxy remotely")
    uvicorn.run(app, host=args.host, port=args.port, workers=1)


if __name__ == "__main__":
    main()
