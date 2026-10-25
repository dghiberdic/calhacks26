"""WorldError: the one error type `world/` raises for bad desk input.

David's server maps it to a 422 `{"error": {"code", "message"}}` (CONTRACTS §3), so `message` must be plain
English a judge can read.
"""
from __future__ import annotations

from typing import Literal

WorldErrorCode = Literal["no_metar", "future_date", "unknown_airport"]
CODES: tuple[str, ...] = ("no_metar", "future_date", "unknown_airport")


class WorldError(Exception):
    def __init__(self, code: WorldErrorCode, message: str) -> None:
        if code not in CODES:
            raise ValueError(f"unknown WorldError code {code!r}")
        super().__init__(f"{code}: {message}")
        self.code: WorldErrorCode = code
        self.message = message
