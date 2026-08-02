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


def _ensure_ds160_draft_pdf_column() -> None:
    """Mesma lógica de _ensure_cartas_zip_path_column() acima, para a
    coluna nova do pseudo-formulário "ds160" (ds160_draft_pdf_path)."""
    from sqlalchemy import text
    with engine.connect() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(form_submissions)"))]
        if "ds160_draft_pdf_path" not in cols:
            conn.execute(text("ALTER TABLE form_submissions ADD COLUMN ds160_draft_pdf_path VARCHAR"))
            conn.commit()


def _ensure_case_ds160_visa_type_column() -> None:
    """Mesma lógica de _ensure_cartas_zip_path_column() acima, para o gate
    do rascunho de DS-160 (Case.ds160_visa_type, ver
    app/crm_models.py::VisaDraftType)."""
    from sqlalchemy import text
    with engine.connect() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(crm_cases)"))]
        if "ds160_visa_type" not in cols:
            conn.execute(text("ALTER TABLE crm_cases ADD COLUMN ds160_visa_type VARCHAR"))
            conn.commit()


def _ensure_service_catalog_slug_column() -> None:
    """Mesma lógica de _ensure_cartas_zip_path_column() acima, para a
    coluna `slug` nova de ServiceCatalog (chave estável que liga um
    serviço do catálogo a um template de procedimento em
    data/service_procedures/<slug>.json, ver
    app/services/service_procedures.py). Índice único criado à parte --
    SQLite não aceita UNIQUE dentro de um ADD COLUMN."""
    from sqlalchemy import text
    with engine.connect() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(crm_services_catalog)"))]
        if "slug" not in cols:
            conn.execute(text("ALTER TABLE crm_services_catalog ADD COLUMN slug VARCHAR"))
            conn.commit()
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_crm_services_catalog_slug "
            "ON crm_services_catalog (slug)"))
        conn.commit()


def _ensure_service_catalog_price_columns() -> None:
    """Mesma lógica de _ensure_cartas_zip_path_column() acima, pras colunas
    novas de preço/auditoria em ServiceCatalog: updated_at/
    updated_by_user_id (2026-08-02, primeira leva) e plus_price_cents
    (2026-08-02, mesmo dia, depois de ler os contratos reais em
    Downloads/Contratos -- cada um dos 15 "Pacotes Completos" tem preço
    Standard E Plus distintos). Ver docstring do modelo em
    app/crm_models.py."""
    from sqlalchemy import text
    with engine.connect() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(crm_services_catalog)"))]
        if "updated_at" not in cols:
            conn.execute(text("ALTER TABLE crm_services_catalog ADD COLUMN updated_at DATETIME"))
            conn.commit()
        if "updated_by_user_id" not in cols:
            conn.execute(text("ALTER TABLE crm_services_catalog ADD COLUMN updated_by_user_id INTEGER"))
            conn.commit()
        if "plus_price_cents" not in cols:
            conn.execute(text("ALTER TABLE crm_services_catalog ADD COLUMN plus_price_cents INTEGER"))
            conn.commit()
        if "plus_price_paper_cents" not in cols:
            conn.execute(text("ALTER TABLE crm_services_catalog ADD COLUMN plus_price_paper_cents INTEGER"))
            conn.commit()


def _migrate_service_mode_full_service() -> None:
    """`ServiceMode.full_service` virou dois níveis de atendimento
    (`saes_standard`/`saes_plus`, ver app/crm_models.py::ServiceMode,
    pedido do usuário 2026-08-01) -- qualquer `Case` gravado com o valor
    antigo vira `saes_standard` (o nível "padrão"), idempotente e seguro
    de rodar mesmo sem nenhuma linha para migrar."""
    from sqlalchemy import text
    with engine.connect() as conn:
        conn.execute(text(
            "UPDATE crm_cases SET service_mode = 'saes_standard' WHERE service_mode = 'full_service'"))
        conn.commit()


def _ensure_onboarding_applicant_columns() -> None:
    """Mesma lógica de _ensure_cartas_zip_path_column() acima, para os 2
    campos novos do titular em post_payment_onboarding (nome completo,
    telefone nos EUA) e o telefone por dependente em onboarding_dependents
    -- pedido do usuário (2026-08-01) pra sincronizar com Client/
    ClientDependent do CRM (ver app/onboarding.py::detail)."""
    from sqlalchemy import text
    with engine.connect() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(post_payment_onboarding)"))]
        if "applicant_full_name" not in cols:
            conn.execute(text("ALTER TABLE post_payment_onboarding ADD COLUMN applicant_full_name VARCHAR"))
            conn.commit()
        if "applicant_us_phone" not in cols:
            conn.execute(text("ALTER TABLE post_payment_onboarding ADD COLUMN applicant_us_phone VARCHAR"))
            conn.commit()
        dep_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(onboarding_dependents)"))]
        if "us_phone" not in dep_cols:
            conn.execute(text("ALTER TABLE onboarding_dependents ADD COLUMN us_phone VARCHAR"))
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


