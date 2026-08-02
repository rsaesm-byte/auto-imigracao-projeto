"""Gera 4 clientes FICTÍCIOS logáveis, cada um parado num estágio
diferente do pipeline pós-pagamento (app/staff.py::confirm_payment ->
app/onboarding.py -> app/staff.py "Documentos"), para o usuário testar as
telas de cliente e de staff lado a lado em cada estágio:

  1. Ana Pendente      -- pagamento ainda não aprovado pela equipe
                          (aba "Aprovações Pendentes").
  2. Bruno Onboarding  -- pagamento aprovado, onboarding recém-criado:
                          endereço ainda não confirmado, checklist vazio
                          (equipe ainda não cadastrou os documentos).
  3. Carla Documentos  -- endereço confirmado, checklist com 3 itens em
                          3 estados diferentes (aprovado / aguardando
                          revisão / aguardando envio) -- mostra o contador
                          da aba "Documentos" do staff com >0.
  4. Diego Finalizado  -- tudo aprovado, caso finalizado (aba
                          "Finalizados" e "Solicitar Review" do staff).

Marcação para identificar/apagar depois: todo e-mail criado aqui começa
com "demo.flow." e termina em "@demo.example" -- nunca colide com cliente
real nem com os e-mails de scripts/seed_demo_crm_data.py. Ver
`wipe_demo_data()` no final (roda com --wipe).

Rodar com: python scripts/seed_demo_onboarding_flows.py
(da raiz do projeto, mesmo venv do site).
"""
from __future__ import annotations

import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from werkzeug.security import generate_password_hash

from app import create_app
from app.db import SessionLocal
from app.models import OnboardingDependent, Payment, PostPaymentOnboarding, RequiredDocument, User
from app.onboarding import DOCUMENTS_DIR

DEMO_PREFIX = "demo.flow."
DEMO_DOMAIN = "@demo.example"
DEMO_PASSWORD = "demo12345"


def _email(local: str) -> str:
    return f"{DEMO_PREFIX}{local}{DEMO_DOMAIN}"


def _make_user(local: str) -> User:
    user = User(email=_email(local), password_hash=generate_password_hash(DEMO_PASSWORD), is_staff=False)
    SessionLocal.add(user)
    SessionLocal.flush()
    return user


def _placeholder_file(name: str) -> str:
    """Cria um arquivo de exemplo em instance/onboarding_documents (mesma
    pasta usada por app/onboarding.py::_save_document) só pra o botão
    "Baixar"/"Ver arquivo enviado" ter algo real pra abrir na demo."""
    dest = DOCUMENTS_DIR / f"{uuid.uuid4().hex}.txt"
    dest.write_text(f"Documento de demonstração: {name}\n(arquivo fictício, sem conteúdo real)\n", encoding="utf-8")
    return str(dest)


def _package_price_cents(slug: str) -> int:
    from app.services.pricing import package_price_cents
    return package_price_cents(slug) or 250000


def seed() -> None:
    app = create_app()
    with app.app_context():
        now = datetime.now(timezone.utc)

        # 1. Ana Pendente -- aguardando aprovação do staff.
        ana = _make_user("pendente")
        SessionLocal.add(Payment(
            user_id=ana.id, package_slug="i539-eos",
            amount_cents=_package_price_cents("i539-eos"), status="pending",
            client_name="Ana Pendente", client_email=ana.email, client_phone="15550001111",
            created_at=now - timedelta(hours=6)))

        # 2. Bruno Onboarding -- aprovado, endereço ainda não confirmado.
        bruno = _make_user("onboarding")
        bruno_payment = Payment(
            user_id=bruno.id, package_slug="gc-aos",
            amount_cents=_package_price_cents("gc-aos"), status="confirmed",
            client_name="Bruno Onboarding", client_email=bruno.email, client_phone="15550002222",
            created_at=now - timedelta(days=2), confirmed_at=now - timedelta(days=1))
        SessionLocal.add(bruno_payment)
        SessionLocal.flush()
        SessionLocal.add(PostPaymentOnboarding(payment_id=bruno_payment.id, address_confirmed=False))

        # 3. Carla Documentos -- endereço confirmado, checklist misto.
        carla = _make_user("documentos")
        carla_payment = Payment(
            user_id=carla.id, package_slug="gc-consular",
            amount_cents=_package_price_cents("gc-consular"), status="confirmed",
            client_name="Carla Documentos", client_email=carla.email, client_phone="15550003333",
            created_at=now - timedelta(days=5), confirmed_at=now - timedelta(days=4))
        SessionLocal.add(carla_payment)
        SessionLocal.flush()
        carla_onboarding = PostPaymentOnboarding(
            payment_id=carla_payment.id, address_confirmed=True,
            us_address_line1="789 Ocean Ave", us_address_complement="Unit 12",
            us_city="Orlando", us_state="FL", us_zip="32801",
            applicant_email="carla.titular@demo.example")
        SessionLocal.add(carla_onboarding)
        SessionLocal.flush()
        SessionLocal.add(OnboardingDependent(
            onboarding_id=carla_onboarding.id, full_name="Pedro Documentos (filho)",
            email="pedro.documentos@demo.example"))
        SessionLocal.add(RequiredDocument(
            onboarding_id=carla_onboarding.id, label="Passaporte (todas as páginas)",
            status="approved", file_path=_placeholder_file("Passaporte"),
            uploaded_at=now - timedelta(days=3), staff_notes="Recebido, tudo certo.",
            reviewed_at=now - timedelta(days=2)))
        SessionLocal.add(RequiredDocument(
            onboarding_id=carla_onboarding.id, label="Comprovante de residência",
            status="uploaded", file_path=_placeholder_file("Comprovante de residência"),
            uploaded_at=now - timedelta(hours=3)))
        SessionLocal.add(RequiredDocument(
            onboarding_id=carla_onboarding.id, label="Certidão de casamento (tradução juramentada)",
            status="pending"))

        # 4. Diego Finalizado -- caso encerrado, tudo aprovado.
        diego = _make_user("finalizado")
        diego_payment = Payment(
            user_id=diego.id, package_slug="cidadania",
            amount_cents=_package_price_cents("cidadania"), status="confirmed",
            client_name="Diego Finalizado", client_email=diego.email, client_phone="15550004444",
            created_at=now - timedelta(days=30), confirmed_at=now - timedelta(days=29),
            finalized_at=now - timedelta(days=2), review_requested=False)
        SessionLocal.add(diego_payment)
        SessionLocal.flush()
        diego_onboarding = PostPaymentOnboarding(
            payment_id=diego_payment.id, address_confirmed=True,
            us_address_line1="200 Liberty St", us_address_complement=None,
            us_city="Newark", us_state="NJ", us_zip="07102",
            applicant_email="diego.titular@demo.example")
        SessionLocal.add(diego_onboarding)
        SessionLocal.flush()
        SessionLocal.add(OnboardingDependent(
            onboarding_id=diego_onboarding.id, full_name="Diego Finalizado Jr.",
            email="diegojr@demo.example"))
        SessionLocal.add(RequiredDocument(
            onboarding_id=diego_onboarding.id, label="Passaporte (todas as páginas)",
            status="approved", file_path=_placeholder_file("Passaporte"),
            uploaded_at=now - timedelta(days=28), staff_notes="Ok.",
            reviewed_at=now - timedelta(days=27)))
        SessionLocal.add(RequiredDocument(
            onboarding_id=diego_onboarding.id, label="Certidão de nascimento",
            status="approved", file_path=_placeholder_file("Certidão de nascimento"),
            uploaded_at=now - timedelta(days=28), staff_notes="Ok.",
            reviewed_at=now - timedelta(days=27)))

        SessionLocal.commit()
        _print_summary()


