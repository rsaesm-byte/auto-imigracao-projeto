"""Área-level staff permissions -- painel do CEO (Prompt Mestre 1, Seção
13, pedido do usuário 2026-08-08: "perfis por área inteira, não ação por
ação"). 6 áreas, o MESMO agrupamento que a equipe já usa de verdade no
menu superior (consultado ao vivo em StaffAreaAccess.StaffNavGlobalLayout
antes de definir esta lista, não inventado do zero):

    CRM                  -- Leads/Clients/Cases/Case Tracking/Comms/Tasks/
                             Documents/Prices/Translations/Completed
    Financial Coaching   -- roster/kanban/perfil/sessões/KPIs de coaching
    Payments             -- Pending/Approved (gate de pagamento antigo) +
                             Payments (CRM)
    Time Management      -- Weekly Planner/Time Tracking
    Customize System     -- Custom Fields/Pipeline Settings/Automations
    Internal Management  -- Dashboard/Reports/Contracts/Credentials

`staff.py` e `crm_staff_ops.py` bundlam rotas de 2 áreas cada (histórico
do código, não reorganizado agora) -- cada um faz seu próprio split por
endpoint dentro do próprio `_require_staff`, em vez de usar
`require_area()` direto. Todos os outros blueprints staff usam
`require_area()` com uma área só.
"""
from __future__ import annotations

from flask import abort
from flask_login import current_user

from app.db import SessionLocal
from app.models import StaffAreaAccess

AREAS: dict[str, str] = {
    "crm": "CRM",
    "financial_coaching": "Financial Coaching",
    "payments": "Payments",
    "time_management": "Time Management",
    "customize_system": "Customize System",
    "internal_management": "Internal Management",
}


def user_areas(user_id: int) -> set[str]:
    return {row.area for row in SessionLocal.query(StaffAreaAccess).filter_by(user_id=user_id).all()}


def has_area(user, area: str) -> bool:
    """CEO (is_ceo=True) sempre passa, sem precisar de linha em
    StaffAreaAccess -- mesmo espírito de "Admin" do modelo aprovado pelo
    usuário: quem gerencia a equipe nunca fica de fora de nenhuma área."""
    if not getattr(user, "is_staff", False):
        return False
    if getattr(user, "is_ceo", False):
        return True
    return area in user_areas(user.id)


def require_area(area: str) -> None:
    """Chamar dentro do `_require_staff` de um blueprint -- aborta 403 se
    o colaborador logado não tiver a área. `area` deve ser uma chave de
    AREAS (não validado aqui de propósito -- erro de digitação vira um 403
    óbvio pra todo mundo em vez de falhar silenciosamente aberto)."""
    if not has_area(current_user, area):
        abort(403)
