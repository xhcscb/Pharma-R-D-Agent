from collections.abc import Generator

from sqlalchemy.orm import Session, sessionmaker

from pharma_data.storage.canonical.database import get_engine


def get_session() -> Generator[Session, None, None]:
    factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
