"""Two runs of the eval on a small world, in separate interpreters with different hash seeds, score identically."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _digest(hash_seed: str) -> str:
    env = dict(os.environ, PYTHONHASHSEED=hash_seed, LLM_MODE="offline", STORMCHECK_MODE="offline")
    p = subprocess.run([sys.executable, "-m", "eval.evaluate", "--small-world-digest"], cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=600)
    assert p.returncode == 0, p.stderr[-2000:]
    return p.stdout.strip().splitlines()[-1]


def test_two_runs_on_a_small_world_score_byte_identically():
    a, b = _digest("1"), _digest("2")
    assert len(a) == 64 and a == b
