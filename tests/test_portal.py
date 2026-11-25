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
        "SUPERADMIN_PHONES": PRINCIPAL, "ADMIN_PHONES": DUAL_PHONE, "CORRESPONDENT_PHONES": PRINCIPAL, "VAN_KEY": "vankey", "CRON_SECRET": "cron",
        "LLM_PROVIDER": "offline", "DATA_KEY": "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8",
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
    h = {"Authorization": f"Bearer {v['token']}", "X-Role": role or roles[0], "X-Device": OFFICE_DEVICE}
    if (role or roles[0]) == "admin":
        _approve_device(client, h, phone)
    return h, roles


OFFICE_DEVICE = "office-pc-" + "a" * 30


def _approve_device(client, admin_headers, phone):
    """First admin call from a device registers it as pending; the principal approves it once."""
    if client.get("/api/portal/team", headers=admin_headers).status_code == 200:
        return
    import auth
    store_devices = __import__("store").get("devices", []) or []
    dev_id = auth.device_ref(admin_headers["X-Device"], phone)
    assert any(d["id"] == dev_id and d["status"] == "pending" for d in store_devices)
    p, _ = login(client, PRINCIPAL, "principal")
    assert client.post(f"/api/portal/devices/{dev_id}/approve", headers=p).status_code == 200
    assert client.get("/api/portal/team", headers=admin_headers).status_code == 200


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
    assert roles == ["admin", "teacher", "parent"]


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
    assert {"superadmin", "principal", "correspondent", "parent"} <= set(roles)
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
    h, _ = login(client, PRINCIPAL, "principal")
    bal = KID_O["fee_total"] - KID_O["fee_paid"]
    e = client.post("/api/portal/fees/payment", headers=h, json={"student": KID_O["id"], "amount": bal, "mode": "UPI"}).json()
    assert e["status"] == "approved"  # principal's own entry is approved at once
    card = client.get(f"/api/portal/student/{KID_O['id']}", headers=h).json()
    assert card["balance"] == 0 and not card["fee_flag"] and card["payments"][-1]["mode"] == "UPI"


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
    h, _ = login(client, DUAL_PHONE, "admin")
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
    h, _ = login(client, PRINCIPAL, "superadmin")
    assert client.post("/api/portal/team", headers=h, json={"phone": "9000011111", "name": "Office", "role": "teacher"}).status_code == 400
    xlsx = Path(SEED).with_name("SPV_Test_Students.xlsx")
    if xlsx.exists():
        r = client.post("/api/portal/import", headers=h, content=xlsx.read_bytes()).json()
        assert r["students"] == 100 and r["staff"] == 10 and r["routes"] == 3 and not r["errors"]
        p, _ = login(client, DUAL_PHONE, "parent")
        kid = client.get("/api/portal/parent", headers=p).json()["children"][0]
        assert kid["marks"]["SA1"]["Maths"] > 0


def test_admin_fee_entry_needs_principal_approval(client):
    a, _ = login(client, DUAL_PHONE, "admin")
    kid = next(x for x in json.loads(Path(SEED).read_text())["students"]
               if x["class"] == 2 and x["fee_paid"] < x["fee_total"])
    before = client.get(f"/api/portal/student/{kid['id']}", headers=a).json()["fee_paid"]
    e = client.post("/api/portal/fees/payment", headers=a, json={"student": kid["id"], "amount": 1000, "mode": "Cash"}).json()
    assert e["status"] == "pending"
    assert client.get(f"/api/portal/student/{kid['id']}", headers=a).json()["fee_paid"] == before  # not applied yet
    assert client.post(f"/api/portal/fees/entries/{e['id']}/approve", headers=a, json={}).status_code == 403
    p, _ = login(client, PRINCIPAL, "principal")
    d0 = client.get("/api/portal/dashboard", headers=p).json()["fees"]
    assert d0["pending"] >= 1
    ok = client.post(f"/api/portal/fees/entries/{e['id']}/approve", headers=p, json={}).json()
    assert ok["status"] == "approved"
    assert client.get(f"/api/portal/student/{kid['id']}", headers=p).json()["fee_paid"] == before + 1000
    d1 = client.get("/api/portal/dashboard", headers=p).json()["fees"]["collection"]["today"]
    assert d1["total"] >= 1000 and d1["modes"]["Cash"] >= 1000
    assert client.post(f"/api/portal/fees/entries/{e['id']}/approve", headers=p, json={}).status_code == 400
    e2 = client.post("/api/portal/fees/payment", headers=a, json={"student": kid["id"], "amount": 500, "mode": "UPI"}).json()
    r = client.post(f"/api/portal/fees/entries/{e2['id']}/reject", headers=p, json={"reason": "wrong amount"}).json()
    assert r["status"] == "rejected"
    assert client.get(f"/api/portal/student/{kid['id']}", headers=p).json()["fee_paid"] == before + 1000
    mine = client.get("/api/portal/fees/entries", headers=a).json()["items"]
    assert {x["status"] for x in mine} >= {"approved", "rejected"}


