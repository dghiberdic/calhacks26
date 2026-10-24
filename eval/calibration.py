"""One logistic calibration model per decision kind; train/test separation is explicit.

- **Label** (every kind): the engine settled the item alone and correctly per the answer key. An abstention
  (``needs_legal``, ``needs_ruling``) is 0. Routing reads the score as exactly this probability: ≥ 0.90 may run alone.
- **Fit:** logistic regression only (CONTRACTS §6). The L2 strength C is chosen from a fixed grid by 5-fold
  cross-validated log-loss on TRAIN rows grouped by world day. It is never chosen on held-out or golden data.
- **Kinds without usable train rows** keep the shipped prior, marked ``"trained_on": "prior", "n": 0``.
- **Reliability:** five bins cut at the routing thresholds, with n and Wilson 95% intervals on held-out rows, plus
  coverage@0.9.
- **Promotion gate** (``acceptance``): a candidate goes to ``data/calibration.json`` only if it keeps every golden
  confidence band in ``contracts/fixtures/golden/expected/`` for the real engine and for FakeEngine. The gate is
  pass/fail and never feeds back into the fit.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

import orjson
from sklearn.linear_model import LogisticRegression

from contracts import calibration

LABEL = "calibrated on synthetic labels; validates the pipeline, not the world"
ROOT = Path(__file__).resolve().parents[1]
Z95 = 1.959963984540054
BIN_EDGES = (0.0, 0.6, 0.75, 0.9, 0.97, 1.0)      # <0.60 asks · 0.60–0.90 batch review · ≥0.90 may run alone
AUTO = 0.9
C_GRID = (0.01, 0.1, 1.0, 10.0, 100.0, 1000.0)
MIN_ROWS, MIN_CLASS, CV_FOLDS = 20, 3, 5
TRAINED_ON = "2023-07-01..2024-12-31"


def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float]:
    """Wilson score interval for k successes in n trials. n = 0 gives the whole interval [0, 1]."""
    if n < 0 or k < 0 or k > n:
        raise ValueError(f"wilson: need 0 <= k <= n, got k={k}, n={n}")
    if n == 0:
        return 0.0, 1.0
    p = k / n
    denominator = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denominator
    radius = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return max(0.0, center - radius), min(1.0, center + radius)


def _bin(p: float) -> int:
    for i in range(len(BIN_EDGES) - 1):
        if p < BIN_EDGES[i + 1]:
            return i
    return len(BIN_EDGES) - 2


def choose_c(x: Sequence[Sequence[float]], y: Sequence[int], groups: Sequence[str]) -> tuple[float, dict]:
    """C with the lowest grouped-CV log-loss on the training rows (C = 1 when there are too few days to fold)."""
    import numpy as np
    from sklearn.metrics import log_loss
    from sklearn.model_selection import GroupKFold

    if len(set(groups)) < CV_FOLDS or len(y) < MIN_ROWS:
        return 1.0, {}
    xa, ya = np.asarray(x, dtype=float), np.asarray(y, dtype=int)
    folds = list(GroupKFold(n_splits=CV_FOLDS).split(xa, ya, list(groups)))
    scores = {}
    for c in C_GRID:
        losses = []
        for a, b in folds:
            if len(set(ya[a])) < 2:
                continue
            m = LogisticRegression(C=c, max_iter=5000).fit(xa[a], ya[a])
            losses.append(log_loss(ya[b], m.predict_proba(xa[b])[:, 1], labels=[0, 1]))
        if losses:
            scores[c] = sum(losses) / len(losses)
    if not scores:
        return 1.0, {}
    best = min(scores, key=lambda c: (round(scores[c], 12), c))
    return best, {str(c): round(v, 6) for c, v in scores.items()}


def fit_calibration(records: list[dict[str, Any]], version: str = "cal-synthetic-v2",
                    prior: Mapping[str, Any] | None = None) -> dict[str, Any]:
    allowed = calibration.schema()["x-features"]
    models = {}
    for kind in calibration.KINDS:
        rows = [r for r in records if r["split"] == "train" and r["kind"] == kind]
        labels = [int(r["correct"]) for r in rows]
        usable = rows and set(labels) == {0, 1} and min(labels.count(0), labels.count(1)) >= min(
            MIN_CLASS, len(rows) // 2)
        if not usable:
            # A one-class (or empty) sample cannot calibrate confidence in correctness: keep the shipped prior.
            pm = ((prior or {}).get("models") or {}).get(kind)
            if pm:
                models[kind] = {**{k: pm[k] for k in ("features", "coef", "intercept")},
                                "trained_on": "prior", "n": 0,
                                "metrics": {"train_rows": float(len(rows)), "train_positive": float(sum(labels))}}
            continue
        features = allowed[kind]
        x = [[float(r["features"].get(f, 0)) for f in features] for r in rows]
        if not all(math.isfinite(value) for row in x for value in row):
            raise ValueError("Calibration features must be finite numbers")
        c, cv = choose_c(x, labels, [str(r.get("day", i)) for i, r in enumerate(rows)])
        model = LogisticRegression(C=c, max_iter=5000).fit(x, labels)
        models[kind] = {
            "features": features,
            "coef": [round(float(v), 12) for v in model.coef_[0]],
            "intercept": round(float(model.intercept_[0]), 12),
            "trained_on": TRAINED_ON,
            "n": len(rows),
            "metrics": {"C": c, "train_positive": float(sum(labels)), **{f"cv_logloss_C{k}": v for k, v in cv.items()}},
        }
    digest = sha256(orjson.dumps(models, option=orjson.OPT_SORT_KEYS)).hexdigest()[:12]
    result = {"version": f"{version}-{digest}", "note": LABEL, "models": models}
    errors = calibration.validate(result)
    if errors:
        raise ValueError("; ".join(errors))
    return result


def reliability(records: list[dict[str, Any]], fitted: dict[str, Any]) -> tuple[dict, dict]:
    """Five held-out bins at the routing thresholds with 95% Wilson intervals, one set per modelled kind.

    A kind on the shipped prior is binned too (its bins show how the prior behaves). A kind with no model has
    no bins: it is "uncalibrated"."""
    result, coverage = {}, {}
    for kind in calibration.KINDS:
        rows = [r for r in records if r["split"] == "test" and r["kind"] == kind]
        if kind not in fitted.get("models", {}):
            result[kind], coverage[kind] = [], 0.0
            continue
        scored = [(calibration.score(fitted, kind, r["features"]), bool(r["correct"])) for r in rows]
        scored = [(p, y) for p, y in scored if p is not None]
        bins = []
        for i in range(len(BIN_EDGES) - 1):
            members = [(p, y) for p, y in scored if _bin(p) == i]
            n, k = len(members), sum(y for _, y in members)
            lo, hi = wilson(k, n)
            bins.append({"lo": BIN_EDGES[i], "hi": BIN_EDGES[i + 1], "n": float(n),
                         "accuracy": round(k / n, 6) if n else 0.0, "wilson_lo": round(lo, 6),
                         "wilson_hi": round(hi, 6),
                         "mean_score": round(sum(p for p, _ in members) / n, 6) if n else 0.0})
        result[kind] = bins
        coverage[kind] = round(sum(p >= AUTO for p, _ in scored) / len(scored), 6) if scored else 0.0
    return result, coverage


def accuracy_at(records: list[dict[str, Any]], fitted: dict[str, Any], kind: str, threshold: float = AUTO
                ) -> tuple[int, int]:
    """(correct, n) among held-out rows of ``kind`` scored at or above ``threshold``."""
    hits = [bool(r["correct"]) for r in records if r["split"] == "test" and r["kind"] == kind
            and (p := calibration.score(fitted, kind, r["features"])) is not None and p >= threshold]
    return sum(hits), len(hits)


# ---------------------------------------------------------------- promotion gate (golden confidence contract)

def acceptance(cal: dict[str, Any]) -> list[str]:
    """Problems that installing ``cal`` as data/calibration.json would cause against the golden expected fixtures
    (real engine: every storm's decision fields and bands plus question bands; FakeEngine: the contracts tests'
    bands and questions). [] = promotable."""
    import json

    from contracts.fakes import FakeEngine, golden_world
    from contracts.models import Role, Rule, RuleAction
    from engine.engine import Engine

    problems = [f"missing model: {k}" for k in ("cause", "voucher", "release") if k not in cal.get("models", {})]
    exp_dir = ROOT / "contracts/fixtures/golden/expected"
    decisions = json.loads((exp_dir / "decisions.json").read_text(encoding="utf-8"))
    questions = json.loads((exp_dir / "questions.json").read_text(encoding="utf-8"))

    def band(score, b) -> bool:
        return score is not None and b.get("min", 0.0) <= score < b.get("max", float("inf"))

    world = golden_world()
    reduce = Rule(id="R-MINED-REDUCE", version=1, kind="mined_policy", scope={},
                  condition={"all": [{"f": "pax.election", "op": "in", "v": ["reroute_partner",
                                                                              "reaccommodated_own"]}]},
                  action=RuleAction.APPLY_7_2_REDUCTION, tier="mined", authority_required=Role.CLAIMS_LEAD,
                  valid_from=None, recorded_at=datetime(2025, 1, 1, tzinfo=UTC), status="active", support="41 of 42")
    eng = Engine(world, calibration=cal)
    for sid, m in world.meta["storms"].items():
        k = datetime.fromisoformat(m["known_at"].replace("Z", "+00:00"))
        run = eng.run_storm(world, m["station"], date.fromisoformat(m["local_date"]), [reduce], k)
        got = {r.flight.id: r.decision for r in run.flights if r.decision is not None}
        for fid, want in decisions["storms"].get(sid, {}).items():
            d = got.get(fid)
            if d is None:
                problems.append(f"real {fid}: no decision")
                continue
            dd = d.model_dump(mode="json")
            for f in decisions["compare"]:
                if dd[f] != want[f]:
                    problems.append(f"real {fid}.{f}: {dd[f]!r} != {want[f]!r}")
            if not band(d.confidence.score, want.get("confidence", {})):
                problems.append(f"real {fid}.confidence {d.confidence.score} outside {want.get('confidence')}")
        qs = {q.pattern: q for q in run.questions}
        if sid not in questions["storms"]:
            continue
        wanted = questions["storms"][sid]
        if set(qs) != {w["pattern"] for w in wanted}:
            problems.append(f"real {sid} question patterns {sorted(qs)} != {sorted(w['pattern'] for w in wanted)}")
        for w in wanted:
            q = qs.get(w["pattern"])
            if q is not None and not band(q.confidence.score, w["confidence"]):
                problems.append(f"real {w['key']}.confidence {q.confidence.score} outside {w['confidence']}")
    fake = FakeEngine(world, calibration=cal)
    (p,) = fake.mine_rules(world)
    mined = p.rule.model_copy(update={"status": "active", "recorded_at": datetime(2025, 1, 20, tzinfo=UTC),
                                      "valid_from": datetime(2025, 1, 20, tzinfo=UTC)})
    run = fake.run_storm(world, "EIDW", date(2025, 1, 24), [mined], datetime(2025, 1, 25, 6, tzinfo=UTC))
    got = {r.flight.id: r.decision for r in run.flights if r.decision}
    for fid, want in decisions["storms"]["EIDW@2025-01-24"].items():
        s = got[fid].confidence.score if fid in got else None
        lo, hi = want["confidence"].get("min", 0.0), want["confidence"].get("max", 1.0)
        if s is None or not (lo <= s < hi or s == hi == 1.0):
            problems.append(f"fake {fid}.confidence {s} outside {want['confidence']}")
    fq = {q.id: q for q in run.questions}
    if set(fq) != {"Q-1", "Q-2", "Q-3"}:
        problems.append(f"fake questions {sorted(fq)} != ['Q-1', 'Q-2', 'Q-3']")
    for qid in ("Q-1", "Q-2"):
        s = fq[qid].confidence.score if qid in fq else None
        if s is None or not s < 0.6:
            problems.append(f"fake {qid}.confidence {s} not < 0.6")
    return problems
