"""SPV portal API (login-only). The public website and Ask SPV widget stay separate in agent.py.

Every /api/portal route needs:  Authorization: Bearer <token>   and   X-Role: <role being used>
Roles are re-checked on every call (auth.session), and each route lists who may call it.

Permissions (least privilege):
  superadmin     everything + assigns roles
  principal      everything except assigning roles; approves fee entries
  correspondent  same as principal (dashboards, fees, approvals, routes, import, attendance)
  admin          WRITE-ONLY: enters fees (pending approval), posts updates/circulars, sends reminders;
                 cannot change or delete existing records, routes, roles or imported data.
                 Works only from the office: approved office device (+ optional office IP / hours).
  Fee amounts and dashboards: ONLY superadmin, principal, correspondent and admin (FEE_ROLES).
  Teachers never receive amounts; parents see only their own children's fees.
  teacher        own class only;  parent: own children only
"""
import json
import os

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

import auth
import notify
import school
import store
import lessons
import passkeys
import practicals
import wa_login
import van
from app_agent import role_chat

router = APIRouter()
MGMT = ("superadmin", "principal", "correspondent", "admin")
APPROVERS = ("superadmin", "principal", "correspondent")   # may change/approve existing records
ALL = ("parent", "teacher") + MGMT
EDITORS = ("admin", "superadmin", "principal", "correspondent")   # may edit the student database and bus stops
FEE_ROLES = ("superadmin", "principal", "correspondent", "admin")   # may see fee amounts and dashboards


def install(app):
    """Middleware: record device id, device label and client IP for this request (used by auth.office_check)."""
    @app.middleware("http")
    async def _request_facts(request: Request, call_next):
        fwd = request.headers.get("x-forwarded-for", "")
        ip = request.headers.get("x-real-ip") or (fwd.split(",")[0].strip() if fwd else "") or \
            (request.client.host if request.client else "")
        auth.REQUEST.set({"device": request.headers.get("x-device", "")[:100],
                          "label": request.headers.get("x-device-label", "")[:80], "ip": ip,
                          "host": request.headers.get("x-forwarded-host") or request.headers.get("host", ""),
                          "proto": request.headers.get("x-forwarded-proto") or request.url.scheme})
        return await call_next(request)


def ctx(authorization: str | None, x_role: str | None, allow: tuple, passkey: bool = True) -> dict:
    token = (authorization or "").removeprefix("Bearer ").strip()
    try:
        c = auth.session(token, x_role, passkey)
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


@router.get("/api/auth/config")
def auth_config():
    """What the login page should offer (no secrets)."""
    return {"wa_login": wa_login.enabled(), "otp_sender": notify.otp_ready(), "otp_dev_mode": auth.dev_mode()}


class WaStartIn(PhoneIn):
    pass


@router.post("/api/auth/wa/start")
def wa_start(body: WaStartIn):
    if not wa_login.enabled():
        raise HTTPException(503, "WhatsApp login is not set up yet.")
    try:
        return wa_login.start(body.phone)
    except auth.AuthError as e:
        raise HTTPException(e.status, str(e))


@router.get("/api/auth/wa/status")
def wa_status(poll: str):
    return wa_login.status(poll[:64])


@router.get("/api/whatsapp/webhook")
def wa_webhook_verify(request: Request):
    q = request.query_params
    if q.get("hub.mode") == "subscribe" and os.getenv("WHATSAPP_VERIFY_TOKEN") and \
            q.get("hub.verify_token") == os.getenv("WHATSAPP_VERIFY_TOKEN"):
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(q.get("hub.challenge", ""))
    raise HTTPException(403, "verification failed")


@router.post("/api/whatsapp/webhook")
async def wa_webhook(request: Request):
    raw = await request.body()
    if not wa_login.check_signature(raw, request.headers.get("x-hub-signature-256")):
        raise HTTPException(401, "bad signature")
    try:
        payload = json.loads(raw)
    except ValueError:
        raise HTTPException(400, "bad json")
    return {"ok": True, "verified": wa_login.handle_webhook(payload)}


