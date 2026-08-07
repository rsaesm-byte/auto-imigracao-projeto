"""Infra de testes automatizados (Seção 16/17) -- antes desta suíte o
projeto não tinha nenhum teste automatizado.

Sobe um Flask app real via `app.create_app()`, mas redirecionado pra um
banco SQLite temporário e isolado por teste -- nunca o
`instance/app.db` de desenvolvimento. Duas coisas precisam ser
redirecionadas pra isso funcionar (ver app/db.py e app/__init__.py):

- `app.db.SessionLocal` é um `scoped_session` mutável -- basta chamar
  `.configure(bind=test_engine)` pra toda query feita através dele (a
  imensa maioria do código da aplicação) passar a ir pro banco de
  teste.
- `app.__init__.engine` é o binding próprio do módulo (`from app.db
  import ...engine`) que `create_app()` usa direto -- em
  `Base.metadata.create_all(engine)` e nas funções `_ensure_*_column`/
  `_seed_*` (essas usam `engine.connect()` cru, não `SessionLocal`, ver
  `_ensure_cartas_zip_path_column` por exemplo). Como é só um nome no
  namespace do módulo (não uma cópia do objeto Engine), dá pra
  sobrescrever com `monkeypatch.setattr(app_module, "engine",
  test_engine)` antes de chamar `create_app()` -- essas funções resolvem
  `engine` de novo a cada chamada (nome global, não capturado em
  closure), então já pegam o engine de teste.

Sem esses dois redirects, `create_app()` tentaria rodar `create_all` e
as seed functions contra o banco de desenvolvimento de verdade.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app as app_module  # noqa: E402
from app.db import Base, SessionLocal  # noqa: E402


@pytest.fixture()
def test_engine(tmp_path, monkeypatch):
    """Banco SQLite isolado por teste, em arquivo temporário -- não
    `:memory:` porque a aplicação abre mais de uma conexão através do
    mesmo `scoped_session`/pool, e `:memory:` não compartilha estado
    entre conexões diferentes sem configuração extra."""
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    # Garante que todos os modelos estão registrados em Base.metadata
    # antes do create_all (mesmo import lazy que create_app() já faz).
    from app import crm_models, crm_financial_models, planner_models, models, document_storage_models, financial_planning_models  # noqa: F401,E402
    Base.metadata.create_all(engine)

    monkeypatch.setattr(app_module, "engine", engine)
    SessionLocal.configure(bind=engine)

    yield engine

    SessionLocal.remove()
    engine.dispose()


@pytest.fixture()
def app(test_engine):
    """App Flask real, apontado pro banco de teste (ver test_engine acima)."""
    flask_app = app_module.create_app()
    flask_app.config.update(TESTING=True)
    return flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def db(test_engine):
    """`SessionLocal` já redirecionado pro banco de teste -- pra criar
    dado de fixture direto por ORM, sem passar por rota HTTP."""
    return SessionLocal


@pytest.fixture()
def staff_user(db):
    """Quase toda rota do CRM staff exige `current_user.is_staff` (ver
    `_require_staff` em app/crm_staff_ops.py e app/crm_staff_pipeline.py)
    e o gate global de e-mail verificado (app/__init__.py) só deixa
    passar direto quem é staff."""
    from app.models import User
    user = User(email="staff@example.com", password_hash="x", is_staff=True, email_verified=True)
    db.add(user)
    db.commit()
    return user


@pytest.fixture()
def logged_in_client(client, staff_user):
    """Test client com uma sessão Flask-Login já autenticada como
    `staff_user` -- injeta a sessão direto (mesma técnica recomendada
    pelo próprio Flask-Login pra testes), sem passar pela tela de
    login.

    Captura `staff_user.id` num int ANTES de abrir `session_transaction`
    -- esse método empurra e depois derruba um app context de verdade,
    o que dispara `@app.teardown_appcontext -> SessionLocal.remove()`
    (app/__init__.py) e desanexa `staff_user` da sessão; acessar
    `.id` depois disso levantaria `DetachedInstanceError`."""
    user_id = staff_user.id
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True
    return client


@pytest.fixture()
def client_record(db):
    """Client mínimo (app/crm_models.py::Client) pra testes que precisam
    de um cliente já existente."""
    from app.crm_models import Client
    c = Client(full_name="Cliente de Teste")
    db.add(c)
    db.commit()
    return c


@pytest.fixture()
def case_record(db, client_record):
    """Case mínimo associado a `client_record`."""
    from app.crm_models import Case, ServiceMode
    case = Case(client_id=client_record.id, title="Caso de Teste", service_mode=ServiceMode.self_service)
    db.add(case)
    db.commit()
    return case
