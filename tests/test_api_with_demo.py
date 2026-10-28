"""API tests on a SQLite database seeded from a demo workbook."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import Base, get_db
from app.main import app
from app.scripts.import_employees import import_workbook


@pytest.fixture()
def client(demo_files):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    seed = Session()
    import_workbook(next(f for f in demo_files if "01_standard" in f.name), db=seed)
    seed.close()

    def override():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    # TestClient without context manager -> lifespan (Postgres create_all) is not run
    yield TestClient(app)
    app.dependency_overrides.clear()
    engine.dispose()


def test_list_filter_and_search(client):
    r = client.get("/api/v1/employees?limit=200")
    assert r.status_code == 200 and r.json()["total"] == 200
    seniors = client.get("/api/v1/employees?role_pool=senior_support&limit=200").json()
    assert seniors["total"] == 24
    one = client.get("/api/v1/employees?search=EMP001").json()
    assert one["total"] == 1


def test_create_conflict_update_and_deactivate(client):
    payload = {"employee_id": "EMP900", "full_name": "Demo Added", "is_shift_eligible_night": True}
    assert client.post("/api/v1/employees", json=payload).status_code == 201
    assert client.post("/api/v1/employees", json=payload).status_code == 409
    r = client.patch("/api/v1/employees/EMP900", json={"role_pool": "senior_support"})
    assert r.status_code == 200 and r.json()["role_pool"] == "senior_support"
    assert client.delete("/api/v1/employees/EMP900").status_code == 204
    assert client.get("/api/v1/employees?search=EMP900").json()["total"] == 0  # hidden (inactive)
    assert client.get("/api/v1/employees/EMP900").json()["is_active"] is False  # history preserved
    assert client.get("/api/v1/employees/NOPE").status_code == 404
