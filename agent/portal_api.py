"""SPV portal API (login-only). The public website and Ask SPV widget stay separate in agent.py.

Every /api/portal route needs:  Authorization: Bearer <token>   and   X-Role: <role being used>
Roles are re-checked on every call (auth.session), and each route lists who may call it.
"""
import os

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

import auth
import notify
import school
import store
import van
from app_agent import role_chat

router = APIRouter()
MGMT = ("principal", "correspondent", "admin")


def ctx(authorization: str | None, x_role: str | None, allow: tuple) -> dict:
    token = (authorization or "").removeprefix("Bearer ").strip()
    try:
        c = auth.session(token, x_role)
    except auth.AuthError as e:
        raise HTTPException(e.status, str(e))
    if c["role"] not in allow:
        raise HTTPException(403, "You do not have access to this section.")
    return c


def _err(fn, *a, **k):
    try:
        return fn(*a, **k)
    except ValueError as e:
        raise HTTPException(400, str(e))


# ---------------------------------------------------------------- login
class PhoneIn(BaseModel):
    phone: str = Field(min_length=10, max_length=16)


class VerifyIn(PhoneIn):
    code: str = Field(min_length=4, max_length=8)


@router.post("/api/auth/otp")
def otp(body: PhoneIn):
    try:
        return auth.send_otp(body.phone)
    except auth.AuthError as e:
        raise HTTPException(e.status, str(e))


@router.post("/api/auth/verify")
def verify(body: VerifyIn):
    try:
        return auth.verify_otp(body.phone, body.code)
    except auth.AuthError as e:
        raise HTTPException(e.status, str(e))


@router.get("/api/portal/status")
def status():
    return {"storage": store.health(), "otp_dev_mode": auth.dev_mode(),
            "whatsapp": "api" if notify.api_ready() else "one-tap", "jwt": bool(os.getenv("JWT_SECRET")),
            "van_key": bool(os.getenv("VAN_KEY"))}


@router.get("/api/portal/me")
def me(authorization: str = Header(None), x_role: str = Header(None)):
    c = ctx(authorization, x_role, ("parent", "teacher") + MGMT)
    return {"phone": c["phone"], "active": {k: c[k] for k in ("role", "name") if k in c} | {"class": c.get("class")},
            "roles": auth.roles_for(c["phone"]), "status": status()}


# ---------------------------------------------------------------- parent
@router.get("/api/portal/parent")
def parent_home(authorization: str = Header(None), x_role: str = Header(None)):
    c = ctx(authorization, x_role, ("parent",))
    kids = school.children(c["phone"])
    routes = {r["id"]: r for r in van.vans(school.routes(), only_routes={k["route"] for k in kids})}
    out = []
    for k in kids:
        out.append(school.card(k) | {
            "attendance": school.student_attendance(k), "homework": school.homework(k["class"], 5),
            "teacher": (school.class_teacher(k["class"]) or {}).get("name"),
            "fee_reminder": school.fee_flag(k), "balance_pct": round(school.balance_pct(k) * 100),
            "route_info": routes.get(k.get("route"))})
    ups = {}
    for k in kids:
        for u in school.updates_for(k["class"], 8):
            ups[u["id"]] = u
    return {"children": out, "updates": sorted(ups.values(), key=lambda u: u["id"], reverse=True)[:8]}


# ---------------------------------------------------------------- class teacher
def _class_for(c, cls):
    if c["role"] == "teacher":
        return int(c["class"])  # a class teacher only ever gets their own class
    if not cls:
        raise HTTPException(400, "Choose a class")
    return int(cls)


@router.get("/api/portal/class")
def class_view(cls: int = 0, authorization: str = Header(None), x_role: str = Header(None)):
    c = ctx(authorization, x_role, ("teacher",) + MGMT)
    k = _class_for(c, cls)
    sheet = school.att_sheet(school.today(), k)
    return {"class": k, "date": school.today(), "teacher": (school.class_teacher(k) or {}).get("name"),
            "students": [school.card(s) | {"today": (sheet or {}).get("marks", {}).get(s["id"])}
                         for s in school.class_students(k)],
            "saved": bool(sheet), "homework": school.homework(k, 10)}


class AttendanceIn(BaseModel):
    cls: int = 0
    marks: dict[str, str]


@router.post("/api/portal/attendance")
def attendance(body: AttendanceIn, authorization: str = Header(None), x_role: str = Header(None)):
    c = ctx(authorization, x_role, ("teacher", "principal", "admin"))
    k = _class_for(c, body.cls)
    res = _err(school.save_attendance, k, body.marks, c["phone"], c.get("name", c["role"].title()))
    auth.audit(c["phone"], "attendance", {"class": k, "absent": res["absent"]})
    return res


