"""Free login: "Verify on WhatsApp".

The parent types their mobile number and taps "Verify on WhatsApp". WhatsApp opens a chat with the
school's portal number with a ready message ("LOGIN SPV 482913"); the parent taps Send. Meta tells our
webhook which number sent which code (signed with the app secret), and the waiting browser logs in.

Why it is free: messages that parents SEND to a business number cost nothing, and a plain (non-template)
reply within 24 hours is free too. No SMS, no OTP template.
Why it is secure: WhatsApp has already verified the sender's number; Meta signs every webhook; the code
works once, for 10 minutes, only for the browser that asked for it (secret poll token) and only if it
arrives FROM the same mobile number that was typed.

Settings (Vercel):  WA_LOGIN_NUMBER (portal WhatsApp number, e.g. 919876543210), WHATSAPP_TOKEN,
WHATSAPP_PHONE_ID, WHATSAPP_APP_SECRET, WHATSAPP_VERIFY_TOKEN. Works with a normal SIM that is used
ONLY for the WhatsApp Cloud API (the school's existing WhatsApp stays as it is).
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import time
import urllib.parse

import auth
import notify
import store

TTL = 600


def enabled() -> bool:
    return bool(os.getenv("WA_LOGIN_NUMBER") and os.getenv("WHATSAPP_APP_SECRET"))


def _h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def start(phone: str) -> dict:
    phone = auth.norm_phone(phone)
    if not auth.valid_mobile(phone):
        raise auth.AuthError("Enter a valid 10-digit mobile number", 400)
    if not auth.roles_for(phone):
        raise auth.AuthError("This number is not registered with the school. Please contact the school office.", 404)
    last = store.get(f"wal_last:{phone}")
    if last and time.time() - last < 15:
        raise auth.AuthError("Please wait a few seconds and try again.", 429)
    store.set(f"wal_last:{phone}", time.time(), ttl=60)
    code = f"{secrets.randbelow(900000) + 100000}"
    poll = secrets.token_urlsafe(24)
    store.set(f"wal:{code}", {"phone": phone, "poll": _h(poll), "status": "pending", "at": int(time.time())}, ttl=TTL)
    store.set(f"walpoll:{_h(poll)}", code, ttl=TTL)
    number = re.sub(r"\D", "", os.getenv("WA_LOGIN_NUMBER", ""))
    text = f"LOGIN SPV {code}"
    return {"poll": poll, "code": code, "text": text,
            "link": f"https://wa.me/{number}?text={urllib.parse.quote(text)}", "expires_in": TTL}


def status(poll: str) -> dict:
    code = store.get(f"walpoll:{_h(poll)}")
    rec = store.get(f"wal:{code}") if code else None
    if not rec:
        return {"status": "expired"}
    if rec["status"] != "verified":
        return {"status": "pending"}
    store.delete(f"wal:{code}")       # one-time
    store.delete(f"walpoll:{_h(poll)}")
    roles = auth.roles_for(rec["phone"])
    auth.audit(rec["phone"], "login", {"via": "whatsapp", "roles": [r["role"] for r in roles]})
    return {"status": "verified", "token": auth.make_token(rec["phone"]), "phone": rec["phone"], "roles": roles}


def check_signature(raw: bytes, header: str | None) -> bool:
    secret = os.getenv("WHATSAPP_APP_SECRET", "")
    if not secret or not header or not header.startswith("sha256="):
        return False
    good = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(header[7:], good)


def handle_webhook(payload: dict) -> int:
    """Process incoming WhatsApp messages. Returns how many logins were verified."""
    done = 0
    for entry in payload.get("entry", []):
        for ch in entry.get("changes", []):
            for msg in (ch.get("value") or {}).get("messages", []) or []:
                body = ((msg.get("text") or {}).get("body") or "") if msg.get("type") == "text" else ""
                m = re.search(r"\b(\d{6})\b", body)
                if not m or "login" not in body.lower():
                    continue
                sender = auth.norm_phone(msg.get("from", ""))
                rec = store.get(f"wal:{m.group(1)}")
                if not rec or rec["status"] != "pending":
                    _reply(sender, "This login code has expired. Please start again in the SPV portal.")
                    continue
                if rec["phone"] != sender:
                    _reply(sender, "Please send this message from the WhatsApp of the mobile number you typed.")
                    continue
                rec["status"] = "verified"
                store.set(f"wal:{m.group(1)}", rec, ttl=TTL)
                done += 1
                _reply(sender, "✅ Verified. Go back to the SPV School Portal - you are logged in.")
    return done


def _reply(phone: str, text: str):
    """Free reply inside the 24-hour window opened by the parent's own message."""
    if not notify.api_ready() or not auth.valid_mobile(phone):
        return
    try:
        notify._graph({"messaging_product": "whatsapp", "to": f"91{phone}", "type": "text", "text": {"body": text}})
    except Exception as e:
        print(f"[wa-login] reply failed: {type(e).__name__}")
