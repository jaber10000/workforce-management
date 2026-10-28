"""Baseline: every table as of Step 5 (employees, leave, roster versions, audit, swaps, users).

Fresh database  -> creates all tables.
Existing Step 3-5 database (tables made by create_all / migrate_step5) -> already-present tables are left alone
and the Step 5 roster_versions columns are added if missing, so `alembic upgrade head` is safe on both.
Revision ID: 0001
"""
import sqlalchemy as sa
from alembic import op

from app import models  # noqa: F401
from app.db.session import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

STEP5_COLUMNS = {
    "created_by": sa.String(100), "approved_by": sa.String(100), "approved_at": sa.DateTime(timezone=True),
    "review_note": sa.String(500), "published_by": sa.String(100), "published_at": sa.DateTime(timezone=True),
}


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, checkfirst=True)
    have = {c["name"] for c in sa.inspect(bind).get_columns("roster_versions")}
    for name, typ in STEP5_COLUMNS.items():
        if name not in have:
            op.add_column("roster_versions", sa.Column(name, typ, nullable=True))


def downgrade() -> None:
    raise RuntimeError("The baseline cannot be downgraded. Restore from a backup instead (docs/BACKUP_RESTORE.md).")
