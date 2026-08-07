"""Blueprint do CRM (staff, admin) -- personalização de cor/descrição por
etapa de pipeline (Fase 4 da reforma do CRM, 2026-08-06). Sibling de
app/crm_staff_pipeline.py etc. -- mesmo url_prefix, arquivo próprio.

Ver app/services/pipeline_stage_service.py e a docstring de
app/crm_models.py::PipelineStageConfig pro raciocínio completo: isto é
uma camada de personalização visual SOBRE o vocabulário fechado
(enum.Enum) de cada pipeline, não um substituto dele -- criar/excluir uma
etapa de verdade ainda exige editar o enum em código.
"""
from __future__ import annotations

from datetime import datetime, timezone

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app import i18n
from app.crm_financial_models import FinancialChallenge, FinancialGoal
from app.crm_models import IncomeSourceType, ServiceCatalog, ServiceInterestOption
from app.db import SessionLocal
from app.services import pipeline_stage_service as stage_svc
from app.services import service_interests as si_svc

crm_pipeline_settings_bp = Blueprint(
    "crm_pipeline_settings", __name__, url_prefix="/staff/crm/configuracoes")


@crm_pipeline_settings_bp.before_request
@login_required
def _require_staff():
    if not current_user.is_staff:
        abort(403)


@crm_pipeline_settings_bp.route("/pipelines")
def pipelines():
    board = []
    for key, meta in stage_svc.PIPELINE_REGISTRY.items():
        configs = stage_svc.get_stage_configs(key)
        stages = [
            {
                "value": stage.value,
                "config": configs.get(stage.value),
                "usage_count": stage_svc.stage_usage_count(key, stage.value),
            }
            for stage in stage_svc.ordered_members(key)
        ]
        board.append({
            "key": key, "label": meta["label"], "stages": stages,
            "reorder_url": url_for("crm_pipeline_settings.stage_reorder", pipeline=key),
        })
    return render_template("crm_pipeline_settings.html", board=board)


@crm_pipeline_settings_bp.route("/pipelines/<pipeline>/<stage_value>", methods=["POST"])
def stage_save(pipeline: str, stage_value: str):
    if pipeline not in stage_svc.PIPELINE_REGISTRY:
        abort(404)
    enum_cls = stage_svc.PIPELINE_REGISTRY[pipeline]["enum"]
    try:
        enum_cls(stage_value)
    except ValueError:
        abort(404)

    color = request.form.get("color", "").strip()
    if color and not (color.startswith("#") and len(color) in (4, 7)):
        flash("Color must be a hex value like #205B5B.", "error")
        return redirect(url_for("crm_pipeline_settings.pipelines"))

    stage_svc.upsert_stage_config(
        pipeline, stage_value,
        color=color or None,
        label=request.form.get("label", "").strip() or None,
        description=request.form.get("description", "").strip() or None,
        active=request.form.get("active") == "on",
        user_id=current_user.id,
    )
    flash("Stage updated.", "success")
    return redirect(url_for("crm_pipeline_settings.pipelines"))


@crm_pipeline_settings_bp.route("/pipelines/<pipeline>/reordenar", methods=["POST"])
def stage_reorder(pipeline: str):
    """Recebe a ordem completa das etapas (montada em JS a partir da
    posição atual das linhas depois de um drag-and-drop, ver
    app/static/pipeline-stage-reorder.js) e persiste sort_order pra
    todas de uma vez."""
    if pipeline not in stage_svc.PIPELINE_REGISTRY:
        abort(404)
    ordered_values = request.form.getlist("stage_value")
    stage_svc.set_stage_order(pipeline, ordered_values, user_id=current_user.id)
    flash("Stage order updated.", "success")
    return redirect(url_for("crm_pipeline_settings.pipelines"))


# --------------------------------------------------------------------------
# "Interested in which service?" list -- app/lead_intake.py,
# app/services/service_interests.py, app/crm_models.py::ServiceInterestOption.
# Pedido do usuário 2026-08-07: reordenar/renomear/adicionar/apagar pelo
# painel, sem precisar editar código.
# --------------------------------------------------------------------------

@crm_pipeline_settings_bp.route("/interesse-servicos")
def service_interest_options():
    catalog_slugs = [
        s.slug for s in
        SessionLocal.query(ServiceCatalog).filter(ServiceCatalog.slug.is_not(None))
        .order_by(ServiceCatalog.name).all()
    ]
    rows = []
    for opt in si_svc.all_options():
        translation_key = f"service_interest_{opt.key}"
        label_pt = i18n.t_in("pt", translation_key)
        label_en = i18n.t_in("en", translation_key)
        label_es = i18n.t_in("es", translation_key)
        rows.append({
            "option": opt,
            "label_pt": label_pt,
            # t_in cai pro português quando o idioma não tem a chave --
            # mostrar esse fallback como se fosse uma tradução de verdade
            # no campo de edição faria alguém salvar o texto em português
            # DENTRO do campo "English"/"Spanish" sem querer. Só mostra
            # se for realmente diferente do português (uma tradução de
            # verdade já existe).
            "label_en": label_en if label_en != label_pt else "",
            "label_es": label_es if label_es != label_pt else "",
        })
    return render_template(
        "crm_service_interest_options.html", rows=rows, catalog_slugs=catalog_slugs)


