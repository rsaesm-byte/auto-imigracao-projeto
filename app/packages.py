"""Blueprint da vitrine de pacotes (data/packages.json): como o negócio
realmente vende os serviços -- agrupando o formulário principal com os
formulários administrativos que quase sempre o acompanham (G-1145 de
notificação, G-1450/G-1650 de pagamento) e, no caso do I-539, com o
I-539A repetível por dependente.

"Iniciar pacote" reaproveita 100% do motor de formulário único já
existente (FormSubmission por form_slug) -- só cria uma submissão nova
para cada formulário "core" do pacote de uma vez, marcada com
package_slug para o dashboard conseguir agrupar visualmente. Nenhuma UI
de wizard nova foi necessária para isso."""
from __future__ import annotations

import json
from pathlib import Path

from flask import (Blueprint, abort, flash, redirect, render_template,
                    request, url_for)
from flask_login import current_user, login_required

from app.db import SessionLocal
from app.models import FormSubmission

packages_bp = Blueprint("packages", __name__, url_prefix="/pacotes")

ROOT = Path(__file__).resolve().parent.parent


def _load_packages() -> list[dict]:
    path = ROOT / "data" / "packages.json"
    return json.loads(path.read_text(encoding="utf-8"))["packages"]


def _find_package(slug: str) -> dict | None:
    return next((p for p in _load_packages() if p["slug"] == slug), None)


def _pick(pkg: dict, key: str, lang: str):
    if lang != "pt":
        alt = pkg.get(f"{key}_{lang}")
        if alt:
            return alt
    return pkg.get(key)


def _get_or_create_diy_lead(package_slug: str):
    """Acha um Lead ainda aberto (stage não fechado) desta conta pra este
    pacote DIY, ou cria um novo -- ver app/crm_models.py::Lead.
    interested_package_slug/user_id (campos novos, plano de compra
    self-service). Dispara notify("lead_new") só quando cria de fato, não
    em reaproveitamentos (clique repetido em "Iniciar pacote")."""
    from app.crm_models import Lead, LeadStage, ServiceMode
    from app.services.notification_service import notify

    lead = (
        SessionLocal.query(Lead)
        .filter(Lead.user_id == current_user.id, Lead.interested_package_slug == package_slug)
        .filter(~Lead.stage.in_([LeadStage.closed_won, LeadStage.closed_lost]))
        .order_by(Lead.id.desc())
        .first()
    )
    if lead is not None:
        return lead

    pkg = _find_package(package_slug)
    pkg_name = pkg["name"] if pkg else package_slug
    lead = Lead(
        user_id=current_user.id, name=current_user.email,
        contact_email=current_user.email, stage=LeadStage.new,
        interested_service_mode=ServiceMode.self_service,
        interested_package_slug=package_slug,
    )
    SessionLocal.add(lead)
    SessionLocal.flush()

    notify(
        "lead_new",
        title=f"New package interest — {current_user.email}",
        body=pkg_name,
        url=url_for("crm_pipeline.lead_detail", lead_id=lead.id),
    )
    return lead


def packages_context(lang: str) -> dict:
    """Monta os dois grupos de "como contratar" (pedido do usuário,
    2026-08-02: "Faça Você Mesmo" vs. "Deixe que um profissional faça por
    você", em dois níveis Saes Standard/Plus) -- função própria (não mais
    só o corpo de `index()` abaixo) porque, desde 2026-08-06, a mesma
    seção passou a aparecer dentro da página unificada /servicos (ver
    app/wizard.py::services()), não mais numa página só sua."""
    from app.services.pricing import package_price_cents
    from app.services.service_procedures import load_service_procedure, service_display_name
    from app.wizard import _form_display_name
    from app.crm_models import ServiceCatalog
    packages = []
    for pkg in _load_packages():
        form_items = [i for i in pkg["items"] if i["type"] == "form"]
        packages.append({
            "slug": pkg["slug"],
            "name": _pick(pkg, "name", lang),
            "description": _pick(pkg, "description", lang),
            "form_names": [_form_display_name(i["slug"]) for i in form_items],
            "price_cents": package_price_cents(pkg["slug"]),
        })

    professional_services = []
    procedure_rows = SessionLocal.query(ServiceCatalog).filter(ServiceCatalog.slug.is_not(None)).order_by(
        ServiceCatalog.name).all()
    for s in procedure_rows:
        template = load_service_procedure(s.slug) or {}
        professional_services.append({
            "slug": s.slug, "name": service_display_name(s.slug, lang),
            "free_consultation_minutes": template.get("free_consultation_minutes"),
            "standard_price_cents": s.base_price_cents,
            "plus_price_cents": s.plus_price_cents,
            "plus_price_paper_cents": s.plus_price_paper_cents,
        })

    return {"packages": packages, "professional_services": professional_services}


