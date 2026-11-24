"""School data and rules for the SPV portal: students, staff, attendance, fees, marks, homework,
circulars, parent updates, bus routes and Excel import. Pure rules live in small functions
(fee_flag, reminder_due, ...) so they are easy to test; everything else goes through store.py.
"""
import base64
import gzip
import io
import json
import os
import random
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import notify
import store

IST = timezone(timedelta(hours=5, minutes=30))
SUBJECTS = ["Telugu", "Hindi", "English", "Maths", "Science", "Social"]
FEE_REMINDER_PCT = 0.30      # remind when more than 30% of the annual fee is unpaid
FEE_REMINDER_DAYS = 21       # ... at most once every 3 weeks
SCHOOL = "Sri Pragathi Vidyaniketan"


def now() -> datetime:
    return datetime.now(IST)


def today() -> str:
    return now().date().isoformat()


def school_days(n: int, until: str | None = None) -> list[str]:
    """Last n school days (Mon-Sat), newest first."""
    d = date.fromisoformat(until or today())
    out = []
    while len(out) < n:
        if d.weekday() != 6:
            out.append(d.isoformat())
        d -= timedelta(days=1)
    return out


# ---------------------------------------------------------------- seed (test data never lives in the public repo)
def _seed_source():
    raw = os.getenv("SEED_DATA", "").strip()
    if raw:
        return json.loads(gzip.decompress(base64.b64decode(raw)))
    f = Path(__file__).parent / "data" / "seed.local.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def _ensure_seed():
    if store.get("students") is not None:
        return
    seed = _seed_source()
    if not seed:
        store.set("students", [])
        return
    load_data(seed, by="seed", history_days=20)


def load_data(seed: dict, by: str, history_days: int = 0):
    """Replace students/staff/routes with seed or imported data."""
    students_ = seed.get("students", [])
    store.set("students", students_)
    team_ = [{"phone": str(t["phone"]), "name": t["name"], "role": t.get("role", "teacher"),
              "class": t.get("class")} for t in seed.get("staff", [])]
    keep = [t for t in (store.get("staff_roles") or []) if t["role"] != "teacher"]  # keep management
    store.set("staff_roles", keep + team_)
    if seed.get("routes"):
        old = {r["id"]: r for r in (store.get("routes") or [])}
        for r in seed["routes"]:  # keep device ids already set in the app
            if old.get(r["id"], {}).get("device_id") and not r.get("device_id"):
                r["device_id"] = old[r["id"]]["device_id"]
        store.set("routes", seed["routes"])
    if seed.get("circulars") and not store.get("circulars"):
        store.set("circulars", seed["circulars"])
    if history_days:
        _seed_attendance_history(students_, history_days)
    store.set("meta", {"loaded_at": int(time.time()), "by": by, "students": len(students_)})


def _seed_attendance_history(students_, days):
    """TEST DATA: past attendance so dashboards have history. Today is left for teachers to mark."""
    rnd = random.Random(7)
    by_class = {}
    for s in students_:
        by_class.setdefault(s["class"], []).append(s)
    for d in school_days(days + 1)[1:]:
        for cls, kids in by_class.items():
            marks = {k["id"]: ("A" if rnd.random() < 0.07 else "P") for k in kids}
            store.set(f"att:{d}:{cls}", {"date": d, "class": cls, "marks": marks, "by": "seed",
                                         "by_name": "Test data", "at": 0, "notified": []})


# ---------------------------------------------------------------- people
def students() -> list[dict]:
    _ensure_seed()
    return store.get("students", []) or []


def student(sid: str) -> dict | None:
    return next((s for s in students() if s["id"] == sid), None)


def class_students(cls) -> list[dict]:
    return sorted([s for s in students() if int(s["class"]) == int(cls)], key=lambda s: s["sno"])


def children(phone: str) -> list[dict]:
    return [s for s in students() if s["phone"] == phone]


def team() -> list[dict]:
    _ensure_seed()
    return store.get("staff_roles", []) or []


