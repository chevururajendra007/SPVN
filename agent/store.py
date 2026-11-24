"""Storage for the SPV portal: one small key -> JSON document API over three backends.

Priority (first one configured wins):
  1. Postgres  - DATABASE_URL / POSTGRES_URL (Neon via Vercel Storage). Durable. Use this in production.
  2. Redis     - KV_REST_API_URL + KV_REST_API_TOKEN (Upstash via Vercel Storage). Durable.
  3. JSON file - local development only. On Vercel it lives in /tmp and is NOT durable.

Keys used (all prefixed with "spv:" so a shared database is safe):
  students, staff_roles, routes, circulars, updates, outbox, audit
  att:<YYYY-MM-DD>:<class>      attendance sheet for one class and day
  hw:<class>                    homework posts for one class
  feerem:<student id>           last fee reminder date
  otp:<phone>                   hashed OTP (short-lived)
  van:latest, van:trail:<device>  GPS
"""
import json
import os
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

PREFIX = "spv:"
_lock = threading.Lock()


def _pg_url():
    return (os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL") or "").strip()


def _redis():
    url = os.getenv("KV_REST_API_URL") or os.getenv("UPSTASH_REDIS_REST_URL")
    tok = os.getenv("KV_REST_API_TOKEN") or os.getenv("UPSTASH_REDIS_REST_TOKEN")
    return (url, tok) if url and tok else None


def backend() -> str:
    if _pg_url():
        return "postgres"
    if _redis():
        return "redis"
    return "file"


def durable() -> bool:
    return backend() != "file" or not os.getenv("VERCEL")


# ---------------------------------------------------------------- Postgres (pg8000, pure Python)
_pg = None


def _pg_conn():
    global _pg
    if _pg is None:
        import ssl

        import pg8000.native
        u = urllib.parse.urlparse(_pg_url())
        q = urllib.parse.parse_qs(u.query)
        local = u.hostname in ("localhost", "127.0.0.1")
        ssl_ctx = None if local or q.get("sslmode") == ["disable"] else ssl.create_default_context()
        _pg = pg8000.native.Connection(
            user=urllib.parse.unquote(u.username or ""), password=urllib.parse.unquote(u.password or ""),
            host=u.hostname, port=u.port or 5432, database=(u.path or "/postgres")[1:], ssl_context=ssl_ctx,
            timeout=15)
        _pg.run("""CREATE TABLE IF NOT EXISTS spv_kv (
                     k TEXT PRIMARY KEY, v JSONB NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
    return _pg


def _pg_run(sql, **params):
    global _pg
    for attempt in (1, 2):  # reconnect once if Neon closed an idle connection
        try:
            return _pg_conn().run(sql, **params)
        except Exception:
            _pg = None
            if attempt == 2:
                raise


# ---------------------------------------------------------------- Redis REST
def _r(*cmd):
    url, tok = _redis()
    req = urllib.request.Request(url, data=json.dumps(cmd).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.loads(r.read())["result"]


# ---------------------------------------------------------------- file
def _file() -> Path:
    if os.getenv("VERCEL"):
        return Path("/tmp/spv_store.json")
    return Path(os.getenv("SPV_STORE_FILE", Path(__file__).parent / "spv_store.json"))


def _fload() -> dict:
    f = _file()
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def _fsave(d: dict):
    f = _file()
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    tmp.replace(f)


# ---------------------------------------------------------------- public API
def get(key: str, default=None):
    k = PREFIX + key
    b = backend()
    if b == "postgres":
        rows = _pg_run("SELECT v FROM spv_kv WHERE k = :k", k=k)
        val = rows[0][0] if rows else None  # pg8000 already decodes JSONB
    elif b == "redis":
        raw = _r("GET", k)
        val = json.loads(raw) if raw else None
    else:
        with _lock:
            val = _fload().get(k)
    if val is None:
        return default
    if isinstance(val, dict) and "__exp" in val:
        if val["__exp"] < time.time():
            return default
        return val["v"]
    return val


def get_many(keys: list[str]) -> dict:
    """Fetch many keys in one round trip. Returns {key: value} for keys that exist."""
    if not keys:
        return {}
    b = backend()
    full = [PREFIX + k for k in keys]
    out = {}
    if b == "postgres":
        for k, v in _pg_run("SELECT k, v FROM spv_kv WHERE k = ANY(:ks)", ks=full):
            out[k[len(PREFIX):]] = v  # pg8000 already decodes JSONB
    elif b == "redis":
        for k, raw in zip(keys, _r("MGET", *full)):
            if raw:
                out[k] = json.loads(raw)
    else:
        with _lock:
            d = _fload()
        out = {k: d[PREFIX + k] for k in keys if PREFIX + k in d}
    return {k: (v["v"] if isinstance(v, dict) and "__exp" in v else v) for k, v in out.items()
            if not (isinstance(v, dict) and "__exp" in v and v["__exp"] < time.time())}


def set(key: str, value, ttl: int | None = None):  # noqa: A001 - mirrors Redis naming
    k = PREFIX + key
    val = {"__exp": time.time() + ttl, "v": value} if ttl else value
    b = backend()
    if b == "postgres":
        _pg_run("""INSERT INTO spv_kv (k, v, updated_at) VALUES (:k, CAST(:v AS JSONB), now())
                   ON CONFLICT (k) DO UPDATE SET v = EXCLUDED.v, updated_at = now()""",
                k=k, v=json.dumps(val, ensure_ascii=False))
    elif b == "redis":
        _r("SET", k, json.dumps(val, ensure_ascii=False), *(["EX", ttl] if ttl else []))
    else:
        with _lock:
            d = _fload()
            d[k] = val
            _fsave(d)


def set_many(items: dict):
    """Write many keys in one round trip (used when loading data)."""
    if not items:
        return
    b = backend()
    if b == "postgres":
        keys = [PREFIX + k for k in items]
        vals = [json.dumps(v, ensure_ascii=False) for v in items.values()]
        _pg_run("""INSERT INTO spv_kv (k, v, updated_at)
                   SELECT k, CAST(v AS JSONB), now() FROM unnest(CAST(:ks AS TEXT[]), CAST(:vs AS TEXT[])) AS t(k, v)
                   ON CONFLICT (k) DO UPDATE SET v = EXCLUDED.v, updated_at = now()""", ks=keys, vs=vals)
    elif b == "redis":
        flat = []
        for k, v in items.items():
            flat += [PREFIX + k, json.dumps(v, ensure_ascii=False)]
        _r("MSET", *flat)
    else:
        with _lock:
            d = _fload()
            d.update({PREFIX + k: v for k, v in items.items()})
            _fsave(d)


def delete(key: str):
    k = PREFIX + key
    b = backend()
    if b == "postgres":
        _pg_run("DELETE FROM spv_kv WHERE k = :k", k=k)
    elif b == "redis":
        _r("DEL", k)
    else:
        with _lock:
            d = _fload()
            d.pop(k, None)
            _fsave(d)


def push(key: str, item, cap: int = 500):
    """Prepend to a list document, keeping the newest `cap` items."""
    items = get(key, []) or []
    items.insert(0, item)
    set(key, items[:cap])
    return item


def health() -> dict:
    try:
        get("health-check")
        return {"backend": backend(), "ok": True, "durable": durable()}
    except Exception as e:  # pragma: no cover - surfaced on the status page
        return {"backend": backend(), "ok": False, "error": type(e).__name__, "durable": durable()}
