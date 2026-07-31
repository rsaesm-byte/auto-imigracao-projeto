"""Modelos SQLAlchemy: usuário e submissões de formulário.

answers_json guarda exatamente o mesmo formato dos arquivos
output/answers-<slug>-e2e.json de hoje (um dict question_id -> valor) —
mesmo formato que is_visible()/active_questions()/validate_required()
(scripts/run_questionnaire.py) e fill_form_for_submission()
(app/services/pdf_service.py) já esperam.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from flask_login import UserMixin
from sqlalchemy import ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base, UserMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(unique=True, index=True)
    password_hash: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
    is_active_: Mapped[bool] = mapped_column(default=True)
    # Acesso ao painel /staff (marcar casos de Cartas Complementares como
    # pagos). Não existe fluxo de auto-cadastro para isso -- é ligado
    # manualmente no banco para as contas da própria equipe.
    is_staff: Mapped[bool] = mapped_column(default=False)
    # Login alternativo, só usado pela equipe hoje (ver app/auth.py::login,
    # aceita e-mail OU username) -- opcional, null pra clientes comuns.
    username: Mapped[str | None] = mapped_column(unique=True, index=True, default=None)
    # Perfil da aba /staff/perfil (app/staff.py) -- preenchido pelo próprio
    # usuário, nunca pela equipe uns dos outros. photo_path aponta pro
    # arquivo em instance/staff_photos/ (fora do git), servido só pra quem
    # está logado como staff (ver staff.profile_photo).
    photo_path: Mapped[str | None] = mapped_column(default=None)
    job_title: Mapped[str | None] = mapped_column(default=None)
    personal_phone: Mapped[str | None] = mapped_column(default=None)
    work_phone: Mapped[str | None] = mapped_column(default=None)
    work_hours: Mapped[str | None] = mapped_column(default=None)

    submissions: Mapped[list["FormSubmission"]] = relationship(
        back_populates="user", cascade="all, delete-orphan")

    # UserMixin.is_active é uma property; sobrescrevemos para usar a coluna
    @property
    def is_active(self) -> bool:  # type: ignore[override]
        return self.is_active_


class FormSubmission(Base):
    __tablename__ = "form_submissions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    form_slug: Mapped[str] = mapped_column(index=True)
    # Só usado por formulários "por dependente" (hoje só I-539A): aponta pro
    # FormSubmission do I-539 principal ao qual este dependente pertence.
    # Null para toda submissão normal (não-dependente).
    parent_submission_id: Mapped[int | None] = mapped_column(
        ForeignKey("form_submissions.id"), default=None, index=True)
    # Preenchido quando a submissão nasceu de um "Iniciar pacote" em
    # app/packages.py (ver data/packages.json) -- usado só para agrupar
    # visualmente no dashboard; null para submissões avulsas.
    package_slug: Mapped[str | None] = mapped_column(default=None, index=True)
    answers_json: Mapped[str] = mapped_column(Text, default="{}")
    # Perguntas opcionais explicitamente deixadas em branco. Sem isso, uma
    # pergunta opcional sem resposta nunca entraria em answers_json e o
    # wizard ficaria perguntando ela pra sempre (achado testando o fluxo
    # completo via HTTP: a mesma pergunta nunca saía de "não respondida").
    skipped_json: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(default="in_progress")  # in_progress | completed
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(default=None)
    filled_pdf_path: Mapped[str | None] = mapped_column(default=None)
    checklist_pdf_path: Mapped[str | None] = mapped_column(default=None)
    documents_pdf_path: Mapped[str | None] = mapped_column(default=None)
    # Só usado pelo pseudo-formulário "i-539-cartas" (sem PDF oficial próprio):
    # zip com o resumo da narrativa + as cartas complementares aplicáveis.
    cartas_zip_path: Mapped[str | None] = mapped_column(default=None)
    # Campos do "núcleo de identidade" pré-preenchidos automaticamente a
    # partir de outra submissão do mesmo usuário (ver
    # app/wizard.py::_build_autofill), ainda não confirmados pelo usuário
    # nesta submissão -- {question_id: form_slug de origem}. Um question_id
    # sai daqui assim que o usuário passa por aquela pergunta no wizard
    # (confirmando ou alterando o valor), então não é "todo campo
    # autopreenchido alguma vez", só os que ainda não foram vistos.
    autofilled_json: Mapped[str] = mapped_column(Text, default="{}")
    # Número de recibo do USCIS, digitado manualmente pelo usuário depois que
    # o caso é protocolado -- não vem do questionário (a maioria dos
    # formulários não pergunta isso, já que o recibo só existe depois do
    # protocolo). Usado só para dar um atalho de "verificar status oficial"
    # no dashboard; não fazemos nenhuma consulta automática ao USCIS (ver
    # references/compliance.md e a decisão desta sessão de não automatizar
    # contorno de CAPTCHA do egov.uscis.gov).
    receipt_number: Mapped[str | None] = mapped_column(default=None)
    # Só usado pelo caso "I-539 — Cartas Complementares" (a submissão
    # i-539-cartas em si, nunca nas 4 cartas de terceiro vinculadas a ela --
    # ver app/wizard.py::_cartas_case): true depois que a equipe confirma
    # manualmente (via /staff) que o cliente pagou pelo serviço, fora do
    # site (Zelle/Venmo/wire/cartão -- ver app/payment_methods.py). Sem
    # isso, generate() recusa gerar a carta narrativa ou qualquer carta de
    # terceiro vinculada a este caso.
    paid: Mapped[bool] = mapped_column(default=False)
    paid_at: Mapped[datetime | None] = mapped_column(default=None)

    user: Mapped[User] = relationship(back_populates="submissions")

    def get_answers(self) -> dict:
        return json.loads(self.answers_json) if self.answers_json else {}

    def set_answers(self, answers: dict) -> None:
        self.answers_json = json.dumps(answers, ensure_ascii=False)

    def get_skipped(self) -> set[str]:
        return set(json.loads(self.skipped_json)) if self.skipped_json else set()

    def set_skipped(self, skipped: set[str]) -> None:
        self.skipped_json = json.dumps(sorted(skipped), ensure_ascii=False)

    def get_autofilled(self) -> dict:
        return json.loads(self.autofilled_json) if self.autofilled_json else {}

    def set_autofilled(self, autofilled: dict) -> None:
        self.autofilled_json = json.dumps(autofilled, ensure_ascii=False)


class Payment(Base):
    """Gate de pagamento genérico (Zelle/Venmo/cartão/wire + comprovante,
    ver app/payment_gate.py) para qualquer formulário avulso ou pacote
    vendido pela Saes conforme data/service_fees.json -- não cobre as
    Cartas Complementares do I-539, que têm seu próprio gate mais simples
    desde antes (FormSubmission.paid/paid_at, ver app/wizard.py::_cartas_case).
    Uma linha por "caso": ou (user_id, package_slug) para um pacote inteiro,
    ou (user_id, submission_id) para um formulário avulso -- submission_id
    aponta pra raiz da cadeia de parent_submission_id quando o formulário
    tem dependentes (ver app/wizard.py::_payment_case), exceto para I-134,
    que sempre tem seu próprio caso/preço (ver mesma função)."""
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    package_slug: Mapped[str | None] = mapped_column(default=None, index=True)
    submission_id: Mapped[int | None] = mapped_column(
        ForeignKey("form_submissions.id"), default=None, index=True)
    amount_cents: Mapped[int]
    method: Mapped[str | None] = mapped_column(default=None)  # zelle | venmo | credit_card | wire
    proof_path: Mapped[str | None] = mapped_column(default=None)
    # Preenchidos pelo cliente na tela de checkout (app/payment_gate.py) --
    # client_phone é o que importa de verdade: quando um staff confirma o
    # pagamento (app/staff.py::confirm_payment), é pra ESSE número que o
    # WhatsApp abre (não o da Saes), pra equipe avisar o cliente direto.
    # client_name/client_email só ficam guardados de referência pra equipe.
    client_name: Mapped[str | None] = mapped_column(default=None)
    client_email: Mapped[str | None] = mapped_column(default=None)
    client_phone: Mapped[str | None] = mapped_column(default=None)
    status: Mapped[str] = mapped_column(default="pending")  # pending | confirmed
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
    confirmed_at: Mapped[datetime | None] = mapped_column(default=None)
    confirmed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None)
    # Ciclo de vida depois da aprovação (painel /staff, abas "Aprovados" /
    # "Finalizados" / "Solicitar Review" -- ver app/staff.py). finalized_at
    # é preenchido quando a equipe marca o caso como encerrado de vez
    # (documentos entregues); review_requested é o "X" que tira o caso da
    # aba "Solicitar Review" depois que a equipe já pediu a avaliação pro
    # cliente -- só faz sentido depois de finalizado.
    finalized_at: Mapped[datetime | None] = mapped_column(default=None)
    review_requested: Mapped[bool] = mapped_column(default=False)


class ServiceFee(Base):
    """Preço cobrado pela Saes Professional Services por um formulário
    avulso ou pacote -- fonte da verdade para app/services/pricing.py
    (não confundir com a taxa oficial da USCIS em data/registry.json).
    Semeada uma vez a partir de data/service_fees.json quando a tabela
    está vazia (ver app/__init__.py::_seed_service_fees) e editável pela
    equipe na aba "Preços" do painel /staff -- dali em diante o arquivo
    JSON só serve de valor inicial/histórico, nunca mais é lido em
    produção. Uma linha por (kind, slug):
      - kind="individual", slug=form_slug: preço quando vendido avulso.
      - kind="in_package", slug=form_slug: preço deste formulário quando
        faz parte de um pacote (usado por I-134 hoje, ver
        app/wizard.py::_payment_case).
      - kind="package", slug=package_slug: preço total do pacote.
    price_cents None = "não vendido separadamente nesse contexto"."""
    __tablename__ = "service_fees"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str]  # individual | in_package | package
    slug: Mapped[str]
    price_cents: Mapped[int | None] = mapped_column(default=None)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)
    updated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None)