def _ensure_crm_case_link_columns() -> None:
    """Mesma lógica de _ensure_cartas_zip_path_column() acima, para o
    `case_id` opcional novo em form_submissions e payments (ver
    app/models.py) -- liga cada um a um Case do CRM (app/crm_models.py)
    quando existir, sem quebrar nenhuma linha já gravada antes do CRM
    existir (fica NULL).

    A cláusula `REFERENCES crm_cases(id)` no próprio ADD COLUMN é
    obrigatória, não cosmética: SQLite só faz cumprir uma foreign key que
    esteja de fato na definição da coluna (confirmado empiricamente) --
    sem ela, `PRAGMA foreign_keys=ON` (app/db.py) não protegeria nada
    nestas duas colunas em nenhum banco que já existia antes deste
    deploy (o cenário real de produção), permitindo um case_id órfão
    silencioso."""
    from sqlalchemy import text
    with engine.connect() as conn:
        for table in ("form_submissions", "payments"):
            cols = [row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))]
            if "case_id" not in cols:
                conn.execute(text(
                    f"ALTER TABLE {table} ADD COLUMN case_id INTEGER REFERENCES crm_cases(id)"))
                conn.commit()


def _ensure_financial_payment_link_column() -> None:
    """`crm_payments_ledger` (Fase 1) ganha `financial_client_id` opcional
    e `client_id` vira opcional também (Fase 2 -- Coaching Financeiro reusa
    o mesmo ledger em vez de duplicar "Payments" por linha de negócio, ver
    app/crm_models.py::PaymentLedgerEntry). `client_id` já existia como
    NOT NULL desde a Fase 1 -- SQLite não altera nullability de uma coluna
    existente via ALTER TABLE, só via recriar a tabela. Como esta tabela é
    nova (criada nesta mesma leva de mudanças) e nenhuma instalação real
    ainda gravou nela, o caminho simples (recriar do zero) é seguro; a
    checagem de linha vazia é só uma trava de segurança caso essa premissa
    deixe de valer no futuro -- aí some **precisa** de uma migração de
    verdade (copiar dados pra uma tabela nova), não deste atalho."""
    from sqlalchemy import text
    with engine.connect() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(crm_payments_ledger)"))]
        if "financial_client_id" in cols:
            return
        count = conn.execute(text("SELECT COUNT(*) FROM crm_payments_ledger")).scalar()
        if count and count > 0:
            raise RuntimeError(
                "crm_payments_ledger já tem linhas e precisa ganhar financial_client_id "
                "(coaching financeiro) -- isso exige uma migração de verdade (recriar a "
                "tabela preservando os dados), não o atalho de _ensure_financial_payment_link_column(). "
                "Pare e escreva essa migração antes de continuar.")
        from app.crm_models import PaymentLedgerEntry
        PaymentLedgerEntry.__table__.drop(engine)
        PaymentLedgerEntry.__table__.create(engine)


def _seed_crm_lookups() -> None:
    """Semeia as tabelas de lookup do CRM (app/crm_models.py) a partir de
    data/crm_lookups.json -- mesmo padrão de _seed_service_fees() abaixo:
    só roda por tabela vazia, pra nunca sobrescrever um valor que a equipe
    já tenha editado/adicionado depois do seed inicial."""
    import json
    from app.db import SessionLocal
    from app.crm_models import (AdSource, CloseLossReason, ContactChannel,
                                 FeeType, FieldOffice, IncomeSourceType,
                                 LeadSource, PaymentMethodLookup)

    path = Path(__file__).resolve().parent.parent / "data" / "crm_lookups.json"
    raw = json.loads(path.read_text(encoding="utf-8"))

    simple_lookups = {
        "lead_sources": LeadSource,
        "ad_sources": AdSource,
        "contact_channels": ContactChannel,
        "fee_types": FeeType,
        "close_loss_reasons": CloseLossReason,
        "income_source_types": IncomeSourceType,
        "payment_methods": PaymentMethodLookup,
    }
    for key, model in simple_lookups.items():
        if SessionLocal.query(model).first() is not None:
            continue
        for name in raw.get(key, []):
            SessionLocal.add(model(name=name))

    if SessionLocal.query(FieldOffice).first() is None:
        for entry in raw.get("field_offices", []):
            SessionLocal.add(FieldOffice(name=entry["name"], address=entry.get("address")))

    SessionLocal.commit()


