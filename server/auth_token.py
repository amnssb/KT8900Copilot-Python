import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any, Dict, Optional


DEFAULT_INSECURE_SECRET = "change-me-ws-auth-secret"


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    pad = "=" * ((4 - len(data) % 4) % 4)
    return base64.urlsafe_b64decode((data + pad).encode("ascii"))


def get_token_secret() -> str:
    return os.getenv("WS_AUTH_SECRET", DEFAULT_INSECURE_SECRET)


def create_ws_token(claims: Dict[str, Any], ttl_seconds: int = 120) -> str:
    now = int(time.time())
    payload: Dict[str, Any] = dict(claims)
    payload["iat"] = now
    payload["exp"] = now + ttl_seconds

    payload_raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    payload_part = _b64url_encode(payload_raw)

    sig = hmac.new(get_token_secret().encode("utf-8"), payload_part.encode("ascii"), hashlib.sha256).digest()
    sig_part = _b64url_encode(sig)
    return payload_part + "." + sig_part


def verify_ws_token(token: str) -> Optional[Dict[str, Any]]:
    try:
        payload_part, sig_part = token.split(".", 1)
    except ValueError:
        return None

    expected_sig = hmac.new(
        get_token_secret().encode("utf-8"),
        payload_part.encode("ascii"),
        hashlib.sha256,
    ).digest()

    actual_sig = _b64url_decode(sig_part)
    if not hmac.compare_digest(expected_sig, actual_sig):
        return None

    try:
        payload = json.loads(_b64url_decode(payload_part).decode("utf-8"))
    except Exception:
        return None

    now = int(time.time())
    exp = payload.get("exp")
    if not isinstance(exp, int) or exp <= now:
        return None

    return payload
