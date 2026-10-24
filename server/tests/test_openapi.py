"""Contract drift guard (plan §8): the real server's OpenAPI ⊇ contracts/openapi.json (the stub's)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CONTRACT = Path(__file__).resolve().parents[2] / "contracts" / "openapi.json"
IGNORED = {"summary", "description", "operationId", "title", "tags", "examples", "example"}


def superset(want: Any, have: Any, path: str = "$") -> list[str]:
    """Every key/value in `want` appears in `have` (dicts recursively; lists element-wise). Prose keys ignored."""
    errs: list[str] = []
    if isinstance(want, dict):
        if not isinstance(have, dict):
            return [f"{path}: expected an object"]
        in_props = path.endswith(".properties")
        for k, v in want.items():
            if k in IGNORED and not in_props:
                continue
            if k not in have:
                errs.append(f"{path}.{k}: missing")
            else:
                errs += superset(v, have[k], f"{path}.{k}")
        return errs
    if isinstance(want, list):
        if not isinstance(have, list) or len(want) != len(have):
            if isinstance(have, list) and all(isinstance(x, dict) and "name" in x for x in want + have):
                names = {x["name"]: x for x in have}
                for x in want:
                    if x["name"] not in names:
                        errs.append(f"{path}[{x['name']}]: missing")
                    else:
                        errs += superset(x, names[x["name"]], f"{path}[{x['name']}]")
                return errs
            return [f"{path}: list differs ({want!r} vs {have!r})"]
        for i, (a, b) in enumerate(zip(want, have)):
            errs += superset(a, b, f"{path}[{i}]")
        return errs
    return [] if want == have else [f"{path}: {want!r} != {have!r}"]


def test_superset_helper():
    assert superset({"a": {"b": 1}}, {"a": {"b": 1, "c": 2}, "d": 3}) == []
    assert superset({"a": {"b": 1}}, {"a": {"b": 2}})
    assert superset({"p": [{"name": "x", "in": "query"}]}, {"p": [{"name": "x", "in": "query"},
                                                                    {"name": "y", "in": "query"}]}) == []


def test_real_openapi_is_a_superset_of_the_contract(mini_app):
    contract = json.loads(CONTRACT.read_text())
    real = mini_app.openapi()
    errs = superset(contract["paths"], real["paths"], "paths")
    errs += superset(contract.get("components", {}), real.get("components", {}), "components")
    assert not errs, "\n".join(errs[:40])


def test_stub_pipeline_openapi_is_a_superset_too(stub_pipeline_app):
    contract = json.loads(CONTRACT.read_text())
    assert not superset(contract["paths"], stub_pipeline_app.openapi()["paths"], "paths")
