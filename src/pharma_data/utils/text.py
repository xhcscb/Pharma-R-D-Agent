import re
import unicodedata

_WHITESPACE = re.compile(r"\s+")


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    return _WHITESPACE.sub(" ", value).strip()


def normalize_alias(value: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", normalize_text(value).casefold())


def canonical_url(value: str) -> str:
    return value.split("#", 1)[0].rstrip("/")