@packages_bp.route("/")
def index():
    """Pedido do usuário 2026-08-06: "Serviços e Pacotes você deverá
    juntar os dois" -- esta página não existe mais sozinha, virou a seção
    #pacotes de /servicos (ver app/wizard.py::services()). Mantida como
    redirect (não removida) pra não quebrar link/favorito antigo."""
    return redirect(url_for("wizard.services") + "#pacotes")


@packages_bp.route("/<slug>")
def detail(slug: str):
    pkg = _find_package(slug)
    if pkg is None:
        abort(404)
    from app.i18n import get_lang, t
    from app.wizard import _form_display_name
    lang = get_lang()

    items = []
    for item in pkg["items"]:
        if item["type"] == "form":
            items.append({
                "type": "form", "slug": item["slug"],
                "name": _form_display_name(item["slug"]),
                "optional": item.get("optional", False),
                "note": _pick(item, "note", lang),
            })
        elif item["type"] == "payment_choice":
            items.append({
                "type": "payment_choice",
                "options": [{"slug": s, "name": _form_display_name(s)} for s in item["options"]],
                "note": _pick(item, "note", lang),
            })
        elif item["type"] == "repeatable":
            items.append({
                "type": "repeatable", "slug": item["slug"],
                "label": _pick(item, "label", lang),
            })
        elif item["type"] == "external":
            items.append({
                "type": "external", "name": item["name"],
                "note": _pick(item, "note", lang),
            })

    from app.services.pricing import package_price_cents

    return render_template(
        "packages_detail.html",
        slug=slug,
        name=_pick(pkg, "name", lang),
        description=_pick(pkg, "description", lang),
        items=items,
        eligibility_quiz=pkg.get("eligibility_quiz"),
        price_cents=package_price_cents(slug),
    )


@packages_bp.route("/<slug>/iniciar", methods=["POST"])
@login_required
def start_package(slug: str):
    pkg = _find_package(slug)
    if pkg is None:
        abort(404)

    core_form_slugs = [i["slug"] for i in pkg["items"] if i["type"] == "form" and not i.get("optional")]

    created = 0
    for form_slug in core_form_slugs:
        existing = (
            SessionLocal.query(FormSubmission)
            .filter_by(user_id=current_user.id, form_slug=form_slug, status="in_progress")
            .first()
        )
        if existing:
            continue
        submission = FormSubmission(user_id=current_user.id, form_slug=form_slug, package_slug=slug)
        submission.set_answers({})
        SessionLocal.add(submission)
        created += 1

    SessionLocal.commit()
    _get_or_create_diy_lead(slug)

    from app.i18n import t
    if created:
        flash(t("pkg_started_flash"), "success")
    else:
        flash(t("pkg_already_started_flash"), "success")
    return redirect(url_for("wizard.dashboard"))


_TIER_SERVICE_MODE = {
    "standard": "saes_standard",
    "plus": "saes_plus",
    "plus_paper": "saes_plus",
}


def _tier_price_cents(service, tier: str) -> int | None:
    return {
        "standard": service.base_price_cents,
        "plus": service.plus_price_cents,
        "plus_paper": service.plus_price_paper_cents,
    }.get(tier)


