"""Binding rule 1 (plan §2): engine/ and books/ never import anthropic (or the llm/world lanes that wrap it), never
read the wall clock, never use randomness.

Two layers:

* An AST scan of every non-test ``engine/`` and ``books/`` file. Comments never trip it. String constants are scanned
  only for SQL that reads the clock or draws randomness inside SQLite (``datetime('now')``, ``CURRENT_TIMESTAMP``,
  ``random()``), since that is the same leak one layer down.
* A runtime check: importing every engine and books module (in a fresh interpreter) loads no ``anthropic*``,
  ``llm`` or ``world`` module.

Test files (``tests/`` dirs, ``conftest.py``) make no decisions and are not scanned. The injected ``Clock.now()``
stays allowed (``clock.now()``, ``self.clock.now()``, ``getattr(clock, "now")``).
"""
from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PURE_DIRS = ("engine", "books")

# any import of these (or their submodules); "anthropic" also covers anthropic_bedrock, anthropic_vertex, …
BANNED_MODULES = {"anthropic", "random", "secrets", "llm", "world", "arrow", "pendulum", "freezegun"}
BANNED_PREFIXES = ("anthropic",)
STAR_BANNED = {"time", "os", "random", "secrets", "uuid", "numpy.random"}     # `from time import *` hides the name
# module -> attributes that are wall clock / randomness (`time` is deny-all except TIME_ALLOWED)
BANNED_ATTRS = {
    "uuid": {"uuid1", "uuid4"},
    "os": {"urandom", "getrandom", "times"},
    "numpy": {"random"},
}
TIME_ALLOWED = {"sleep", "struct_time"}                        # nothing in time.* that reads a clock
CLOCK_ATTRS = {"now", "utcnow", "today"}                       # datetime.now(), datetime.utcnow(), date.today()
DATETIME_CLASSES = {"datetime", "date"}
CLOCK_HOLDERS = DATETIME_CLASSES | {"Timestamp"}               # pandas.Timestamp.now() too
DYNAMIC_IMPORTS = {"__import__", "import_module"}
ALIASED_MODULES = {"time", "uuid", "os", "numpy"}

SQL_CLOCK = re.compile(
    r"\b(?:date|time|datetime|julianday|unixepoch|strftime|timediff)\s*\([^)]*['\"]now['\"]"
    r"|\bcurrent_(?:timestamp|date|time)\b"
    r"|(?<![.\w])random\s*\(\s*\)|\brandomblob\s*\(", re.IGNORECASE)


def _banned_module(name: str) -> bool:
    root = name.split(".")[0]
    return root in BANNED_MODULES or root.startswith(BANNED_PREFIXES) or name.startswith("numpy.random")