def class_teacher(cls) -> dict | None:
    return next((t for t in team() if t["role"] == "teacher" and str(t.get("class")) == str(cls)), None)


def add_member(phone, name, role, cls=None, by=""):
    from auth import norm_phone, valid_mobile
    phone = norm_phone(phone)
    if not valid_mobile(phone):
        raise ValueError("Enter a valid 10-digit mobile number")
    if role not in ("teacher", "principal", "correspondent", "admin"):
        raise ValueError("Unknown role")
    if role == "teacher" and not cls:
        raise ValueError("Choose the class for a class teacher")
    t = [m for m in team() if not (m["phone"] == phone and m["role"] == role)]
    t.append({"phone": phone, "name": name.strip() or role.title(), "role": role,
              "class": int(cls) if role == "teacher" else None})
    store.set("staff_roles", t)


def remove_member(phone, role):
    store.set("staff_roles", [m for m in team() if not (m["phone"] == phone and m["role"] == role)])


# ---------------------------------------------------------------- fees (pure rules first)
def balance(s) -> int:
    return max(0, int(s["fee_total"]) - int(s["fee_paid"]))


def balance_pct(s) -> float:
    return balance(s) / s["fee_total"] if s["fee_total"] else 0.0


def fee_flag(s) -> bool:
    return balance_pct(s) > FEE_REMINDER_PCT


def reminder_due(s, last_sent: str | None, on: str) -> bool:
    if not fee_flag(s):
        return False
    if not last_sent:
        return True
    return (date.fromisoformat(on) - date.fromisoformat(last_sent)).days >= FEE_REMINDER_DAYS


def fee_message(s) -> str:
    return (f"Dear {s['parent']}, fee reminder for {s['name']} (Class {s['class']}): "
            f"Rs.{balance(s):,} is pending out of Rs.{s['fee_total']:,} ({round(balance_pct(s) * 100)}%). "
            f"Please pay at the school office. Ignore if already paid. - {SCHOOL}, Kota")


def run_fee_reminders(by="cron", on: str | None = None) -> dict:
    on = on or today()
    studs = students()
    last = store.get_many([f"feerem:{s['id']}" for s in studs])
    sent = []
    for s in studs:
        if reminder_due(s, last.get(f"feerem:{s['id']}"), on):
            m = notify.send(s["phone"], fee_message(s), "fee", {"student": s["id"]})
            store.set(f"feerem:{s['id']}", on)
            sent.append({"student": s["id"], "name": s["name"], "status": m["status"]})
    store.set("fee_reminder_run", {"at": int(time.time()), "by": by, "count": len(sent)})
    return {"date": on, "count": len(sent), "messages": sent}


def record_payment(sid, amount, by) -> dict:
    amount = int(amount)
    if amount <= 0:
        raise ValueError("Amount must be more than 0")
    studs = students()
    s = next((x for x in studs if x["id"] == sid), None)
    if not s:
        raise ValueError("Student not found")
    s["fee_paid"] = min(int(s["fee_total"]), int(s["fee_paid"]) + amount)
    s.setdefault("payments", []).append({"date": today(), "amount": amount, "by": by})
    store.set("students", studs)
    return s


def fee_summary() -> dict:
    studs = students()
    tot = sum(s["fee_total"] for s in studs)
    paid = sum(min(s["fee_paid"], s["fee_total"]) for s in studs)
    classes = []
    for c in range(1, 11):
        cs = [s for s in studs if int(s["class"]) == c]
        if cs:
            ct, cp = sum(s["fee_total"] for s in cs), sum(min(s["fee_paid"], s["fee_total"]) for s in cs)
            classes.append({"class": c, "total": ct, "paid": cp, "balance": ct - cp,
                            "pct": round(cp / ct * 100) if ct else 0, "flagged": sum(fee_flag(s) for s in cs)})
    last = store.get_many([f"feerem:{s['id']}" for s in studs])
    flagged = sorted([{"id": s["id"], "name": s["name"], "class": s["class"], "parent": s["parent"],
                       "phone": s["phone"], "balance": balance(s), "pct": round(balance_pct(s) * 100),
                       "last_reminder": last.get(f"feerem:{s['id']}")} for s in studs if fee_flag(s)],
                     key=lambda x: -x["balance"])
    return {"total": tot, "paid": paid, "balance": tot - paid, "pct": round(paid / tot * 100) if tot else 0,
            "classes": classes, "flagged": flagged, "rule": "Reminder when more than 30% is unpaid, every 3 weeks",
            "last_run": store.get("fee_reminder_run")}


