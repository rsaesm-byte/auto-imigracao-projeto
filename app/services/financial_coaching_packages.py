"""Carrega o conteúdo contratual (includes/excludes EN/PT/ES) dos 3
pacotes de Financial Coaching de data/financial_coaching_packages/
<slug>.json -- mesmo padrão de cache-em-memória de
app/services/service_procedures.py, mas sem `phases`/`documents`/`steps`
(Financial Coaching não gera checklist de documentos por fase como os
serviços de imigração; é sessão de coaching, não filing de formulário).
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
PACKAGES_DIR = ROOT / "data" / "financial_coaching_packages"

_cache: dict[str, dict] = {}


def load_package_content(slug: str) -> dict | None:
    if slug not in _cache:
        path = PACKAGES_DIR / f"{slug}.json"
        if not path.exists():
            return None
        _cache[slug] = json.loads(path.read_text(encoding="utf-8"))
    return _cache[slug]


def save_package_content_lists(slug: str, updates: dict[str, list[str]]) -> None:
    path = PACKAGES_DIR / f"{slug}.json"
    if not path.exists():
        raise FileNotFoundError(slug)
    data = json.loads(path.read_text(encoding="utf-8"))
    data.update(updates)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    _cache.pop(slug, None)