def violations(source: str, filename: str = "<src>") -> list[str]:
    tree = ast.parse(source, filename=filename)
    found: list[str] = []
    dt_modules = {"datetime"}            # names bound to the datetime module
    dt_classes = set(CLOCK_HOLDERS)      # names bound to datetime.datetime / datetime.date (/ pandas.Timestamp)
    module_alias: dict[str, str] = {"time": "time", "uuid": "uuid", "os": "os", "numpy": "numpy", "np": "numpy"}

    def bad(node: ast.AST, what: str) -> None:
        found.append(f"{filename}:{getattr(node, 'lineno', '?')}: {what}")

    def banned_attr(mod: str, attr: str) -> bool:
        if mod == "time":
            return attr not in TIME_ALLOWED
        return attr in BANNED_ATTRS.get(mod, set())

    def is_dt_class(v: ast.AST) -> bool:
        """`datetime` / `D` (bound to a datetime class) / `dt.datetime` / `pd.Timestamp`."""
        if isinstance(v, ast.Name):
            return v.id in dt_classes
        if isinstance(v, ast.Attribute):
            return v.attr == "Timestamp" or (v.attr in DATETIME_CLASSES and isinstance(v.value, ast.Name)
                                             and v.value.id in dt_modules)
        return False

    def is_module(v: ast.AST) -> bool:
        return isinstance(v, ast.Name) and v.id in module_alias

    # pass 1: imports and aliases (`now = datetime.datetime`, `T = time`), so pass 2 sees them wherever used
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                root = a.name.split(".")[0]
                if root == "datetime":
                    dt_modules.add(a.asname or root)
                if root in ALIASED_MODULES:
                    module_alias[a.asname or root] = root
        elif isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "datetime":
            for a in node.names:
                if a.name in DATETIME_CLASSES:
                    dt_classes.add(a.asname or a.name)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            v, name = node.value, node.targets[0].id
            if is_dt_class(v):
                dt_classes.add(name)
            elif is_module(v):
                module_alias[name] = module_alias[v.id]

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if _banned_module(a.name):
                    bad(node, f"import {a.name}")
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level == 0 and _banned_module(mod):
                bad(node, f"from {mod} import ...")
            for a in node.names:
                if a.name == "*" and mod in STAR_BANNED:
                    bad(node, f"from {mod} import *")
                elif node.level == 0 and mod in ALIASED_MODULES and banned_attr(mod, a.name):
                    bad(node, f"from {mod} import {a.name}")
        elif isinstance(node, ast.Attribute):
            v = node.value
            # datetime.now / datetime.utcnow / date.today / datetime.datetime.now / pd.Timestamp.now
            if node.attr in CLOCK_ATTRS and is_dt_class(v):
                bad(node, f"{ast.unparse(v)}.{node.attr}")
            # time.time / time.monotonic / uuid.uuid4 / os.urandom / np.random
            if is_module(v) and banned_attr(module_alias[v.id], node.attr):
                bad(node, f"{v.id}.{node.attr}")
        elif isinstance(node, ast.Call):
            f = node.func
            fname = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
            if fname in DYNAMIC_IMPORTS and node.args:
                arg = node.args[0]
                if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
                    bad(node, f"dynamic import of a computed name ({ast.unparse(arg)})")
                elif _banned_module(arg.value):
                    bad(node, f"dynamic import {arg.value}")
            # getattr(datetime, "now") / getattr(time, "time"): the same attribute, spelled as a string
            if isinstance(f, ast.Name) and f.id == "getattr" and len(node.args) >= 2:
                obj, attr = node.args[0], node.args[1]
                if isinstance(attr, ast.Constant) and isinstance(attr.value, str):
                    if attr.value in CLOCK_ATTRS and is_dt_class(obj):
                        bad(node, f"getattr({ast.unparse(obj)}, {attr.value!r})")
                    if is_module(obj) and banned_attr(module_alias[obj.id], attr.value):
                        bad(node, f"getattr({obj.id}, {attr.value!r})")
                elif is_dt_class(obj) or is_module(obj):
                    bad(node, f"getattr({ast.unparse(obj)}, <computed>)")
            # local-timezone conversion: datetime.fromtimestamp(ts) without a tz
            if isinstance(f, ast.Attribute) and f.attr == "fromtimestamp" and len(node.args) < 2 and \
                    not any(k.arg == "tz" for k in node.keywords):
                bad(node, f"{ast.unparse(f)}() without tz (local time zone)")
            # str/bytes hash() is salted per process (PYTHONHASHSEED)
            if isinstance(f, ast.Name) and f.id == "hash":
                bad(node, "hash() (salted per process)")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            m = SQL_CLOCK.search(node.value)
            if m:
                bad(node, f"SQL reads the clock or randomness: {m.group(0)!r}")
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


RUNTIME_PROBE = """
import importlib, json, pkgutil, sys
loaded = []
for name in {pkgs!r}:
    try:
        pkg = importlib.import_module(name)
    except ModuleNotFoundError:
        continue
    loaded.append(name)
    for m in pkgutil.walk_packages(pkg.__path__, name + "."):
        if ".tests" not in m.name and not m.name.endswith(".conftest"):
            importlib.import_module(m.name)
bad = sorted(n for n in sys.modules
             if n.split(".")[0] in {{"llm", "world"}} or n.split(".")[0].startswith("anthropic"))
print(json.dumps({{"loaded": loaded, "bad": bad}}))
"""


