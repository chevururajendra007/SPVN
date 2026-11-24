"""Storage for the SPV portal: a small key -> JSON document API on the Vercel (Neon) Postgres database.

Security (see docs/SECURITY.md):
  * Production uses ONLY the Vercel Neon Postgres database (DATABASE_URL, added by the Vercel Neon
    integration). If it is missing on Vercel the app refuses to start ("fail closed"); it never falls
    back to a temporary or local file.
  * Every connection is TLS with certificate AND hostname verification. A non-local database URL with
    sslmode=disable is rejected.
  * Every stored value is encrypted in the app with AES-256-GCM before it reaches the database
    (DATA_KEY, a Vercel environment secret). Someone with database access but without the Vercel key
    sees only ciphertext. The key name is bound to each value so ciphertexts cannot be swapped.
  * Database credentials and DATA_KEY live only in Vercel environment variables, never in code.
  * A local JSON file is allowed only for development and tests on a laptop (never on Vercel).

Keys (prefixed "spv:"): students, staff_roles, routes, circulars, updates, outbox, audit, meta,
  att:<date>:<class>, hw:<class>, feerem:<student id>, otp:<phone>, van:latest, van:trail:<device>
"""
import base64
import json
import os
import secrets
import ssl
import threading
import time
import urllib.parse
from pathlib import Path

PREFIX = "spv:"
_lock = threading.Lock()


class StorageError(RuntimeError):
    pass


