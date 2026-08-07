"""Metadados administráveis por etapa de pipeline (Fase 4 da reforma do
CRM) -- ver docstring de app/crm_models.py::PipelineStageConfig pro
raciocínio completo de por que isso é uma camada sobre o enum, não um
substituto dele.

Convenção deste projeto (mesmo padrão de app/services/crm_service.py):
estas funções não chamam `SessionLocal.commit()` sozinhas, exceto
`upsert_stage_config` (que já é a "função-botão" da tela de admin -- o
commit faz parte da própria ação de salvar).
"""
from __future__ import annotations

from app.crm_models import (Case, CaseStatus, Document, DocumentStatus, Lead,
                             LeadStage, PipelineStageConfig, Task, TaskStatus)
from app.crm_financial_models import FinancialClient, FinancialClientStatus
from app.db import SessionLocal

# Registro de todo pipeline com kanban no CRM -- chave estável (`pipeline`)
# usada como parte da PK lógica de PipelineStageConfig, enum de vocabulário
# fechado correspondente, e o modelo cujo kanban o usa (só pra dar o
# contador de "quantos registros usam esta etapa" na tela de admin).
PIPELINE_REGISTRY: dict[str, dict] = {
    "case_status": {"label": "Cases", "enum": CaseStatus, "model": Case, "field": "case_status"},
    "lead_stage": {"label": "Leads", "enum": LeadStage, "model": Lead, "field": "stage"},
    "task_status": {"label": "Tasks", "enum": TaskStatus, "model": Task, "field": "status"},
    "document_status": {"label": "Translations", "enum": DocumentStatus, "model": Document, "field": "status"},
    "financial_client_status": {
        "label": "Financial Coaching", "enum": FinancialClientStatus,
        "model": FinancialClient, "field": "client_status"},
}


def get_stage_configs(pipeline: str) -> dict[str, PipelineStageConfig]:
    """Configs existentes para um pipeline, indexadas por stage_value.
    Etapas sem linha aqui simplesmente não aparecem no dict -- quem chama
    trata a ausência como "sem personalização" (cor automática por
    posição, sem descrição)."""
    rows = SessionLocal.query(PipelineStageConfig).filter_by(pipeline=pipeline).all()
    return {row.stage_value: row for row in rows}


def stage_colors(pipeline: str) -> dict[str, str]:
    """Atalho só com as cores definidas (ignora etapas sem cor customizada)
    -- pro template passar como `--col-accent` inline, caindo de volta pra
    cor automática por posição quando a chave não existe."""
    return {
        stage_value: cfg.color
        for stage_value, cfg in get_stage_configs(pipeline).items()
        if cfg.color
    }


def ordered_members(pipeline: str) -> list:
    """Membros do enum do pipeline na ordem customizada (drag-and-drop na
    tela de admin), caindo de volta pra ordem de definição do enum quando
    nenhuma ordem foi salva ainda. Isto é só ORDEM DE EXIBIÇÃO -- o
    vocabulário em si (quais valores existem) continua vindo do enum, não
    desta tabela (ver docstring de PipelineStageConfig)."""
    enum_cls = PIPELINE_REGISTRY[pipeline]["enum"]
    members = list(enum_cls)
    configs = get_stage_configs(pipeline)
    original_index = {member: i for i, member in enumerate(members)}

    def sort_key(member):
        cfg = configs.get(member.value)
        has_order = cfg is not None and cfg.sort_order is not None
        return (0 if has_order else 1, cfg.sort_order if has_order else 0, original_index[member])

    return sorted(members, key=sort_key)


def stage_labels(pipeline: str) -> dict[str, str]:
    """Atalho só com os nomes customizados definidos (ignora etapas sem
    label customizado) -- pro template passar como `crm_badge(stage,
    label=stage_labels.get(stage.value))`, caindo de volta pro texto
    derivado do stage_value quando a chave não existe."""
    return {
        stage_value: cfg.label
        for stage_value, cfg in get_stage_configs(pipeline).items()
        if cfg.label
    }


def upsert_stage_config(
    pipeline: str, stage_value: str, *,
    color: str | None, label: str | None, description: str | None, active: bool,
    user_id: int | None,
) -> PipelineStageConfig:
    row = (
        SessionLocal.query(PipelineStageConfig)
        .filter_by(pipeline=pipeline, stage_value=stage_value)
        .first()
    )
    if row is None:
        row = PipelineStageConfig(pipeline=pipeline, stage_value=stage_value)
        SessionLocal.add(row)
    row.color = color or None
    row.label = label or None
    row.description = description or None
    row.active = active
    row.updated_by_user_id = user_id
    SessionLocal.commit()
    return row


def set_stage_order(pipeline: str, ordered_stage_values: list[str], user_id: int | None) -> None:
    """Persiste a nova ordem (drag-and-drop) -- sempre escreve sort_order
    pra TODA etapa da lista recebida (0..N-1), nunca só as que o usuário
    tocou, pra não acabar com uma ordem "meio customizada, meio original"
    difícil de prever. Preserva color/label/description/active já salvos
    de cada linha (só mexe em sort_order)."""
    enum_cls = PIPELINE_REGISTRY[pipeline]["enum"]
    valid_values = {member.value for member in enum_cls}
    configs = get_stage_configs(pipeline)
    for index, stage_value in enumerate(ordered_stage_values):
        if stage_value not in valid_values:
            continue
        row = configs.get(stage_value)
        if row is None:
            row = PipelineStageConfig(pipeline=pipeline, stage_value=stage_value)
            SessionLocal.add(row)
        row.sort_order = index
        row.updated_by_user_id = user_id
    SessionLocal.commit()


def stage_usage_count(pipeline: str, stage_value: str) -> int:
    """Quantos registros reais estão nesta etapa agora -- mostrado na tela
    de admin antes de marcar uma etapa como inativa (pedido do usuário:
    avisar impacto antes de qualquer alteração que afete dados)."""
    meta = PIPELINE_REGISTRY[pipeline]
    model, field = meta["model"], meta["field"]
    enum_cls = meta["enum"]
    try:
        value = enum_cls(stage_value)
    except ValueError:
        return 0
    return SessionLocal.query(model).filter(getattr(model, field) == value).count()
