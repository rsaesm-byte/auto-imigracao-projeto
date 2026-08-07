"""financial planning fase 9: net worth

Revision ID: 1439a4f245aa
Revises: 7b76be97acad
Create Date: 2026-08-07 16:30:41.552436

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1439a4f245aa'
down_revision: Union[str, Sequence[str], None] = '7b76be97acad'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Só a tabela nova (app/financial_planning_models.py, Fase 9) -- o
    autogenerate detectou de novo a mesma pilha de drift pré-existente e
    não relacionado já vista em toda migração anterior desta sessão;
    removida manualmente pelo mesmo motivo. `create_table` puro, sem FK em
    tabela já existente.
    """
    op.create_table('financial_account_balance_snapshots',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('account_id', sa.Integer(), nullable=False),
    sa.Column('balance_cents', sa.Integer(), nullable=False),
    sa.Column('available_balance_cents', sa.Integer(), nullable=True),
    sa.Column('snapshot_date', sa.Date(), nullable=False),
    sa.Column('source', sa.Enum('manual', 'imported', 'integration', 'month_close', name='snapshotsource'), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['account_id'], ['financial_accounts.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('account_id', 'snapshot_date', name='uq_account_balance_snapshot_day')
    )
    with op.batch_alter_table('financial_account_balance_snapshots', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_financial_account_balance_snapshots_account_id'), ['account_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_financial_account_balance_snapshots_snapshot_date'), ['snapshot_date'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('financial_account_balance_snapshots', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_financial_account_balance_snapshots_snapshot_date'))
        batch_op.drop_index(batch_op.f('ix_financial_account_balance_snapshots_account_id'))

    op.drop_table('financial_account_balance_snapshots')
