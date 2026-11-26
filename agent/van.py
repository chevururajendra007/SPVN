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
FRESH = 3 * 60         # updated within 3 min: shown as moving / stopped right now
STALE_AFTER = 30 * 60  # 3-30 min: van parked or phone idle; older: offline
BAD_ACCURACY = 100     # metres: worse than this = Wi-Fi / tower position, not GPS
GOOD_KEEP = 10 * 60    # keep showing a real GPS fix this long rather than replace it with a rough one


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
    import school
    return {"id": school.devkey(dev), "lat": round(lat, 6), "lon": round(lon, 6),
            "ts": _ts(f.get("timestamp") or loc.get("timestamp")), "kmh": kmh,
            "heading": _num(f.get("bearing") or coords.get("heading")),
            "battery": None if batt is None else round(batt), "received": time.time(),
            "acc": _num(f.get("accuracy") or coords.get("accuracy"))}


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
    if cur and (p.get("acc") or 0) > BAD_ACCURACY and (cur.get("acc") or 0) <= BAD_ACCURACY \
            and p["ts"] - cur.get("fix_ts", cur["ts"]) < GOOD_KEEP:
        cur["ts"] = p["ts"]  # phone is alive; keep the good GPS point as the position
        cur["battery"] = p.get("battery", cur.get("battery"))
        latest[p["id"]] = cur
        store.set("van:latest", latest)
        return "rough location (no GPS lock) - kept last GPS point"
    if (p.get("acc") or 0) <= BAD_ACCURACY:
        p["fix_ts"] = p["ts"]
    elif cur and cur.get("fix_ts"):
        p["fix_ts"] = cur["fix_ts"]
    if p.get("kmh") is None and cur:  # some phones send no speed: work it out from the last point
        dt = p["ts"] - cur.get("fix_ts", cur["ts"])  # time since the point we actually measured
        if 0 < dt < 600:
            p["kmh"] = round(_km(cur, p) / (dt / 3600), 1)
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
        if p and now - p["ts"] > OLD_POINT:
            p = None  # weeks-old position: don't show it as where the van is
        pos = _pos(p, now, r.get("device_id"))
        if pos:
            pos["place"] = place_name(pos["lat"], pos["lon"])
            pos["near_stop"] = nearest_stop(pos, r.get("stops"))
        out.append(dict(r, live=_live(p, now), position=pos))
    if only_routes is None:  # unassigned test phones (management view only)
        for dev, p in latest.items():
            if dev not in assigned and dev == dev.lower() and now - p["ts"] < 86400:
                out.append({"id": f"dev-{dev}", "name": f"Unassigned phone {dev[-4:]}", "stops": [],
                            "device_id": dev, "live": _live(p, now), "position": _pos(p, now, dev)})
    return out


# ---------------------------------------------------------------- place names (free OpenStreetMap lookup)
GEO_URL = "https://nominatim.openstreetmap.org/reverse"
GEO_TTL = 30 * 86400   # a street keeps its name; cache per ~100 m square for 30 days


def _geo_key(lat, lon):
    return f"geo2:{round(lat, 4)}:{round(lon, 4)}"  # ~11 m squares


def _format_place(a: dict) -> str:
    road = a.get("road") or a.get("pedestrian") or a.get("residential")
    area = a.get("neighbourhood") or a.get("suburb") or a.get("quarter") or a.get("hamlet")
    town = a.get("village") or a.get("town") or a.get("city") or a.get("county")
    parts = []
    for x in (road, area, town):
        if x and x not in parts:
            parts.append(x)
    return ", ".join(parts[:3])


