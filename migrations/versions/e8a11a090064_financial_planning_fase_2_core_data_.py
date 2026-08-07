"""financial planning fase 2: core data model

Revision ID: e8a11a090064
Revises: c916339cd11e
Create Date: 2026-08-07 12:18:40.803521

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e8a11a090064'
down_revision: Union[str, Sequence[str], None] = 'c916339cd11e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Só as 5 tabelas novas (app/financial_planning_models.py) -- o
    autogenerate detectou de novo a mesma pilha de drift pré-existente e
    não relacionado já vista nas migrações anteriores; removida
    manualmente pelo mesmo motivo (tratada à parte pelas funções
    `_ensure_*_column` em app/__init__.py). Nenhuma delas mexe numa
    tabela já existente (todas são `create_table` puro), então não bate
    no problema de FK-em-tabela-referenciada já visto na migração da
    Fase 1 (c916339cd11e).
    """
    op.create_table('financial_accounts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('financial_workspace_id', sa.Integer(), nullable=False),
    sa.Column('account_name', sa.String(), nullable=False),
    sa.Column('institution_name', sa.String(), nullable=True),
    sa.Column('account_type', sa.Enum('checking', 'savings', 'money_market', 'cash', 'other_bank_account', name='accounttype'), nullable=False),
    sa.Column('nickname', sa.String(), nullable=True),
    sa.Column('last_four_digits', sa.String(), nullable=True),
    sa.Column('current_balance_cents', sa.Integer(), nullable=False),
    sa.Column('available_balance_cents', sa.Integer(), nullable=True),
    sa.Column('currency', sa.String(), nullable=False),
    sa.Column('include_in_cash_flow', sa.Boolean(), nullable=False),
    sa.Column('include_in_net_worth', sa.Boolean(), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_by_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('deleted_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['financial_workspace_id'], ['financial_workspaces.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('financial_accounts', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_financial_accounts_deleted_at'), ['deleted_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_financial_accounts_financial_workspace_id'), ['financial_workspace_id'], unique=False)

    op.create_table('financial_attachments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('financial_workspace_id', sa.Integer(), nullable=False),
    sa.Column('record_type', sa.String(), nullable=False),
    sa.Column('record_id', sa.Integer(), nullable=False),
    sa.Column('storage_key', sa.String(), nullable=False),
    sa.Column('original_filename', sa.String(), nullable=False),
    sa.Column('mime_type', sa.String(), nullable=False),
    sa.Column('file_size_bytes', sa.Integer(), nullable=False),
    sa.Column('file_hash', sa.String(), nullable=True),
    sa.Column('uploaded_by_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('deleted_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['financial_workspace_id'], ['financial_workspaces.id'], ),
    sa.ForeignKeyConstraint(['uploaded_by_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('financial_attachments', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_financial_attachments_financial_workspace_id'), ['financial_workspace_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_financial_attachments_record_id'), ['record_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_financial_attachments_record_type'), ['record_type'], unique=False)

    op.create_table('financial_budget_categories',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('financial_workspace_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('category_group', sa.Enum('needs', 'wants', 'savings', name='budgetcategorygroup'), nullable=False),
    sa.Column('parent_category_id', sa.Integer(), nullable=True),
    sa.Column('icon', sa.String(), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['financial_workspace_id'], ['financial_workspaces.id'], ),
    sa.ForeignKeyConstraint(['parent_category_id'], ['financial_budget_categories.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('financial_budget_categories', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_financial_budget_categories_financial_workspace_id'), ['financial_workspace_id'], unique=False)

    op.create_table('financial_income_sources',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('financial_workspace_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('type', sa.String(), nullable=True),
    sa.Column('default_amount_cents', sa.Integer(), nullable=True),
    sa.Column('frequency', sa.String(), nullable=True),
    sa.Column('default_account_id', sa.Integer(), nullable=True),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['default_account_id'], ['financial_accounts.id'], ),
    sa.ForeignKeyConstraint(['financial_workspace_id'], ['financial_workspaces.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('financial_income_sources', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_financial_income_sources_financial_workspace_id'), ['financial_workspace_id'], unique=False)

    op.create_table('financial_transactions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('financial_workspace_id', sa.Integer(), nullable=False),
    sa.Column('transaction_type', sa.Enum('income', 'expense', 'transfer', name='transactiontype'), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('amount_cents', sa.Integer(), nullable=False),
    sa.Column('currency', sa.String(), nullable=False),
    sa.Column('transaction_date', sa.Date(), nullable=False),
    sa.Column('account_id', sa.Integer(), nullable=True),
    sa.Column('transfer_from_account_id', sa.Integer(), nullable=True),
    sa.Column('transfer_to_account_id', sa.Integer(), nullable=True),
    sa.Column('budget_category_id', sa.Integer(), nullable=True),
    sa.Column('merchant_or_source', sa.String(), nullable=True),
    sa.Column('payment_method', sa.Enum('cash', 'debit_card', 'credit_card', 'check', 'bank_transfer', 'other', name='paymentmethodtype'), nullable=True),
    sa.Column('classification', sa.Enum('needs', 'wants', 'savings', name='transactionclassification'), nullable=True),
    sa.Column('status', sa.Enum('projected', 'scheduled', 'completed', 'cancelled', name='transactionstatus'), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_by_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('deleted_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['account_id'], ['financial_accounts.id'], ),
    sa.ForeignKeyConstraint(['budget_category_id'], ['financial_budget_categories.id'], ),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['financial_workspace_id'], ['financial_workspaces.id'], ),
    sa.ForeignKeyConstraint(['transfer_from_account_id'], ['financial_accounts.id'], ),
    sa.ForeignKeyConstraint(['transfer_to_account_id'], ['financial_accounts.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('financial_transactions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_financial_transactions_account_id'), ['account_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_financial_transactions_budget_category_id'), ['budget_category_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_financial_transactions_deleted_at'), ['deleted_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_financial_transactions_financial_workspace_id'), ['financial_workspace_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_financial_transactions_status'), ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_financial_transactions_transaction_date'), ['transaction_date'], unique=False)
        batch_op.create_index(batch_op.f('ix_financial_transactions_transaction_type'), ['transaction_type'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('financial_transactions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_financial_transactions_transaction_type'))
        batch_op.drop_index(batch_op.f('ix_financial_transactions_transaction_date'))
        batch_op.drop_index(batch_op.f('ix_financial_transactions_status'))
        batch_op.drop_index(batch_op.f('ix_financial_transactions_financial_workspace_id'))
        batch_op.drop_index(batch_op.f('ix_financial_transactions_deleted_at'))
        batch_op.drop_index(batch_op.f('ix_financial_transactions_budget_category_id'))
        batch_op.drop_index(batch_op.f('ix_financial_transactions_account_id'))

    op.drop_table('financial_transactions')
    with op.batch_alter_table('financial_income_sources', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_financial_income_sources_financial_workspace_id'))

    op.drop_table('financial_income_sources')
    with op.batch_alter_table('financial_budget_categories', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_financial_budget_categories_financial_workspace_id'))

    op.drop_table('financial_budget_categories')
    with op.batch_alter_table('financial_attachments', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_financial_attachments_record_type'))
        batch_op.drop_index(batch_op.f('ix_financial_attachments_record_id'))
        batch_op.drop_index(batch_op.f('ix_financial_attachments_financial_workspace_id'))

    op.drop_table('financial_attachments')
    with op.batch_alter_table('financial_accounts', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_financial_accounts_financial_workspace_id'))
        batch_op.drop_index(batch_op.f('ix_financial_accounts_deleted_at'))

    op.drop_table('financial_accounts')
