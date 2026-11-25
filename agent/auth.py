"""Mobile number + OTP login and role sessions for the SPV portal.

Who can log in (roles are re-checked on every request, so removing someone works at once):
  parent         mobile number is a parent number on a student record
  teacher        number in the staff list (class teacher of a class)
  superadmin     SUPERADMIN_PHONES (Vercel env) or assigned by a super admin: all powers + assigns roles
  principal / correspondent / admin
                 numbers in PRINCIPAL_PHONES / CORRESPONDENT_PHONES / ADMIN_PHONES (Vercel env, comma
                 separated) or assigned by a super admin in the portal (Roles tab).
                 Admin = write-only: can add entries (fees go to the principal for approval) but not
                 change or delete existing records.
One number can hold several roles (e.g. a teacher who is also a parent): the app asks which one to use.

OTP: 6 digits, stored only as an HMAC hash, valid 5 minutes, 5 tries, 30 s between sends.
Delivery: SMS (Fast2SMS) or WhatsApp Cloud API (notify.py) when configured. OTP_DEV_MODE=true shows the code on screen
for testing - that gives NO real protection and must be switched off before parents use the app.
"""
import base64
import contextvars
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import time

import notify
import store

TOKEN_DAYS = 365  # stay logged in for a year on that phone (fewer logins = no OTP cost)
# Per-request facts set by the API middleware (portal_api.install): device id, device label, client IP.
REQUEST: contextvars.ContextVar = contextvars.ContextVar("spv_request", default={})
IST_OFFSET = 5.5 * 3600
MGMT_ROLES = ("superadmin", "principal", "correspondent", "admin")
ROLE_ORDER = ("superadmin", "principal", "correspondent", "admin", "teacher", "parent")


ROLE_NAMES = {"superadmin": "Super admin", "principal": "Principal", "correspondent": "Correspondent",
              "admin": "Admin", "teacher": "Class teacher", "parent": "Parent"}


class AuthError(Exception):
    def __init__(self, msg, status=401):
        super().__init__(msg)
        self.status = status


def _secret() -> bytes:
    s = os.getenv("JWT_SECRET", "")
    if not s:
        if os.getenv("VERCEL"):
            raise AuthError("Server not configured (JWT_SECRET missing)", 503)
        s = "dev-only-secret"
    return s.encode()


def norm_phone(p) -> str:
    d = re.sub(r"\D", "", str(p or ""))
    if len(d) == 12 and d.startswith("91"):
        d = d[2:]
    if len(d) == 11 and d.startswith("0"):
        d = d[1:]
    return d


def valid_mobile(p: str) -> bool:
    return bool(re.fullmatch(r"[6-9]\d{9}", p or ""))


def dev_mode() -> bool:
    return os.getenv("OTP_DEV_MODE", "").lower() in ("1", "true", "yes")


# ---------------------------------------------------------------- roles
def _env_phones(name):
    return {norm_phone(x) for x in os.getenv(name, "").split(",") if norm_phone(x)}


ENV_ROLES = (("superadmin", "SUPERADMIN_PHONES"), ("principal", "PRINCIPAL_PHONES"),
             ("correspondent", "CORRESPONDENT_PHONES"), ("admin", "ADMIN_PHONES"))


def roles_for(phone: str) -> list[dict]:
    """All roles this mobile number holds right now."""
    import school  # local import: school imports auth
    phone = norm_phone(phone)
    out = []
    team = school.team()
    for role, env in ENV_ROLES:
        names = [t["name"] for t in team if t["phone"] == phone and t["role"] == role]
        if phone in _env_phones(env) or names:
            out.append({"role": role, "name": names[0] if names else ROLE_NAMES[role]})
    for t in team:
        if t["phone"] == phone and t["role"] == "teacher":
            out.append({"role": "teacher", "name": t["name"], "class": t.get("class")})
    kids = [s for s in school.students() if s["phone"] == phone]
    if kids:
        out.append({"role": "parent", "name": kids[0].get("parent") or "Parent",
                    "children": [k["id"] for k in kids]})
    out.sort(key=lambda r: ROLE_ORDER.index(r["role"]))
    return out


