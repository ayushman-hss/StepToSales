"""alert_chat.hourly: opt-in hourly updates per chat

Revision ID: f3b8d1a6c2e4
Revises: e5a1c9d3b7f2
Create Date: 2026-09-30 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f3b8d1a6c2e4'
down_revision: Union[str, None] = 'e5a1c9d3b7f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    # Skip if the API's startup create_all() already made the column.
    if 'hourly' not in {c['name'] for c in insp.get_columns('alert_chat')}:
        op.add_column('alert_chat', sa.Column(
            'hourly', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column('alert_chat', 'hourly')