class HomeworkIn(BaseModel):
    cls: int = 0
    subject: str = Field(min_length=1, max_length=40)
    text: str = Field(min_length=1, max_length=1500)


@router.post("/api/portal/homework")
def homework(body: HomeworkIn, authorization: str = Header(None), x_role: str = Header(None)):
    c = ctx(authorization, x_role, ("teacher", "principal", "admin"))
    k = _class_for(c, body.cls)
    return _err(school.post_homework, k, body.subject, body.text, c["phone"], c.get("name", ""))


# ---------------------------------------------------------------- management dashboards
@router.get("/api/portal/dashboard")
def dashboard(authorization: str = Header(None), x_role: str = Header(None)):
    ctx(authorization, x_role, MGMT)
    return {"attendance": school.attendance_summary(), "trend": school.attendance_trend(7),
            "fees": school.fee_summary(), "students": len(school.students())}


@router.post("/api/portal/fees/remind")
def fees_remind(authorization: str = Header(None), x_role: str = Header(None)):
    c = ctx(authorization, x_role, ("principal", "admin", "correspondent"))
    res = school.run_fee_reminders(by=c["phone"])
    auth.audit(c["phone"], "fee_reminders", {"count": res["count"]})
    return res


class PaymentIn(BaseModel):
    student: str
    amount: int = Field(gt=0, lt=1_000_000)


@router.post("/api/portal/fees/payment")
def fees_payment(body: PaymentIn, authorization: str = Header(None), x_role: str = Header(None)):
    c = ctx(authorization, x_role, ("principal", "admin"))
    s = _err(school.record_payment, body.student, body.amount, c["phone"])
    auth.audit(c["phone"], "payment", {"student": body.student, "amount": body.amount})
    return school.card(s)


@router.get("/api/portal/search")
def search(q: str = "", authorization: str = Header(None), x_role: str = Header(None)):
    c = ctx(authorization, x_role, ("parent", "teacher") + MGMT)
    scope = (school.children(c["phone"]) if c["role"] == "parent"
             else school.class_students(c["class"]) if c["role"] == "teacher" else school.students())
    return {"results": school.search(q, scope), "scope": c["role"]}


@router.get("/api/portal/student/{sid}")
def student(sid: str, authorization: str = Header(None), x_role: str = Header(None)):
    c = ctx(authorization, x_role, ("parent", "teacher") + MGMT)
    s = school.student(sid)
    allowed = s and (c["role"] in MGMT or (c["role"] == "teacher" and int(s["class"]) == int(c["class"]))
                     or (c["role"] == "parent" and s["phone"] == c["phone"]))
    if not allowed:
        raise HTTPException(404, "Student not found")
    return school.card(s) | {"attendance": school.student_attendance(s), "payments": s.get("payments", [])}


# ---------------------------------------------------------------- circulars (principal -> staff) and parent updates
class TextIn(BaseModel):
    text: str = Field(min_length=1, max_length=1500)
    audience: str = "all"


@router.get("/api/portal/circulars")
def circulars(authorization: str = Header(None), x_role: str = Header(None)):
    ctx(authorization, x_role, ("teacher",) + MGMT)
    return {"items": school.circulars(30)}


@router.post("/api/portal/circulars")
def post_circular(body: TextIn, authorization: str = Header(None), x_role: str = Header(None)):
    c = ctx(authorization, x_role, MGMT)
    item = _err(school.post_circular, body.text, c["phone"], c.get("name") or c["role"].title())
    auth.audit(c["phone"], "circular", {"id": item["id"]})
    return item


@router.get("/api/portal/updates")
def updates(authorization: str = Header(None), x_role: str = Header(None)):
    ctx(authorization, x_role, MGMT)
    return {"items": school.updates_for(None, 30)}


@router.post("/api/portal/updates")
def post_update(body: TextIn, authorization: str = Header(None), x_role: str = Header(None)):
    c = ctx(authorization, x_role, ("admin", "principal"))
    res = _err(school.post_update, body.text, body.audience, c["phone"], c.get("name") or c["role"].title())
    auth.audit(c["phone"], "update", {"audience": body.audience})
    return res


