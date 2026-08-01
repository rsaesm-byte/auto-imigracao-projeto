"""Configuração do SQLAlchemy: engine, sessão e Base declarativa.

Módulo isolado (sem depender de app/__init__.py) para evitar import
circular entre app/models.py e a app factory.
"""
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, scoped_session, sessionmaker

INSTANCE_DIR = Path(__file__).resolve().parent.parent / "instance"
INSTANCE_DIR.mkdir(exist_ok=True)
DB_PATH = INSTANCE_DIR / "app.db"

engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})


@event.listens_for(engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _record):
    # SQLite ignora FOREIGN KEY por padrão (mesmo já as tendo no schema) --
    # sem isso, um bug de aplicação podia gravar um case_id/client_id órfão
    # sem erro nenhum. Liga em toda conexão nova do pool (é por-conexão,
    # não global).
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = scoped_session(sessionmaker(bind=engine, autoflush=False, autocommit=False))


class Base(DeclarativeBase):
    pass
