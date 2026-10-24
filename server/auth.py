"""Sessions: `POST /api/session` → an HMAC-signed principal; every request sends `Authorization: Bearer <token>`.

Fail closed: a missing, malformed, forged or unknown-role token is the read-only `judge`. Uses `engine.acl`'s signer
when it exposes one (`sign_session` / `verify_session`), else this local signer (same token shape as the stub:
`<urlsafe b64 Session JSON>.<hex hmac-sha256>`).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
from datetime import datetime

from contracts.models import Role, Session

from .impls import _module

AGENT_ROLES = {Role.READER, Role.DRAFTER, Role.ENGINE, Role.CRM_BOT}
HUMAN_APPROVERS = {Role.CONTROLLER, Role.CFO, Role.CLAIMS_LEAD}


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def principal_for(role: Role, name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "anon"
    return role.value if role in AGENT_ROLES or role == Role.JUDGE else f"{role.value}:{slug}"


class Signer:
    def __init__(self, secret: str):
        self._key = secret.encode()
        acl = _module("engine.acl")
        self._ext_sign = getattr(acl, "sign_session", None) if acl else None
        self._ext_verify = getattr(acl, "verify_session", None) if acl else None
        self.kind = "engine.acl" if self._ext_sign and self._ext_verify else "local-hmac"

    def _mac(self, payload: str) -> str:
        return hmac.new(self._key, payload.encode(), hashlib.sha256).hexdigest()

    def issue(self, role: Role, name: str, at: datetime) -> tuple[str, Session]:
        s = Session(principal=principal_for(role, name), role=role, name=name.strip()[:80] or "anon", issued_at=at)
        if self.kind == "engine.acl":
            try:
                return str(self._ext_sign(s, self._key)), s
            except Exception:
                pass
        payload = _b64(s.model_dump_json().encode())
        return f"{payload}.{self._mac(payload)}", s

    def verify(self, token: str) -> Session | None:
        if self.kind == "engine.acl":
            try:
                out = self._ext_verify(token, self._key)
                if isinstance(out, Session):
                    return out
            except Exception:
                pass
        try:
            payload, sig = token.rsplit(".", 1)
            if not hmac.compare_digest(sig, self._mac(payload)):
                return None
            return Session.model_validate_json(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        except Exception:
            return None

    def session_of(self, authorization: str | None, now: datetime) -> Session:
        judge = Session(principal="judge", role=Role.JUDGE, name="Judge", issued_at=now)
        if not authorization or not authorization.lower().startswith("bearer "):
            return judge
        return self.verify(authorization.split(" ", 1)[1].strip()) or judge
