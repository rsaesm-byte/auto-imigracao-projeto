"""Backup manual do SQLite antes de alterações de schema.

Segue o mesmo padrão já usado em scripts/import_notion_crm.py
(bak = caminho do banco + sufixo com label e timestamp, cópia via
shutil.copy2). Centralizado aqui para ser reusado por qualquer script
de migração ou pela própria app factory, em vez de cada script
reimplementar a cópia.
"""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from app.db import engine


def backup_database(label: str) -> Path:
    """Copia o arquivo SQLite atual para <db>.bak-pre-<label>-<timestamp>.

    Não faz nada e levanta FileNotFoundError se o banco ainda não existe
    (ex.: primeiro boot em ambiente novo) -- não há o que copiar.
    """
    db_path = Path(engine.url.database)
    if not db_path.exists():
        raise FileNotFoundError(f"Banco não encontrado em {db_path}, nada para copiar")
    backup_path = db_path.with_name(
        f"{db_path.name}.bak-pre-{label}-{datetime.now():%Y%m%d%H%M%S}"
    )
    shutil.copy2(db_path, backup_path)
    return backup_path
