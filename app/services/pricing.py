"""Preços cobrados pela Saes Professional Services por formulário avulso ou
pacote -- não confundir com a taxa oficial da USCIS (data/registry.json).
Fonte da verdade: tabela ServiceFee (app/models.py), semeada uma vez a
partir de data/service_fees.json quando está vazia (ver
app/__init__.py::_seed_service_fees) e editável pela equipe na aba
"Preços" do painel /staff (ver app/staff.py) -- uma edição ali reflete
imediatamente aqui, em /servicos e em /pacotes, sem precisar reiniciar o
servidor. Usado pelo gate de pagamento genérico (app/wizard.py::
_payment_case, app/payment_gate.py); as Cartas Complementares do I-539 têm
seu próprio gate mais simples e não passam por aqui (ver
app/wizard.py::_cartas_case)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from flask_login import current_user

from app.db import SessionLocal
from app.models import Payment, ServiceFee

ROOT = Path(__file__).resolve().parent.parent.parent
_PACKAGES_PATH = ROOT / "data" / "packages.json"

_packages_cache: list[dict] | None = None


def _get_fee(kind: str, slug: str) -> int | None:
    row = SessionLocal.query(ServiceFee).filter_by(kind=kind, slug=slug).first()
    return row.price_cents if row is not None else None


def individual_price_cents(form_slug: str) -> int | None:
    return _get_fee("individual", form_slug)


def package_price_cents(package_slug: str) -> int | None:
    return _get_fee("package", package_slug)


def in_package_price_cents(form_slug: str) -> int | None:
    """Preço deste formulário quando faz parte de um pacote -- só usado
    hoje pelo I-134 (ver app/wizard.py::_payment_case), que tem preço
    próprio mesmo dentro de um caso de pacote."""
    return _get_fee("in_package", form_slug)


def all_fees() -> list[ServiceFee]:
    """Usado pela aba "Preços" do painel /staff para listar tudo que dá
    pra editar. Ordenado por kind depois slug pra ficar estável na tela."""
    return SessionLocal.query(ServiceFee).order_by(ServiceFee.kind, ServiceFee.slug).all()


def set_fee(kind: str, slug: str, price_cents: int | None, updated_by_user_id: int) -> None:
    row = SessionLocal.query(ServiceFee).filter_by(kind=kind, slug=slug).first()
    if row is None:
        row = ServiceFee(kind=kind, slug=slug)
        SessionLocal.add(row)
    row.price_cents = price_cents
    row.updated_by_user_id = updated_by_user_id
    SessionLocal.commit()


def package_display_name(slug: str, lang: str | None = None) -> str:
    """`lang` força um idioma específico (usado pela mensagem do WhatsApp em
    app/payment_gate.py, que precisa do rótulo sempre em inglês independente
    do idioma da sessão) -- por padrão usa o idioma atual da sessão."""
    global _packages_cache
    if _packages_cache is None:
        _packages_cache = json.loads(_PACKAGES_PATH.read_text(encoding="utf-8"))["packages"]
    pkg = next((p for p in _packages_cache if p["slug"] == slug), None)
    if pkg is None:
        return slug
    from app.i18n import DEFAULT_LANG, get_lang
    lang = lang or get_lang()
    if lang != DEFAULT_LANG:
        alt = pkg.get(f"name_{lang}")
        if alt:
            return alt
    return pkg.get("name", slug)


@dataclass
class PaymentCase:
    """Descreve o "caso" de pagamento genérico ao qual uma submissão
    pertence -- ver app/wizard.py::_payment_case para como isso é
    montado. `key` é o package_slug (kind="package") ou o id da submissão
    raiz/própria em string (kind="form"), usado por find_payment_for_case
    para achar o Payment já existente desse caso. `label` é no idioma da
    sessão (mostrado na tela de checkout); `label_en` é sempre em inglês,
    usado só na mensagem do WhatsApp (app/payment_gate.py::_whatsapp_url)
    -- decisão do usuário de 2026-07-31: a mensagem pro WhatsApp da equipe
    tem que ficar em inglês mesmo com o site em português/espanhol."""
    kind: str  # "package" | "form" | "professional"
    key: str
    price_cents: int
    label: str
    label_en: str


def find_payment_for_case(case: PaymentCase) -> Payment | None:
    query = SessionLocal.query(Payment).filter_by(user_id=current_user.id)
    if case.kind == "package":
        query = query.filter_by(package_slug=case.key)
    elif case.kind == "professional":
        query = query.filter_by(lead_id=int(case.key))
    else:
        query = query.filter_by(submission_id=int(case.key))
    return query.order_by(Payment.id.desc()).first()
