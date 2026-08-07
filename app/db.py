"""Configuração do SQLAlchemy: engine, sessão e Base declarativa.

Módulo isolado (sem depender de app/__init__.py) para evitar import
circular entre app/models.py e a app factory.
"""
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, scoped_session, sessionmaker

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


class VersionedMixin:
    """Controle de edição simultânea (optimistic concurrency) -- Seção
    16/17. Toda entidade que herda isto ganha uma coluna `version`
    (começa em 1, incrementada a cada update bem-sucedido pela própria
    rota via app/services/concurrency_service.py::bump_versao).

    O formulário de edição carrega a versão atual num campo oculto
    (`<input type="hidden" name="version">`); no POST, a rota chama
    `concurrency_service.checar_versao(registro, request.form.get(
    "version"))` ANTES de aplicar qualquer mudança de campo -- se a
    versão enviada não bater com a que está no banco agora, alguém mais
    editou o registro nesse meio-tempo e a rota aborta em vez de
    sobrescrever silenciosamente o que essa outra pessoa salvou."""
    version: Mapped[int] = mapped_column(default=1, nullable=False)
