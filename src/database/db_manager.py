from contextlib import contextmanager
from typing import Generator

from loguru import logger
from sqlalchemy import create_engine, Engine
from sqlalchemy.orm import Session, sessionmaker

from config.settings import settings
from src.database.models import Base


def _build_engine() -> Engine:
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    url = f"sqlite:///{settings.db_path}"
    return create_engine(url, connect_args={"check_same_thread": False})


_engine = _build_engine()
_SessionFactory = sessionmaker(bind=_engine, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(_engine)
    logger.info(f"Database ready at {settings.db_path}")


@contextmanager
def get_session() -> Generator[Session, None, None]:
    session = _SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