def place_name(lat: float, lon: float, lookup: bool = True) -> str | None:
    """'NCR Nagar Road, Vidyanagar, Kota' for a position. Cached; at most one new lookup per second
    (OpenStreetMap's rule). Returns None when not known yet - the next refresh fills it in."""
    if os.getenv("GEOCODE", "on").lower() in ("off", "0", "false"):
        return None
    key = _geo_key(lat, lon)
    hit = store.get(key)
    if hit is not None:
        return hit or None
    if not lookup or store.get("geo:busy"):
        return None
    store.set("geo:busy", 1, ttl=2)
    import urllib.parse
    import urllib.request
    q = urllib.parse.urlencode({"format": "jsonv2", "lat": lat, "lon": lon, "zoom": 18,
                                "addressdetails": 1, "accept-language": "en"})
    try:
        req = urllib.request.Request(f"{GEO_URL}?{q}", headers={
            "User-Agent": "SPV-School-Portal/1.0 (https://spvn.vercel.app; school van tracking)"})
        with urllib.request.urlopen(req, timeout=4) as r:
            name = _format_place(json.loads(r.read()).get("address") or {})
        store.set(key, name, ttl=GEO_TTL)
        return name or None
    except Exception as e:
        print(f"[van] place lookup failed: {type(e).__name__}")
        store.set(key, "", ttl=600)  # try again in 10 minutes
        return None


def _km(a, b):
    from math import asin, cos, radians, sin, sqrt
    la1, lo1, la2, lo2 = map(radians, (a["lat"], a["lon"], b["lat"], b["lon"]))
    return 2 * 6371 * asin(sqrt(sin((la2 - la1) / 2) ** 2 + cos(la1) * cos(la2) * sin((lo2 - lo1) / 2) ** 2))


def nearest_stop(pos: dict, stops: list[dict]) -> dict | None:
    best = min(((_km(pos, x), x) for x in stops or [] if x.get("lat") is not None), default=None, key=lambda t: t[0])
    if not best or best[0] > 2:
        return None
    return {"name": best[1]["name"], "m": int(best[0] * 1000)}


def _live(p, now):
    return bool(p) and now - p["ts"] < STALE_AFTER


def _state(p, now) -> tuple[str, str]:
    age = now - p["ts"]
    mins = int(age // 60)
    when = "just now" if mins < 1 else f"{mins} min ago"
    if age < FRESH:
        return ("moving", f"Moving · {round(p['kmh'])} km/h") if (p.get("kmh") or 0) > 3 else ("stopped", "Stopped")
    if age < STALE_AFTER:
        return "idle", f"Parked or phone idle · last update {when}"
    return "offline", f"Offline · phone not sending since {when}" if mins < 600 else "Offline · phone not sending"


def _pos(p, now, dev):
    if not p:
        return None
    trail = store.get(f"van:trail:{dev}", []) or []
    state, text = _state(p, now)
    return {"lat": p["lat"], "lon": p["lon"], "kmh": p.get("kmh"), "battery": p.get("battery"),
            "age_s": int(now - p["ts"]), "trail": trail[:60], "state": state, "state_text": text,
            "acc": None if p.get("acc") is None else int(p["acc"]),
            "rough": (p.get("acc") or 0) > BAD_ACCURACY}


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
        state = p.get("state_text", "")
        when = "just now" if p["age_s"] < 60 else f"{p['age_s'] // 60} min ago"
        where = f" near {p['place']}" if p.get("place") else ""
        stop = f" ({p['near_stop']['m']} m from {p['near_stop']['name']} stop)" if p.get("near_stop") else ""
        out.append(f"{v['name']}: {state}{where}{stop}, last update {when}. "
                   f"Map: https://www.google.com/maps?q={p['lat']},{p['lon']}")
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
    if "notificationToken" in fields and "lat" not in fields:  # Traccar start-up message, no location yet
        import school
        note_attempt(school.devkey(dev_hint), True, "phone started - waiting for its first GPS location")
        return {"ok": True}
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
    if not store.get(f"van:fields:{p['id']}"):
        store.set(f"van:fields:{p['id']}", 1, ttl=3600)
        print(f"[van] {p['id']} sends: {sorted(set(fields) | set((body or {}).keys()))} acc={p.get('acc')}")
    res = save_point(p)  # unknown phones are kept as "Unassigned phone" until linked to a route
    link = "linked" if p["id"] in known else "not linked to a route yet"
    if res == "ok":
        note_attempt(p["id"], True, link)
    else:
        age_h = int((time.time() - p["ts"]) // 3600)
        note_attempt(p["id"], True, f"{link} - sending saved old locations ({age_h} h old), please wait")
        print(f"[van] {p['id']}: {res} ({age_h} h old)")
    return {"ok": True}
