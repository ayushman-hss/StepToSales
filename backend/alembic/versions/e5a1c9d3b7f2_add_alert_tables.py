"""add telegram alert tables

Revision ID: e5a1c9d3b7f2
Revises: c41e7d2b8f15
Create Date: 2026-09-30 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'e5a1c9d3b7f2'
down_revision: Union[str, None] = 'c41e7d2b8f15'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    # The API's startup create_all() may already have made them on a dev DB.
    if not insp.has_table('alert_chat'):
        op.create_table('alert_chat',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('store_id', sa.Integer(), nullable=False),
        sa.Column('chat_id', sa.BigInteger(), nullable=False),
        sa.Column('title', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('linked_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['store_id'], ['store.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('store_id', 'chat_id')
        )
        op.create_index(op.f('ix_alert_chat_store_id'), 'alert_chat', ['store_id'], unique=False)
        op.create_index(op.f('ix_alert_chat_chat_id'), 'alert_chat', ['chat_id'], unique=False)
    if not insp.has_table('alert_link_code'):
        op.create_table('alert_link_code',
        sa.Column('code', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('store_id', sa.Integer(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['store_id'], ['store.id'], ),
        sa.PrimaryKeyConstraint('code')
        )
        op.create_index(op.f('ix_alert_link_code_store_id'), 'alert_link_code', ['store_id'], unique=False)
    if not insp.has_table('alert_sent'):
        op.create_table('alert_sent',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('store_id', sa.Integer(), nullable=False),
        sa.Column('kind', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('key', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('text', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('shop_time', sa.DateTime(), nullable=False),
        sa.Column('delivered', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['store_id'], ['store.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('store_id', 'kind', 'key')
        )
        op.create_index(op.f('ix_alert_sent_store_id'), 'alert_sent', ['store_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_alert_sent_store_id'), table_name='alert_sent')
    op.drop_table('alert_sent')
    op.drop_index(op.f('ix_alert_link_code_store_id'), table_name='alert_link_code')
    op.drop_table('alert_link_code')
    op.drop_index(op.f('ix_alert_chat_chat_id'), table_name='alert_chat')
    op.drop_index(op.f('ix_alert_chat_store_id'), table_name='alert_chat')
    op.drop_table('alert_chat')
