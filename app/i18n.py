"""Sistema de i18n leve, sem dependência nova: um dict por idioma
carregado de app/translations/<lang>.json, idioma preferido guardado na
sessão do usuário (cookie), com fallback pro português se uma chave não
existir em inglês.
"""
from __future__ import annotations

import json
from pathlib import Path

from flask import session

TRANSLATIONS_DIR = Path(__file__).resolve().parent / "translations"
SUPPORTED_LANGS = ("pt", "en", "es")
DEFAULT_LANG = "pt"

_cache: dict[str, dict] = {}


def _load(lang: str) -> dict:
    if lang not in _cache:
        path = TRANSLATIONS_DIR / f"{lang}.json"
        _cache[lang] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return _cache[lang]


def get_lang() -> str:
    lang = session.get("lang", DEFAULT_LANG)
    return lang if lang in SUPPORTED_LANGS else DEFAULT_LANG


def t(key: str, **kwargs) -> str:
    """Busca `key` no idioma atual da sessão; cai pro português se faltar
    lá, e por fim devolve a própria chave (fácil de notar strings sem
    tradução ainda) se nem isso existir."""
    return t_in(get_lang(), key, **kwargs)


def t_in(lang: str, key: str, **kwargs) -> str:
    """Mesma busca de `t()`, mas num idioma FIXO em vez do da sessão --
    usado só onde o texto tem que sair sempre no mesmo idioma
    independente de quem está navegando (ex.: a mensagem de WhatsApp pro
    time, sempre em inglês -- mesma regra já aplicada em
    app/payment_gate.py::_whatsapp_url, "pedido explícito do usuário")."""
    if lang not in SUPPORTED_LANGS:
        lang = DEFAULT_LANG
    text = _load(lang).get(key)
    if text is None and lang != DEFAULT_LANG:
        text = _load(DEFAULT_LANG).get(key)
    if text is None:
        text = key
    if kwargs:
        text = text.format(**kwargs)
    return text


def _write(lang: str, data: dict) -> None:
    path = TRANSLATIONS_DIR / f"{lang}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _cache[lang] = data


def set_translation(lang: str, key: str, value: str) -> None:
    """Escreve `value` em app/translations/<lang>.json sob `key`,
    preservando a formatação existente do arquivo (indent=2,
    ensure_ascii=False), e atualiza o cache em memória na hora -- fica
    visível sem reiniciar o processo. Usado pela tela de administração
    do catálogo de "interesse em serviço"
    (app/crm_pipeline_settings.py::service_interest_options) pra editar
    o texto público em cada idioma; serve pra qualquer outro texto de UI
    que ganhe edição pelo painel no futuro."""
    if not value:
        return
    if lang not in SUPPORTED_LANGS:
        raise ValueError(f"idioma desconhecido: {lang!r}")
    data = _load(lang)
    data[key] = value
    _write(lang, data)


def delete_translation(lang: str, key: str) -> None:
    """Remove `key` de app/translations/<lang>.json, se existir. Chamado
    nos 3 idiomas quando um item do catálogo de interesse é apagado --
    fail-silent se a chave já não existir num idioma específico (ex.:
    nunca teve tradução pra inglês/espanhol ainda)."""
    if lang not in SUPPORTED_LANGS:
        raise ValueError(f"idioma desconhecido: {lang!r}")
    data = _load(lang)
    if key in data:
        del data[key]
        _write(lang, data)