# ---------------------------------------------------------------- admin passkey (fingerprint / Windows Hello)
class CredIn(BaseModel):
    credential: dict


def _pk_ctx(authorization, x_role):
    c = ctx(authorization, x_role, ("admin",), passkey=False)
    try:
        return c, auth.current_device(c["phone"])
    except auth.AuthError as e:
        raise HTTPException(e.status, str(e))


def _pk(fn, *a):
    try:
        return fn(*a)
    except auth.AuthError as e:
        raise HTTPException(e.status, str(e))


@router.post("/api/portal/passkey/register/options")
def pk_reg_options(authorization: str = Header(None), x_role: str = Header(None)):
    c, dev = _pk_ctx(authorization, x_role)
    return passkeys.register_options(c["phone"], dev, c.get("name") or "Admin", auth.REQUEST.get())


@router.post("/api/portal/passkey/register/verify")
def pk_reg_verify(body: CredIn, authorization: str = Header(None), x_role: str = Header(None)):
    c, dev = _pk_ctx(authorization, x_role)
    return _pk(passkeys.register_verify, c["phone"], dev, body.credential, auth.REQUEST.get())


@router.post("/api/portal/passkey/unlock/options")
def pk_auth_options(authorization: str = Header(None), x_role: str = Header(None)):
    c, dev = _pk_ctx(authorization, x_role)
    return passkeys.auth_options(c["phone"], dev, auth.REQUEST.get())


@router.post("/api/portal/passkey/unlock/verify")
def pk_auth_verify(body: CredIn, authorization: str = Header(None), x_role: str = Header(None)):
    c, dev = _pk_ctx(authorization, x_role)
    return _pk(passkeys.auth_verify, c["phone"], dev, body.credential, auth.REQUEST.get())


@router.get("/api/portal/status")
def public_status():
    """Public health check: says only whether the service works (no setup details)."""
    return {"ok": store.health()["ok"]}


def status(oidc: str | None = None):
    h = store.health()
    try:
        h |= store.tls_status()
    except Exception:
        h["tls"] = False
    return {"storage": h, "otp_dev_mode": auth.dev_mode(), "otp_sender": notify.otp_ready(),
            "whatsapp": "api" if notify.api_ready() else "one-tap", "jwt": bool(os.getenv("JWT_SECRET")),
            "van_key": bool(os.getenv("VAN_KEY")), "lesson_ai": lessons.ai_ready(oidc)}


@router.get("/api/portal/me")
def me(request: Request, authorization: str = Header(None), x_role: str = Header(None)):
    c = ctx(authorization, x_role, ALL)
    out = {"phone": c["phone"], "active": {k: c[k] for k in ("role", "name") if k in c} | {"class": c.get("class")},
           "roles": auth.roles_for(c["phone"])}
    st = status(request.headers.get("x-vercel-oidc-token"))
    out["status"] = st if c["role"] in MGMT else {"storage": {"durable": st["storage"]["durable"]}}
    return out


# ---------------------------------------------------------------- parent
@router.get("/api/portal/parent")
def parent_home(authorization: str = Header(None), x_role: str = Header(None)):
    c = ctx(authorization, x_role, ("parent",))
    kids = school.children(c["phone"])
    routes = {r["id"]: r for r in van.vans(school.routes(), only_routes={k["route"] for k in kids})}
    out = []
    for k in kids:
        ri = routes.get(k.get("route"))
        stop = next((x for x in (ri or {}).get("stops", []) if x["id"] == k.get("stop")), None)
        out.append(school.card(k) | {"my_stop": stop,
                                     "van_eta": van.eta_to_stop((ri or {}).get("position"), stop, bool((ri or {}).get("live"))),
            "attendance": school.student_attendance(k), "homework": school.homework(k["class"], 5),
            "teacher": (school.class_teacher(k["class"]) or {}).get("name"),
            "fee_reminder": school.fee_flag(k), "balance_pct": round(school.balance_pct(k) * 100),
            "route_info": routes.get(k.get("route")), "lessons": lessons.notes(k["class"], 5),
            "practical": practicals.class_view(k["class"], school.today())})
    ups = {}
    for k in kids:
        for u in school.updates_for(k["class"], 8):
            ups[u["id"]] = u
    for k in out:
        pv = k.pop("practical")
        k["practical"] = next(w for w in pv["weeks"] if w["no"] == pv["current"])
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
            "students": [school.card(s, c["role"] in FEE_ROLES) | {"today": (sheet or {}).get("marks", {}).get(s["id"])}
                         for s in school.class_students(k)],
            "saved": bool(sheet), "homework": school.homework(k, 10), "lessons": lessons.notes(k, 10)}