def _save_option_labels(key: str) -> None:
    """Grava os 3 idiomas enviados pelo form nos arquivos de tradução
    (app/i18n.py::set_translation) -- pt é obrigatório (já validado antes
    de chamar isto); en/es em branco simplesmente não são escritos, e
    `t()` cai pro português sozinho até alguém preencher (mesmo
    comportamento tolerado em outros textos do site, ver
    memory/auto_imigracao_full_reaudit_status -- rótulos sem tradução
    ainda não quebram nada, só mostram o fallback)."""
    i18n.set_translation("pt", f"service_interest_{key}", request.form.get("label_pt", "").strip())
    label_en = request.form.get("label_en", "").strip()
    if label_en:
        i18n.set_translation("en", f"service_interest_{key}", label_en)
    label_es = request.form.get("label_es", "").strip()
    if label_es:
        i18n.set_translation("es", f"service_interest_{key}", label_es)


@crm_pipeline_settings_bp.route("/interesse-servicos/<int:option_id>/salvar", methods=["POST"])
def service_interest_option_save(option_id: int):
    option = SessionLocal.get(ServiceInterestOption, option_id)
    if option is None:
        abort(404)

    label_pt = request.form.get("label_pt", "").strip()
    if not label_pt:
        flash("Portuguese label is required.", "error")
        return redirect(url_for("crm_pipeline_settings.service_interest_options"))

    is_group = request.form.get("is_group") == "on"
    option.is_group = is_group
    option.indent = False if is_group else request.form.get("indent") == "on"
    option.slug = None if is_group else (request.form.get("slug") or "").strip() or None

    _save_option_labels(option.key)
    SessionLocal.commit()
    flash("Service interest option updated.", "success")
    return redirect(url_for("crm_pipeline_settings.service_interest_options"))


@crm_pipeline_settings_bp.route("/interesse-servicos/novo", methods=["POST"])
def service_interest_option_new():
    label_pt = request.form.get("label_pt", "").strip()
    if not label_pt:
        flash("Portuguese label is required.", "error")
        return redirect(url_for("crm_pipeline_settings.service_interest_options"))

    is_group = request.form.get("is_group") == "on"
    slug = None if is_group else (request.form.get("slug") or "").strip() or None
    indent = False if is_group else request.form.get("indent") == "on"

    key = si_svc.unique_key(slug or si_svc.slugify_key(label_pt))
    next_order = (SessionLocal.query(func.max(ServiceInterestOption.sort_order)).scalar() or -1) + 1

    option = ServiceInterestOption(key=key, slug=slug, is_group=is_group, indent=indent, sort_order=next_order)
    SessionLocal.add(option)
    SessionLocal.flush()

    _save_option_labels(key)
    SessionLocal.commit()
    flash("Service interest option added.", "success")
    return redirect(url_for("crm_pipeline_settings.service_interest_options"))


@crm_pipeline_settings_bp.route("/interesse-servicos/<int:option_id>/excluir", methods=["POST"])
def service_interest_option_delete(option_id: int):
    option = SessionLocal.get(ServiceInterestOption, option_id)
    if option is None:
        abort(404)
    key = option.key
    SessionLocal.delete(option)
    SessionLocal.commit()
    for lang in i18n.SUPPORTED_LANGS:
        i18n.delete_translation(lang, f"service_interest_{key}")
    flash("Service interest option deleted.", "success")
    return redirect(url_for("crm_pipeline_settings.service_interest_options"))


@crm_pipeline_settings_bp.route("/interesse-servicos/reordenar", methods=["POST"])
def service_interest_options_reorder():
    """Mesmo padrão de stage_reorder acima -- recebe a ordem completa
    (IDs) montada em JS depois de um drag-and-drop
    (app/static/service-interest-options-reorder.js) e persiste
    sort_order pra todas de uma vez."""
    ordered_ids = request.form.getlist("option_id")
    options_by_id = {str(o.id): o for o in SessionLocal.query(ServiceInterestOption).all()}
    for index, raw_id in enumerate(ordered_ids):
        option = options_by_id.get(raw_id)
        if option is None:
            continue
        option.sort_order = index
    SessionLocal.commit()
    flash("Order updated.", "success")
    return redirect(url_for("crm_pipeline_settings.service_interest_options"))


