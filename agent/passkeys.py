"""Passkeys (WebAuthn) for the admin: fingerprint / face / Windows Hello on the approved office device.

The private key stays inside the device's security chip (TPM / secure enclave), so the admin login
cannot be copied to another phone or computer. Flow:
  1. admin logs in with OTP on the office device -> principal approves the device (auth.office_check)
  2. first time: "Set up fingerprint / Windows Hello" creates a passkey for this admin + device
  3. every working day: "Unlock" with fingerprint/Windows Hello -> admin works for UNLOCK_HOURS
The principal removing the device also deletes its passkeys.
Switch off with ADMIN_PASSKEY=false (Vercel) - then only the approved device check applies.
"""
import base64
import json
import os
import time

import store

UNLOCK_HOURS = int(os.getenv("ADMIN_UNLOCK_HOURS", "12"))
RP_NAME = "SPV School Portal"


def enabled() -> bool:
    return os.getenv("ADMIN_PASSKEY", "true").lower() not in ("0", "false", "no")


def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64u(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _rp(req: dict) -> tuple[str, str]:
    """(rp_id, expected origin) from settings or the request's host."""
    host = (os.getenv("RP_ID") or req.get("host", "")).split(":")[0]
    origin = os.getenv("RP_ORIGIN") or f"{req.get('proto', 'https')}://{req.get('host', host)}"
    return host, origin


def creds(phone: str, devref: str) -> list[dict]:
    return [c for c in (store.get("passkeys", []) or []) if c["phone"] == phone and c["dev"] == devref]


def require(phone: str, devref: str):
    """Raise unless this admin has a passkey on this device and unlocked it recently."""
    from auth import AuthError
    if not enabled():
        return
    if not creds(phone, devref):
        raise AuthError("[passkey-setup] One more step: set up fingerprint / Windows Hello for admin work "
                        "on this office device.", 403)
    if not store.get(f"pkunlock:{devref}"):
        raise AuthError("[passkey-unlock] Unlock admin work with your fingerprint / Windows Hello.", 403)


def register_options(phone: str, devref: str, name: str, req: dict) -> dict:
    from webauthn import generate_registration_options, options_to_json
    from webauthn.helpers.structs import (AuthenticatorAttachment, AuthenticatorSelectionCriteria,
                                          PublicKeyCredentialDescriptor, ResidentKeyRequirement,
                                          UserVerificationRequirement)
    rp_id, _ = _rp(req)
    opts = generate_registration_options(
        rp_id=rp_id, rp_name=RP_NAME, user_id=f"{phone}:{devref}".encode(), user_name=f"{name} ({phone})",
        user_display_name=f"{name} - SPV admin",
        exclude_credentials=[PublicKeyCredentialDescriptor(id=_unb64u(c["id"])) for c in creds(phone, devref)],
        authenticator_selection=AuthenticatorSelectionCriteria(
            authenticator_attachment=AuthenticatorAttachment.PLATFORM,       # this device's own sensor
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.REQUIRED))        # fingerprint / face / PIN
    store.set(f"pkchal:{devref}", _b64u(opts.challenge), ttl=300)
    return json.loads(options_to_json(opts))


def register_verify(phone: str, devref: str, credential: dict, req: dict) -> dict:
    from webauthn import verify_registration_response
    from auth import AuthError, audit
    chal = store.get(f"pkchal:{devref}")
    if not chal:
        raise AuthError("Setup timed out. Please try again.", 400)
    rp_id, origin = _rp(req)
    try:
        v = verify_registration_response(credential=credential, expected_challenge=_unb64u(chal),
                                         expected_rp_id=rp_id, expected_origin=origin, require_user_verification=True)
    except Exception as e:
        raise AuthError(f"Could not set up the passkey ({type(e).__name__}). Please try again.", 400)
    store.delete(f"pkchal:{devref}")
    items = store.get("passkeys", []) or []
    items.append({"id": _b64u(v.credential_id), "pk": _b64u(v.credential_public_key), "count": v.sign_count,
                  "phone": phone, "dev": devref, "at": int(time.time())})
    store.set("passkeys", items)
    store.set(f"pkunlock:{devref}", int(time.time()), ttl=UNLOCK_HOURS * 3600)
    audit(phone, "passkey_registered", {"device": devref})
    return {"ok": True, "unlocked_hours": UNLOCK_HOURS}


def auth_options(phone: str, devref: str, req: dict) -> dict:
    from webauthn import generate_authentication_options, options_to_json
    from webauthn.helpers.structs import PublicKeyCredentialDescriptor, UserVerificationRequirement
    rp_id, _ = _rp(req)
    opts = generate_authentication_options(
        rp_id=rp_id, allow_credentials=[PublicKeyCredentialDescriptor(id=_unb64u(c["id"])) for c in creds(phone, devref)],
        user_verification=UserVerificationRequirement.REQUIRED)
    store.set(f"pkchal:{devref}", _b64u(opts.challenge), ttl=300)
    return json.loads(options_to_json(opts))


def auth_verify(phone: str, devref: str, credential: dict, req: dict) -> dict:
    from webauthn import verify_authentication_response
    from auth import AuthError, audit
    chal = store.get(f"pkchal:{devref}")
    mine = {c["id"]: c for c in creds(phone, devref)}
    c = mine.get(credential.get("id", ""))
    if not chal or not c:
        raise AuthError("Unlock failed. Please try again.", 400)
    rp_id, origin = _rp(req)
    try:
        v = verify_authentication_response(credential=credential, expected_challenge=_unb64u(chal),
                                           expected_rp_id=rp_id, expected_origin=origin,
                                           credential_public_key=_unb64u(c["pk"]), credential_current_sign_count=c["count"],
                                           require_user_verification=True)
    except Exception as e:
        raise AuthError(f"Unlock failed ({type(e).__name__}). Please try again.", 400)
    store.delete(f"pkchal:{devref}")
    items = store.get("passkeys", []) or []
    for x in items:
        if x["id"] == c["id"]:
            x["count"] = v.new_sign_count
    store.set("passkeys", items)
    store.set(f"pkunlock:{devref}", int(time.time()), ttl=UNLOCK_HOURS * 3600)
    audit(phone, "admin_unlocked", {"device": devref})
    return {"ok": True, "unlocked_hours": UNLOCK_HOURS}


def remove_for_device(devref: str):
    store.set("passkeys", [c for c in (store.get("passkeys", []) or []) if c["dev"] != devref])
    store.delete(f"pkunlock:{devref}")