class AttendanceIn(BaseModel):
    cls: int = 0
    marks: dict[str, str]


@router.post("/api/portal/attendance")
def attendance(body: AttendanceIn, authorization: str = Header(None), x_role: str = Header(None)):
    c = ctx(authorization, x_role, ("teacher",) + APPROVERS)
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
    c = ctx(authorization, x_role, ("teacher",) + APPROVERS)
    k = _class_for(c, body.cls)
    return _err(school.post_homework, k, body.subject, body.text, c["phone"], c.get("name", ""))


# ---------------------------------------------------------------- management dashboards
@router.get("/api/portal/dashboard")
def dashboard(authorization: str = Header(None), x_role: str = Header(None)):
    ctx(authorization, x_role, FEE_ROLES)
    classes = sorted({int(s["class"]) for s in school.students()})
    return {"attendance": school.attendance_summary(), "trend": school.attendance_trend(7),
            "fees": school.fee_summary(), "students": len(school.students()),
            "practicals": practicals.school_view(school.today(), classes),
            "fleet": _fleet()}


def _fleet():
    counts = {}
    for s in school.students():
        counts[s.get("route")] = counts.get(s.get("route"), 0) + 1
    return [v | {"students": counts.get(v["id"], 0)} for v in van.vans(school.routes())]


@router.post("/api/portal/fees/remind")
def fees_remind(authorization: str = Header(None), x_role: str = Header(None)):
    c = ctx(authorization, x_role, FEE_ROLES)
    res = school.run_fee_reminders(by=c["phone"])
    auth.audit(c["phone"], "fee_reminders", {"count": res["count"]})
    return res


@router.post("/api/portal/fees/remind/{sid}")
def fee_remind_one(sid: str, authorization: str = Header(None), x_role: str = Header(None)):
    """Class teacher (own class) or management sends one fee reminder to a parent now."""
    c = ctx(authorization, x_role, ("teacher",) + FEE_ROLES)
    cls = c["class"] if c["role"] == "teacher" else None
    res = _err(school.teacher_fee_reminder, sid, cls, c["phone"], c.get("name") or c["role"].title(),
               with_amount=c["role"] in FEE_ROLES)
    auth.audit(c["phone"], "fee_reminder", {"student": sid})
    return res


class PaymentIn(BaseModel):
    student: str
    amount: int = Field(gt=0, lt=1_000_000)
    mode: str = "Cash"
    ref: str = Field("", max_length=40)


@router.post("/api/portal/fees/payment")
def fees_payment(body: PaymentIn, authorization: str = Header(None), x_role: str = Header(None)):
    """Admin entries wait for the principal's approval; a principal's own entry is approved at once."""
    c = ctx(authorization, x_role, ("admin",) + APPROVERS)
    e = _err(school.submit_fee_entry, body.student, body.amount, body.mode, body.ref, c["phone"],
             c.get("name") or c["role"].title(), approve_now=c["role"] in APPROVERS)
    auth.audit(c["phone"], "fee_entry", {"student": body.student, "amount": body.amount, "status": e["status"]})
    return e


@router.get("/api/portal/fees/entries")
def fee_entries(status: str = "", authorization: str = Header(None), x_role: str = Header(None)):
    c = ctx(authorization, x_role, FEE_ROLES)
    items = school.fee_entries(status or None)
    if c["role"] == "admin":  # admin sees what they entered and its status
        items = [e for e in items if e["by"] == c["phone"]]
    return {"items": items[:200]}


class DecisionIn(BaseModel):
    reason: str = Field("", max_length=200)