def _seed_crm_financial_lookups() -> None:
    """Semeia os lookups novos do Coaching Financeiro (Fase 2) a partir de
    data/crm_financial_lookups.json. As tabelas totalmente novas
    (financial_goals/challenges/task_categories) seguem o mesmo padrão de
    _seed_crm_lookups() (só roda por tabela vazia). `close_loss_reasons`
    já existe da Fase 1 com outras linhas -- aqui só ACRESCENTA os motivos
    específicos de coaching que ainda não estiverem lá (checagem por nome,
    não por tabela vazia, já que a tabela não está vazia)."""
    import json
    from app.db import SessionLocal
    from app.crm_models import CloseLossReason
    from app.crm_financial_models import (FinancialChallenge, FinancialGoal,
                                           FinancialTaskCategory)

    path = Path(__file__).resolve().parent.parent / "data" / "crm_financial_lookups.json"
    raw = json.loads(path.read_text(encoding="utf-8"))

    simple_lookups = {
        "financial_goals": FinancialGoal,
        "financial_challenges": FinancialChallenge,
        "financial_task_categories": FinancialTaskCategory,
    }
    for key, model in simple_lookups.items():
        if SessionLocal.query(model).first() is not None:
            continue
        for name in raw.get(key, []):
            SessionLocal.add(model(name=name))

    existing_reasons = {r.name for r in SessionLocal.query(CloseLossReason).all()}
    for name in raw.get("additional_close_loss_reasons", []):
        if name not in existing_reasons:
            SessionLocal.add(CloseLossReason(name=name))

    SessionLocal.commit()


def _ensure_document_status_column() -> None:
    """Mesma lógica de _ensure_cartas_zip_path_column() acima, para a coluna
    nova de status unificado de Document (DocumentStatus, pedido do
    usuário 2026-08-02) -- default 'pending' pros 4 documentos já
    existentes na tabela real."""
    from sqlalchemy import text
    with engine.connect() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(crm_documents)"))]
        if "status" not in cols:
            conn.execute(text("ALTER TABLE crm_documents ADD COLUMN status VARCHAR DEFAULT 'pending'"))
            conn.commit()


def _seed_translators() -> None:
    """Pré-cadastra os 5 tradutores já usados pela equipe hoje (pedido do
    usuário 2026-08-02) -- só o nome; endereço/telefone/idiomas/forma de
    pagamento/dados bancários ficam em branco até o staff completar a
    ficha em /staff/crm/traducoes. Checagem por nome (não por tabela
    vazia), pra permitir adicionar um tradutor novo no futuro sem duplicar
    os 5 já semeados."""
    from app.db import SessionLocal
    from app.crm_models import Translator

    existing_names = {t.full_name for t in SessionLocal.query(Translator).all()}
    for name in ("Rodrigo", "Ricardo", "Helio", "Lucia", "Samuel Eduardo"):
        if name not in existing_names:
            SessionLocal.add(Translator(full_name=name))
    SessionLocal.commit()


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


def _seed_saes_procedure_services() -> None:
    """Cria uma linha em ServiceCatalog (app/crm_models.py) por template em
    data/service_procedures/*.json -- os 15 serviços "Pacotes Completos"
    (Saes Standard/Plus, pedido do usuário 2026-08-01). Preço fica NULL
    (ainda não definido pelo usuário) -- roda por `slug` individualmente
    (não por "tabela vazia" como _seed_service_fees()) pra permitir
    adicionar um serviço novo depois sem duplicar os já existentes, e
    nunca sobrescreve `base_price_cents` se a equipe já tiver editado."""
    import json
    from app.db import SessionLocal
    from app.crm_models import ServiceCatalog

    dir_path = Path(__file__).resolve().parent.parent / "data" / "service_procedures"
    if not dir_path.exists():
        return
    existing_by_slug = {
        s.slug: s for s in SessionLocal.query(ServiceCatalog).filter(ServiceCatalog.slug.is_not(None)).all()
    }
    for file_path in sorted(dir_path.glob("*.json")):
        raw = json.loads(file_path.read_text(encoding="utf-8"))
        slug = raw["service_id"]
        existing = existing_by_slug.get(slug)
        if existing is None:
            SessionLocal.add(ServiceCatalog(name=raw["name"], slug=slug))
        elif existing.name != raw["name"]:
            # `name` é sempre inglês (painel staff, ver feedback_staff_
            # interface_english.md) -- sincroniza aqui se o template mudar
            # de nome, sem nunca tocar em base_price_cents.
            existing.name = raw["name"]
    SessionLocal.commit()


