"""School van GPS: receives locations from the Traccar Client phone app and serves them to the SPV App.

Traccar Client  ->  POST https://<site>/api/van/loc/<VAN_KEY>   (OsmAnd format: query, form or JSON)
SPV App map     ->  GET  https://<site>/api/van/latest

Settings (Vercel -> Project -> Settings -> Environment Variables):
  VAN_KEY        secret part of the URL the phone sends to (required; anything else is rejected)
  VAN_DEVICES    optional names, e.g. "12345678=Van 1 Kota-Vidyanagar,87654321=Van 2 Gudur road"
  KV_REST_API_URL / KV_REST_API_TOKEN  (or UPSTASH_REDIS_REST_URL / _TOKEN): Upstash Redis from the
                 Vercel Marketplace, so positions survive between serverless calls. Without it they are
                 kept in memory only (fine on a laptop, unreliable on Vercel).
"""
import hmac
import json
import os
import time
import urllib.request
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/van")
TRAIL = 200            # points of route history kept per van
STALE_AFTER = 10 * 60  # seconds: older than this = "not moving / offline"

_mem: dict[str, dict] = {}
_trail: dict[str, list] = {}


# ---------------------------------------------------------------- storage (Upstash Redis REST, else memory)
def _kv(*cmd):
    url = os.getenv("KV_REST_API_URL") or os.getenv("UPSTASH_REDIS_REST_URL")
    tok = os.getenv("KV_REST_API_TOKEN") or os.getenv("UPSTASH_REDIS_REST_TOKEN")
    if not (url and tok):
        return None
    req = urllib.request.Request(url, data=json.dumps(cmd).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())["result"]


def storage() -> str:
    return "redis" if (os.getenv("KV_REST_API_URL") or os.getenv("UPSTASH_REDIS_REST_URL")) else "memory"


def _save(p: dict):
    if storage() == "redis":
        _kv("HSET", "spv:vans", p["id"], json.dumps(p))
        _kv("LPUSH", f"spv:trail:{p['id']}", json.dumps([p["lat"], p["lon"], p["ts"]]))
        _kv("LTRIM", f"spv:trail:{p['id']}", 0, TRAIL - 1)
    else:
        _mem[p["id"]] = p
        _trail.setdefault(p["id"], []).insert(0, [p["lat"], p["lon"], p["ts"]])
        del _trail[p["id"]][TRAIL:]


def _load() -> list[dict]:
    if storage() == "redis":
        raw = _kv("HGETALL", "spv:vans") or []
        vans = [json.loads(v) for v in raw[1::2]]
        for v in vans:
            v["trail"] = [json.loads(t) for t in (_kv("LRANGE", f"spv:trail:{v['id']}", 0, 60) or [])]
    else:
        vans = [dict(v, trail=_trail.get(k, [])[:60]) for k, v in _mem.items()]
    return vans


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
    """Accepts OsmAnd query/form fields (id, lat, lon, timestamp, speed, bearing, batt)
    or the JSON body of the newer client ({device_id, location: {timestamp, coords, battery}})."""
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
    batt = f.get("batt") or (loc.get("battery") or {}).get("level")
    batt = _num(batt)
    if batt is not None and batt <= 1:
        batt *= 100
    return {
        "id": str(dev)[:40], "lat": round(lat, 6), "lon": round(lon, 6),
        "ts": _ts(f.get("timestamp") or loc.get("timestamp")),
        "kmh": kmh, "heading": _num(f.get("bearing") or coords.get("heading")),
        "battery": None if batt is None else round(batt),
        "received": time.time(),
    }


def _names() -> dict:
    out = {}
    for part in os.getenv("VAN_DEVICES", "").split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


# ---------------------------------------------------------------- routes
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
        ctype = request.headers.get("content-type", "")
        try:
            if "json" in ctype or raw.lstrip()[:1] in (b"{", b"["):
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
    names = _names()
    if names and p["id"] not in names:
        raise HTTPException(403, "unknown device id")
    _save(p)
    return {"ok": True}


@router.get("/latest")
def latest():
    names, now = _names(), time.time()
    vans = []
    for v in _load():
        age = now - v["ts"]
        vans.append(dict(v, name=names.get(v["id"], f"Van {v['id'][-4:]}"),
                         age_s=int(age), live=age < STALE_AFTER))
    vans.sort(key=lambda v: v["name"])
    return {"vans": vans, "storage": storage(), "configured": bool(os.getenv("VAN_KEY"))}


def van_status() -> str:
    """Where is the school van now? Latest GPS position, speed and time of each van."""
    data = latest()["vans"]
    if not data:
        return "No van location received yet. The van's GPS app may be switched off."
    out = []
    for v in data:
        mins = v["age_s"] // 60
        when = "just now" if mins < 1 else f"{mins} min ago"
        if not v["live"]:
            state = "offline (GPS not sending)"
        elif (v.get("kmh") or 0) > 3:
            state = f"moving at {v['kmh']:.0f} km/h"
        else:
            state = "stopped"
        out.append(f"{v['name']}: {state}, last update {when}. "
                   f"Map: https://www.google.com/maps?q={v['lat']},{v['lon']}")
    return "\n".join(out) + "\nOpen the Van tab in the SPV App for the live map."