@router.post("/api/portal/fees/entries/{eid}/{decision}")
def fee_decide(eid: str, decision: str, body: DecisionIn, authorization: str = Header(None),
               x_role: str = Header(None)):
    c = ctx(authorization, x_role, APPROVERS)
    if decision not in ("approve", "reject"):
        raise HTTPException(404, "Unknown action")
    e = _err(school.decide_fee_entry, eid, decision == "approve", c["phone"], c.get("name") or "Principal",
             body.reason)
    auth.audit(c["phone"], f"fee_{decision}", {"entry": eid, "amount": e["amount"]})
    return e


@router.get("/api/portal/search")
def search(q: str = "", authorization: str = Header(None), x_role: str = Header(None)):
    c = ctx(authorization, x_role, ALL)
    scope = (school.children(c["phone"]) if c["role"] == "parent"
             else school.class_students(c["class"]) if c["role"] == "teacher" else school.students())
    fees = c["role"] in FEE_ROLES or c["role"] == "parent"  # a parent sees only own children anyway
    return {"results": school.search(q, scope, fees), "scope": c["role"]}


@router.get("/api/portal/student/{sid}")
def student(sid: str, authorization: str = Header(None), x_role: str = Header(None)):
    c = ctx(authorization, x_role, ALL)
    s = school.student(sid)
    allowed = s and (c["role"] in MGMT or (c["role"] == "teacher" and int(s["class"]) == int(c["class"]))
                     or (c["role"] == "parent" and s["phone"] == c["phone"]))
    if not allowed:
        raise HTTPException(404, "Student not found")
    fees = c["role"] in FEE_ROLES or c["role"] == "parent"
    return school.card(s, fees) | {"attendance": school.student_attendance(s),
                                   "payments": s.get("payments", []) if fees else []}


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
    c = ctx(authorization, x_role, ("admin",) + APPROVERS)
    res = _err(school.post_update, body.text, body.audience, c["phone"], c.get("name") or c["role"].title())
    auth.audit(c["phone"], "update", {"audience": body.audience})
    return res


@router.get("/api/portal/outbox")
def outbox(kind: str = "", authorization: str = Header(None), x_role: str = Header(None)):
    c = ctx(authorization, x_role, ("teacher",) + MGMT)
    items = store.get("outbox", []) or []
    if c["role"] not in FEE_ROLES:  # fee reminders contain amounts
        items = [m for m in items if m["kind"] != "fee"]
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
    c = ctx(authorization, x_role, ALL)
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


class StopsIn(BaseModel):
    stops: list[dict]


@router.put("/api/portal/routes/{rid}/stops")
def save_stops(rid: str, body: StopsIn, authorization: str = Header(None), x_role: str = Header(None)):
    c = ctx(authorization, x_role, EDITORS)
    r = _err(school.save_stops, rid, body.stops, c["phone"])
    auth.audit(c["phone"], "bus_stops", {"route": rid, "stops": len(r["stops"])})
    return r


# ---------------------------------------------------------------- student database (admin + principal)
@router.get("/api/portal/students")
def students_list(cls: int = 0, q: str = "", authorization: str = Header(None), x_role: str = Header(None)):
    c = ctx(authorization, x_role, EDITORS)
    items = [s for s in school.students() if (not cls or int(s["class"]) == cls)]
    if q:
        ql = q.lower()
        items = [s for s in items if ql in s["name"].lower() or ql in s["id"].lower() or ql in s["phone"]
                 or ql in (s.get("area") or "").lower() or ql in (s.get("parent") or "").lower()]
    items.sort(key=lambda s: (int(s["class"]), s.get("sno", 0)))
    return {"items": [school.card(s, True) for s in items[:500]], "routes": school.routes(),
            "can_fee": c["role"] in APPROVERS, "can_delete": c["role"] in APPROVERS}


