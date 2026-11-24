"""Evaluation tests for the SPV portal: logins, role access, attendance alerts, fee reminders,
homework, circulars, parent updates, vans, agent answers and Excel import.

Run:  SPV_SEED=<seed.json> python -m pytest tests -q
      (add DATABASE_URL=postgresql://... to run the same tests on Postgres)
The seed file is the test data (not in the repo, because it has real test phone numbers).
"""
import base64
import gzip
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SEED = os.getenv("SPV_SEED")
pytestmark = pytest.mark.skipif(not SEED, reason="set SPV_SEED to the test seed.json")



def _people():
    """Pick test people from the seed itself, so no real names or numbers live in this public repo."""
    import re
    seed = json.loads(Path(SEED).read_text(encoding="utf-8"))
    ok = lambda ph: re.fullmatch(r"[6-9]\d{9}", ph)
    staff = {t["phone"]: t for t in seed["staff"]}
    real = sorted([s for s in seed["students"] if ok(s["phone"])], key=lambda s: s["class"])
    dual_kid = next(s for s in real if s["phone"] in staff)               # parent who is also a teacher
    teacher = next(t for t in seed["staff"] if t["class"] == dual_kid["class"])
    a = next(s for s in real if s["phone"] != dual_kid["phone"])          # lowest-class other parent
    principal = next(s for s in real if s["phone"] not in (a["phone"], dual_kid["phone"]) and s["route"] == a["route"])
    other = next(s for s in reversed(real) if s["route"] not in (a["route"], "Own")
                 and s["fee_paid"] / s["fee_total"] < .7)
    route_name = next(r["name"] for r in seed["routes"] if r["id"] == a["route"])
    return dual_kid, teacher, a, principal, other, route_name


if SEED:
    KID_D, TEACHER, KID_A, KID_P, KID_O, ROUTE_A = _people()
    PRINCIPAL, PARENT_A, DUAL_PHONE, TEACHER_PHONE = KID_P["phone"], KID_A["phone"], KID_D["phone"], TEACHER["phone"]
    OTHER_PARENT = KID_O["phone"]


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    os.environ.update({
        "SPV_STORE_FILE": str(tmp_path_factory.mktemp("db") / "store.json"),
        "OTP_DEV_MODE": "true", "JWT_SECRET": "test-secret", "PRINCIPAL_PHONES": PRINCIPAL,
        "ADMIN_PHONES": PRINCIPAL, "CORRESPONDENT_PHONES": PRINCIPAL, "VAN_KEY": "vankey", "CRON_SECRET": "cron",
        "LLM_PROVIDER": "offline",
        "SEED_DATA": base64.b64encode(gzip.compress(Path(SEED).read_bytes())).decode()})
    for k in ("WHATSAPP_TOKEN", "WHATSAPP_PHONE_ID"):
        os.environ.pop(k, None)
    sys.path.insert(0, str(ROOT / "agent"))
    sys.path.insert(0, str(ROOT))
    if os.getenv("DATABASE_URL"):
        import store
        store._pg_run("DROP TABLE IF EXISTS spv_kv")
        store._pg = None
    from fastapi.testclient import TestClient

    from api.index import app
    return TestClient(app)


def login(client, phone, role=None):
    import store
    store.delete(f"otp:{phone}")  # tests log in many times; the 30 s resend limit has its own test
    r = client.post("/api/auth/otp", json={"phone": phone})
    assert r.status_code == 200, r.text
    v = client.post("/api/auth/verify", json={"phone": phone, "code": r.json()["dev_code"]}).json()
    roles = [x["role"] for x in v["roles"]]
    h = {"Authorization": f"Bearer {v['token']}", "X-Role": role or roles[0]}
    return h, roles


def test_unknown_number_cannot_login(client):
    assert client.post("/api/auth/otp", json={"phone": "9000000001"}).status_code == 404


def test_wrong_otp_rejected_and_resend_limited(client):
    import store
    store.delete(f"otp:{OTHER_PARENT}")
    client.post("/api/auth/otp", json={"phone": OTHER_PARENT})
    assert client.post("/api/auth/verify", json={"phone": OTHER_PARENT, "code": "000000"}).status_code == 400
    assert client.post("/api/auth/otp", json={"phone": OTHER_PARENT}).status_code == 429
    for _ in range(4):
        client.post("/api/auth/verify", json={"phone": OTHER_PARENT, "code": "000000"})
    assert client.post("/api/auth/verify", json={"phone": OTHER_PARENT, "code": "000000"}).status_code == 429


