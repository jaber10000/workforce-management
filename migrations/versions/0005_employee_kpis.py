"""Monthly KPI per employee (uploaded by supervisor / senior agent).
Revision ID: 0005
"""
from alembic import op

from app.models.kpi import EmployeeKpi

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    EmployeeKpi.__table__.create(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    op.drop_table("employee_kpis")