# ---------------------------------------------------------------- attendance
def att_sheet(d: str, cls) -> dict | None:
    return store.get(f"att:{d}:{cls}")


def absent_message(s, d, teacher_name) -> str:
    return (f"Dear {s['parent']}, {s['name']} (Class {s['class']}) is ABSENT today ({d}). "
            f"ఈ రోజు మీ పిల్లలు పాఠశాలకు రాలేదు. If this is wrong, please inform class teacher {teacher_name}. "
            f"- {SCHOOL}, Kota")


def save_attendance(cls, marks: dict, by_phone: str, by_name: str, d: str | None = None) -> dict:
    d = d or today()
    kids = {s["id"]: s for s in class_students(cls)}
    clean = {sid: ("A" if str(v).upper().startswith("A") else "P") for sid, v in marks.items() if sid in kids}
    if len(clean) != len(kids):
        raise ValueError(f"Mark all {len(kids)} students (P or A) before saving")
    sheet = att_sheet(d, cls) or {"notified": []}
    notified = set(sheet.get("notified", []))
    messages = []
    for sid, v in clean.items():
        if v == "A" and sid not in notified:  # one alert per child per day, even if saved twice
            m = notify.send(kids[sid]["phone"], absent_message(kids[sid], d, by_name), "absent",
                            {"student": sid, "date": d})
            notified.add(sid)
            messages.append({"student": sid, "name": kids[sid]["name"], "status": m["status"], "link": m["link"],
                             "id": m["id"]})
    store.set(f"att:{d}:{cls}", {"date": d, "class": int(cls), "marks": clean, "by": by_phone, "by_name": by_name,
                                 "at": int(time.time()), "notified": sorted(notified)})
    return {"date": d, "class": int(cls), "present": sum(v == "P" for v in clean.values()),
            "absent": sum(v == "A" for v in clean.values()), "messages": messages}


def attendance_summary(d: str | None = None) -> dict:
    d = d or today()
    sheets = store.get_many([f"att:{d}:{c}" for c in range(1, 11)])
    rows, P, A = [], 0, 0
    for c in range(1, 11):
        kids = class_students(c)
        if not kids:
            continue
        sh = sheets.get(f"att:{d}:{c}")
        t = class_teacher(c)
        row = {"class": c, "teacher": t["name"] if t else "", "strength": len(kids), "marked": bool(sh)}
        if sh:
            ab = [k["name"] for k in kids if sh["marks"].get(k["id"]) == "A"]
            row.update(present=len(kids) - len(ab), absent=len(ab), absentees=ab,
                       pct=round((len(kids) - len(ab)) / len(kids) * 100))
            P, A = P + len(kids) - len(ab), A + len(ab)
        rows.append(row)
    return {"date": d, "classes": rows, "present": P, "absent": A,
            "pct": round(P / (P + A) * 100) if P + A else None,
            "marked": sum(r["marked"] for r in rows), "total_classes": len(rows)}


def attendance_trend(days=7) -> list[dict]:
    ds = school_days(days)
    sheets = store.get_many([f"att:{d}:{c}" for d in ds for c in range(1, 11)])
    out = []
    for d in reversed(ds):
        vals = [v for sh in (sheets.get(f"att:{d}:{c}") for c in range(1, 11)) if sh for v in sh["marks"].values()]
        out.append({"date": d, "pct": round(sum(v == "P" for v in vals) / len(vals) * 100) if vals else None})
    return out


