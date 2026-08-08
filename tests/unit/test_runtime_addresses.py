from pathlib import Path

from pharma_data.cli.main import _database_error_hint


def _dotenv(path: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def test_env_example_separates_local_and_container_addresses() -> None:
    values = _dotenv(".env.example")

    assert values["DATABASE_URL"].startswith("sqlite:///")
    assert "@postgres:5432" in values["CONTAINER_DATABASE_URL"]
    assert values["OBJECT_STORE_ROOT"].startswith("./")
    assert values["CONTAINER_OBJECT_STORE_ROOT"].startswith("/app/")


def test_compose_service_name_error_has_actionable_hint() -> None:
    hint = _database_error_hint("postgres")

    assert "Docker 内部服务名" in hint
    assert "localhost" in hint
