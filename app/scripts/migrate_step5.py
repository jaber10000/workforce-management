"""Upgrade an existing Step 3/4 database to Step 5 (idempotent).

    python -m app.scripts.migrate_step5

Adds the approval columns to roster_versions. New tables (app_users, swap_requests, off_day_plans) are created
by the app's create_all; for real production use Alembic and turn this into a migration."""
from sqlalchemy import inspect, text

from app import models  # noqa: F401
from app.db.session import Base, engine

COLUMNS = {
    "created_by": "VARCHAR(100)", "approved_by": "VARCHAR(100)", "approved_at": "TIMESTAMP WITH TIME ZONE",
    "review_note": "VARCHAR(500)", "published_by": "VARCHAR(100)",
}


def main():
    Base.metadata.create_all(bind=engine)  # new tables only; existing tables are not altered
    have = {c["name"] for c in inspect(engine).get_columns("roster_versions")}
    with engine.begin() as conn:
        for name, ddl in COLUMNS.items():
            if name not in have:
                conn.execute(text(f"ALTER TABLE roster_versions ADD COLUMN {name} {ddl}"))
                print(f"added roster_versions.{name}")
    print("up to date")


if __name__ == "__main__":
    main()