# ---------------------------------------------------------------- OTP
def _otp_hash(phone, code):
    return hmac.new(_secret(), f"{phone}:{code}".encode(), hashlib.sha256).hexdigest()


def send_otp(phone) -> dict:
    phone = norm_phone(phone)
    if not valid_mobile(phone):
        raise AuthError("Enter a valid 10-digit mobile number", 400)
    if not roles_for(phone):
        raise AuthError("This number is not registered with the school. Please contact the school office.", 404)
    old = store.get(f"otp:{phone}")
    if old and time.time() - old["sent"] < 30:
        raise AuthError("Please wait 30 seconds before asking for a new OTP", 429)
    code = f"{secrets.randbelow(1_000_000):06d}"
    store.set(f"otp:{phone}", {"h": _otp_hash(phone, code), "sent": time.time(), "tries": 0}, ttl=300)
    sent = notify.send_otp(phone, code)
    out = {"ok": True, "channel": sent}
    if dev_mode():
        out["dev_code"] = code  # testing only
    elif sent == "none":
        store.delete(f"otp:{phone}")
        raise AuthError("OTP service is not set up yet. Please contact the school office.", 503)
    return out


def verify_otp(phone, code) -> dict:
    phone = norm_phone(phone)
    rec = store.get(f"otp:{phone}")
    if not rec:
        raise AuthError("OTP expired. Please ask for a new one.", 400)
    if rec["tries"] >= 5:
        store.delete(f"otp:{phone}")
        raise AuthError("Too many wrong tries. Please ask for a new OTP.", 429)
    if not hmac.compare_digest(rec["h"], _otp_hash(phone, re.sub(r"\D", "", str(code)))):
        rec["tries"] += 1
        store.set(f"otp:{phone}", rec, ttl=300)
        raise AuthError("Wrong OTP. Please check and try again.", 400)
    store.delete(f"otp:{phone}")
    roles = roles_for(phone)
    if not roles:
        raise AuthError("This number is no longer registered.", 403)
    audit(phone, "login", {"roles": [r["role"] for r in roles]})
    return {"token": make_token(phone), "phone": phone, "roles": roles}


# ---------------------------------------------------------------- tokens (HMAC-signed, no extra library)
def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def make_token(phone: str) -> str:
    body = _b64(json.dumps({"p": phone, "exp": int(time.time()) + TOKEN_DAYS * 86400}).encode())
    sig = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def read_token(token: str) -> str:
    try:
        body, sig = token.split(".")
        good = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, good):
            raise ValueError
        data = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        if data["exp"] < time.time():
            raise AuthError("Session expired. Please log in again.")
        return data["p"]
    except AuthError:
        raise
    except Exception:
        raise AuthError("Please log in")


def session(token: str, role: str | None, passkey: bool = True) -> dict:
    """Validate the token and the role the app wants to act as. Returns the active role record."""
    phone = read_token(token)
    roles = roles_for(phone)
    if not roles:
        raise AuthError("This number is no longer registered.", 403)
    pick = next((r for r in roles if r["role"] == role), None) if role else roles[0]
    if not pick:
        raise AuthError("You do not have access to this section.", 403)
    office_check(phone, pick["role"], passkey)
    return dict(pick, phone=phone, all_roles=[r["role"] for r in roles])


# ---------------------------------------------------------------- admin: office only
def device_hash(device_id: str) -> str:
    return hashlib.sha256(("spv-device:" + device_id).encode()).hexdigest()


def device_ref(device_id: str, phone: str) -> str:
    """Short public id of one (device, admin number) pair, shown to the principal."""
    return hashlib.sha256((device_hash(device_id) + phone).encode()).hexdigest()[:12]


def _client_ip() -> str:
    return REQUEST.get().get("ip", "")


def _in_office_network(ip: str) -> bool:
    nets = [n.strip() for n in os.getenv("OFFICE_IPS", "").split(",") if n.strip()]
    if not nets:
        return True  # IP lock not switched on
    try:
        addr = ipaddress.ip_address(ip)
        return any(addr in ipaddress.ip_network(n, strict=False) for n in nets)
    except ValueError:
        return False


