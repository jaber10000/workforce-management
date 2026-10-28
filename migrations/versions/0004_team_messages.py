"""Team conversations (employee <-> team leader) with optional image attachments.
Revision ID: 0004
"""
import sqlalchemy as sa
from alembic import op

from app.models.message import TeamMessage

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    TeamMessage.__table__.create(bind=op.get_bind(), checkfirst=True)  # fresh DBs already got it from 0001's create_all


def downgrade() -> None:
    op.drop_table("team_messages")
