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
    return render_template(
        "crm_case_contracts.html", case=case, services=services, current_service=current_service,
        tiers=list(ContractTier), document_types=list(ContractDocumentType),
        price_cents=svc.contract_price_cents)


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
    SessionLocal.delete(contract)
    SessionLocal.commit()
    flash("Signature request cancelled.", "success")
    return redirect(url_for("crm_contracts.case_contracts", case_id=case_id))
