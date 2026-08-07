"""baseline: adoção do Alembic sobre o schema já existente

Revision ID: 4182fc577a23
Revises:
Create Date: 2026-08-06 10:26:43.700989

Esta revisão é deliberadamente um no-op. O schema já existe em produção
(criado por Base.metadata.create_all() + ~28 funções _ensure_*_column()
hand-rolled em app/__init__.py, ver histórico do projeto) e contém dados
reais (2.184 clientes migrados do Notion, 137 casos, 257 pagamentos).

O autogenerate inicial (`alembic revision --autogenerate`) detectou
diferenças entre app/crm_models.py e o banco real -- a mais importante:
ele queria fazer DROP COLUMN em `notion_page_id` de crm_cases/crm_clients/
crm_payments_ledger. Essa coluna é intencional: foi adicionada por ALTER
TABLE direto em scripts/import_notion_crm.py (fora do ORM, de propósito)
e é a chave de idempotência da importação do Notion -- removê-la
quebraria a idempotência e apagaria o vínculo com os registros de
origem. As demais diferenças (índices faltando, NOT NULL não declarado
formalmente, tipo Enum vs VARCHAR) são inofensivas mas não foram
aplicadas aqui para manter esta baseline como um marco puro: "a partir
daqui, mudanças de schema passam por migration revisada", sem tentar
corrigir retroativamente cada detalhe de um schema que já funciona.

Rodar `alembic stamp head` marca o banco como estando nesta revisão sem
executar nenhum upgrade/downgrade.
"""
from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = '4182fc577a23'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """No-op: baseline marca o schema já existente, não o altera."""
    pass


def downgrade() -> None:
    """No-op: não há schema anterior a restaurar."""
    pass
