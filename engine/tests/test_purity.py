"""Binding rule 1 (plan §2): engine/ and books/ never import anthropic, never read the wall clock, never use randomness.

AST-based, so comments and strings never trip it. Test files (``tests/`` dirs, ``conftest.py``) are not decision
code and are not scanned. ``books/`` is skipped until it exists. The injected ``Clock.now()`` stays allowed.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PURE_DIRS = ("engine", "books")

BANNED_MODULES = {"anthropic", "random", "secrets"}          # any import of these (or their submodules)
BANNED_FROM_IMPORTS = {                                        # module -> names that are wall clock / randomness
    "time": {"time", "time_ns"},
    "uuid": {"uuid1", "uuid4"},
    "os": {"urandom"},
    "numpy": {"random"},
}
CLOCK_ATTRS = {"now", "utcnow", "today"}                       # datetime.now(), datetime.utcnow(), date.today()
DATETIME_CLASSES = {"datetime", "date"}


def violations(source: str, filename: str = "<src>") -> list[str]:
    tree = ast.parse(source, filename=filename)
    found: list[str] = []
    dt_modules = {"datetime"}          # names bound to the datetime module
    dt_classes = set(DATETIME_CLASSES)  # names bound to datetime.datetime / datetime.date
    module_alias: dict[str, str] = {"time": "time", "uuid": "uuid", "os": "os", "numpy": "numpy", "np": "numpy"}

    def bad(node: ast.AST, what: str) -> None:
        found.append(f"{filename}:{getattr(node, 'lineno', '?')}: {what}")

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                root = a.name.split(".")[0]
                bound = a.asname or root
                if root in BANNED_MODULES:
                    bad(node, f"import {a.name}")
                if a.name.startswith("numpy.random"):
                    bad(node, f"import {a.name}")
                if root == "datetime":
                    dt_modules.add(bound)
                if root in BANNED_FROM_IMPORTS:
                    module_alias[bound] = root
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            root = mod.split(".")[0]
            if root in BANNED_MODULES or mod.startswith("numpy.random"):
                bad(node, f"from {mod} import ...")
            for a in node.names:
                if root == "datetime" and a.name in DATETIME_CLASSES:
                    dt_classes.add(a.asname or a.name)
                if a.name in BANNED_FROM_IMPORTS.get(mod, set()):
                    bad(node, f"from {mod} import {a.name}")
        elif isinstance(node, ast.Attribute):
            v = node.value
            # datetime.now / datetime.utcnow / date.today / datetime.datetime.now / dt.date.today
            if node.attr in CLOCK_ATTRS:
                if isinstance(v, ast.Name) and v.id in dt_classes:
                    bad(node, f"{v.id}.{node.attr}")
                elif (isinstance(v, ast.Attribute) and v.attr in DATETIME_CLASSES
                      and isinstance(v.value, ast.Name) and v.value.id in dt_modules):
                    bad(node, f"{v.value.id}.{v.attr}.{node.attr}")
            # time.time, uuid.uuid4, os.urandom, np.random
            if isinstance(v, ast.Name) and v.id in module_alias:
                mod = module_alias[v.id]
                if node.attr in BANNED_FROM_IMPORTS.get(mod, set()):
                    bad(node, f"{v.id}.{node.attr}")
        elif isinstance(node, ast.Call):
            f = node.func
            is_dynamic_import = (isinstance(f, ast.Name) and f.id == "__import__") or (
                isinstance(f, ast.Attribute) and f.attr == "import_module")
            if is_dynamic_import and node.args and isinstance(node.args[0], ast.Constant):
                name = str(node.args[0].value)
                if name.split(".")[0] in BANNED_MODULES or name.startswith("numpy.random"):
                    bad(node, f"dynamic import {name}")
    return found


def pure_files() -> list[Path]:
    files: list[Path] = []
    for d in PURE_DIRS:
        base = ROOT / d
        if not base.is_dir():
            continue  # books/ may not exist yet
        for p in sorted(base.rglob("*.py")):
            rel = p.relative_to(base).parts
            if "tests" in rel or p.name == "conftest.py" or "__pycache__" in rel:
                continue
            files.append(p)
    return files


def test_engine_and_books_are_pure():
    files = pure_files()
    assert any(p.is_relative_to(ROOT / "engine") for p in files), "no engine/ source scanned"
    problems = [v for p in files for v in violations(p.read_text(encoding="utf-8"), str(p.relative_to(ROOT)))]
    assert problems == [], "purity violations (plan §2 rule 1):\n" + "\n".join(problems)


@pytest.mark.parametrize(
    "src",
    [
        "import anthropic",
        "import anthropic.types as t",
        "from anthropic import Anthropic",
        "import random",
        "from random import choice",
        "import secrets",
        "from datetime import datetime\nx = datetime.now()",
        "from datetime import datetime as DT\nx = DT.utcnow()",
        "from datetime import date\nx = date.today()",
        "import datetime\nx = datetime.datetime.now()",
        "import datetime as dt\nx = dt.datetime.now(dt.timezone.utc)",
        "import datetime as dt\nx = dt.date.today()",
        "import time\nx = time.time()",
        "from time import time_ns",
        "import uuid\nx = uuid.uuid4()",
        "import os\nx = os.urandom(8)",
        "import numpy as np\nx = np.random.default_rng(0)",
        "from numpy import random",
        "import numpy.random",
        "m = __import__('anthropic')",
        "import importlib\nm = importlib.import_module('random')",
        "f = datetime.now",  # referencing the function is as bad as calling it
    ],
)
def test_checker_catches(src):
    assert violations(src), src


@pytest.mark.parametrize(
    "src",
    [
        "def f(clock):\n    return clock.now()",
        "class E:\n    def run(self):\n        return self.clock.now()",
        "from datetime import datetime, timedelta, timezone\nx = datetime(2025, 1, 24, tzinfo=timezone.utc) + timedelta(hours=2)",
        "from datetime import datetime\nx = datetime.fromisoformat('2025-01-24T00:00:00+00:00')",
        "import numpy as np\nx = np.mean([1, 2])",
        "s = 'import anthropic; datetime.now(); random.random()'",
        "# import random",
        "from contracts.models import Entitlement",
    ],
)
def test_checker_allows(src):
    assert violations(src) == [], src
