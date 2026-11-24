"""WhatsApp messages to parents and staff.

Two ways, chosen automatically:
  1. Automatic  - WhatsApp Business Cloud API (Meta). Needs WHATSAPP_TOKEN + WHATSAPP_PHONE_ID in Vercel.
                  Messages outside a 24-hour chat window must use approved templates; set the template
                  names below (each with ONE body variable {{1}} that receives the full message text):
                    WA_TPL_ABSENT, WA_TPL_FEE, WA_TPL_HOMEWORK, WA_TPL_UPDATE, WA_TPL_CIRCULAR
                  and WA_TPL_OTP (an "authentication" template) for login codes. WA_TPL_LANG (default en).
  2. One-tap    - without the API, every message is queued in the outbox with a wa.me link. The teacher
                  or office taps "Send on WhatsApp" and it opens WhatsApp with the text ready. Free.
Numbers that are not valid Indian mobiles (test data uses numbers starting with 5) are never messaged.
"""
import json
import os
import re
import time
import urllib.parse
import urllib.request

import store

GRAPH = "https://graph.facebook.com/v21.0"


def api_ready() -> bool:
    return bool(os.getenv("WHATSAPP_TOKEN") and os.getenv("WHATSAPP_PHONE_ID"))


def _valid(phone) -> bool:
    return bool(re.fullmatch(r"[6-9]\d{9}", phone or ""))


def wa_link(phone: str | None, text: str) -> str:
    q = urllib.parse.quote(text)
    return f"https://wa.me/91{phone}?text={q}" if phone else f"https://wa.me/?text={q}"


def _graph(payload: dict) -> dict:
    req = urllib.request.Request(
        f"{GRAPH}/{os.environ['WHATSAPP_PHONE_ID']}/messages", data=json.dumps(payload).encode(), method="POST",
        headers={"Authorization": f"Bearer {os.environ['WHATSAPP_TOKEN']}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def _send_api(phone: str, text: str, kind: str):
    tpl = os.getenv(f"WA_TPL_{kind.upper()}")
    if tpl:
        payload = {"messaging_product": "whatsapp", "to": f"91{phone}", "type": "template",
                   "template": {"name": tpl, "language": {"code": os.getenv("WA_TPL_LANG", "en")},
                                "components": [{"type": "body", "parameters": [{"type": "text", "text": text[:1000]}]}]}}
    else:  # free-form text: only delivered inside a 24 h window (fine for testing after the parent says "hi")
        payload = {"messaging_product": "whatsapp", "to": f"91{phone}", "type": "text", "text": {"body": text}}
    return _graph(payload)


def send(phone: str, text: str, kind: str, meta: dict | None = None) -> dict:
    """Send (or queue) one WhatsApp message and record it in the outbox. Never raises."""
    item = {"id": f"m{int(time.time() * 1000)}{len(text) % 97}", "at": int(time.time()), "to": phone,
            "kind": kind, "text": text, "meta": meta or {}, "link": wa_link(phone, text)}
    if not _valid(phone):
        item["status"] = "skipped"  # test/fake number
    elif api_ready():
        try:
            _send_api(phone, text, kind)
            item["status"] = "sent"
        except Exception as e:
            item["status"], item["error"] = "failed", f"{type(e).__name__}"
    else:
        item["status"] = "queued"  # one-tap send from the app
    try:
        store.push("outbox", item, cap=800)
    except Exception:
        pass
    return item


def send_otp(phone: str, code: str) -> str:
    """Returns the channel used: whatsapp | none."""
    if api_ready() and os.getenv("WA_TPL_OTP"):
        try:
            _graph({"messaging_product": "whatsapp", "to": f"91{phone}", "type": "template",
                    "template": {"name": os.environ["WA_TPL_OTP"], "language": {"code": os.getenv("WA_TPL_LANG", "en")},
                                 "components": [{"type": "body", "parameters": [{"type": "text", "text": code}]},
                                                {"type": "button", "sub_type": "url", "index": "0",
                                                 "parameters": [{"type": "text", "text": code}]}]}})
            return "whatsapp"
        except Exception:
            return "none"
    return "none"


def mark_sent(msg_id: str, by: str) -> bool:
    items = store.get("outbox", []) or []
    for m in items:
        if m["id"] == msg_id:
            m["status"], m["sent_by"], m["sent_at"] = "sent-manual", by, int(time.time())
            store.set("outbox", items)
            return True
    return False