def _pg_url() -> str:
    return (os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL") or "").strip()


def on_vercel() -> bool:
    return bool(os.getenv("VERCEL"))


def backend() -> str:
    if _pg_url():
        return "postgres"
    if on_vercel():
        raise StorageError("Database not configured: connect the Vercel Neon database (DATABASE_URL).")
    return "file"


def durable() -> bool:
    return backend() == "postgres" or not on_vercel()


# ---------------------------------------------------------------- encryption (AES-256-GCM)
_aead = None


def _key_bytes():
    raw = os.getenv("DATA_KEY", "").strip()
    if not raw:
        return None
    key = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    if len(key) != 32:
        raise StorageError("DATA_KEY must be 32 bytes, base64 encoded")
    return key


def encryption_on() -> bool:
    return _key_bytes() is not None


def _cipher():
    global _aead
    if _aead is None:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        _aead = AESGCM(_key_bytes())
    return _aead


def _seal(key: str, value):
    """Encrypt one value. The storage key is authenticated data, so a value cannot be moved to another key."""
    if not encryption_on():
        return value
    nonce = secrets.token_bytes(12)
    ct = _cipher().encrypt(nonce, json.dumps(value, ensure_ascii=False).encode(), key.encode())
    return {"enc": 1, "d": base64.b64encode(nonce + ct).decode()}


def _open(key: str, stored):
    if isinstance(stored, dict) and stored.get("enc") == 1 and "d" in stored:
        if not encryption_on():
            raise StorageError("Data is encrypted but DATA_KEY is not set")
        blob = base64.b64decode(stored["d"])
        return json.loads(_cipher().decrypt(blob[:12], blob[12:], key.encode()))
    return stored  # older plaintext row (encrypted on the next write, or by encrypt_existing())


def _unwrap(val):
    if isinstance(val, dict) and "__exp" in val:
        return None if val["__exp"] < time.time() else val["v"]
    return val


# ---------------------------------------------------------------- Postgres (pg8000, pure Python)
_pg = None


def _ssl_context(url: urllib.parse.ParseResult):
    q = urllib.parse.parse_qs(url.query)
    local = url.hostname in ("localhost", "127.0.0.1", "::1")
    if q.get("sslmode") == ["disable"]:
        if local:
            return None  # laptop / test database only
        raise StorageError("Refusing an unencrypted database connection (sslmode=disable)")
    ctx = ssl.create_default_context()          # verifies the server certificate ...
    ctx.check_hostname = True                    # ... and that it belongs to this host
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return None if local and not q.get("sslmode") else ctx


def _pg_conn():
    global _pg
    if _pg is None:
        import pg8000.native
        u = urllib.parse.urlparse(_pg_url())
        _pg = pg8000.native.Connection(
            user=urllib.parse.unquote(u.username or ""), password=urllib.parse.unquote(u.password or ""),
            host=u.hostname, port=u.port or 5432, database=(u.path or "/postgres")[1:],
            ssl_context=_ssl_context(u), timeout=15, application_name="spv-portal")
        _pg.run("""CREATE TABLE IF NOT EXISTS spv_kv (
                     k TEXT PRIMARY KEY, v JSONB NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
    return _pg


def _pg_run(sql, **params):
    global _pg
    for attempt in (1, 2):  # reconnect once if Neon closed an idle connection
        try:
            return _pg_conn().run(sql, **params)
        except StorageError:
            raise
        except Exception:
            _pg = None
            if attempt == 2:
                raise


def tls_status() -> dict:
    """What the live connection is actually using (for the admin status card)."""
    if backend() != "postgres":
        return {"tls": False}
    rows = _pg_run("SELECT ssl, version FROM pg_stat_ssl WHERE pid = pg_backend_pid()")
    return {"tls": bool(rows and rows[0][0]), "version": rows[0][1] if rows else None}


# ---------------------------------------------------------------- local file (development only)
def _file() -> Path:
    return Path(os.getenv("SPV_STORE_FILE", Path(__file__).parent / "spv_store.json"))


def _fload() -> dict:
    f = _file()
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def _fsave(d: dict):
    f = _file()
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    tmp.replace(f)


# ---------------------------------------------------------------- raw read/write (stored form)
def _raw_get(k):
    if backend() == "postgres":
        rows = _pg_run("SELECT v FROM spv_kv WHERE k = :k", k=k)
        return rows[0][0] if rows else None  # pg8000 already decodes JSONB
    with _lock:
        return _fload().get(k)


def _raw_set_many(items: dict):
    if backend() == "postgres":
        _pg_run("""INSERT INTO spv_kv (k, v, updated_at)
                   SELECT k, CAST(v AS JSONB), now() FROM unnest(CAST(:ks AS TEXT[]), CAST(:vs AS TEXT[])) AS t(k, v)
                   ON CONFLICT (k) DO UPDATE SET v = EXCLUDED.v, updated_at = now()""",
                ks=list(items), vs=[json.dumps(v, ensure_ascii=False) for v in items.values()])
    else:
        with _lock:
            d = _fload()
            d.update(items)
            _fsave(d)


# ---------------------------------------------------------------- public API
def get(key: str, default=None):
    ensure_ready()
    k = PREFIX + key
    raw = _raw_get(k)
    val = None if raw is None else _unwrap(_open(k, raw))
    return default if val is None else val


def get_many(keys: list[str]) -> dict:
    """Fetch many keys in one round trip. Returns {key: value} for keys that exist."""
    ensure_ready()
    if not keys:
        return {}
    full = [PREFIX + k for k in keys]
    if backend() == "postgres":
        rows = dict(_pg_run("SELECT k, v FROM spv_kv WHERE k = ANY(:ks)", ks=full))
    else:
        with _lock:
            d = _fload()
        rows = {k: d[k] for k in full if k in d}
    out = {}
    for k, raw in rows.items():
        val = _unwrap(_open(k, raw))
        if val is not None:
            out[k[len(PREFIX):]] = val
    return out


def set(key: str, value, ttl: int | None = None):  # noqa: A001 - mirrors Redis naming
    ensure_ready()
    k = PREFIX + key
    val = {"__exp": time.time() + ttl, "v": value} if ttl else value
    _raw_set_many({k: _seal(k, val)})


def set_many(items: dict):
    """Write many keys in one round trip (used when loading data)."""
    ensure_ready()
    if items:
        _raw_set_many({PREFIX + k: _seal(PREFIX + k, v) for k, v in items.items()})


def delete(key: str):
    ensure_ready()
    k = PREFIX + key
    if backend() == "postgres":
        _pg_run("DELETE FROM spv_kv WHERE k = :k", k=k)
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


def encrypt_existing() -> int:
    """Encrypt any rows still stored as plain JSON (e.g. written before DATA_KEY was set)."""
    if not encryption_on() or backend() != "postgres":
        return 0
    rows = _pg_run("SELECT k, v FROM spv_kv WHERE k LIKE 'spv:%' AND NOT (v ? 'enc')")
    if rows:
        _raw_set_many({k: _seal(k, v) for k, v in rows})
    return len(rows)


_checked = False


def ensure_ready():
    """Called once per server start: fail closed without the database, encrypt old plaintext rows."""
    global _checked
    if _checked:
        return
    backend()  # raises on Vercel without DATABASE_URL
    _checked = True
    if backend() == "postgres":
        encrypt_existing()


def health() -> dict:
    try:
        b = backend()
        get("meta")  # an encrypted record: proves the database is reachable AND DATA_KEY decrypts it
        return {"backend": b, "ok": True, "durable": durable(), "encrypted": encryption_on()}
    except Exception as e:  # surfaced on the admin status card
        return {"backend": "none", "ok": False, "error": type(e).__name__, "durable": False,
                "encrypted": encryption_on() if not isinstance(e, StorageError) else False}
