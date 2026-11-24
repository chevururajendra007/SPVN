"""Security tests for storage: encryption at rest in the app, tamper detection, fail-closed on
Vercel without the database, and refusing unencrypted database connections."""
import base64
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "agent"))
KEY = base64.urlsafe_b64encode(bytes(range(32))).decode().rstrip("=")


@pytest.fixture
def store(tmp_path, monkeypatch):
    import store as st
    monkeypatch.setenv("SPV_STORE_FILE", str(tmp_path / "s.json"))
    monkeypatch.setenv("DATA_KEY", KEY)
    for k in ("DATABASE_URL", "POSTGRES_URL", "VERCEL"):
        if not (k == "DATABASE_URL" and os.getenv("SECURITY_PG")):
            monkeypatch.delenv(k, raising=False)
    if os.getenv("SECURITY_PG"):
        monkeypatch.setenv("DATABASE_URL", os.environ["SECURITY_PG"])
    st._aead, st._checked, st._pg = None, False, None
    yield st
    st._aead, st._checked, st._pg = None, False, None


def _raw(st, key):
    return st._raw_get(st.PREFIX + key)


def test_values_are_encrypted_at_rest(store):
    store.set("students", [{"name": "Test Child", "phone": "9876543210"}])
    raw = _raw(store, "students")
    assert raw["enc"] == 1 and "Test Child" not in json.dumps(raw) and "9876543210" not in json.dumps(raw)
    assert store.get("students")[0]["name"] == "Test Child"
    store.set_many({"a": 1, "b": {"x": "secret"}})
    assert "secret" not in json.dumps(_raw(store, "b")) and store.get_many(["a", "b"]) == {"a": 1, "b": {"x": "secret"}}


def test_ciphertext_cannot_be_moved_to_another_key(store):
    from cryptography.exceptions import InvalidTag
    store.set("x", "for x only")
    store._raw_set_many({store.PREFIX + "y": _raw(store, "x")})
    with pytest.raises(InvalidTag):
        store.get("y")


def test_wrong_key_cannot_read(store, monkeypatch):
    from cryptography.exceptions import InvalidTag
    store.set("x", "hello")
    monkeypatch.setenv("DATA_KEY", base64.urlsafe_b64encode(b"\x01" * 32).decode())
    store._aead = None
    with pytest.raises(InvalidTag):
        store.get("x")


def test_vercel_without_database_fails_closed(store, monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    store._checked = False
    with pytest.raises(store.StorageError):
        store.get("students")
    assert store.health()["ok"] is False


def test_unencrypted_remote_connection_refused(store):
    import urllib.parse
    with pytest.raises(store.StorageError):
        store._ssl_context(urllib.parse.urlparse("postgresql://u:p@db.example.com/x?sslmode=disable"))
    ctx = store._ssl_context(urllib.parse.urlparse("postgresql://u:p@ep-x.neon.tech/x?sslmode=require"))
    import ssl
    assert ctx.check_hostname and ctx.verify_mode == ssl.CERT_REQUIRED


@pytest.mark.skipif(not os.getenv("SECURITY_PG"), reason="set SECURITY_PG to a test Postgres URL")
def test_existing_plaintext_rows_get_encrypted(store, monkeypatch):
    monkeypatch.delenv("DATA_KEY")
    store._aead = None
    store.set("old", {"name": "Plain Row"})
    assert _raw(store, "old") == {"name": "Plain Row"}
    monkeypatch.setenv("DATA_KEY", KEY)
    store._aead, store._checked = None, False
    assert store.get("old") == {"name": "Plain Row"}  # ensure_ready() encrypted it on first use
    assert _raw(store, "old")["enc"] == 1