def student_attendance(s, days=30) -> dict:
    ds = school_days(days)
    sheets = store.get_many([f"att:{d}:{s['class']}" for d in ds])
    rec = [{"date": d, "status": sheets[f"att:{d}:{s['class']}"]["marks"].get(s["id"])}
           for d in ds if f"att:{d}:{s['class']}" in sheets]
    rec = [r for r in rec if r["status"]]
    p = sum(r["status"] == "P" for r in rec)
    return {"days": len(rec), "present": p, "absent": len(rec) - p,
            "pct": round(p / len(rec) * 100) if rec else None, "recent": rec[:10],
            "today": next((r["status"] for r in rec if r["date"] == today()), None)}


# ---------------------------------------------------------------- homework, circulars, parent updates
def post_homework(cls, subject, text, by_phone, by_name) -> dict:
    text = (text or "").strip()
    if not text:
        raise ValueError("Write the homework")
    item = {"id": f"h{int(time.time() * 1000)}", "date": today(), "class": int(cls), "subject": subject.strip(),
            "text": text, "by": by_name, "at": int(time.time())}
    store.push(f"hw:{cls}", item, cap=120)
    msg = f"Homework - Class {cls} ({item['date']})\n{item['subject']}: {text}\n- {by_name}, {SCHOOL}"
    sent = [notify.send(s["phone"], msg, "homework", {"class": int(cls)}) for s in class_students(cls)]
    return {"item": item, "group_link": notify.wa_link(None, msg),
            "messages": {k: sum(m["status"] == k for m in sent) for k in ("sent", "queued", "skipped", "failed")}}


def homework(cls, limit=10) -> list[dict]:
    return (store.get(f"hw:{cls}", []) or [])[:limit]


def post_circular(text, by_phone, by_name) -> dict:
    text = (text or "").strip()
    if not text:
        raise ValueError("Write the circular")
    item = {"id": f"c{int(time.time() * 1000)}", "date": today(), "from": by_name, "to": "staff", "text": text}
    store.push("circulars", item, cap=200)
    seen = set()
    for t in team():
        if t["phone"] not in seen and t["phone"] != by_phone:
            seen.add(t["phone"])
            notify.send(t["phone"], f"Circular from {by_name}: {text}", "circular", {"circular": item["id"]})
    return item


def circulars(limit=20) -> list[dict]:
    return (store.get("circulars", []) or [])[:limit]


def post_update(text, audience, by_phone, by_name) -> dict:
    text = (text or "").strip()
    if not text:
        raise ValueError("Write the update")
    aud = "all" if str(audience) in ("", "all") else int(audience)
    item = {"id": f"u{int(time.time() * 1000)}", "date": today(), "audience": aud, "from": by_name, "text": text}
    store.push("updates", item, cap=200)
    targets = students() if aud == "all" else class_students(aud)
    phones = sorted({s["phone"] for s in targets})
    msg = f"{SCHOOL}: {text}"
    sent = [notify.send(p, msg, "update", {"update": item["id"]}) for p in phones]
    return {"item": item, "group_link": notify.wa_link(None, msg),
            "messages": {k: sum(m["status"] == k for m in sent) for k in ("sent", "queued", "skipped", "failed")}}


def updates_for(cls=None, limit=10) -> list[dict]:
    items = store.get("updates", []) or []
    return [u for u in items if u["audience"] == "all" or cls is None or u["audience"] == int(cls)][:limit]


# ---------------------------------------------------------------- search & routes
def search(q: str, scope: list[dict]) -> list[dict]:
    q = (q or "").strip().lower()
    if not q:
        return []
    hits = [s for s in scope if q in s["name"].lower() or q in s["id"].lower() or q in s["phone"]
            or q in (s.get("parent") or "").lower() or q == f"class {s['class']}" or q == str(s["class"])]
    return [card(s) for s in hits[:25]]


