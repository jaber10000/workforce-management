"""Step 6/8: employee CRUD and 'an employee cannot read or change someone else's private data'."""
from tests.test_leave_and_versions import client  # noqa: F401  (fixture)
from tests.test_production import API, hdr, sec  # noqa: F401

NEW = {"employee_id": "N100", "full_name": "New Person", "phone_number": "0170000000", "home_thana": "Mirpur",
       "role_pool": "general", "weekly_off_day": "Friday", "joining_date": "2026-01-05", "notes": "manager-only note",
       "is_shift_eligible_night": True}


def test_employee_crud_lifecycle(sec):
    mgr = hdr(sec, "mgr1")
    r = sec.post(f"{API}/employees?auto_roster=false", json=NEW, headers=mgr)
    assert r.status_code == 201 and r.json()["employee_id"] == "N100" and r.json()["is_active"] is True
    assert sec.get(f"{API}/employees/N100", headers=mgr).json()["notes"] == "manager-only note"
    r = sec.patch(f"{API}/employees/N100", json={"full_name": "Renamed", "weekly_off_day": "Sunday"}, headers=mgr)
    assert r.status_code == 200 and r.json()["full_name"] == "Renamed" and r.json()["weekly_off_day"] == "Sunday"
    assert sec.get(f"{API}/employees?search=Renamed", headers=mgr).json()["total"] == 1
    assert sec.delete(f"{API}/employees/N100?auto_roster=false", headers=mgr).status_code == 204
    assert sec.get(f"{API}/employees/N100", headers=mgr).json()["is_active"] is False  # soft delete keeps history
    assert sec.get(f"{API}/employees?search=N100", headers=mgr).json()["total"] == 0
    assert sec.get(f"{API}/employees?search=N100&is_active=false", headers=mgr).json()["total"] == 1
    assert sec.get(f"{API}/employees/NOPE", headers=mgr).status_code == 404
    log = sec.get(f"{API}/roster/audit-log?entity_id=N100", headers=mgr).json()
    assert {"employee_created", "employee_updated", "employee_deactivated"} <= {a["action"] for a in log}


def test_unique_employee_id_is_case_insensitive_and_message_is_useful(sec):
    mgr = hdr(sec, "mgr1")
    assert sec.post(f"{API}/employees?auto_roster=false", json=NEW, headers=mgr).status_code == 201
    for dup in ("N100", "n100"):
        r = sec.post(f"{API}/employees?auto_roster=false", json={**NEW, "employee_id": dup}, headers=mgr)
        assert r.status_code == 409 and "already exists" in r.json()["detail"] and dup in r.json()["detail"]


def test_employee_validation_errors_are_readable(sec):
    mgr = hdr(sec, "mgr1")
    r = sec.post(f"{API}/employees", json={"employee_id": "bad id!", "full_name": ""}, headers=mgr)
    body = r.json()
    assert r.status_code == 422 and {e["field"] for e in body["errors"]} == {"employee_id", "full_name"}
    assert "employee_id" in body["detail"] and body["request_id"]
    r = sec.post(f"{API}/employees", json={**NEW, "weekly_off_day": "Funday"}, headers=mgr)
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "weekly_off_day"


def test_employee_sees_only_own_record_without_manager_notes(sec):
    mgr, emp1, emp2 = hdr(sec, "mgr1"), hdr(sec, "emp1"), hdr(sec, "emp2")
    sec.patch(f"{API}/employees/T001", json={"notes": "performance concern", "phone_number": "0181"}, headers=mgr)
    mine = sec.get(f"{API}/employees", headers=emp1).json()
    assert [e["employee_id"] for e in mine["items"]] == ["T001"] and mine["total"] == 1
    assert mine["items"][0]["notes"] is None and mine["items"][0]["phone_number"] == "0181"
    assert sec.get(f"{API}/employees/T001", headers=emp1).json()["notes"] is None
    assert sec.get(f"{API}/employees/T002", headers=emp1).status_code == 403
    found = sec.get(f"{API}/employees?search=T002", headers=emp1).json()["items"]
    assert "T002" not in [e["employee_id"] for e in found]  # searching never reveals a colleague
    assert [e["employee_id"] for e in sec.get(f"{API}/employees", headers=emp2).json()["items"]] == ["T002"]


def test_directory_exposes_names_only(sec):
    emp = hdr(sec, "emp1")
    d = sec.get(f"{API}/employees/directory", headers=emp).json()
    assert len(d) == 70 and set(d[0]) == {"employee_id", "full_name", "role_pool"}
    assert sec.get(f"{API}/employees/directory").status_code == 401


def test_employee_cannot_change_anyones_private_data(sec):
    mgr, emp1, emp2 = hdr(sec, "mgr1"), hdr(sec, "emp1"), hdr(sec, "emp2")
    before = sec.get(f"{API}/employees/T002", headers=mgr).json()
    assert sec.patch(f"{API}/employees/T002", json={"phone_number": "hacked"}, headers=emp1).status_code == 403
    assert sec.patch(f"{API}/employees/T001", json={"weekly_off_day": "Sunday"}, headers=emp1).status_code == 403  # not even own
    assert sec.delete(f"{API}/employees/T002", headers=emp1).status_code == 403
    assert sec.get(f"{API}/employees/T002", headers=mgr).json() == before
    # leave
    lv = sec.post(f"{API}/leaves", headers=emp2, json={"employee_id": "T002", "leave_type": "Casual",
                                                       "start_date": "2026-11-05", "end_date": "2026-11-05"}).json()
    lid = lv["application_id"]
    assert sec.post(f"{API}/leaves/{lid}/cancel", headers=emp1).status_code == 403
    assert sec.get(f"{API}/leaves/{lid}", headers=emp1).status_code == 403
    assert sec.get(f"{API}/leaves/balance/T002", headers=emp1).status_code == 403
    assert sec.post(f"{API}/leaves/{lid}/reject", headers=emp2).status_code == 403  # nobody approves/rejects own leave
    assert sec.get(f"{API}/leaves/{lid}", headers=mgr).json()["status"] == "Pending"
    # swaps: cannot request in someone else's name, cannot respond for them
    r = sec.post(f"{API}/swaps", headers=emp1, json={"requester_id": "T002", "counterpart_id": "T003", "work_date": "2026-11-02"})
    assert r.status_code == 403
    # users / audit / roster admin
    assert sec.get(f"{API}/auth/users", headers=emp1).status_code == 403
    assert sec.get(f"{API}/auth/users", headers=mgr).status_code == 403  # managers are not admins
    assert sec.post(f"{API}/auth/users", headers=emp1, json={"username": "evil1", "password": "Passw0rd!x", "role": "admin"}).status_code == 403
    assert sec.patch(f"{API}/auth/users/emp1", headers=emp1, json={"role": "admin"}).status_code == 403
    assert sec.get(f"{API}/roster/audit-log", headers=emp1).status_code == 403


def test_role_matrix_for_manager_vs_admin(sec):
    admin, mgr = hdr(sec, "admin"), hdr(sec, "mgr1")
    assert sec.get(f"{API}/auth/users", headers=admin).status_code == 200
    assert sec.post(f"{API}/employees?auto_roster=false", json=NEW, headers=mgr).status_code == 201
    assert sec.post(f"{API}/auth/users", headers=mgr, json={"username": "x1234", "password": "Passw0rd!x"}).status_code == 403
    me = sec.get(f"{API}/auth/me", headers=mgr).json()
    assert me["role"] == "manager" and me["username"] == "mgr1"
    assert sec.get(f"{API}/auth/me", headers={"Authorization": "Bearer garbage"}).status_code == 401
