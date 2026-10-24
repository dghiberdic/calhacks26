"""land.sh serialises landings across worktrees: one flock on <git common dir>/land.lock around fetch → push.

Black-box: the real scripts/land.sh runs against fake `git`, `uv` and `python3` on PATH (nothing is fetched,
merged or pushed), with a fake lane command that logs when it starts and ends.
"""
from __future__ import annotations

import fcntl
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

LAND = Path(__file__).resolve().parents[2] / "scripts" / "land.sh"

FAKE_GIT = """#!/usr/bin/env bash
case "$1 $2" in
  "rev-parse --show-toplevel") echo "$FAKE_TOP" ;;
  "rev-parse --git-common-dir") echo "$FAKE_COMMON" ;;
  "rev-parse --abbrev-ref") echo "david/lock-test" ;;
  *) echo "git $*" >> "$FAKE_TOP/git.log" ;;
esac
"""
NOOP = "#!/usr/bin/env bash\nexit 0\n"
LANE = 'echo "start $NAME" >> "$LOG"; sleep 1; echo "end $NAME" >> "$LOG"'

pytestmark = pytest.mark.skipif(shutil.which("flock") is None, reason="flock(1) not installed")


@pytest.fixture
def sandbox(tmp_path):
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    for name, body in {"git": FAKE_GIT, "uv": NOOP, "python3": NOOP}.items():
        p = bin_ / name
        p.write_text(body)
        p.chmod(0o755)
    common = tmp_path / "common"
    common.mkdir()
    return tmp_path, bin_, common


def run_land(tmp: Path, bin_: Path, common: Path, name: str, **env) -> subprocess.Popen:
    top = tmp / name
    top.mkdir(exist_ok=True)
    e = {**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}", "STORMCHECK_OWNER": "david", "FAKE_TOP": str(top),
         "FAKE_COMMON": str(common), "LOG": str(tmp / "lane.log"), "NAME": name, **env}
    return subprocess.Popen(["bash", str(LAND), LANE], env=e, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True)


def wait_for(path: Path, text: str, timeout: float = 10.0) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if path.exists() and text in path.read_text():
            return
        time.sleep(0.05)
    raise AssertionError(f"{text!r} never appeared in {path}")


def test_two_concurrent_landings_do_not_overlap(sandbox):
    tmp, bin_, common = sandbox
    a = run_land(tmp, bin_, common, "a")
    wait_for(tmp / "lane.log", "start a")                 # a holds the lock and is inside its lane suite
    b = run_land(tmp, bin_, common, "b")
    out_a, _ = a.communicate(timeout=30)
    out_b, _ = b.communicate(timeout=30)
    assert a.returncode == 0 and b.returncode == 0, (out_a, out_b)
    assert (tmp / "lane.log").read_text().split("\n")[:-1] == ["start a", "end a", "start b", "end b"]
    assert "waiting for land lock…" in out_b and "waiting for land lock…" not in out_a
    assert "landed david/lock-test → main" in out_a and "landed david/lock-test → main" in out_b
    assert (common / "land.lock").exists()


def test_lock_wait_times_out(sandbox):
    tmp, bin_, common = sandbox
    with open(common / "land.lock", "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX)                  # another worktree is landing
        p = run_land(tmp, bin_, common, "c", LAND_LOCK_WAIT="1")
        out, _ = p.communicate(timeout=30)
    assert p.returncode == 1
    assert "waiting for land lock…" in out and "land.sh: lock wait timed out" in out
    assert not (tmp / "lane.log").exists()                # never ran its suite
    assert not (tmp / "c" / "git.log").exists()           # never fetched, merged or pushed