def test_admin_is_write_only(client):
    a, _ = login(client, DUAL_PHONE, "admin")
    assert client.post("/api/portal/team", headers=a, json={"phone": "9000011111", "name": "X", "role": "admin"}).status_code == 403
    assert client.delete(f"/api/portal/team/{TEACHER_PHONE}/teacher", headers=a).status_code == 403
    assert client.post("/api/portal/routes/R1", headers=a, json={"driver": "X"}).status_code == 403
    assert client.post("/api/portal/import", headers=a, content=b"x").status_code == 403
    assert client.post("/api/portal/attendance", headers=a, json={"cls": 1, "marks": {}}).status_code == 403
    assert client.get("/api/portal/team", headers=a).json()["can_assign"] is False


def test_superadmin_assigns_roles(client):
    sa, _ = login(client, PRINCIPAL, "superadmin")
    assert client.get("/api/portal/team", headers=sa).json()["can_assign"] is True
    assert client.post("/api/portal/team", headers=sa, json={"phone": "9123456780", "name": "New Admin", "role": "admin"}).json()["ok"]
    _, roles = login(client, "9123456780")
    assert roles == ["admin"]
    client.delete("/api/portal/team/9123456780/admin", headers=sa)
    assert client.post("/api/auth/otp", json={"phone": "9123456780"}).status_code == 404


def test_teacher_fee_reminder_own_class_once_a_day(client):
    t, _ = login(client, TEACHER_PHONE, "teacher")
    r = client.post(f"/api/portal/fees/remind/{KID_D['id']}", headers=t)
    assert r.status_code in (200, 400)  # 400 if this child's fee was already paid or reminded today
    if r.status_code == 200:
        assert r.json()["status"] == "queued" and "fee is pending" in r.json()["link"].lower().replace("%20", " ")
        assert "Rs" not in r.json()["link"]
        assert client.post(f"/api/portal/fees/remind/{KID_D['id']}", headers=t).status_code == 400
    assert client.post(f"/api/portal/fees/remind/{KID_O['id']}", headers=t).status_code == 400  # other class


def test_absent_message_text():
    import school
    msg = school.absent_message({"name": "Ravi", "class": 4})
    assert msg.startswith("Dear parent, your kid: Name: Ravi (Class 4) is absent today. Kindly check and do the needful.")


def test_practicals_plan_and_marking(client):
    import practicals
    weeks = practicals.all_weeks()
    assert len(weeks) == 40 and all(set(w["activities"]) == set(practicals.BANDS) for w in weeks)
    assert all(w["inspired"].startswith(("Japan", "Europe", "Netherlands", "Finland", "Germany", "Denmark",
                                         "Switzerland", "Montessori", "Estonia", "Norway")) for w in weeks)
    t, _ = login(client, TEACHER_PHONE, "teacher")
    v = client.get("/api/portal/practicals", headers=t).json()
    assert v["class"] == TEACHER["class"] and len(v["weeks"]) == 40
    client.post("/api/portal/practicals/done", headers=t, json={"no": v["current"], "note": "Done in the ground"})
    p, _ = login(client, PRINCIPAL, "principal")
    sv = client.get("/api/portal/dashboard", headers=p).json()["practicals"]
    assert sv["done_count"] >= 1
    k, _ = login(client, DUAL_PHONE, "parent")
    assert client.get("/api/portal/parent", headers=k).json()["children"][0]["practical"]["activity"]


def test_lesson_summary_without_ai_and_share(client, monkeypatch):
    for k in ("AI_GATEWAY_API_KEY", "VERCEL_OIDC_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    t, _ = login(client, TEACHER_PHONE, "teacher")
    text = ("Plants make their own food by photosynthesis. Leaves contain chlorophyll which captures sunlight. "
            "Roots absorb water from the soil. Stems carry water to the leaves. Plants release oxygen into the air.")
    r = client.post("/api/portal/lessons/summarize", headers=t, json={"subject": "Science", "text": text}).json()
    assert r["source"] == "simple" and "KEY POINTS" in r["summary"]
    img = "data:image/jpeg;base64,/9j/4AAQ"
    assert client.post("/api/portal/lessons/summarize", headers=t, json={"images": [img]}).status_code == 400
    s = client.post("/api/portal/lessons", headers=t, json={"subject": "Science", "summary": r["summary"]}).json()
    assert s["item"]["class"] == TEACHER["class"] and s["messages"]["queued"] >= 1
    k, _ = login(client, DUAL_PHONE, "parent")
    kid = client.get("/api/portal/parent", headers=k).json()["children"][0]
    assert kid["lessons"][0]["subject"] == "Science"


def test_lesson_summary_with_ai(client, monkeypatch):
    import lessons
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "test")
    seen = {}
    def fake(content, hdr):
        seen["n"] = sum(1 for c in content if c["type"] == "image_url")
        return "TITLE: Water cycle\nKEY POINTS:\n- Water evaporates"
    monkeypatch.setattr(lessons, "_call_ai", fake)
    t, _ = login(client, TEACHER_PHONE, "teacher")
    img = "data:image/jpeg;base64," + base64.b64encode(b"x" * 100).decode()
    r = client.post("/api/portal/lessons/summarize", headers=t, json={"subject": "Science", "images": [img, img]}).json()
    assert r["source"] == "ai" and seen["n"] == 2 and r["summary"].startswith("TITLE: Water cycle")