def _backfill_case_for_confirmed_payments() -> None:
    """Roda uma vez por boot: cria o Client+Case do CRM que faltava pra
    QUALQUER pagamento já confirmado antes desta migração existir (pedido
    do usuário, 2026-08-02 -- ver app/staff.py::confirm_payment, que agora
    faz isso automaticamente pra pagamentos confirmados dali em diante).
    Sem isso, contas/pagamentos antigos continuariam sem "Meu Caso"
    mesmo depois da correção. Idempotente: só processa payments com
    case_id IS NULL, então uma segunda chamada não encontra nada a fazer."""
    from app.models import Payment
    from app.services import crm_service as svc

    pending = (
        SessionLocal.query(Payment)
        .filter(Payment.status == "confirmed", Payment.case_id.is_(None))
        .all()
    )
    if not pending:
        return
    from app.staff import _case_label
    for payment in pending:
        case = svc.get_or_create_case_for_payment(payment, case_title=_case_label(payment))
        payment.case_id = case.id
    SessionLocal.commit()


def create_app() -> Flask:
    app = Flask(__name__)

    secret = os.environ.get("FLASK_SECRET_KEY")
    if not secret:
        # Só aceitável em desenvolvimento local -- em produção FLASK_SECRET_KEY
        # é obrigatório (ver plano: Fase 5 / hardening).
        secret = "dev-only-insecure-secret-change-me"
    app.config["SECRET_KEY"] = secret

    # Garante que todos os modelos (inclusive o CRM) foram importados antes
    # do create_all() -- SQLAlchemy ordena a criação das tabelas pelas
    # dependências de FK sozinho, a ordem dos imports aqui não importa.
    from app import crm_models  # noqa: F401
    from app import crm_financial_models  # noqa: F401
    from app import planner_models  # noqa: F401
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
    _ensure_crm_case_link_columns()
    _ensure_financial_payment_link_column()
    _ensure_ds160_draft_pdf_column()
    _ensure_case_ds160_visa_type_column()
    _ensure_service_catalog_slug_column()
    _ensure_service_catalog_price_columns()
    _migrate_service_mode_full_service()
    _ensure_onboarding_applicant_columns()
    _ensure_document_status_column()
    _seed_service_fees()
    _seed_crm_lookups()
    _seed_crm_financial_lookups()
    _seed_saes_procedure_services()
    _seed_translators()
    _backfill_case_for_confirmed_payments()

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
    from app.crm_staff_pipeline import crm_pipeline_bp
    from app.crm_staff_ops import crm_ops_bp
    from app.crm_client import crm_client_bp
    from app.crm_credentials import crm_credentials_bp
    from app.crm_case_tracking import crm_tracking_bp
    from app.crm_translations import crm_translations_bp
    from app.crm_contracts import crm_contracts_bp
    from app.crm_financial_staff import crm_financial_bp
    from app.crm_financial_client import crm_financial_client_bp
    from app.onboarding import onboarding_bp
    from app.planner import planner_bp
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
    app.register_blueprint(crm_pipeline_bp)
    app.register_blueprint(crm_ops_bp)
    app.register_blueprint(crm_client_bp)
    app.register_blueprint(crm_credentials_bp)
    app.register_blueprint(crm_tracking_bp)
    app.register_blueprint(crm_translations_bp)
    app.register_blueprint(crm_contracts_bp)
    app.register_blueprint(crm_financial_bp)
    app.register_blueprint(crm_financial_client_bp)
    app.register_blueprint(onboarding_bp)
    app.register_blueprint(planner_bp)

    @app.context_processor
    def _inject_planner_running_timer():
        # Registrado no nível do app (não de um blueprint específico) de
        # propósito -- o widget de cronômetro aparece em staff_base.html,
        # que é a base compartilhada por VÁRIOS blueprints (staff, CRM,
        # planner); um context_processor de blueprint só injeta pras
        # próprias views dele, deixaria o widget errado/ausente nas
        # páginas de outro blueprint.
        from flask_login import current_user as _cu
        if not getattr(_cu, "is_authenticated", False) or not getattr(_cu, "is_staff", False):
            return {}
        from app.services.planner_service import running_entry_for
        return {"planner_running_entry": running_entry_for(_cu.id)}

    @app.context_processor
    def _inject_staff_nav_slots():
        # Same reasoning as _inject_planner_running_timer() above -- the
        # nav bar itself lives in staff_base.html, shared by several
        # blueprints, so this has to be an app-level context processor
        # (a blueprint-scoped one would only fire for that blueprint's own
        # routes, leaving the nav empty/wrong on every other blueprint's
        # pages).
        from flask import request as _req
        from flask_login import current_user as _cu
        if not getattr(_cu, "is_authenticated", False) or not getattr(_cu, "is_staff", False):
            return {}
        from app.staff_nav import resolve_nav_layout
        return {"staff_nav_slots": resolve_nav_layout(_cu.id, _req.endpoint, _req.blueprint)}

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
