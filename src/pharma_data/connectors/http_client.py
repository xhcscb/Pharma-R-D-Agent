import time
from collections.abc import Mapping
from typing import Any

import httpx

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def authoritative_get(
    url: str,
    *,
    params: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
    timeout: float = 60,
    attempts: int = 4,
) -> httpx.Response:
    """执行带有限重试的只读请求，并保留最终响应供调用方审计。"""
    last_response: httpx.Response | None = None
    last_error: httpx.RequestError | None = None
    for attempt in range(attempts):
        try:
            with httpx.Client(follow_redirects=True, timeout=timeout) as client:
                response = client.get(url, params=params, headers=headers)
            last_response = response
            if response.status_code not in RETRYABLE_STATUS_CODES:
                response.raise_for_status()
                return response
        except httpx.RequestError as exc:
            last_error = exc
        if attempt < attempts - 1:
            time.sleep(min(0.5 * (2**attempt), 4.0))

    if last_response is not None:
        last_response.raise_for_status()
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"权威来源请求失败且没有响应: {url}")
