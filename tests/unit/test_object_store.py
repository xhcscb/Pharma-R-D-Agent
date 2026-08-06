from pharma_data.storage.object_store import LocalObjectStore


def test_content_addressed_store_is_idempotent(tmp_path) -> None:
    store = LocalObjectStore(tmp_path / "objects")
    first = store.put_bytes(b"same content")
    second = store.put_bytes(b"same content")

    assert first.content_hash == second.content_hash
    assert first.path == second.path
    assert first.path.read_bytes() == b"same content"
