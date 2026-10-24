#!/usr/bin/env python3
"""Write contracts/openapi.json from the contract stub (`make openapi`). A test fails if the file is stale."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from contracts.stub_app import openapi_json  # noqa: E402

OUT = ROOT / "contracts" / "openapi.json"


def main() -> int:
    text = openapi_json()
    changed = not OUT.exists() or OUT.read_text() != text
    OUT.write_text(text)
    print(f"{'wrote' if changed else 'unchanged'} {OUT.relative_to(ROOT)} ({len(text):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
