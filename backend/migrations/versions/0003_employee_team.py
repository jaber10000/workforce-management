"""Teams: employees.team (e.g. 'Team 1'), set by POST /teams/auto-assign or edited per employee.
Revision ID: 0003
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("employees")}
    if "team" not in cols:  # fresh databases already have it (0001 runs create_all from the current models)
        op.add_column("employees", sa.Column("team", sa.String(40), nullable=True))
    op.execute("CREATE INDEX IF NOT EXISTS ix_employees_team ON employees (team)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_employees_team")
    op.drop_column("employees", "team")
