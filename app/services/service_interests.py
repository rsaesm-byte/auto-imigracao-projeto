"""Leitura da lista de serviços mostrada no formulário público de
interesse inicial (app/lead_intake.py) -- dado real em
app/crm_models.py::ServiceInterestOption (crm_service_interest_options),
editável pelo painel do colaborador (reordenar/renomear/adicionar/
apagar, ver app/crm_pipeline_settings.py::service_interest_options).

Até 2026-08-07 esta lista era uma constante Python hardcoded
(`SERVICE_INTEREST_OPTIONS`) -- este módulo virou só um conjunto de
helpers de leitura por cima do banco; o texto exibido continua vindo de
app/translations/*.json (chave `service_interest_{key}`), mesma
convenção de sempre, só a ORDEM/ESTRUTURA (quais itens existem, em que
ordem, quais são cabeçalho de grupo) que deixou de estar em código.
"""
from __future__ import annotations

import re

from app.crm_models import ServiceInterestOption
from app.db import SessionLocal


def all_options() -> list[ServiceInterestOption]:
    """Lista completa, na ordem de exibição -- inclui cabeçalhos de
    grupo (`is_group=True`). Usada pelos templates que renderizam a
    lista inteira (_lead_intake_form.html)."""
    return SessionLocal.query(ServiceInterestOption).order_by(ServiceInterestOption.sort_order).all()


def selectable_options() -> list[ServiceInterestOption]:
    """Só os itens que o visitante de fato marca -- cabeçalhos de grupo
    são só títulos visuais, sem checkbox próprio."""
    return [opt for opt in all_options() if not opt.is_group]


def labels_for_keys(keys: list[str], lang: str = "pt") -> list[str]:
    from app.i18n import t_in
    by_key = {o.key: o for o in all_options()}
    return [t_in(lang, "service_interest_" + k) for k in keys if k in by_key]


def slugs_for_keys(keys: list[str]) -> list[str]:
    by_key = {o.key: o for o in all_options()}
    return [by_key[k].slug for k in keys if k in by_key and by_key[k].slug]


def slugify_key(label: str) -> str:
    """Deriva uma chave estável a partir de um rótulo -- usado quando um
    novo item é criado sem um ServiceCatalog vinculado (que já traria um
    slug pronto). Unicidade fica por conta de quem chama (ver
    `unique_key` abaixo)."""
    base = re.sub(r"[^a-z0-9]+", "_", label.strip().lower()).strip("_")
    return base or "servico"


def unique_key(base: str) -> str:
    """`base`, ou `base_2`/`base_3`/... se já existir -- chamar dentro
    da mesma transação que vai criar a linha, pra não ter duas
    requisições gerando a mesma chave em paralelo (risco baixo nesta
    tela de admin, mas barato de evitar)."""
    existing = {row[0] for row in SessionLocal.query(ServiceInterestOption.key).all()}
    if base not in existing:
        return base
    n = 2
    while f"{base}_{n}" in existing:
        n += 1
    return f"{base}_{n}"
