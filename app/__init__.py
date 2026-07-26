"""App factory Flask para o auto-imigração web."""
from __future__ import annotations

import os

from flask import Flask
from flask_login import LoginManager

from app.db import Base, SessionLocal, engine


def _ensure_cartas_zip_path_column() -> None:
    """create_all() só cria TABELAS que faltam, nunca altera colunas de uma
    tabela já existente. Bancos SQLite de sessões anteriores (antes da
    coluna cartas_zip_path existir no modelo) precisam desse ALTER TABLE
    manual uma vez -- idempotente, seguro de rodar toda vez que o app sobe."""
    from sqlalchemy import text
    with engine.connect() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(form_submissions)"))]
        if "cartas_zip_path" not in cols:
            conn.execute(text("ALTER TABLE form_submissions ADD COLUMN cartas_zip_path VARCHAR"))
            conn.commit()


def _ensure_package_columns() -> None:
    """Mesma lógica de _ensure_cartas_zip_path_column() acima, para as duas
    colunas novas da feature de pacotes (parent_submission_id, package_slug)."""
    from sqlalchemy import text
    with engine.connect() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(form_submissions)"))]
        if "parent_submission_id" not in cols:
            conn.execute(text("ALTER TABLE form_submissions ADD COLUMN parent_submission_id INTEGER"))
            conn.commit()
        if "package_slug" not in cols:
            conn.execute(text("ALTER TABLE form_submissions ADD COLUMN package_slug VARCHAR"))
            conn.commit()


def _ensure_autofilled_column() -> None:
    """Mesma lógica de _ensure_cartas_zip_path_column() acima, para a coluna
    nova da feature de autofill entre formulários (autofilled_json)."""
    from sqlalchemy import text
    with engine.connect() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(form_submissions)"))]
        if "autofilled_json" not in cols:
            conn.execute(text(
                "ALTER TABLE form_submissions ADD COLUMN autofilled_json TEXT DEFAULT '{}'"))
            conn.commit()


def _ensure_receipt_number_column() -> None:
    """Mesma lógica de _ensure_cartas_zip_path_column() acima, para a coluna
    nova do atalho de status de caso (receipt_number)."""
    from sqlalchemy import text
    with engine.connect() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(form_submissions)"))]
        if "receipt_number" not in cols:
            conn.execute(text("ALTER TABLE form_submissions ADD COLUMN receipt_number VARCHAR"))
            conn.commit()


def create_app() -> Flask:
    app = Flask(__name__)

    secret = os.environ.get("FLASK_SECRET_KEY")
    if not secret:
        # Só aceitável em desenvolvimento local -- em produção FLASK_SECRET_KEY
        # é obrigatório (ver plano: Fase 5 / hardening).
        secret = "dev-only-insecure-secret-change-me"
    app.config["SECRET_KEY"] = secret

    # Garante que todos os modelos foram importados antes do create_all().
    from app import models  # noqa: F401
    Base.metadata.create_all(engine)
    _ensure_cartas_zip_path_column()
    _ensure_package_columns()
    _ensure_autofilled_column()
    _ensure_receipt_number_column()

    login_manager = LoginManager()
    login_manager.login_view = "auth.login"
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id: str):
        from app.models import User
        return SessionLocal.get(User, int(user_id))

    from app.auth import auth_bp
    from app.wizard import wizard_bp
    from app.eligibility import eligibility_bp
    from app.civics import civics_bp
    from app.packages import packages_bp
    from app.medical_exam import medical_exam_bp
    from app.income_calculator import income_calculator_bp
    from app.visa_bulletin import visa_bulletin_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(wizard_bp)
    app.register_blueprint(eligibility_bp)
    app.register_blueprint(civics_bp)
    app.register_blueprint(packages_bp)
    app.register_blueprint(medical_exam_bp)
    app.register_blueprint(income_calculator_bp)
    app.register_blueprint(visa_bulletin_bp)

    from app.i18n import get_lang, t
    app.jinja_env.globals["t"] = t
    app.jinja_env.globals["get_lang"] = get_lang

    @app.teardown_appcontext
    def remove_session(exception=None):
        SessionLocal.remove()

    return app
