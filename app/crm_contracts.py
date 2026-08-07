"""Blueprint do CRM (staff) -- aba "Contracts": acompanhamento do status de
assinatura de contrato (não começado, em análise, assinado, rejeitado) por
caso, tanto do contrato de serviço ("Pacote Completo" + tier cotado) quanto
dos Termos & Condições. Pedido do usuário, 2026-08-02.

Irmão de app/crm_staff_ops.py -- blueprint próprio (mesmo url_prefix
/staff/crm) já que "Contracts" é um domínio auto-contido (não estende
nenhum modelo existente).
"""
from __future__ import annotations

from flask import Blueprint, abort, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required

from app.crm_models import (Case, CaseContract, ContractDocumentType,
                             ContractStatus, ContractTier, ServiceCatalog)
from app.db import SessionLocal
from app.models import User
from app.services import audit_service
from app.services import crm_service as svc

crm_contracts_bp = Blueprint("crm_contracts", __name__, url_prefix="/staff/crm/contratos")


@crm_contracts_bp.before_request
@login_required
def _require_staff():
    if not current_user.is_staff:
        abort(403)


@crm_contracts_bp.route("/")
def dashboard():
    status_filter = request.args.get("status", "").strip()
    query = SessionLocal.query(CaseContract)
    if status_filter in {s.value for s in ContractStatus}:
        query = query.filter_by(status=ContractStatus(status_filter))
    rows = query.order_by(CaseContract.created_at.desc()).all()

    counts = {s: SessionLocal.query(CaseContract).filter_by(status=s).count() for s in ContractStatus}
    return render_template(
        "crm_contracts_dashboard.html", rows=rows, status_filter=status_filter, counts=counts,
        statuses=list(ContractStatus), price_cents=svc.contract_price_cents)


@crm_contracts_bp.route("/casos/<int:case_id>")
def case_contracts(case_id: int):
    case = SessionLocal.get(Case, case_id)
    if case is None:
        abort(404)
    services = SessionLocal.query(ServiceCatalog).filter(ServiceCatalog.slug.is_not(None)).order_by(
        ServiceCatalog.name).all()
    current_service = next((cs.service for cs in case.services if cs.role.value == "current"), None)
    contract_history = {c.id: audit_service.get_history("Contract", c.id) for c in case.contracts}
    history_users = {u.id: u for u in SessionLocal.query(User).all()}
    return render_template(
        "crm_case_contracts.html", case=case, services=services, current_service=current_service,
        tiers=list(ContractTier), document_types=list(ContractDocumentType),
        price_cents=svc.contract_price_cents,
        contract_history=contract_history, history_users=history_users)


@crm_contracts_bp.route("/casos/<int:case_id>/novo", methods=["POST"])
def contract_new(case_id: int):
    case = SessionLocal.get(Case, case_id)
    if case is None:
        abort(404)

    document_type = svc.parse_enum(ContractDocumentType, request.form.get("document_type"))
    if document_type is None:
        flash("Select a document type.", "error")
        return redirect(url_for("crm_contracts.case_contracts", case_id=case_id))

    service_id = None
    tier = None
    if document_type == ContractDocumentType.service_contract:
        service_id = svc.parse_int(request.form.get("service_catalog_id"))
        tier = svc.parse_enum(ContractTier, request.form.get("tier"))
        if service_id is None or tier is None:
            flash("Select a service and a pricing tier for a service contract.", "error")
            return redirect(url_for("crm_contracts.case_contracts", case_id=case_id))

    contract = CaseContract(
        case_id=case.id, document_type=document_type, service_catalog_id=service_id, tier=tier,
        requested_by_id=current_user.id)
    SessionLocal.add(contract)
    SessionLocal.flush()
    audit_service.log_change(
        "Contract", contract.id, "create",
        description=f"Signature requested ({document_type.value}{' — ' + tier.value if tier else ''})",
        user_id=current_user.id)
    SessionLocal.commit()
    flash("Signature requested.", "success")
    return redirect(url_for("crm_contracts.case_contracts", case_id=case_id))


@crm_contracts_bp.route("/<int:contract_id>/assinatura")
def signature_image(contract_id: int):
    contract = SessionLocal.get(CaseContract, contract_id)
    if contract is None or not contract.signature_image_path:
        abort(404)
    return send_file(contract.signature_image_path)


@crm_contracts_bp.route("/<int:contract_id>/cancelar", methods=["POST"])
def contract_cancel(contract_id: int):
    """Só permite cancelar um pedido ainda não assinado -- um contrato já
    assinado é um registro, não deve sumir do histórico."""
    contract = SessionLocal.get(CaseContract, contract_id)
    if contract is None:
        abort(404)
    if contract.status == ContractStatus.signed:
        flash("A signed contract can't be cancelled.", "error")
        return redirect(url_for("crm_contracts.case_contracts", case_id=contract.case_id))
    case_id = contract.case_id
    audit_service.log_change("Contract", contract.id, "delete",
                              description="Signature request cancelled", user_id=current_user.id)
    SessionLocal.delete(contract)
    SessionLocal.commit()
    flash("Signature request cancelled.", "success")
    return redirect(url_for("crm_contracts.case_contracts", case_id=case_id))


# --------------------------------------------------------------------------
# Modelos de contrato por serviço -- pedido do usuário 2026-08-02:
# "visualizar os contratos de cada serviço e alterar o contrato da
# empresa por lá, exemplos termos etc, antes de disponibilizar o contrato
# para os clientes". Edita direto o que a tela de assinatura do cliente
# (app/crm_client.py::contract_view, template meu_contrato.html) lê --
# preço (Prices, já editável), includes/excludes por tier (aqui) e os
# Termos Gerais compartilhados (aqui, CompanyContractTerms).
# --------------------------------------------------------------------------