def test_one_number_two_roles(client):
    _, roles = login(client, DUAL_PHONE)
    assert roles == ["teacher", "parent"]


def test_parent_sees_only_own_child(client):
    h, _ = login(client, PARENT_A, "parent")
    kids = client.get("/api/portal/parent", headers=h).json()["children"]
    assert [k["name"] for k in kids] == [KID_A["name"]]
    first = KID_A["name"].split()[0].lower()
    assert [r["name"] for r in client.get(f"/api/portal/search?q={first}", headers=h).json()["results"]] == [KID_A["name"]]
    assert client.get(f"/api/portal/student/{KID_O['id']}", headers=h).status_code == 404  # other family
    assert client.get("/api/portal/dashboard", headers=h).status_code == 403


def test_role_cannot_be_faked(client):
    h, _ = login(client, PARENT_A, "parent")
    h["X-Role"] = "principal"
    assert client.get("/api/portal/dashboard", headers=h).status_code == 403


def test_teacher_attendance_absent_alerts_parent_once(client):
    h, roles = login(client, TEACHER_PHONE, "teacher")
    cls = client.get("/api/portal/class?cls=9", headers=h).json()
    assert cls["class"] == TEACHER["class"]  # a class teacher always gets their own class
    marks = {s["id"]: ("A" if s["id"] == KID_D["id"] else "P") for s in cls["students"]}
    r = client.post("/api/portal/attendance", headers=h, json={"cls": 1, "marks": marks}).json()
    assert r["class"] == TEACHER["class"] and r["absent"] == 1
    msg = r["messages"][0]
    assert msg["status"] == "queued" and f"wa.me/91{DUAL_PHONE}" in msg["link"] and "ABSENT" in msg["link"].upper()
    again = client.post("/api/portal/attendance", headers=h, json={"marks": marks}).json()
    assert again["messages"] == []  # no duplicate alert on re-save
    p, _ = login(client, DUAL_PHONE, "parent")
    kid = client.get("/api/portal/parent", headers=p).json()["children"][0]
    assert kid["attendance"]["today"] == "A"


def test_attendance_needs_every_student(client):
    h, _ = login(client, TEACHER_PHONE, "teacher")
    assert client.post("/api/portal/attendance", headers=h, json={"marks": {KID_D["id"]: "P"}}).status_code == 400


def test_principal_dashboard_and_search(client):
    h, roles = login(client, PRINCIPAL, "principal")
    assert {"principal", "correspondent", "admin", "parent"} <= set(roles)
    d = client.get("/api/portal/dashboard", headers=h).json()
    assert d["students"] == 100 and d["attendance"]["marked"] >= 1
    assert d["fees"]["flagged"] and all(x["pct"] > 30 for x in d["fees"]["flagged"])
    assert client.get(f"/api/portal/search?q={KID_O['id']}", headers=h).json()["results"][0]["class"] == KID_O["class"]


def test_fee_reminder_rule():
    import school
    s = {"fee_total": 10000, "fee_paid": 6000}
    assert school.fee_flag(s) and not school.fee_flag({"fee_total": 10000, "fee_paid": 7000})
    assert school.reminder_due(s, None, "2026-11-25")
    assert not school.reminder_due(s, "2026-11-10", "2026-11-25")  # 15 days
    assert school.reminder_due(s, "2026-11-04", "2026-11-25")      # 21 days


def test_fee_reminders_run_once_per_three_weeks(client):
    h, _ = login(client, PRINCIPAL, "principal")
    first = client.post("/api/portal/fees/remind", headers=h).json()
    assert first["count"] > 0
    assert any(m["name"] == KID_O["name"] and m["status"] == "queued" for m in first["messages"])
    assert client.post("/api/portal/fees/remind", headers=h).json()["count"] == 0
    assert client.get("/api/cron/fee-reminders").status_code == 401
    assert client.get("/api/cron/fee-reminders", headers={"Authorization": "Bearer cron"}).json()["count"] == 0


def test_payment_clears_reminder(client):
    h, _ = login(client, PRINCIPAL, "admin")
    card = client.post("/api/portal/fees/payment", headers=h, json={"student": KID_O["id"], "amount": KID_O["fee_total"]}).json()
    assert card["balance"] == 0 and not card["fee_flag"]


