from __future__ import annotations

import pytest


@pytest.fixture(scope="session")
def full_world():
    """The whole generated Northstar world (seed 0, golden embedded when it exists). ~15 s, built once."""
    from world.generator import generate_world

    return generate_world(0)
