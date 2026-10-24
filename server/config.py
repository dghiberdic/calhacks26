"""Server settings, read from the environment once per app (tests build their own `Settings`)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GOLDEN_WORLD = ROOT / "contracts" / "fixtures" / "golden" / "world.json"
WEB_DIST = ROOT / "web" / "dist"
DEFAULT_DB = ROOT / "data" / "stormcheck.db"
MODES = ("live", "cache", "offline")
IMPL_KEYS = ("engine", "books", "reader", "drafter", "world")
DEV_SECRET = "stormcheck-dev-secret-not-for-production"


def _impl(key: str) -> str:
    v = os.environ.get(f"{key.upper()}_IMPL", "real").strip().lower()
    return v if v in ("fake", "real") else "real"


@dataclass(frozen=True)
class Settings:
    db_path: Path = DEFAULT_DB
    baseline_path: Path | None = None           # default: <db dir>/baseline.db
    world_path: Path = GOLDEN_WORLD
    web_dist: Path = WEB_DIST
    mode: str = "cache"
    impl: dict[str, str] = field(default_factory=lambda: {k: "real" for k in IMPL_KEYS})
    secret: str = DEV_SECRET
    reader_timeout_s: float = 8.0
    heartbeat_s: float = 15.0
    sse_poll_s: float = 0.5

    @property
    def baseline(self) -> Path:
        return self.baseline_path or self.db_path.with_name("baseline.db")

    @classmethod
    def from_env(cls) -> "Settings":
        mode = os.environ.get("STORMCHECK_MODE", "cache").strip().lower()
        base = os.environ.get("STORMCHECK_BASELINE")
        return cls(
            db_path=Path(os.environ.get("STORMCHECK_DB", str(DEFAULT_DB))),
            baseline_path=Path(base) if base else None,
            world_path=Path(os.environ.get("STORMCHECK_WORLD", str(GOLDEN_WORLD))),
            web_dist=Path(os.environ.get("STORMCHECK_WEB_DIST", str(WEB_DIST))),
            mode=mode if mode in MODES else "cache",
            impl={k: _impl(k) for k in IMPL_KEYS},
            secret=os.environ.get("STORMCHECK_SECRET", DEV_SECRET),
            reader_timeout_s=float(os.environ.get("STORMCHECK_READER_TIMEOUT_S", "8")),
            heartbeat_s=float(os.environ.get("STORMCHECK_HEARTBEAT_S", "15")),
            sse_poll_s=float(os.environ.get("STORMCHECK_SSE_POLL_S", "0.5")),
        )
