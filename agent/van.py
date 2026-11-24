"""School van GPS: receives locations from the Traccar Client phone app and serves them to the portal.

Traccar Client  ->  POST https://<site>/api/van/loc/<VAN_KEY>   (OsmAnd format: query, form or JSON)
Portal map      ->  GET  /api/portal/routes  (logged-in users; parents see only their child's route)

Settings (Vercel -> Project -> Settings -> Environment Variables):
  VAN_KEY   secret part of the URL the phone sends to (required; anything else is rejected)
Which phone belongs to which route: set the Traccar "Device identifier" on each route in the portal
(Principal/Admin -> Bus routes). Unknown devices are accepted only while no route has a device id,
so a first test works before setup.
Positions are stored with store.py (Postgres / Redis), so they survive between serverless calls.
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


def save_point(p: dict):
    latest = store.get("van:latest", {}) or {}
    latest[p["id"]] = p
    store.set("van:latest", latest)
    trail = store.get(f"van:trail:{p['id']}", []) or []
    trail.insert(0, [p["lat"], p["lon"], p["ts"]])
    store.set(f"van:trail:{p['id']}", trail[:TRAIL])


def vans(route_list: list[dict], only_routes: set | None = None) -> list[dict]:
    """Routes with their live van position. only_routes limits what a parent can see."""
    latest = store.get("van:latest", {}) or {}
    assigned = {r.get("device_id") for r in route_list if r.get("device_id")}
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
@router.api_route("/loc/{key}", methods=["GET", "POST"])
async def receive(key: str, request: Request):
    expected = os.getenv("VAN_KEY", "")
    if not expected:
        raise HTTPException(503, "VAN_KEY is not set on the server")
    if not hmac.compare_digest(key, expected):
        raise HTTPException(403, "wrong key")
    fields = dict(request.query_params)
    body = None
    raw = await request.body()
    if raw:
        try:
            if "json" in request.headers.get("content-type", "") or raw.lstrip()[:1] in (b"{", b"["):
                body = json.loads(raw)
                if isinstance(body, list):
                    body = body[-1] if body else {}
            else:
                fields.update((await request.form()).items())
        except Exception:
            pass
    try:
        p = parse(fields, body)
    except ValueError as e:
        raise HTTPException(400, str(e))
    import school
    known = {r.get("device_id") for r in school.routes() if r.get("device_id")}
    if known and p["id"] not in known:
        raise HTTPException(403, "unknown device id - add it to a bus route in the portal")
    save_point(p)
    return {"ok": True}
