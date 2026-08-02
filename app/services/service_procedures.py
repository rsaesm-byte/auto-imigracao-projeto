"""Carrega os templates de procedimento dos serviços "Pacotes Completos"
(Saes Standard/Plus) de data/service_procedures/<service_id>.json --
mesmo padrão de app/wizard.py::_load_questionnaire (cache em memória, o
motor é genérico e os 15 serviços são só dado, não código).

Cada template descreve fases; cada fase tem `documents` (itens que o
cliente envia como arquivo, viram RequiredDocument -- ver
app/services/crm_service.py::apply_service_procedure_checklist) e `steps`
(passos internos da equipe, sem upload, marcados via CaseStepLog).

`name`/`documents`/`steps` são sempre em inglês -- o painel da equipe é
100% inglês (ver memory/feedback_staff_interface_english.md), então esse é
o valor canônico gravado em `RequiredDocument.label`/`ServiceCatalog.name`.
`name_pt`/`name_es`/`documents_pt`/`documents_es` existem só pra exibir pro
CLIENTE (que escolhe o idioma) em telas como /pendencias e /servicos --
`steps` não precisa de tradução porque nunca aparece pro cliente."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
PROCEDURES_DIR = ROOT / "data" / "service_procedures"

_cache: dict[str, dict] = {}
_label_translations_cache: dict[str, dict[str, str]] | None = None


def load_service_procedure(slug: str) -> dict | None:
    if slug not in _cache:
        path = PROCEDURES_DIR / f"{slug}.json"
        if not path.exists():
            return None
        _cache[slug] = json.loads(path.read_text(encoding="utf-8"))
    return _cache[slug]


def save_service_procedure_lists(slug: str, updates: dict[str, list[str]]) -> None:
    """Sobrescreve os campos de `updates` (ex.: standard_includes/
    standard_includes_pt/standard_includes_es/standard_excludes/...)
    direto no JSON em disco e invalida o cache em memória deste slug --
    pedido do usuário 2026-08-02: "visualizar e alterar" o contrato de
    cada serviço direto pela UI, sem precisar editar o arquivo à mão nem
    reiniciar o servidor (a limitação de cache documentada na sessão de
    Contracts era exatamente essa: mudar o arquivo no disco não bastava
    sem reboot -- esta função invalida `_cache[slug]` no mesmo request
    que grava, então a próxima leitura já vê o valor novo)."""
    path = PROCEDURES_DIR / f"{slug}.json"
    if not path.exists():
        raise FileNotFoundError(slug)
    data = json.loads(path.read_text(encoding="utf-8"))
    data.update(updates)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    _cache.pop(slug, None)


def phase1_documents(slug: str) -> list[str]:
    """Em inglês -- é o que vira `RequiredDocument.label` (ver
    apply_service_procedure_checklist), porque o painel do staff que
    revisa esses documentos é sempre inglês."""
    template = load_service_procedure(slug)
    if template is None or not template["phases"]:
        return []
    return list(template["phases"][0].get("documents", []))


def all_service_slugs() -> list[str]:
    return sorted(p.stem for p in PROCEDURES_DIR.glob("*.json"))


def service_display_name(slug: str, lang: str) -> str:
    """Nome do serviço no idioma do CLIENTE -- usado só em telas
    client-facing (ex.: catálogo público /servicos). Nunca usar isto no
    painel do staff -- lá é sempre `ServiceCatalog.name` (inglês)."""
    template = load_service_procedure(slug)
    if template is None:
        return slug
    if lang == "pt":
        return template.get("name_pt", template["name"])
    if lang == "es":
        return template.get("name_es", template["name"])
    return template["name"]


def _build_label_translations() -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for slug in all_service_slugs():
        template = load_service_procedure(slug)
        if template is None:
            continue
        for phase in template["phases"]:
            docs_en = phase.get("documents", [])
            docs_pt = phase.get("documents_pt", [])
            docs_es = phase.get("documents_es", [])
            for i, en in enumerate(docs_en):
                result[en] = {
                    "pt": docs_pt[i] if i < len(docs_pt) else en,
                    "es": docs_es[i] if i < len(docs_es) else en,
                }
    return result


def translate_document_label(label_en: str, lang: str) -> str:
    """Traduz um `RequiredDocument.label` (sempre gravado em inglês, ver
    phase1_documents acima) pro idioma do CLIENTE em telas como
    /pendencias -- pesquisa nos 15 templates por esse texto exato. Itens
    que o staff digitou manualmente (não vieram de um template) não têm
    tradução cadastrada -- caem no fallback e mostram o texto original
    (em inglês) mesmo pro cliente, o que é aceitável (caso raro,
    checklist customizado caso a caso)."""
    if lang not in ("pt", "es"):
        return label_en
    global _label_translations_cache
    if _label_translations_cache is None:
        _label_translations_cache = _build_label_translations()
    entry = _label_translations_cache.get(label_en)
    return entry[lang] if entry else label_en
