"""adiciona campos de confirmacao e pacote a crm_payments_ledger

Revision ID: 80aa42ffc8ad
Revises: 4f793030e267
Create Date: 2026-08-06 13:31:04.363322

Só crm_payments_ledger (app/crm_models.py::PaymentLedgerEntry): 4 colunas
novas (package, confirmation_id, paid_by, receipt_file_path/name) e o
DROP de `package_id` -- era FK morta pra ServiceCatalog, nunca usada por
nenhuma rota, 0 das 263 linhas reais tinham valor, confirmado antes desta
migration. Mesmo drift pré-existente (notion_page_id e outras tabelas)
removido daqui de propósito -- ver e7f089f746b1 pro mesmo raciocínio.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '80aa42ffc8ad'
down_revision: Union[str, Sequence[str], None] = '4f793030e267'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("PRAGMA foreign_keys=OFF")
    with op.batch_alter_table('crm_payments_ledger', schema=None) as batch_op:
        batch_op.add_column(sa.Column('package', sa.Enum('self_service', 'saes_standard', 'saes_plus', name='servicemode'), nullable=True))
        batch_op.add_column(sa.Column('confirmation_id', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('paid_by', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('receipt_file_path', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('receipt_file_name', sa.String(), nullable=True))
        batch_op.drop_column('package_id')
    op.execute("PRAGMA foreign_keys=ON")


def downgrade() -> None:
    op.execute("PRAGMA foreign_keys=OFF")
    with op.batch_alter_table('crm_payments_ledger', schema=None) as batch_op:
        batch_op.add_column(sa.Column('package_id', sa.INTEGER(), nullable=True))
        batch_op.drop_column('receipt_file_name')
        batch_op.drop_column('receipt_file_path')
        batch_op.drop_column('paid_by')
        batch_op.drop_column('confirmation_id')
        batch_op.drop_column('package')
    op.execute("PRAGMA foreign_keys=ON")
