import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.db.session import Base  # noqa: E402
from app import models  # noqa: F401,E402

DEMO_DIR = Path(__file__).resolve().parents[2] / "demo_data"


@pytest.fixture(scope="session")
def demo_files():
    files = sorted(DEMO_DIR.glob("demo_roster_*.xlsx"))
    assert files, f"No demo workbooks in {DEMO_DIR}. Run: python -m app.scripts.generate_demo_data"
    return files


@pytest.fixture()
def sqlite_session():
    """In-memory SQLite so tests never need PostgreSQL."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


@pytest.fixture(autouse=True)
def _open_mode(monkeypatch):
    """Legacy engine/leave/roster tests run in open mode (no login, direct publish).
    test_production.py switches auth and the approval workflow back on."""
    monkeypatch.setattr(settings, "auth_required", False)
    monkeypatch.setattr(settings, "require_approval", False)
