"""Configuração do SQLAlchemy: engine, sessão e Base declarativa.

Módulo isolado (sem depender de app/__init__.py) para evitar import
circular entre app/models.py e a app factory.
"""
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, scoped_session, sessionmaker

INSTANCE_DIR = Path(__file__).resolve().parent.parent / "instance"
INSTANCE_DIR.mkdir(exist_ok=True)
DB_PATH = INSTANCE_DIR / "app.db"

engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = scoped_session(sessionmaker(bind=engine, autoflush=False, autocommit=False))


class Base(DeclarativeBase):
    pass
