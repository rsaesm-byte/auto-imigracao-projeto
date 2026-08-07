"""add client verified flags, notification recipient, required document translation flag

Revision ID: c9c72316523d
Revises: 460694814161
Create Date: 2026-08-06 17:19:40.377796

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c9c72316523d'
down_revision: Union[str, Sequence[str], None] = '460694814161'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # crm_clients é referenciada por muitas outras tabelas -- batch mode
    # recria a tabela inteira (DROP + CREATE) mesmo pra um simples ADD
    # COLUMN, o que estoura FOREIGN KEY constraint sem desligar a checagem
    # temporariamente (mesmo problema já visto nas migrações c1926f006c3f/
    # 80aa42ffc8ad desta sessão).
    op.execute("PRAGMA foreign_keys=OFF")
    with op.batch_alter_table('crm_clients', schema=None) as batch_op:
        batch_op.add_column(sa.Column('personal_email_verified', sa.Boolean(), nullable=False, server_default=sa.text('0')))
        batch_op.add_column(sa.Column('us_phone_verified', sa.Boolean(), nullable=False, server_default=sa.text('0')))
        batch_op.add_column(sa.Column('us_address_verified', sa.Boolean(), nullable=False, server_default=sa.text('0')))
    op.execute("PRAGMA foreign_keys=ON")

    with op.batch_alter_table('notifications', schema=None) as batch_op:
        batch_op.add_column(sa.Column('recipient_user_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_notifications_recipient_user_id'), ['recipient_user_id'], unique=False)
        batch_op.create_foreign_key(
            'fk_notifications_recipient_user_id_users', 'users', ['recipient_user_id'], ['id'])

    with op.batch_alter_table('required_documents', schema=None) as batch_op:
        batch_op.add_column(sa.Column('needs_translation', sa.Boolean(), nullable=False, server_default=sa.text('0')))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('required_documents', schema=None) as batch_op:
        batch_op.drop_column('needs_translation')

    with op.batch_alter_table('notifications', schema=None) as batch_op:
        batch_op.drop_constraint('fk_notifications_recipient_user_id_users', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_notifications_recipient_user_id'))
        batch_op.drop_column('recipient_user_id')

    with op.batch_alter_table('crm_clients', schema=None) as batch_op:
        batch_op.drop_column('us_address_verified')
        batch_op.drop_column('us_phone_verified')
        batch_op.drop_column('personal_email_verified')