def test_importing_engine_and_books_loads_no_llm_module():
    """A fresh interpreter: the pytest process itself has llm/anthropic loaded by other lanes' tests."""
    out = subprocess.run([sys.executable, "-c", RUNTIME_PROBE.format(pkgs=list(PURE_DIRS))], cwd=ROOT,
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    res = json.loads(out.stdout.strip().splitlines()[-1])
    assert "engine" in res["loaded"]
    assert res["bad"] == [], f"engine/books pulled in {res['bad']} (plan §2 rule 1)"


@pytest.mark.parametrize(
    "src",
    [
        "import anthropic",
        "import anthropic.types as t",
        "from anthropic import Anthropic",
        "from anthropic.types import Message",
        "import anthropic_bedrock",
        "import random",
        "from random import choice",
        "from random import *",
        "import secrets",
        "import llm.client",
        "from llm import client",
        "from llm.client import LLMClient",
        "import world.loader",
        "from world import loader",
        "from datetime import datetime\nx = datetime.now()",
        "from datetime import datetime as DT\nx = DT.utcnow()",
        "from datetime import datetime as dt\nx = dt.now()",
        "from datetime import date\nx = date.today()",
        "import datetime\nx = datetime.datetime.now()",
        "import datetime\nx = datetime.datetime.now",
        "import datetime as dt\nx = dt.datetime.now(dt.timezone.utc)",
        "import datetime as dt\nx = dt.date.today()",
        "import datetime as d\nx = d.datetime.today()",
        "import datetime\nnow = datetime.datetime\nx = now.now()",
        "from datetime import datetime as D\nclass A:\n  t = D.now",
        "from datetime import datetime\nx = getattr(datetime, 'now')()",
        "from datetime import datetime\nx = datetime.fromtimestamp(0)",
        "import pandas as pd\nx = pd.Timestamp.now()",
        "import time\nx = time.time()",
        "import time\nx = time.monotonic()",
        "import time\nx = time.perf_counter()",
        "import time\nx = time.localtime()",
        "import time\nx = time.gmtime()",
        "import time\nx = time.strftime('%H')",
        "import time as t\nx = t.time_ns()",
        "import time\nT = time\nx = T.monotonic()",
        "import time\nx = getattr(time, 'monotonic')()",
        "from time import time_ns",
        "from time import monotonic_ns",
        "from time import *\nx = time()",
        "import uuid\nx = uuid.uuid1()",
        "import uuid\nx = uuid.uuid4()",
        "import uuid as U\nx = U.uuid4()",
        "from uuid import uuid4 as u\nx = u()",
        "import os\nx = os.urandom(8)",
        "import os\nx = os.getrandom(8)",
        "from os import getrandom",
        "from os import *",
        "import os\nx = os.times()",
        "import numpy as np\nx = np.random.default_rng(0)",
        "import numpy as N\nx = N.random.rand()",
        "import numpy\nx = numpy.random.rand()",
        "from numpy import random",
        "import numpy.random",
        "m = __import__('anthropic')",
        "import importlib\nm = importlib.import_module('random')",
        "import importlib\nm = importlib.import_module('ran' + 'dom')",
        "import builtins\nm = builtins.__import__('random')",
        "f = datetime.now",  # referencing the function is as bad as calling it
        "x = hash('abc')",
        "import sqlite3\nc.execute(\"SELECT datetime('now')\")",
        "c.execute(\"INSERT INTO t VALUES (strftime('%s', 'now'))\")",
        "c.execute('SELECT CURRENT_TIMESTAMP')",
        "c.execute('CREATE TABLE t (at TEXT DEFAULT current_date)')",
        "c.execute('SELECT random()')",
        "c.execute('SELECT hex(randomblob(16))')",
        "q = f\"SELECT * FROM t ORDER BY RANDOM() LIMIT {n}\"",
    ],
)
def test_checker_catches(src):
    assert violations(src), src


@pytest.mark.parametrize(
    "src",
    [
        "def f(clock):\n    return clock.now()",
        "class E:\n    def run(self):\n        return self.clock.now()",
        "x = getattr(self.clock, 'now', None)",
        "if not callable(getattr(clock, 'now', None)):\n    pass",
        "from datetime import datetime, timedelta, timezone\n"
        "x = datetime(2025, 1, 24, tzinfo=timezone.utc) + timedelta(hours=2)",
        "from datetime import datetime\nx = datetime.fromisoformat('2025-01-24T00:00:00+00:00')",
        "from datetime import UTC, datetime\nx = datetime.fromtimestamp(0, UTC)",
        "from datetime import UTC, datetime\nx = datetime.fromtimestamp(0, tz=UTC)",
        "from datetime import UTC\nx = t.astimezone(UTC)",
        "import numpy as np\nx = np.mean([1, 2])",
        "import time\ntime.sleep(0)",
        "s = 'import anthropic; datetime.now(); random.random()'",
        "# import random",
        "from contracts.models import Entitlement",
        "from . import dsl",
        "from .world_view import x",
        "import uuid\nx = uuid.uuid5(uuid.NAMESPACE_URL, 'a')",
        "c.execute('SELECT * FROM t WHERE at_key <= ? ORDER BY seq')",
        "c.execute(\"SELECT strftime('%Y', at) FROM t\")",
        "doc = 'the date is known at known_at, never now'",
        "x = rng_seeded.random_state",
    ],
)
def test_checker_allows(src):
    assert violations(src) == [], src