def _in_office_hours() -> bool:
    """OFFICE_HOURS like '08:00-18:00' (IST, Monday-Saturday). Empty = any time."""
    rng = os.getenv("OFFICE_HOURS", "").strip()
    if not rng:
        return True
    t = time.gmtime(time.time() + IST_OFFSET)
    start, end = [int(x[:2]) * 60 + int(x[3:5]) for x in rng.split("-")]
    return t.tm_wday != 6 and start <= t.tm_hour * 60 + t.tm_min <= end


def device_code(devref: str) -> str:
    """Short code shown on the admin's screen and in the principal's list, to match the right device."""
    return f"{devref[:4]}-{devref[4:8]}".upper()


def current_device(phone: str) -> str:
    """The approved device id (devref) of this request, or raise."""
    dev = REQUEST.get().get("device", "")
    if len(dev) < 20:
        raise AuthError("Admin access works only on an approved office device.", 403)
    ref = device_ref(dev, phone)
    rec = next((d for d in (store.get("devices", []) or []) if d["id"] == ref), None)
    if not rec or rec["status"] != "approved":
        raise AuthError("This device is not approved for admin work.", 403)
    return ref


def office_check(phone: str, role: str, passkey: bool = True):
    """The admin role works only from the school office:
       1. an office device approved by the principal (ADMIN_DEVICE_APPROVAL, on by default)
       2. optional: the office internet connection only (OFFICE_IPS, e.g. '49.204.10.20' or a range)
       3. optional: office hours only (OFFICE_HOURS, e.g. '08:00-18:00', Mon-Sat IST)"""
    if role != "admin":
        return
    if not _in_office_network(_client_ip()):
        raise AuthError("Admin access is allowed only from the school office internet connection.", 403)
    if not _in_office_hours():
        raise AuthError(f"Admin access is allowed only in office hours ({os.getenv('OFFICE_HOURS')}, Mon-Sat).", 403)
    if os.getenv("ADMIN_DEVICE_APPROVAL", "true").lower() in ("0", "false", "no"):
        return
    req = REQUEST.get()
    dev = req.get("device", "")
    if len(dev) < 20:
        raise AuthError("Admin access works only on an approved office device.", 403)
    h = device_hash(dev)
    devices = store.get("devices", []) or []
    rec = next((d for d in devices if d["h"] == h and d["phone"] == phone), None)
    if rec and rec["status"] == "approved":
        if passkey:
            import passkeys
            passkeys.require(phone, rec["id"])  # fingerprint / Windows Hello on this device
        return
    if not rec:
        devices.insert(0, {"id": device_ref(dev, phone), "h": h, "phone": phone, "label": req.get("label", "")[:80],
                           "ip": _client_ip(), "at": int(time.time()), "status": "pending"})
        store.set("devices", devices[:200])
        audit(phone, "admin_device_request", {"device": device_ref(dev, phone)})
    if rec and rec["status"] == "revoked":
        raise AuthError("This device was removed from admin access. Please use the office device.", 403)
    raise AuthError(f"This device (code {device_code(device_ref(dev, phone))}) is not yet approved for admin work. "
                    "Ask the principal to approve it (Roles & data > Admin office devices), then try again.", 403)


def decide_device(dev_id: str, approve: bool, by_phone: str) -> dict:
    devices = store.get("devices", []) or []
    rec = next((d for d in devices if d["id"] == dev_id), None)
    if not rec:
        raise AuthError("Device not found", 404)
    rec.update(status="approved" if approve else "revoked", by=by_phone, decided_at=int(time.time()))
    store.set("devices", devices)
    if not approve:
        import passkeys
        passkeys.remove_for_device(dev_id)  # a removed device loses its fingerprint login too
    audit(by_phone, "device_" + rec["status"], {"device": dev_id, "admin": rec["phone"]})
    return {k: v for k, v in rec.items() if k != "h"} | {"code": device_code(rec["id"])}


def audit(phone, action, detail=None):
    try:
        store.push("audit", {"at": int(time.time()), "by": phone, "action": action, "detail": detail or {}}, cap=1000)
    except Exception:
        pass