def wipe_demo_data() -> None:
    """Apaga TUDO criado por seed() -- identificado pelo prefixo de e-mail
    "demo.flow.", em ordem segura de FK. Seguro rodar mesmo se seed() nunca
    rodou (não acha nada, não faz nada)."""
    import os

    app = create_app()
    with app.app_context():
        user_ids = [u.id for u in SessionLocal.query(User.id)
                    .filter(User.email.like(f"{DEMO_PREFIX}%")).all()]
        payment_ids = [p.id for p in SessionLocal.query(Payment.id)
                       .filter(Payment.user_id.in_(user_ids or [0])).all()]
        onboarding_rows = SessionLocal.query(PostPaymentOnboarding.id, PostPaymentOnboarding.payment_id).filter(
            PostPaymentOnboarding.payment_id.in_(payment_ids or [0])).all()
        onboarding_ids = [row[0] for row in onboarding_rows]

        docs = SessionLocal.query(RequiredDocument).filter(
            RequiredDocument.onboarding_id.in_(onboarding_ids or [0])).all()
        for d in docs:
            if d.file_path and os.path.exists(d.file_path):
                os.remove(d.file_path)

        SessionLocal.query(RequiredDocument).filter(
            RequiredDocument.onboarding_id.in_(onboarding_ids or [0])).delete(synchronize_session=False)
        SessionLocal.query(OnboardingDependent).filter(
            OnboardingDependent.onboarding_id.in_(onboarding_ids or [0])).delete(synchronize_session=False)
        SessionLocal.flush()
        SessionLocal.query(PostPaymentOnboarding).filter(
            PostPaymentOnboarding.id.in_(onboarding_ids or [0])).delete(synchronize_session=False)
        SessionLocal.flush()
        SessionLocal.query(Payment).filter(Payment.id.in_(payment_ids or [0])).delete(synchronize_session=False)
        SessionLocal.flush()
        SessionLocal.query(User).filter(User.id.in_(user_ids or [0])).delete(synchronize_session=False)
        SessionLocal.commit()
        print(f"Removidos: {len(user_ids)} contas de login, {len(payment_ids)} pagamentos, "
              f"{len(onboarding_ids)} onboardings, {len(docs)} documentos.")


def _print_summary() -> None:
    print("=" * 70)
    print("4 exemplos de fluxo criados com sucesso.")
    print("=" * 70)
    print(f"Senha de todos: {DEMO_PASSWORD}")
    print()
    print(f"1. Ana Pendente      -- {_email('pendente')}")
    print("   Pagamento aguardando aprovação. Veja em /staff/pendentes.")
    print()
    print(f"2. Bruno Onboarding  -- {_email('onboarding')}")
    print("   Pagamento aprovado, endereço ainda não confirmado. Login como")
    print("   cliente mostra o aviso no dashboard; /staff/documentos mostra")
    print("   'Endereço confirmado: Não'.")
    print()
    print(f"3. Carla Documentos  -- {_email('documentos')}")
    print("   Endereço confirmado, checklist com 1 aprovado + 1 aguardando")
    print("   revisão (aparece no contador de /staff/documentos) + 1 ainda")
    print("   não enviado.")
    print()
    print(f"4. Diego Finalizado  -- {_email('finalizado')}")
    print("   Caso encerrado, todos os documentos aprovados. Veja em")
    print("   /staff/finalizados e /staff/solicitar-review.")
    print()
    print("Para apagar tudo depois: python scripts/seed_demo_onboarding_flows.py --wipe")


if __name__ == "__main__":
    if "--wipe" in sys.argv:
        wipe_demo_data()
    else:
        seed()