@crm_contracts_bp.route("/modelos")
def templates_dashboard():
    services = SessionLocal.query(ServiceCatalog).filter(ServiceCatalog.slug.is_not(None)).order_by(
        ServiceCatalog.name).all()
    return render_template("crm_contracts_templates_dashboard.html", services=services)


@crm_contracts_bp.route("/modelos/<slug>", methods=["GET", "POST"])
def template_edit(slug: str):
    from app.services.service_procedures import (load_service_procedure,
                                                   save_service_procedure_lists)

    template = load_service_procedure(slug)
    if template is None:
        abort(404)
    service = SessionLocal.query(ServiceCatalog).filter_by(slug=slug).first()
    if service is None:
        abort(404)

    fields = ("standard_includes", "standard_excludes", "plus_includes", "plus_excludes")
    langs = ("", "_pt", "_es")  # "" = English (canonical)

    if request.method == "POST":
        updates = {}
        for field in fields:
            for lang_suffix in langs:
                key = f"{field}{lang_suffix}"
                raw = request.form.get(key, "")
                updates[key] = [line.strip() for line in raw.splitlines() if line.strip()]
        save_service_procedure_lists(slug, updates)
        audit_service.log_change(
            "ContractTemplate", service.id, "field_update",
            description=f"Includes/Excludes updated for '{service.name}'", user_id=current_user.id)
        SessionLocal.commit()
        flash("Contract template updated.", "success")
        return redirect(url_for("crm_contracts.template_edit", slug=slug))

    lists = {
        f"{field}{lang_suffix}": "\n".join(template.get(f"{field}{lang_suffix}", []))
        for field in fields for lang_suffix in langs
    }
    history = audit_service.get_history("ContractTemplate", service.id)
    history_users = {u.id: u for u in SessionLocal.query(User).all()}
    return render_template(
        "crm_contract_template_edit.html", slug=slug, service=service, template=template, lists=lists,
        history=history, history_users=history_users)


@crm_contracts_bp.route("/modelos/<slug>/previa")
def template_preview(slug: str):
    """Mostra exatamente o que o cliente veria (preço real, includes/
    excludes, termos gerais) sem precisar criar uma solicitação de
    assinatura de verdade -- staff escolhe tier + idioma de visualização."""
    from app.services.service_procedures import load_service_procedure, service_display_name
    from app.services.text_format import markdown_lite_to_html

    template = load_service_procedure(slug)
    service = SessionLocal.query(ServiceCatalog).filter_by(slug=slug).first()
    if template is None or service is None:
        abort(404)

    tier = svc.parse_enum(ContractTier, request.args.get("tier"), default=ContractTier.standard)
    preview_lang = request.args.get("lang", "pt")
    if preview_lang not in ("pt", "en", "es"):
        preview_lang = "pt"

    price_cents = {
        ContractTier.standard: service.base_price_cents,
        ContractTier.plus_online: service.plus_price_cents,
        ContractTier.plus_paper: service.plus_price_paper_cents,
    }.get(tier)

    suffix = f"_{preview_lang}" if preview_lang in ("pt", "es") else ""
    base_field = "standard" if tier == ContractTier.standard else "plus"
    tier_includes = template.get(f"{base_field}_includes{suffix}", [])
    tier_excludes = template.get(f"{base_field}_excludes{suffix}", [])

    terms = svc.get_company_contract_terms()
    lang_suffix = preview_lang if preview_lang in ("pt", "es") else "en"
    general_terms_md = getattr(terms, f"general_terms_{lang_suffix}") or terms.general_terms_en
    general_terms_md += "\n- " + (getattr(terms, f"payment_separate_{lang_suffix}") or terms.payment_separate_en)
    general_terms_html = markdown_lite_to_html(general_terms_md)

    return render_template(
        "crm_contract_template_preview.html", slug=slug,
        service_name=service_display_name(slug, preview_lang), price_cents=price_cents,
        tier_includes=tier_includes, tier_excludes=tier_excludes, general_terms_html=general_terms_html,
        tier=tier, preview_lang=preview_lang, tiers=list(ContractTier))


@crm_contracts_bp.route("/termos", methods=["GET", "POST"])
def terms_edit():
    terms = svc.get_company_contract_terms()

    if request.method == "POST":
        for lang_suffix in ("en", "pt", "es"):
            setattr(terms, f"general_terms_{lang_suffix}", request.form.get(f"general_terms_{lang_suffix}", "").strip())
            setattr(terms, f"payment_separate_{lang_suffix}",
                    request.form.get(f"payment_separate_{lang_suffix}", "").strip())
            setattr(terms, f"tc_intro_{lang_suffix}", request.form.get(f"tc_intro_{lang_suffix}", "").strip())
        terms.updated_by_user_id = current_user.id
        audit_service.log_change("ContractTerms", terms.id, "field_update",
                                  description="Terms & Conditions updated", user_id=current_user.id)
        SessionLocal.commit()
        flash("Terms & Conditions updated.", "success")
        return redirect(url_for("crm_contracts.terms_edit"))

    fields = {
        f"{section}_{lang_suffix}": getattr(terms, f"{section}_{lang_suffix}")
        for section in ("general_terms", "payment_separate", "tc_intro")
        for lang_suffix in ("en", "pt", "es")
    }
    history = audit_service.get_history("ContractTerms", terms.id)
    history_users = {u.id: u for u in SessionLocal.query(User).all()}
    return render_template("crm_contract_terms_edit.html", fields=fields,
                            history=history, history_users=history_users)