class StudentIn(BaseModel):
    id: str | None = Field(None, max_length=20)
    name: str | None = Field(None, max_length=80)
    cls: int | None = None
    section: str | None = Field(None, max_length=4)
    gender: str | None = Field(None, max_length=2)
    parent: str | None = Field(None, max_length=80)
    phone: str | None = Field(None, max_length=16)
    area: str | None = Field(None, max_length=60)
    route: str | None = Field(None, max_length=20)
    stop: str | None = Field(None, max_length=10)
    fee_total: int | None = Field(None, ge=0, lt=1_000_000)

    def fields(self):
        d = {k: v for k, v in self.model_dump().items() if v is not None and k not in ("cls",)}
        if self.cls is not None:
            d["class"] = self.cls
        return d


@router.put("/api/portal/students/{sid}")
def student_update(sid: str, body: StudentIn, authorization: str = Header(None), x_role: str = Header(None)):
    c = ctx(authorization, x_role, EDITORS)
    s = _err(school.update_student, sid, body.fields(), c["phone"], c["role"] in APPROVERS)
    auth.audit(c["phone"], "student_edit", {"student": sid})
    return school.card(s, True)


@router.post("/api/portal/students")
def student_add(body: StudentIn, authorization: str = Header(None), x_role: str = Header(None)):
    c = ctx(authorization, x_role, EDITORS)
    s = _err(school.add_student, body.fields(), c["phone"], c["role"] in APPROVERS)
    auth.audit(c["phone"], "student_add", {"student": s["id"]})
    return school.card(s, True)


@router.delete("/api/portal/students/{sid}")
def student_delete(sid: str, authorization: str = Header(None), x_role: str = Header(None)):
    c = ctx(authorization, x_role, APPROVERS)
    _err(school.delete_student, sid, c["phone"])
    auth.audit(c["phone"], "student_delete", {"student": sid})
    return {"ok": True}


class RouteIn(BaseModel):
    device_id: str | None = Field(None, max_length=40)
    driver: str | None = Field(None, max_length=60)
    driver_phone: str | None = Field(None, max_length=16)


@router.post("/api/portal/routes/{rid}")
def save_route(rid: str, body: RouteIn, authorization: str = Header(None), x_role: str = Header(None)):
    c = ctx(authorization, x_role, APPROVERS)
    r = _err(school.save_route, rid, body.device_id, body.driver, body.driver_phone)
    auth.audit(c["phone"], "route", {"route": rid})
    return r


# ---------------------------------------------------------------- admin office devices
@router.get("/api/portal/devices")
def devices(authorization: str = Header(None), x_role: str = Header(None)):
    ctx(authorization, x_role, APPROVERS)
    pk = {c["dev"] for c in (store.get("passkeys", []) or [])}
    return {"items": [{k: v for k, v in d.items() if k != "h"} | {"code": auth.device_code(d["id"]), "passkey": d["id"] in pk}
                      for d in (store.get("devices", []) or [])],
            "ip_lock": bool(os.getenv("OFFICE_IPS")), "hours": os.getenv("OFFICE_HOURS", ""),
            "your_ip": auth.REQUEST.get().get("ip", "")}


@router.post("/api/portal/devices/{dev_id}/{action}")
def device_decide(dev_id: str, action: str, authorization: str = Header(None), x_role: str = Header(None)):
    c = ctx(authorization, x_role, APPROVERS)
    if action not in ("approve", "revoke"):
        raise HTTPException(404, "Unknown action")
    try:
        return auth.decide_device(dev_id, action == "approve", c["phone"])
    except auth.AuthError as e:
        raise HTTPException(e.status, str(e))


# ---------------------------------------------------------------- admin: team and data
class MemberIn(BaseModel):
    phone: str
    name: str = ""
    role: str
    cls: int | None = None


@router.get("/api/portal/team")
def team(authorization: str = Header(None), x_role: str = Header(None)):
    c = ctx(authorization, x_role, ("admin",) + APPROVERS)
    env = [{"phone": p, "role": r, "name": f"{auth.ROLE_NAMES[r]} (Vercel setting)", "fixed": True}
           for r, e in auth.ENV_ROLES for p in auth._env_phones(e)]
    return {"items": env + school.team(), "meta": store.get("meta"), "can_assign": c["role"] == "superadmin"}