def card(s) -> dict:
    return {"id": s["id"], "sno": s.get("sno"), "name": s["name"], "class": s["class"], "section": s.get("section", "A"),
            "parent": s["parent"], "phone": s["phone"], "route": s.get("route"),
            "fee_total": s["fee_total"], "fee_paid": s["fee_paid"], "balance": balance(s),
            "fee_flag": fee_flag(s), "marks": s.get("marks", {})}


def routes() -> list[dict]:
    _ensure_seed()
    return store.get("routes", []) or []


def save_route(rid, device_id=None, driver=None, driver_phone=None):
    rs = routes()
    r = next((x for x in rs if x["id"] == rid), None)
    if not r:
        raise ValueError("Route not found")
    for k, v in (("device_id", device_id), ("driver", driver), ("driver_phone", driver_phone)):
        if v is not None:
            r[k] = str(v).strip()
    store.set("routes", rs)
    return r


# ---------------------------------------------------------------- Excel import (same format as the test workbook)
def import_excel(content: bytes, by: str) -> dict:
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
    if "Students" not in wb.sheetnames:
        raise ValueError("The workbook needs a 'Students' sheet (download the template from the test file)")

    def rows(name):
        if name not in wb.sheetnames:
            return []
        it = wb[name].iter_rows(values_only=True)
        head = [str(h or "").strip().lower() for h in next(it)]
        return [dict(zip(head, r)) for r in it if r and any(c not in (None, "") for c in r)]

    from auth import norm_phone
    route_names = {}
    routes_ = []
    for r in rows("Routes"):
        rid = str(r.get("route id") or "").strip()
        if rid:
            routes_.append({"id": rid, "name": str(r.get("route name") or rid),
                            "stops": [x.strip() for x in str(r.get("stops") or "").split("→") if x.strip()],
                            "device_id": str(r.get("gps device id (traccar)") or "").strip(),
                            "driver": str(r.get("driver") or ""), "driver_phone": norm_phone(r.get("driver mobile"))})
            route_names[routes_[-1]["name"].lower()] = rid
    marks = {}
    for m in rows("Marks"):
        sid = str(m.get("admission no") or "").strip()
        if sid:
            marks.setdefault(sid, {})[str(m.get("exam") or "Exam")] = {
                s: int(m.get(s.lower()) or 0) for s in SUBJECTS if m.get(s.lower()) is not None}
    studs, errors = [], []
    for i, r in enumerate(rows("Students"), 2):
        sid, name = str(r.get("admission no") or "").strip(), str(r.get("student name") or "").strip()
        try:
            cls = int(r.get("class"))
            assert sid and name and 1 <= cls <= 12
        except Exception:
            errors.append(f"Row {i}: needs Admission No, Student Name and Class")
            continue
        route = str(r.get("route") or "Own").strip()
        studs.append({"id": sid, "sno": int(r.get("s.no") or len(studs) + 1), "name": name, "class": cls,
                      "section": str(r.get("section") or "A"), "gender": str(r.get("gender") or ""),
                      "parent": str(r.get("parent name") or "Parent"), "phone": norm_phone(r.get("parent mobile")),
                      "route": route_names.get(route.lower(), route if route in {x["id"] for x in routes_} else "Own"),
                      "fee_total": int(r.get("annual fee") or 0), "fee_paid": int(r.get("fee paid") or 0),
                      "marks": marks.get(sid, {})})
    staff = []
    for t in rows("Staff"):
        if t.get("name") and t.get("mobile"):
            staff.append({"name": str(t["name"]).strip(), "role": "teacher",
                          "class": int(t.get("class teacher of") or 0) or None, "phone": norm_phone(t["mobile"])})
    if not studs:
        raise ValueError("No students found. " + "; ".join(errors[:5]))
    load_data({"students": studs, "staff": [s for s in staff if s["class"]], "routes": routes_}, by=by)
    return {"students": len(studs), "staff": len(staff), "routes": len(routes_), "errors": errors[:20]}