def test_circular_to_staff(client):
    t, _ = login(client, TEACHER_PHONE, "teacher")
    items = client.get("/api/portal/circulars", headers=t).json()["items"]
    assert "pls inform about fees" in items[-1]["text"]
    p, _ = login(client, PRINCIPAL, "principal")
    client.post("/api/portal/circulars", headers=p, json={"text": "Staff meeting at 4 pm"})
    assert client.get("/api/portal/circulars", headers=t).json()["items"][0]["text"] == "Staff meeting at 4 pm"
    a, _ = login(client, PARENT_A, "parent")
    assert client.get("/api/portal/circulars", headers=a).status_code == 403


def test_admin_update_reaches_right_class(client):
    h, _ = login(client, PRINCIPAL, "admin")
    r = client.post("/api/portal/updates", headers=h, json={"text": "Class picnic on Friday", "audience": str(KID_D["class"])}).json()
    assert r["messages"]["queued"] >= 1
    p, _ = login(client, DUAL_PHONE, "parent")
    assert client.get("/api/portal/parent", headers=p).json()["updates"][0]["text"] == "Class picnic on Friday"
    a, _ = login(client, PARENT_A, "parent")
    assert all(u["text"] != "Class picnic on Friday" for u in client.get("/api/portal/parent", headers=a).json()["updates"])


def test_homework_to_class_parents(client):
    h, _ = login(client, TEACHER_PHONE, "teacher")
    r = client.post("/api/portal/homework", headers=h, json={"subject": "Maths", "text": "Table of 7"}).json()
    assert r["item"]["class"] == TEACHER["class"] and r["messages"]["queued"] == 1 and r["group_link"].startswith("https://wa.me/?text=")
    p, _ = login(client, DUAL_PHONE, "parent")
    assert client.get("/api/portal/parent", headers=p).json()["children"][0]["homework"][0]["text"] == "Table of 7"


def test_van_gps_and_route_privacy(client):
    assert client.post("/api/van/loc/wrong?id=111&lat=14.04&lon=79.98").status_code == 403
    assert client.post("/api/van/loc/vankey?id=111&lat=14.04&lon=79.98&speed=10").json()["ok"]
    h, _ = login(client, PRINCIPAL, "principal")
    rs = client.get("/api/portal/routes", headers=h).json()["routes"]
    assert any(r["device_id"] == "111" and r["name"].startswith("Unassigned") for r in rs)
    client.post(f"/api/portal/routes/{KID_A['route']}", headers=h, json={"device_id": "111", "driver": "Ravi"})
    assert client.post("/api/van/loc/vankey?id=999&lat=14&lon=79").status_code == 403  # unknown phone now
    client.post("/api/van/loc/vankey", json={"device_id": "111", "location": {
        "timestamp": "2030-01-01T00:00:00Z", "coords": {"latitude": 14.05, "longitude": 79.99, "speed": 8}}})
    a, _ = login(client, PARENT_A, "parent")
    mine = client.get("/api/portal/routes", headers=a).json()["routes"]
    assert [r["id"] for r in mine] == [KID_A["route"]] and mine[0]["position"]["lat"] == 14.05
    d, _ = login(client, OTHER_PARENT, "parent")  # other family on another route must not see it
    assert all(r["id"] != KID_A["route"] for r in client.get("/api/portal/routes", headers=d).json()["routes"])


def test_agent_answers_from_own_data(client):
    a, _ = login(client, PARENT_A, "parent")
    reply = client.post("/api/portal/chat", headers=a, json={"message": "How is my child doing?"}).json()["reply"]
    assert KID_A["name"] in reply and KID_O["name"] not in reply
    reply = client.post("/api/portal/chat", headers=a, json={"message": "where is the van?"}).json()["reply"]
    assert ROUTE_A in reply
    p, _ = login(client, PRINCIPAL, "principal")
    assert "classes marked" in client.post("/api/portal/chat", headers=p, json={"message": "today's attendance"}).json()["reply"]
    assert KID_O["name"] in client.post("/api/portal/chat", headers=p, json={"message": f"search {KID_O['id']}"}).json()["reply"]


def test_team_and_excel_import(client):
    h, _ = login(client, PRINCIPAL, "admin")
    assert client.post("/api/portal/team", headers=h, json={"phone": "9000011111", "name": "Office", "role": "teacher"}).status_code == 400
    xlsx = Path(SEED).with_name("SPV_Test_Students.xlsx")
    if xlsx.exists():
        r = client.post("/api/portal/import", headers=h, content=xlsx.read_bytes()).json()
        assert r["students"] == 100 and r["staff"] == 10 and r["routes"] == 3 and not r["errors"]
        p, _ = login(client, DUAL_PHONE, "parent")
        kid = client.get("/api/portal/parent", headers=p).json()["children"][0]
        assert kid["marks"]["SA1"]["Maths"] > 0
