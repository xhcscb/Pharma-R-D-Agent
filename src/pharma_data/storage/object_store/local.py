from dataclasses import dataclass
from pathlib import Path
from shutil import copyfileobj
from typing import BinaryIO

from pharma_data.utils.hashing import sha256_file


@dataclass(frozen=True)
class StoredObject:
    content_hash: str
    path: Path
    size_bytes: int


class LocalObjectStore:
    """Immutable content-addressed storage.

    Objects are never overwritten. The same content always resolves to the same
    path, which makes retries and source-level duplication safe.
    """

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _target(self, content_hash: str) -> Path:
        return self.root / content_hash[:2] / content_hash

    def put_file(self, source: str | Path) -> StoredObject:
        source_path = Path(source)
        content_hash = sha256_file(source_path)
        target = self._target(content_hash)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            temp = target.with_suffix(".partial")
            with source_path.open("rb") as read_stream, temp.open("wb") as write_stream:
                copyfileobj(read_stream, write_stream)
            temp.replace(target)
        return StoredObject(content_hash, target, target.stat().st_size)

    def put_bytes(self, content: bytes) -> StoredObject:
        import hashlib

        content_hash = hashlib.sha256(content).hexdigest()
        target = self._target(content_hash)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            temp = target.with_suffix(".partial")
            temp.write_bytes(content)
            temp.replace(target)
        return StoredObject(content_hash, target, target.stat().st_size)

    def open(self, content_hash: str) -> BinaryIO:
        return self._target(content_hash).open("rb")

    def path_for(self, content_hash: str) -> Path:
        path = self._target(content_hash)
        if not path.exists():
            raise FileNotFoundError(content_hash)
        return path
