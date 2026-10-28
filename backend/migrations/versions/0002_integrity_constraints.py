"""Integrity rules enforced by the database itself (Step 9).

* employees.employee_id unique ignoring case (t001 == T001)
* one live (Pending/Approved) leave application per employee and start date - blocks double-submits that race
  past the application-level overlap check
* one open swap per requester + counterpart + date
* leave / roster date sanity as CHECK constraints (PostgreSQL only; SQLite ignores them)
Revision ID: 0002
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def _pg() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_employee_id_ci ON employees (lower(employee_id))")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_leave_live_start ON leave_applications (employee_id, start_date) "
               "WHERE status IN ('Pending', 'Approved')")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_swap_open ON swap_requests (requester_id, counterpart_id, work_date) "
               "WHERE status IN ('pending_counterpart', 'pending_manager')")
    if _pg():
        op.create_check_constraint("ck_leave_dates", "leave_applications", "end_date >= start_date")
        op.create_check_constraint("ck_leave_days_positive", "leave_applications", "days > 0")
        op.create_check_constraint("ck_roster_dates", "roster_versions", "end_date >= start_date")
        op.create_check_constraint("ck_leave_status", "leave_applications",
                                   "status IN ('Pending','Approved','Rejected','Cancelled')")


def downgrade() -> None:
    if _pg():
        for name, table in (("ck_leave_status", "leave_applications"), ("ck_roster_dates", "roster_versions"),
                            ("ck_leave_days_positive", "leave_applications"), ("ck_leave_dates", "leave_applications")):
            op.drop_constraint(name, table)
    for ix in ("uq_swap_open", "uq_leave_live_start", "uq_employee_id_ci"):
        op.execute(f"DROP INDEX IF EXISTS {ix}")
