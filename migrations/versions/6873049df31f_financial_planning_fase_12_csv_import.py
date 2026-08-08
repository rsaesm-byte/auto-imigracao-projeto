"""financial planning fase 12: csv import

Revision ID: 6873049df31f
Revises: ee75e3d70039
Create Date: 2026-08-07 19:51:51.596202

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6873049df31f'
down_revision: Union[str, Sequence[str], None] = 'ee75e3d70039'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Só as 2 tabelas novas (app/financial_planning_models.py, Fase 12) --
    o autogenerate detectou de novo a mesma pilha de drift pré-existente
    e não relacionado já vista em toda migração anterior desta sessão;
    removida manualmente pelo mesmo motivo. `create_table` puro, sem FK
    em tabela já existente que crie ciclo.
    """
    op.create_table('financial_csv_import_batches',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('financial_workspace_id', sa.Integer(), nullable=False),
    sa.Column('account_id', sa.Integer(), nullable=False),
    sa.Column('original_filename', sa.String(), nullable=False),
    sa.Column('detected_columns', sa.JSON(), nullable=False),
    sa.Column('column_mapping', sa.JSON(), nullable=True),
    sa.Column('status', sa.Enum('uploaded', 'mapped', 'completed', name='csvimportstatus'), nullable=False),
    sa.Column('imported_count', sa.Integer(), nullable=False),
    sa.Column('skipped_count', sa.Integer(), nullable=False),
    sa.Column('duplicate_count', sa.Integer(), nullable=False),
    sa.Column('error_count', sa.Integer(), nullable=False),
    sa.Column('created_by_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('completed_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['account_id'], ['financial_accounts.id'], ),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['financial_workspace_id'], ['financial_workspaces.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('financial_csv_import_batches', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_financial_csv_import_batches_financial_workspace_id'), ['financial_workspace_id'], unique=False)

    op.create_table('financial_csv_import_rows',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('batch_id', sa.Integer(), nullable=False),
    sa.Column('row_number', sa.Integer(), nullable=False),
    sa.Column('raw_data', sa.JSON(), nullable=False),
    sa.Column('parsed_date', sa.Date(), nullable=True),
    sa.Column('parsed_description', sa.String(), nullable=True),
    sa.Column('parsed_amount_cents', sa.Integer(), nullable=True),
    sa.Column('suggested_type', sa.Enum('income', 'expense', 'transfer', name='transactiontype'), nullable=True),
    sa.Column('suggested_category_id', sa.Integer(), nullable=True),
    sa.Column('is_duplicate', sa.Boolean(), nullable=False),
    sa.Column('duplicate_of_transaction_id', sa.Integer(), nullable=True),
    sa.Column('parse_error', sa.String(), nullable=True),
    sa.Column('status', sa.Enum('pending', 'imported', 'skipped', 'duplicate', 'error', name='csvimportrowstatus'), nullable=False),
    sa.Column('created_transaction_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['batch_id'], ['financial_csv_import_batches.id'], ),
    sa.ForeignKeyConstraint(['created_transaction_id'], ['financial_transactions.id'], ),
    sa.ForeignKeyConstraint(['duplicate_of_transaction_id'], ['financial_transactions.id'], ),
    sa.ForeignKeyConstraint(['suggested_category_id'], ['financial_budget_categories.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('financial_csv_import_rows', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_financial_csv_import_rows_batch_id'), ['batch_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('financial_csv_import_rows', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_financial_csv_import_rows_batch_id'))

    op.drop_table('financial_csv_import_rows')
    with op.batch_alter_table('financial_csv_import_batches', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_financial_csv_import_batches_financial_workspace_id'))

    op.drop_table('financial_csv_import_batches')