@router.get("/api/portal/outbox")
def outbox(kind: str = "", authorization: str = Header(None), x_role: str = Header(None)):
    c = ctx(authorization, x_role, ("teacher",) + MGMT)
    items = store.get("outbox", []) or []
    if c["role"] == "teacher":  # a teacher sees only messages for their class's parents
        mine = {s["phone"] for s in school.class_students(c["class"])}
        items = [m for m in items if m["to"] in mine]
    if kind:
        items = [m for m in items if m["kind"] == kind]
    return {"mode": "api" if notify.api_ready() else "one-tap", "items": items[:150]}


@router.post("/api/portal/outbox/{mid}/sent")
def outbox_sent(mid: str, authorization: str = Header(None), x_role: str = Header(None)):
    c = ctx(authorization, x_role, ("teacher",) + MGMT)
    return {"ok": notify.mark_sent(mid, c["phone"])}


# ---------------------------------------------------------------- bus routes & live vans
@router.get("/api/portal/routes")
def routes(authorization: str = Header(None), x_role: str = Header(None)):
    c = ctx(authorization, x_role, ("parent", "teacher") + MGMT)
    only = None
    if c["role"] == "parent":
        only = {k["route"] for k in school.children(c["phone"])}
    items = van.vans(school.routes(), only_routes=only)
    if c["role"] != "parent":
        counts = {}
        for s in school.students():
            counts[s.get("route")] = counts.get(s.get("route"), 0) + 1
        for v in items:
            v["students"] = counts.get(v["id"], 0)
    return {"routes": items}


class RouteIn(BaseModel):
    device_id: str | None = Field(None, max_length=40)
    driver: str | None = Field(None, max_length=60)
    driver_phone: str | None = Field(None, max_length=16)


@router.post("/api/portal/routes/{rid}")
def save_route(rid: str, body: RouteIn, authorization: str = Header(None), x_role: str = Header(None)):
    c = ctx(authorization, x_role, ("principal", "admin"))
    r = _err(school.save_route, rid, body.device_id, body.driver, body.driver_phone)
    auth.audit(c["phone"], "route", {"route": rid})
    return r


# ---------------------------------------------------------------- admin: team and data
class MemberIn(BaseModel):
    phone: str
    name: str = ""
    role: str
    cls: int | None = None


@router.get("/api/portal/team")
def team(authorization: str = Header(None), x_role: str = Header(None)):
    ctx(authorization, x_role, ("admin", "principal"))
    env = [{"phone": p, "role": r, "name": f"{r.title()} (Vercel setting)", "fixed": True}
           for r, e in (("principal", "PRINCIPAL_PHONES"), ("correspondent", "CORRESPONDENT_PHONES"),
                        ("admin", "ADMIN_PHONES")) for p in auth._env_phones(e)]
    return {"items": env + school.team(), "meta": store.get("meta")}


@router.post("/api/portal/team")
def add_member(body: MemberIn, authorization: str = Header(None), x_role: str = Header(None)):
    c = ctx(authorization, x_role, ("admin",))
    _err(school.add_member, body.phone, body.name, body.role, body.cls, c["phone"])
    auth.audit(c["phone"], "team_add", {"phone": body.phone, "role": body.role})
    return {"ok": True}


@router.delete("/api/portal/team/{phone}/{role}")
def remove_member(phone: str, role: str, authorization: str = Header(None), x_role: str = Header(None)):
    c = ctx(authorization, x_role, ("admin",))
    school.remove_member(phone, role)
    auth.audit(c["phone"], "team_remove", {"phone": phone, "role": role})
    return {"ok": True}


@router.post("/api/portal/import")
async def import_excel(request: Request, authorization: str = Header(None), x_role: str = Header(None)):
    c = ctx(authorization, x_role, ("admin",))
    body = await request.body()
    if not body or len(body) > 4_000_000:
        raise HTTPException(400, "Choose an Excel file under 4 MB")
    try:
        res = school.import_excel(body, by=c["phone"])
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception:
        raise HTTPException(400, "Could not read this file. Use the .xlsx format of the test workbook.")
    auth.audit(c["phone"], "import", res)
    return res


# ---------------------------------------------------------------- agent
class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[dict] = []


@router.post("/api/portal/chat")
def chat(body: ChatIn, authorization: str = Header(None), x_role: str = Header(None)):
    c = ctx(authorization, x_role, ("parent", "teacher") + MGMT)
    return {"reply": role_chat(c, body.message, body.history[-8:])}


# ---------------------------------------------------------------- scheduled job (Vercel Cron, daily)
@router.get("/api/cron/fee-reminders")
def cron_fee(authorization: str = Header(None)):
    secret = os.getenv("CRON_SECRET", "")
    if not secret or authorization != f"Bearer {secret}":
        raise HTTPException(401, "cron only")
    return school.run_fee_reminders(by="cron")