def _get_or_create_professional_lead(service, tier: str, price_cents: int):
    """Espelha _get_or_create_diy_lead acima, mas pra pacote profissional
    (ServiceCatalog) -- usa LeadInterestedService em vez de
    interested_package_slug (ver app/crm_models.py::Lead). Reaproveitar um
    lead aberto atualiza o nível/preço escolhido (cliente pode voltar e
    trocar de Standard pra Plus antes de pagar) sem duplicar a linha em
    LeadInterestedService nem disparar uma segunda notificação."""
    from app.crm_models import (Lead, LeadInterestedService, LeadStage,
                                 ServiceMode)
    from app.services.notification_service import notify

    lead = (
        SessionLocal.query(Lead)
        .join(LeadInterestedService, LeadInterestedService.lead_id == Lead.id)
        .filter(Lead.user_id == current_user.id, LeadInterestedService.service_id == service.id)
        .filter(~Lead.stage.in_([LeadStage.closed_won, LeadStage.closed_lost]))
        .order_by(Lead.id.desc())
        .first()
    )
    service_mode = ServiceMode(_TIER_SERVICE_MODE[tier])

    if lead is not None:
        lead.interested_service_mode = service_mode
        lead.selected_price_cents = price_cents
        SessionLocal.commit()
        return lead

    lead = Lead(
        user_id=current_user.id, name=current_user.email,
        contact_email=current_user.email, stage=LeadStage.new,
        interested_service_mode=service_mode, selected_price_cents=price_cents,
    )
    SessionLocal.add(lead)
    SessionLocal.flush()
    SessionLocal.add(LeadInterestedService(lead_id=lead.id, service_id=service.id))
    SessionLocal.commit()

    notify(
        "lead_new",
        title=f"New service interest — {current_user.email}",
        body=f"{service.name} ({tier.replace('_', ' ').title()})",
        url=url_for("crm_pipeline.lead_detail", lead_id=lead.id),
    )
    return lead


@packages_bp.route("/servico/<slug>", methods=["GET", "POST"])
def service_confirm(slug: str):
    """Confirmação de nível (Standard/Plus/Plus-Papel) pro pacote
    profissional -- equivalente a detail()/start_package() acima, mas
    para os 15 "Pacotes Completos" (ServiceCatalog), que não têm
    FormSubmission (a equipe conduz o caso, o cliente não preenche PDF).
    GET é público (preço é conteúdo de vitrine); POST exige login (mesmo
    padrão de start_package, mas checado manualmente aqui porque o GET
    precisa ficar aberto pra visitante anônimo)."""
    from app.crm_models import ServiceCatalog
    from app.i18n import get_lang, t
    from app.services.service_procedures import load_service_procedure, service_display_name

    service = SessionLocal.query(ServiceCatalog).filter_by(slug=slug).first()
    if service is None:
        abort(404)

    lang = get_lang()
    template = load_service_procedure(slug) or {}

    tiers = []
    for tier_key, label_key in (
        ("standard", "packages_pro_tier_standard"),
        ("plus", "packages_pro_tier_plus"),
        ("plus_paper", "packages_pro_tier_plus_paper"),
    ):
        price = _tier_price_cents(service, tier_key)
        if price is None:
            continue
        includes_key = "standard_includes" if tier_key == "standard" else "plus_includes"
        includes = template.get(f"{includes_key}_{lang}") or template.get(includes_key) or []
        tiers.append({"key": tier_key, "label": t(label_key), "price_cents": price, "includes": includes})

    if request.method == "POST":
        if not current_user.is_authenticated:
            return redirect(url_for("auth.signup", next=request.url))
        tier = request.form.get("tier")
        price = _tier_price_cents(service, tier) if tier in _TIER_SERVICE_MODE else None
        if price is None:
            flash(t("packages_pro_tier_invalid"), "error")
            return redirect(url_for("packages.service_confirm", slug=slug))

        lead = _get_or_create_professional_lead(service, tier, price)
        return redirect(url_for("payment_gate.checkout_lead", lead_id=lead.id))

    return render_template(
        "service_confirm.html", slug=slug,
        name=service_display_name(slug, lang), service=service, tiers=tiers,
        free_consultation_minutes=template.get("free_consultation_minutes"),
    )
