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
