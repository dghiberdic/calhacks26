"""Sessions: `POST /api/session` → an HMAC-signed principal; every request sends `Authorization: Bearer <token>`.

Uses `engine.acl.issue` / `session_or_judge` (the binding signer: `<b64url canonical Session>.<64-hex HMAC>`,
fail closed). A local signer of the same shape stands in when `engine.acl` is not importable. Missing, malformed,
forged or unknown-role tokens are the read-only `judge`.
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


def principal_for(role: Role, name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "anon"
    return role.value if role in AGENT_ROLES or role == Role.JUDGE else f"{role.value}:{slug}"


class Signer:
    def __init__(self, secret: str):
        self._secret = secret
        self._acl = _module("engine.acl")
        self.kind = "engine.acl" if self._acl is not None and hasattr(self._acl, "issue") else "local-hmac"

    # ---- local fallback (same shape) ----
    def _mac(self, payload: str) -> str:
        return hmac.new(self._secret.encode(), payload.encode(), hashlib.sha256).hexdigest()

    def issue(self, role: Role, name: str, at: datetime) -> tuple[str, Session]:
        name = name.strip()[:80] or "anon"
        if self.kind == "engine.acl":
            token = self._acl.issue(role, name, self._secret, at=at)
            return token, self._acl.verify(token, self._secret)
        s = Session(principal=principal_for(role, name), role=role, name=name, issued_at=at)
        payload = base64.urlsafe_b64encode(s.model_dump_json().encode()).decode().rstrip("=")
        return f"{payload}.{self._mac(payload)}", s

    def session_of(self, authorization: str | None, now: datetime) -> Session:
        token = None
        if authorization and authorization.lower().startswith("bearer "):
            token = authorization.split(" ", 1)[1].strip()
        if self.kind == "engine.acl":
            return self._acl.session_or_judge(token, self._secret, at=now)
        judge = Session(principal="judge", role=Role.JUDGE, name="Judge", issued_at=now)
        if not token:
            return judge
        try:
            payload, sig = token.rsplit(".", 1)
            if not hmac.compare_digest(sig, self._mac(payload)):
                return judge
            return Session.model_validate_json(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        except Exception:
            return judge
