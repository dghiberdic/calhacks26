from __future__ import annotations

import pytest

from books import Books

from .helpers import FixedClock, ts


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(ts("2025-01-25T07:00:00Z"))


@pytest.fixture
def books(clock: FixedClock) -> Books:
    return Books(":memory:", clock)
