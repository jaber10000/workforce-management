"""Data fix: teams called "Team 1", "Team 2" ... are renamed after their supervisor ("Team Arif").
Members are not moved; a numbered team without a supervisor keeps its name.
Revision ID: 0006
"""
import re

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT employee_id, full_name, role_pool, team FROM employees WHERE team IS NOT NULL")).fetchall()
    taken = {r.team for r in rows if not re.match(r"^Team \d+$", r.team)}
    numbered = sorted({r.team for r in rows if re.match(r"^Team \d+$", r.team)})
    for old in numbered:
        leaders = sorted((r for r in rows if r.team == old and str(r.role_pool).lower().endswith("supervisor")), key=lambda r: r.employee_id)
        if not leaders:
            continue
        new = f"Team {leaders[0].full_name}"
        if new in taken:
            new = f"{new} ({leaders[0].employee_id})"
        taken.add(new)
        bind.execute(sa.text("UPDATE employees SET team = :new WHERE team = :old"), {"new": new, "old": old})


def downgrade() -> None:
    pass  # names are data; nothing to undo
