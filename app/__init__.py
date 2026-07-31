"""App factory Flask para o auto-imigração web."""
from __future__ import annotations

import os
from pathlib import Path

from flask import Flask
from flask_login import LoginManager

from app.db import Base, SessionLocal, engine

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")


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


def _ensure_payment_columns() -> None:
    """Mesma lógica de _ensure_cartas_zip_path_column() acima, para as duas
    colunas novas do gate de pagamento das Cartas Complementares
    (paid, paid_at)."""
    from sqlalchemy import text
    with engine.connect() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(form_submissions)"))]
        if "paid" not in cols:
            conn.execute(text("ALTER TABLE form_submissions ADD COLUMN paid BOOLEAN DEFAULT 0"))
            conn.commit()
        if "paid_at" not in cols:
            conn.execute(text("ALTER TABLE form_submissions ADD COLUMN paid_at DATETIME"))
            conn.commit()


def _ensure_staff_column() -> None:
    """Mesma lógica de _ensure_cartas_zip_path_column() acima, para a coluna
    nova de acesso ao painel /staff (users.is_staff)."""
    from sqlalchemy import text
    with engine.connect() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(users)"))]
        if "is_staff" not in cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN is_staff BOOLEAN DEFAULT 0"))
            conn.commit()


def _ensure_staff_profile_columns() -> None:
    """Mesma lógica de _ensure_cartas_zip_path_column() acima, para as
    colunas novas do login por username e do perfil da equipe (aba
    /staff/perfil, ver app/staff.py) -- username precisa de índice único
    à parte, já que SQLite não deixa adicionar UNIQUE junto do ALTER TABLE
    ADD COLUMN."""
    from sqlalchemy import text
    with engine.connect() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(users)"))]
        for col in ("username", "photo_path", "job_title", "personal_phone",
                    "work_phone", "work_hours"):
            if col not in cols:
                conn.execute(text(f"ALTER TABLE users ADD COLUMN {col} VARCHAR"))
                conn.commit()
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_username ON users(username)"))
        conn.commit()


def _ensure_payment_contact_columns() -> None:
    """Mesma lógica de _ensure_cartas_zip_path_column() acima, para as três
    colunas novas de contato do cliente na tela de checkout (client_name,
    client_email, client_phone) -- a tabela payments já existia antes
    delas."""
    from sqlalchemy import text
    with engine.connect() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(payments)"))]
        for col in ("client_name", "client_email", "client_phone"):
            if col not in cols:
                conn.execute(text(f"ALTER TABLE payments ADD COLUMN {col} VARCHAR"))
                conn.commit()


def _ensure_payment_lifecycle_columns() -> None:
    """Mesma lógica de _ensure_cartas_zip_path_column() acima, para as duas
    colunas novas do ciclo de vida pós-aprovação (finalized_at,
    review_requested) -- a tabela payments já existia antes delas."""
    from sqlalchemy import text
    with engine.connect() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(payments)"))]
        if "finalized_at" not in cols:
            conn.execute(text("ALTER TABLE payments ADD COLUMN finalized_at DATETIME"))
            conn.commit()
        if "review_requested" not in cols:
            conn.execute(text("ALTER TABLE payments ADD COLUMN review_requested BOOLEAN DEFAULT 0"))
            conn.commit()


def _seed_service_fees() -> None:
    """Semeia a tabela service_fees (nova, ver app/models.py::ServiceFee) a
    partir de data/service_fees.json -- só roda se a tabela estiver
    vazia, pra nunca sobrescrever preços que a equipe já editou na aba
    "Preços" do painel /staff (ver app/staff.py). Dali em diante o JSON
    vira só o valor inicial/histórico, nunca mais é lido em produção."""
    import json
    from app.db import SessionLocal
    from app.models import ServiceFee

    if SessionLocal.query(ServiceFee).first() is not None:
        return

    path = Path(__file__).resolve().parent.parent / "data" / "service_fees.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    for kind in ("individual", "in_package", "package"):
        for slug, price_cents in raw.get(kind, {}).items():
            SessionLocal.add(ServiceFee(kind=kind, slug=slug, price_cents=price_cents))
    SessionLocal.commit()


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
    _ensure_payment_columns()
    _ensure_staff_column()
    _ensure_payment_contact_columns()
    _ensure_payment_lifecycle_columns()
    _ensure_staff_profile_columns()
    _seed_service_fees()

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
    from app.chatbot import chatbot_bp
    from app.about import about_bp
    from app.payment_methods import payment_methods_bp
    from app.payment_gate import payment_gate_bp
    from app.staff import staff_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(wizard_bp)
    app.register_blueprint(eligibility_bp)
    app.register_blueprint(civics_bp)
    app.register_blueprint(packages_bp)
    app.register_blueprint(medical_exam_bp)
    app.register_blueprint(income_calculator_bp)
    app.register_blueprint(visa_bulletin_bp)
    app.register_blueprint(chatbot_bp)
    app.register_blueprint(about_bp)
    app.register_blueprint(payment_methods_bp)
    app.register_blueprint(payment_gate_bp)
    app.register_blueprint(staff_bp)

    from app.i18n import get_lang, t
    app.jinja_env.globals["t"] = t
    app.jinja_env.globals["get_lang"] = get_lang

    from app.wizard import _form_display_name, _payment_status_for
    app.jinja_env.globals["form_display_name"] = _form_display_name
    app.jinja_env.globals["payment_status_for"] = _payment_status_for

    @app.teardown_appcontext
    def remove_session(exception=None):
        SessionLocal.remove()

    return app
