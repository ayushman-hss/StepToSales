"""add live_event table

Revision ID: c41e7d2b8f15
Revises: 7b2e4c1f9a30
Create Date: 2026-09-30 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'c41e7d2b8f15'
down_revision: Union[str, None] = '7b2e4c1f9a30'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _repair_pre_release_login_tables(insp) -> None:
    """Databases that ran the branch before the login work was finished have a
    ``store_user`` without ``created_at`` and an unused ``session`` table.
    create_all() never alters existing tables, so fix them here."""
    if insp.has_table('store_user'):
        cols = {c['name'] for c in insp.get_columns('store_user')}
        if 'created_at' not in cols:
            op.add_column('store_user', sa.Column(
                'created_at', sa.DateTime(), nullable=False,
                server_default=sa.text('CURRENT_TIMESTAMP')))
    if insp.has_table('session'):
        op.drop_table('session')


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    _repair_pre_release_login_tables(insp)
    # The API's startup create_all() may already have made it on a dev DB.
    if insp.has_table('live_event'):
        return
    op.create_table('live_event',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('event_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('store_id', sa.Integer(), nullable=False),
    sa.Column('kind', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('source', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('ts', sa.DateTime(), nullable=False),
    sa.Column('date', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('hour', sa.Integer(), nullable=False),
    sa.Column('amount_paise', sa.Integer(), nullable=False),
    sa.Column('lines', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.ForeignKeyConstraint(['store_id'], ['store.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_live_event_date'), 'live_event', ['date'], unique=False)
    op.create_index(op.f('ix_live_event_event_id'), 'live_event', ['event_id'], unique=True)
    op.create_index(op.f('ix_live_event_kind'), 'live_event', ['kind'], unique=False)
    op.create_index(op.f('ix_live_event_store_id'), 'live_event', ['store_id'], unique=False)
    op.create_index(op.f('ix_live_event_ts'), 'live_event', ['ts'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_live_event_ts'), table_name='live_event')
    op.drop_index(op.f('ix_live_event_store_id'), table_name='live_event')
    op.drop_index(op.f('ix_live_event_kind'), table_name='live_event')
    op.drop_index(op.f('ix_live_event_event_id'), table_name='live_event')
    op.drop_index(op.f('ix_live_event_date'), table_name='live_event')
    op.drop_table('live_event')
