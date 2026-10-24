"""land.sh lock hygiene: children never inherit the lock fd, and without flock(1) (macOS) a mkdir lock serialises.

Black-box like test_land_lock.py: the real scripts/land.sh runs against fake `git`, `uv` and `python3` on PATH.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

LAND = Path(__file__).resolve().parents[2] / "scripts" / "land.sh"

# every fake records whether fd 9 (the flock fd) is open in it
FD_PROBE = 'if { : >&9; } 2>/dev/null; then echo "fd9 open in $(basename "$0") $*" >> "$FAKE_TOP/fd.log"; fi\n'
FAKE_GIT = """#!/usr/bin/env bash
""" + FD_PROBE + """case "$1 $2" in
  "rev-parse --show-toplevel") echo "$FAKE_TOP" ;;
  "rev-parse --git-common-dir") echo "$FAKE_COMMON" ;;
  "rev-parse --abbrev-ref") echo "david/lock-test" ;;
  *) echo "git $*" >> "$FAKE_TOP/git.log" ;;
esac
"""
NOOP = "#!/usr/bin/env bash\n" + FD_PROBE + "exit 0\n"
LANE = ('{ : >&9; } 2>/dev/null && echo "fd9 open in lane" >> "$FAKE_TOP/fd.log"; '
        'echo "start $NAME" >> "$LOG"; sleep 1; echo "end $NAME" >> "$LOG"')
SYSTEM_TOOLS = ["bash", "mkdir", "rm", "rmdir", "sleep", "cat", "date", "basename", "dirname"]


def make_bin(tmp: Path, *, with_system: bool) -> Path:
    bin_ = tmp / "bin"
    bin_.mkdir()
    for name, body in {"git": FAKE_GIT, "uv": NOOP, "python3": NOOP}.items():
        p = bin_ / name
        p.write_text(body)
        p.chmod(0o755)
    if with_system:      # a PATH with only these tools: no flock(1), as on macOS
        for tool in SYSTEM_TOOLS:
            src = shutil.which(tool)
            assert src, f"{tool} not found"
            (bin_ / tool).symlink_to(src)
    return bin_


def run_land(tmp: Path, bin_: Path, common: Path, name: str, *, path: str, **env) -> subprocess.Popen:
    top = tmp / name
    top.mkdir(exist_ok=True)
    e = {**os.environ, "PATH": path, "STORMCHECK_OWNER": "david", "FAKE_TOP": str(top),
         "FAKE_COMMON": str(common), "LOG": str(tmp / "lane.log"), "NAME": name, **env}
    return subprocess.Popen([shutil.which("bash"), str(LAND), LANE], env=e, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)


def wait_for(path: Path, text: str, timeout: float = 15.0) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if path.exists() and text in path.read_text():
            return
        time.sleep(0.05)
    raise AssertionError(f"{text!r} never appeared in {path}")


@pytest.mark.skipif(shutil.which("flock") is None, reason="flock(1) not installed")
def test_children_never_inherit_the_lock_fd(tmp_path):
    bin_ = make_bin(tmp_path, with_system=False)
    common = tmp_path / "common"
    common.mkdir()
    p = run_land(tmp_path, bin_, common, "a", path=f"{bin_}:{os.environ['PATH']}")
    out, _ = p.communicate(timeout=60)
    assert p.returncode == 0, out
    log = (tmp_path / "a" / "git.log").read_text()
    assert "git fetch" in log and "git merge" in log and "git push" in log    # the fakes did run
    fd_log = tmp_path / "a" / "fd.log"
    assert not fd_log.exists(), fd_log.read_text()


def test_mkdir_lock_serialises_when_flock_is_missing(tmp_path):
    bin_ = make_bin(tmp_path, with_system=True)
    common = tmp_path / "common"
    common.mkdir()
    a = run_land(tmp_path, bin_, common, "a", path=str(bin_))
    wait_for(tmp_path / "lane.log", "start a")
    b = run_land(tmp_path, bin_, common, "b", path=str(bin_))
    out_a, _ = a.communicate(timeout=60)
    out_b, _ = b.communicate(timeout=60)
    assert a.returncode == 0 and b.returncode == 0, (out_a, out_b)
    assert (tmp_path / "lane.log").read_text().split("\n")[:-1] == ["start a", "end a", "start b", "end b"]
    assert "flock(1) not found" in out_a and "waiting for land lock…" in out_b
    assert "landed david/lock-test → main" in out_a and "landed david/lock-test → main" in out_b
    assert not (common / "land.lock.d").exists()            # released on exit


def test_mkdir_lock_times_out_and_takes_over_a_dead_holder(tmp_path):
    bin_ = make_bin(tmp_path, with_system=True)
    common = tmp_path / "common"
    lockdir = common / "land.lock.d"
    lockdir.mkdir(parents=True)
    (lockdir / "pid").write_text(f"{os.getpid()}\n")          # a live holder (this test process)
    p = run_land(tmp_path, bin_, common, "c", path=str(bin_), LAND_LOCK_WAIT="1")
    out, _ = p.communicate(timeout=60)
    assert p.returncode == 1 and "land.sh: lock wait timed out" in out
    assert not (tmp_path / "c" / "git.log").exists()          # never fetched, merged or pushed
    assert lockdir.exists()                                  # someone else's lock is left alone

    dead = subprocess.Popen(["true"])
    dead.wait()
    (lockdir / "pid").write_text(f"{dead.pid}\n")             # the holder died without cleaning up
    p = run_land(tmp_path, bin_, common, "d", path=str(bin_), LAND_LOCK_WAIT="5")
    out, _ = p.communicate(timeout=60)
    assert p.returncode == 0 and "taking over a stale land lock" in out, out
    assert not lockdir.exists()


@pytest.mark.skipif(shutil.which("flock") is None, reason="flock(1) not installed")
def test_mkdir_lock_can_be_forced(tmp_path):
    bin_ = make_bin(tmp_path, with_system=False)
    common = tmp_path / "common"
    common.mkdir()
    p = run_land(tmp_path, bin_, common, "e", path=f"{bin_}:{os.environ['PATH']}", LAND_LOCK_IMPL="mkdir")
    out, _ = p.communicate(timeout=60)
    assert p.returncode == 0 and "mkdir lock" in out, out
