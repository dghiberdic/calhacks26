"""Books errors. `code` matches the CONTRACTS §3 error envelope."""
from __future__ import annotations


class BooksError(Exception):
    code = "validation"

    def __init__(self, message: str, **detail):
        super().__init__(message)
        self.message = message
        self.detail = detail


class NotFound(BooksError, KeyError):
    code = "not_found"

    def __str__(self) -> str:  # KeyError would repr() the message
        return self.message


class Forbidden(BooksError, PermissionError):
    code = "forbidden"


class SoDViolation(Forbidden):
    """Preparer ≠ approver, JEs need the Controller, payouts need the Claims Lead (hard controls)."""

    code = "sod_violation"


class PeriodLocked(Forbidden):
    """Locked periods are never written."""

    code = "forbidden"
