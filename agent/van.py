"""School van GPS: receives locations from the Traccar Client phone app and serves them to the portal.

Traccar Client  ->  POST https://<site>/api/van/loc/<VAN_KEY>   (OsmAnd format: query, form or JSON)
Portal map      ->  GET  /api/portal/routes  (logged-in users; parents see only their child's route)

Settings (Vercel -> Project -> Settings -> Environment Variables):
  VAN_KEY   secret part of the URL the phone sends to (required; anything else is rejected)
Which phone belongs to which route: set the Traccar "Device identifier" on each route in the portal
(Principal -> Bus routes). A phone with the right URL but an unknown identifier appears as
"Unassigned phone" (max 10) until it is linked. Every attempt (also rejected ones) is listed in Bus routes.
Positions are stored (encrypted) in the Vercel Neon Postgres database via store.py.
"""
import hmac
import json
import os
import time
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request

import store

router = APIRouter(prefix="/api/van")
TRAIL = 120            # points of route history kept per van
STALE_AFTER = 10 * 60  # seconds: older than this = offline


# ---------------------------------------------------------------- parsing (old and new Traccar Client formats)
def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _ts(x) -> float:
    if x in (None, ""):
        return time.time()
    n = _num(x)
    if n is not None:
        return n / 1000 if n > 1e11 else n  # milliseconds or seconds
    try:
        return datetime.fromisoformat(str(x).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return time.time()


def parse(fields: dict, body: dict | None) -> dict:
    """OsmAnd query/form fields (id, lat, lon, timestamp, speed, bearing, batt) or the JSON body of the
    newer client ({device_id, location: {timestamp, coords, battery}})."""
    f = dict(fields)
    b = body or {}
    loc = b.get("location") or {}
    if isinstance(loc, list):
        loc = loc[-1] if loc else {}
    coords = loc.get("coords") or {}
    dev = f.get("id") or f.get("deviceid") or b.get("device_id") or b.get("id") or b.get("deviceId")
    lat = _num(f.get("lat")) if "lat" in f else _num(coords.get("latitude", b.get("lat")))
    lon = _num(f.get("lon")) if "lon" in f else _num(coords.get("longitude", b.get("lon")))
    if not dev or lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("need device id, lat and lon")
    speed = _num(f.get("speed")) if "speed" in f else _num(coords.get("speed"))
    knots = "speed" in f  # OsmAnd query speed is in knots; JSON coords speed is m/s
    kmh = None if speed is None or speed < 0 else round(speed * (1.852 if knots else 3.6), 1)
    batt = _num(f.get("batt") or (loc.get("battery") or {}).get("level"))
    if batt is not None and batt <= 1:
        batt *= 100
    return {"id": str(dev)[:40], "lat": round(lat, 6), "lon": round(lon, 6),
            "ts": _ts(f.get("timestamp") or loc.get("timestamp")), "kmh": kmh,
            "heading": _num(f.get("bearing") or coords.get("heading")),
            "battery": None if batt is None else round(batt), "received": time.time()}


OLD_POINT = 6 * 3600  # Traccar Client uploads its offline backlog (oldest first); skip points older than this


def save_point(p: dict) -> str:
    """Keep only the newest position as 'latest'. Old buffered points are accepted (so the phone
    deletes them) but never shown as the van's current place."""
    now = time.time()
    if p["ts"] > now + 300:      # phone clock ahead: trust the server time
        p["ts"] = now
    if now - p["ts"] > OLD_POINT:
        return "old point from the phone's backlog - skipped"
    latest = store.get("van:latest", {}) or {}
    cur = latest.get(p["id"])
    if cur and cur.get("ts", 0) > p["ts"]:
        return "older than the last position - skipped"
    latest[p["id"]] = p
    store.set("van:latest", latest)
    trail = [t for t in (store.get(f"van:trail:{p['id']}", []) or []) if now - t[2] < OLD_POINT]
    trail.insert(0, [p["lat"], p["lon"], p["ts"]])
    store.set(f"van:trail:{p['id']}", trail[:TRAIL])
    return "ok"


def vans(route_list: list[dict], only_routes: set | None = None) -> list[dict]:
    """Routes with their live van position. only_routes limits what a parent can see."""
    latest = store.get("van:latest", {}) or {}
    assigned = {r.get("device_id") for r in route_list if r.get("device_id")}
    store.get_many([f"van:trail:{d}" for d in latest])  # one round trip; _pos below reads from the cache
    now = time.time()
    out = []
    for r in route_list:
        if only_routes is not None and r["id"] not in only_routes:
            continue
        p = latest.get(r.get("device_id") or "")
        out.append(dict(r, live=_live(p, now), position=_pos(p, now, r.get("device_id"))))
    if only_routes is None:  # unassigned test phones (management view only)
        for dev, p in latest.items():
            if dev not in assigned:
                out.append({"id": f"dev-{dev}", "name": f"Unassigned phone {dev[-4:]}", "stops": [],
                            "device_id": dev, "live": _live(p, now), "position": _pos(p, now, dev)})
    return out


def _live(p, now):
    return bool(p) and now - p["ts"] < STALE_AFTER


def _pos(p, now, dev):
    if not p:
        return None
    trail = store.get(f"van:trail:{dev}", []) or []
    return {"lat": p["lat"], "lon": p["lon"], "kmh": p.get("kmh"), "battery": p.get("battery"),
            "age_s": int(now - p["ts"]), "trail": trail[:60]}


def eta_to_stop(position: dict | None, stop: dict | None, live: bool) -> dict | None:
    """Rough distance and time from the van to a bus stop: straight line x 1.3 for roads, 20 km/h average."""
    if not position or not stop or stop.get("lat") is None:
        return None
    from math import asin, cos, radians, sin, sqrt
    la1, lo1, la2, lo2 = map(radians, (position["lat"], position["lon"], stop["lat"], stop["lon"]))
    km = 2 * 6371 * asin(sqrt(sin((la2 - la1) / 2) ** 2 + cos(la1) * cos(la2) * sin((lo2 - lo1) / 2) ** 2)) * 1.3
    return {"km": round(km, 1), "minutes": max(1, round(km / 20 * 60)) if live else None, "near": km < 0.4}


def status_text(items: list[dict]) -> str:
    if not items:
        return "No bus route is linked to your child."
    out = []
    for v in items:
        p = v.get("position")
        if not p:
            out.append(f"{v['name']}: no GPS yet (van phone not set up or switched off).")
            continue
        mins = p["age_s"] // 60
        when = "just now" if mins < 1 else f"{mins} min ago"
        state = ("offline (GPS not sending)" if not v["live"] else
                 f"moving at {p['kmh']:.0f} km/h" if (p.get("kmh") or 0) > 3 else "stopped")
        out.append(f"{v['name']}: {state}, last update {when}. Map: https://www.google.com/maps?q={p['lat']},{p['lon']}")
    return "\n".join(out)


# ---------------------------------------------------------------- receiver
def note_attempt(dev: str, ok: bool, reason: str):
    """Last attempts per phone, so the principal can see in Bus routes whether a phone is reaching us."""
    items = [x for x in (store.get("van:attempts", []) or []) if x["id"] != dev]
    items.insert(0, {"id": dev[:40], "ok": ok, "reason": reason, "at": time.time()})
    store.set("van:attempts", items[:15])
    print(f"[van] {'ok' if ok else 'rejected'} device={dev[:40]} {reason}")


def attempts() -> list[dict]:
    now = time.time()
    return [x | {"age_s": int(now - x["at"])} for x in (store.get("van:attempts", []) or []) if now - x["at"] < 86400]


MAX_UNASSIGNED = 10


@router.api_route("/loc/{key}", methods=["GET", "POST"])
async def receive(key: str, request: Request):
    fields = dict(request.query_params)
    body = None
    raw = await request.body()
    if raw:
        try:
            if "json" in request.headers.get("content-type", "") or raw.lstrip()[:1] in (b"{", b"["):
                body = json.loads(raw)
                if isinstance(body, list):
                    body = body[-1] if body else {}
            else:  # OsmAnd form body (id=..&lat=..&lon=..)
                from urllib.parse import parse_qsl
                fields.update(parse_qsl(raw.decode("utf-8", "replace"), keep_blank_values=False))
        except Exception:
            pass
    dev_hint = str(fields.get("id") or (body or {}).get("device_id") or (body or {}).get("id") or "unknown")
    expected = os.getenv("VAN_KEY", "")
    if not expected:
        raise HTTPException(503, "VAN_KEY is not set on the server")
    if not hmac.compare_digest(key, expected):
        note_attempt(dev_hint, False, "wrong server URL (key)")
        raise HTTPException(403, "wrong key")
    try:
        p = parse(fields, body)
    except ValueError as e:
        note_attempt(dev_hint, False, "no location in the message (GPS off or no fix yet)")
        print(f"[van] unreadable: type={request.headers.get('content-type', '')[:60]} "
              f"query={sorted(request.query_params.keys())} body={raw[:200]!r}")
        raise HTTPException(400, str(e))
    import school
    known = {r.get("device_id") for r in school.routes() if r.get("device_id")}
    latest = store.get("van:latest", {}) or {}
    if p["id"] not in known and p["id"] not in latest and sum(d not in known for d in latest) >= MAX_UNASSIGNED:
        note_attempt(p["id"], False, "too many unlinked phones - link or remove some")
        raise HTTPException(403, "too many unassigned devices")
    res = save_point(p)  # unknown phones are kept as "Unassigned phone" until linked to a route
    link = "linked" if p["id"] in known else "not linked to a route yet"
    if res == "ok":
        note_attempt(p["id"], True, link)
    else:
        age_h = int((time.time() - p["ts"]) // 3600)
        note_attempt(p["id"], True, f"{link} - sending saved old locations ({age_h} h old), please wait")
        print(f"[van] {p['id']}: {res} ({age_h} h old)")
    return {"ok": True}
