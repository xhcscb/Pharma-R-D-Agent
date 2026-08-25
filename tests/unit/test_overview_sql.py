from sqlalchemy import select
from sqlalchemy.dialects import postgresql, sqlite

from pharma_data.storage.canonical.models import DocumentElementRecord
from pharma_data.visualization.overview import _rounded_average


def test_rounded_average_compiles_for_sqlite_and_postgresql() -> None:
    statement = select(_rounded_average(DocumentElementRecord.confidence))
    sqlite_sql = str(statement.compile(dialect=sqlite.dialect()))
    postgres_sql = str(statement.compile(dialect=postgresql.dialect()))

    assert "round(CAST(avg(document_element.confidence) AS NUMERIC)" in sqlite_sql
    assert "round(CAST(avg(document_element.confidence) AS NUMERIC)" in postgres_sql
