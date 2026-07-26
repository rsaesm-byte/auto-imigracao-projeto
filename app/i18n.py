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
SUPPORTED_LANGS = ("pt", "en")
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
    lang = get_lang()
    text = _load(lang).get(key)
    if text is None and lang != DEFAULT_LANG:
        text = _load(DEFAULT_LANG).get(key)
    if text is None:
        text = key
    if kwargs:
        text = text.format(**kwargs)
    return text
