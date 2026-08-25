"""Run a bounded, real-PDF smoke test against the MinerU service."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import httpx


def _result_payload(response: httpx.Response) -> dict[str, Any]:
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("MinerU returned a non-object JSON payload")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--url", default="http://127.0.0.1:18010")
    parser.add_argument("--page", type=int, default=0)
    parser.add_argument("--timeout", type=float, default=1800.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    pdf_path = args.pdf.resolve()
    if not pdf_path.is_file():
        raise FileNotFoundError(pdf_path)

    health = httpx.get(f"{args.url.rstrip('/')}/gpu-health", timeout=15.0)
    health_payload = _result_payload(health)
    if not health_payload.get("cuda_available"):
        raise RuntimeError(f"GPU health verification failed: {health_payload}")

    with pdf_path.open("rb") as pdf_file:
        response = httpx.post(
            f"{args.url.rstrip('/')}/file_parse",
            files={"files": (pdf_path.name, pdf_file, "application/pdf")},
            data={
                "backend": "pipeline",
                "parse_method": "auto",
                "formula_enable": "true",
                "table_enable": "true",
                "return_md": "true",
                "return_middle_json": "true",
                "return_model_output": "true",
                "return_content_list": "true",
                "return_images": "true",
                "response_format_zip": "false",
                "start_page_id": str(args.page),
                "end_page_id": str(args.page),
            },
            timeout=args.timeout,
        )
    payload = _result_payload(response)
    output_bytes = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(output_bytes)

    results = payload.get("results", payload)
    if not isinstance(results, dict) or not results:
        raise RuntimeError(f"MinerU response contains no parsed result: keys={list(payload)}")
    first = next(iter(results.values()))
    if not isinstance(first, dict):
        raise RuntimeError("MinerU first result is not an object")
    content = first.get("content_list")
    middle = first.get("middle_json")
    model = first.get("model_output")
    images = first.get("images")
    summary = {
        "ok": bool(content) and bool(middle),
        "input": str(pdf_path),
        "page": args.page,
        "device": health_payload.get("device_name"),
        "mineru_version": health_payload.get("mineru_version"),
        "response_keys": sorted(first),
        "content_items": len(content) if isinstance(content, list) else None,
        "middle_present": bool(middle),
        "model_output_present": bool(model),
        "images_returned": len(images) if isinstance(images, dict) else 0,
        "output_sha256": hashlib.sha256(output_bytes).hexdigest(),
        "saved_to": str(args.output.resolve()) if args.output else None,
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