# --------------------------------------------------------------------------
# Checkboxes da ficha do cliente de Financial Coaching (Income sources,
# Financial goals, Main challenges) -- pedido do usuário 2026-08-07,
# escopo confirmado: só estes 3 grupos (já eram tabelas no banco, só
# faltava a tela de admin); os 8 selects de vocabulário fechado
# (Household income range, Progress status, etc.) ficam pra uma rodada
# seguinte -- transformá-los em editável exige tabela+migração nova pra
# cada um. Mesmo padrão de reorder/add/edit/delete de "interesse-
# serviços" acima, mas 3 grupos na mesma tela em vez de um só -- rotas
# parametrizadas por `kind` em vez de tripicar o código.
# --------------------------------------------------------------------------

_FINANCIAL_OPTION_MODELS = {
    "income_source": IncomeSourceType,
    "financial_goal": FinancialGoal,
    "financial_challenge": FinancialChallenge,
}
_FINANCIAL_OPTION_LABELS = {
    "income_source": "Income sources",
    "financial_goal": "Financial goals",
    "financial_challenge": "Main challenges",
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@crm_pipeline_settings_bp.route("/coaching-financeiro-opcoes")
def financial_coaching_options():
    groups = []
    for kind, model in _FINANCIAL_OPTION_MODELS.items():
        options = (
            SessionLocal.query(model).filter(model.deleted_at.is_(None))
            .order_by(model.sort_order, model.name).all()
        )
        groups.append({"kind": kind, "label": _FINANCIAL_OPTION_LABELS[kind], "options": options})
    return render_template("crm_financial_coaching_options.html", groups=groups)


@crm_pipeline_settings_bp.route("/coaching-financeiro-opcoes/<kind>/nova", methods=["POST"])
def financial_coaching_option_new(kind: str):
    model = _FINANCIAL_OPTION_MODELS.get(kind)
    if model is None:
        abort(404)

    name = request.form.get("name", "").strip()
    if not name:
        flash("Name is required.", "error")
        return redirect(url_for("crm_pipeline_settings.financial_coaching_options"))

    next_order = (SessionLocal.query(func.max(model.sort_order)).scalar() or -1) + 1
    SessionLocal.add(model(name=name, sort_order=next_order))
    try:
        SessionLocal.commit()
    except IntegrityError:
        SessionLocal.rollback()
        flash("An option with this name already exists.", "error")
    else:
        flash("Option added.", "success")
    return redirect(url_for("crm_pipeline_settings.financial_coaching_options"))


@crm_pipeline_settings_bp.route("/coaching-financeiro-opcoes/<kind>/<int:option_id>/salvar", methods=["POST"])
def financial_coaching_option_save(kind: str, option_id: int):
    model = _FINANCIAL_OPTION_MODELS.get(kind)
    if model is None:
        abort(404)
    option = SessionLocal.get(model, option_id)
    if option is None:
        abort(404)

    name = request.form.get("name", "").strip()
    if not name:
        flash("Name is required.", "error")
        return redirect(url_for("crm_pipeline_settings.financial_coaching_options"))

    option.name = name
    try:
        SessionLocal.commit()
    except IntegrityError:
        SessionLocal.rollback()
        flash("An option with this name already exists.", "error")
    else:
        flash("Option updated.", "success")
    return redirect(url_for("crm_pipeline_settings.financial_coaching_options"))


@crm_pipeline_settings_bp.route("/coaching-financeiro-opcoes/<kind>/<int:option_id>/excluir", methods=["POST"])
def financial_coaching_option_delete(kind: str, option_id: int):
    """Exclusão sempre LÓGICA -- clientes que já têm essa opção marcada
    mantêm o vínculo (`FinancialClientGoal`/`...Challenge`/
    `...IncomeSource`) intacto, só some da lista de novas seleções."""
    model = _FINANCIAL_OPTION_MODELS.get(kind)
    if model is None:
        abort(404)
    option = SessionLocal.get(model, option_id)
    if option is None:
        abort(404)

    option.deleted_at = _utcnow()
    SessionLocal.commit()
    flash("Option removed. Clients who already had it selected keep their record.", "success")
    return redirect(url_for("crm_pipeline_settings.financial_coaching_options"))


@crm_pipeline_settings_bp.route("/coaching-financeiro-opcoes/<kind>/reordenar", methods=["POST"])
def financial_coaching_options_reorder(kind: str):
    model = _FINANCIAL_OPTION_MODELS.get(kind)
    if model is None:
        abort(404)
    ordered_ids = request.form.getlist("option_id")
    items_by_id = {str(o.id): o for o in SessionLocal.query(model).all()}
    for index, raw_id in enumerate(ordered_ids):
        item = items_by_id.get(raw_id)
        if item is None:
            continue
        item.sort_order = index
    SessionLocal.commit()
    flash("Order updated.", "success")
    return redirect(url_for("crm_pipeline_settings.financial_coaching_options"))