def test_fee_amounts_only_for_principal_and_admin(client):
    c, _ = login(client, PRINCIPAL, "correspondent")
    assert client.get("/api/portal/dashboard", headers=c).status_code == 403
    assert client.get("/api/portal/fees/entries", headers=c).status_code == 403
    hit = client.get(f"/api/portal/search?q={KID_O['id']}", headers=c).json()["results"][0]
    assert "balance" not in hit and "fee_total" not in hit
    assert "fee_total" not in client.get(f"/api/portal/student/{KID_O['id']}", headers=c).json()
    assert "Rs." not in client.post("/api/portal/chat", headers=c, json={"message": f"search {KID_O['id']}"}).json()["reply"]
    t, _ = login(client, TEACHER_PHONE, "teacher")
    kids = client.get("/api/portal/class", headers=t).json()["students"]
    assert all("balance" not in k and "fee_total" not in k and "fee_due" in k for k in kids)
    assert all(m["kind"] != "fee" for m in client.get("/api/portal/outbox", headers=t).json()["items"])
    p, _ = login(client, PRINCIPAL, "principal")
    assert "balance" in client.get(f"/api/portal/search?q={KID_O['id']}", headers=p).json()["results"][0]
    a, _ = login(client, DUAL_PHONE, "admin")
    assert client.get("/api/portal/dashboard", headers=a).status_code == 200
    k, _ = login(client, DUAL_PHONE, "parent")
    assert "fee_total" in client.get("/api/portal/parent", headers=k).json()["children"][0]  # own child's fees


def test_teacher_reminder_has_no_amount():
    import school
    s = {"name": "Ravi", "class": 4, "fee_total": 20000, "fee_paid": 5000}
    assert "Rs" not in school.fee_note(s) and "pending" in school.fee_note(s)


def test_admin_only_from_approved_office_device(client, monkeypatch):
    a, _ = login(client, DUAL_PHONE, "admin")          # this device was approved by the principal
    other = dict(a, **{"X-Device": "home-phone-" + "b" * 30})
    r = client.get("/api/portal/team", headers=other)
    assert r.status_code == 403 and "not yet approved" in r.json()["detail"]
    assert client.get("/api/portal/team", headers=dict(a, **{"X-Device": ""})).status_code == 403
    import auth, store
    dev = auth.device_ref(other["X-Device"], DUAL_PHONE)
    p, _ = login(client, PRINCIPAL, "principal")
    listed = client.get("/api/portal/devices", headers=p).json()["items"]
    assert any(d["id"] == dev and d["status"] == "pending" and "h" not in d for d in listed)
    assert client.get("/api/portal/devices", headers=a).status_code == 403   # admin cannot approve itself
    mine = auth.device_ref(a["X-Device"], DUAL_PHONE)
    rv = client.post(f"/api/portal/devices/{mine}/revoke", headers=p)
    assert rv.status_code == 200, rv.text
    assert "removed" in client.get("/api/portal/team", headers=a).json()["detail"]
    client.post(f"/api/portal/devices/{mine}/approve", headers=p)
    assert client.get("/api/portal/team", headers=a).status_code == 200
    # other roles are not tied to a device
    k, _ = login(client, DUAL_PHONE, "parent")
    assert client.get("/api/portal/parent", headers=dict(k, **{"X-Device": ""})).status_code == 200


def test_admin_only_from_office_internet(client, monkeypatch):
    a, _ = login(client, DUAL_PHONE, "admin")
    monkeypatch.setenv("OFFICE_IPS", "49.204.10.0/24")
    assert client.get("/api/portal/team", headers=dict(a, **{"X-Forwarded-For": "49.204.10.25"})).status_code == 200
    r = client.get("/api/portal/team", headers=dict(a, **{"X-Forwarded-For": "106.200.1.9"}))
    assert r.status_code == 403 and "office internet" in r.json()["detail"]
