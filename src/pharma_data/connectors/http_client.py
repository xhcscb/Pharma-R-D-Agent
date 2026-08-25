import time
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urljoin

import httpx

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def authoritative_get(
    url: str,
    *,
    params: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
    timeout: float = 60,
    attempts: int = 4,
    max_redirects: int = 5,
    url_validator: Callable[[str], None] | None = None,
) -> httpx.Response:
    """执行带有限重试的只读请求，并在每次重定向前校验目标地址。"""
    last_response: httpx.Response | None = None
    last_error: httpx.RequestError | None = None
    for attempt in range(attempts):
        try:
            current_url = url
            current_params = params
            with httpx.Client(follow_redirects=False, timeout=timeout) as client:
                for redirect_count in range(max_redirects + 1):
                    if url_validator is not None:
                        url_validator(current_url)
                    response = client.get(current_url, params=current_params, headers=headers)
                    last_response = response
                    if url_validator is not None:
                        url_validator(str(response.url))
                    if not response.is_redirect:
                        break
                    location = response.headers.get("location")
                    if not location:
                        response.raise_for_status()
                    if redirect_count >= max_redirects:
                        raise httpx.TooManyRedirects(
                            "权威来源重定向次数超过限制",
                            request=response.request,
                        )
                    current_url = urljoin(str(response.url), location)
                    current_params = None
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
