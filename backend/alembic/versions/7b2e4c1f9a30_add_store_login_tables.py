"""add store login tables

Revision ID: 7b2e4c1f9a30
Revises: 0cc0e18d4fcc
Create Date: 2026-09-30 12:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '7b2e4c1f9a30'
down_revision: Union[str, None] = '0cc0e18d4fcc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _exists(table: str) -> bool:
    # The API's startup create_all() may already have made these tables on a
    # dev database; skip rather than fail so `alembic upgrade head` still runs.
    return sa.inspect(op.get_bind()).has_table(table)


def upgrade() -> None:
    if not _exists('store_user'):
        op.create_table('store_user',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('store_id', sa.Integer(), nullable=False),
        sa.Column('username', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('password_hash', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['store_id'], ['store.id'], ),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_store_user_store_id'), 'store_user', ['store_id'], unique=False)
        op.create_index(op.f('ix_store_user_username'), 'store_user', ['username'], unique=True)

    if not _exists('auth_session'):
        op.create_table('auth_session',
        sa.Column('token_hash', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('store_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['store_id'], ['store.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['store_user.id'], ),
        sa.PrimaryKeyConstraint('token_hash')
        )
        op.create_index(op.f('ix_auth_session_expires_at'), 'auth_session', ['expires_at'], unique=False)
        op.create_index(op.f('ix_auth_session_store_id'), 'auth_session', ['store_id'], unique=False)
        op.create_index(op.f('ix_auth_session_user_id'), 'auth_session', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_auth_session_user_id'), table_name='auth_session')
    op.drop_index(op.f('ix_auth_session_store_id'), table_name='auth_session')
    op.drop_index(op.f('ix_auth_session_expires_at'), table_name='auth_session')
    op.drop_table('auth_session')
    op.drop_index(op.f('ix_store_user_username'), table_name='store_user')
    op.drop_index(op.f('ix_store_user_store_id'), table_name='store_user')
    op.drop_table('store_user')
