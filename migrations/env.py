import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context

# Permite `python -m alembic ...` a partir da raiz do projeto encontrar o
# pacote `app` mesmo quando migrations/ não está no PYTHONPATH.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Reusa o engine e o Base já existentes em app/db.py (mesmo arquivo SQLite,
# mesma DeclarativeBase) em vez de duplicar a URL de conexão aqui -- evita
# alembic.ini e app/db.py divergirem sobre onde fica o banco.
from app.db import Base, engine  # noqa: E402

# Garante que todos os modelos (inclusive CRM) estão registrados em
# Base.metadata antes do autogenerate comparar contra o banco real --
# mesmo import lazy que app/__init__.py::create_app() já faz.
from app import crm_models  # noqa: E402,F401
from app import crm_financial_models  # noqa: E402,F401
from app import planner_models  # noqa: E402,F401
from app import models  # noqa: E402,F401
from app import document_storage_models  # noqa: E402,F401
from app import financial_planning_models  # noqa: E402,F401

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    context.configure(
        url=str(engine.url),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    Usa o `engine` de app/db.py diretamente (mesma conexão que a aplicação
    usa em runtime) em vez de instanciar outro a partir do alembic.ini.
    `render_as_batch=True` é obrigatório no SQLite: ALTER TABLE nativo só
    suporta ADD COLUMN -- qualquer DROP/ALTER TYPE/RENAME precisa do modo
    batch do Alembic (recria a tabela por trás dos panos, preservando os
    dados).
    """
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