@router.post("/api/portal/team")
def add_member(body: MemberIn, authorization: str = Header(None), x_role: str = Header(None)):
    c = ctx(authorization, x_role, ("superadmin",))
    _err(school.add_member, body.phone, body.name, body.role, body.cls, c["phone"])
    auth.audit(c["phone"], "team_add", {"phone": body.phone, "role": body.role})
    return {"ok": True}


@router.delete("/api/portal/team/{phone}/{role}")
def remove_member(phone: str, role: str, authorization: str = Header(None), x_role: str = Header(None)):
    c = ctx(authorization, x_role, ("superadmin",))
    school.remove_member(phone, role)
    auth.audit(c["phone"], "team_remove", {"phone": phone, "role": role})
    return {"ok": True}


@router.post("/api/portal/import")
async def import_excel(request: Request, authorization: str = Header(None), x_role: str = Header(None)):
    c = ctx(authorization, x_role, APPROVERS)
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


# ---------------------------------------------------------------- lesson scan / upload
class SummarizeIn(BaseModel):
    cls: int = 0
    subject: str = Field("", max_length=40)
    images: list[str] = []
    pdf: str | None = None
    text: str = Field("", max_length=20000)


@router.post("/api/portal/lessons/summarize")
def lesson_summarize(body: SummarizeIn, request: Request, authorization: str = Header(None),
                     x_role: str = Header(None)):
    c = ctx(authorization, x_role, ("teacher",) + APPROVERS)
    k = _class_for(c, body.cls)
    res = _err(lessons.summarize, k, body.subject, body.images, body.pdf, body.text,
               request.headers.get("x-vercel-oidc-token"))
    auth.audit(c["phone"], "lesson_summary", {"class": k, "source": res["source"], "pages": res["pages"]})
    return res | {"class": k}


class LessonIn(BaseModel):
    cls: int = 0
    subject: str = Field("", max_length=40)
    summary: str = Field(min_length=1, max_length=6000)
    send: bool = True


@router.post("/api/portal/lessons")
def lesson_save(body: LessonIn, authorization: str = Header(None), x_role: str = Header(None)):
    c = ctx(authorization, x_role, ("teacher",) + APPROVERS)
    k = _class_for(c, body.cls)
    return _err(lessons.save_note, k, body.subject, body.summary, c["phone"], c.get("name") or "Teacher", body.send)


# ---------------------------------------------------------------- practical sessions
@router.get("/api/portal/practicals")
def practicals_view(cls: int = 0, authorization: str = Header(None), x_role: str = Header(None)):
    c = ctx(authorization, x_role, ("teacher",) + MGMT)
    if c["role"] != "teacher" and not cls:
        classes = sorted({int(s["class"]) for s in school.students()})
        return {"school": practicals.school_view(school.today(), classes), "weeks": practicals.all_weeks()}
    return practicals.class_view(_class_for(c, cls), school.today())


class PracticalDoneIn(BaseModel):
    no: int
    cls: int = 0
    note: str = Field("", max_length=300)


@router.post("/api/portal/practicals/done")
def practicals_done(body: PracticalDoneIn, authorization: str = Header(None), x_role: str = Header(None)):
    c = ctx(authorization, x_role, ("teacher",) + APPROVERS)
    k = _class_for(c, body.cls)
    return _err(practicals.mark_done, body.no, k, c.get("name") or "Teacher", body.note)


# ---------------------------------------------------------------- agent
class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[dict] = []


@router.post("/api/portal/chat")
def chat(body: ChatIn, authorization: str = Header(None), x_role: str = Header(None)):
    c = ctx(authorization, x_role, ALL)
    return {"reply": role_chat(c, body.message, body.history[-8:])}


# ---------------------------------------------------------------- scheduled job (Vercel Cron, daily)
@router.get("/api/cron/fee-reminders")
def cron_fee(authorization: str = Header(None)):
    secret = os.getenv("CRON_SECRET", "")
    if not secret or authorization != f"Bearer {secret}":
        raise HTTPException(401, "cron only")
    return school.run_fee_reminders(by="cron")
