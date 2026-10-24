"""scripts/check_owners.py: the lane owner check run by .githooks/pre-commit (--staged) and land.sh (--range).

Each case is a bypass from the integrity review (owners_probe.sh), replayed in a scratch git repo that holds a copy
of the real OWNERS and check_owners.py. The real repository is never touched.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


class Repo:
    def __init__(self, path: Path):
        self.path = path

    def git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *args], cwd=self.path, capture_output=True, text=True, check=check,
                              env={**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})

    def write(self, rel: str, text: str) -> None:
        p = self.path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def commit(self, msg: str) -> None:
        self.git("add", "-A")
        self.git("commit", "-qm", msg)

    def check(self, *args: str, owner: str = "david") -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "scripts/check_owners.py", *args], cwd=self.path, capture_output=True,
                              text=True, env={**os.environ, "STORMCHECK_OWNER": owner})

    def blocked(self, *args: str, owner: str = "david") -> str:
        r = self.check(*args, owner=owner)
        assert r.returncode == 1, (r.stdout, r.stderr)
        return r.stderr

    def passes(self, *args: str, owner: str = "david") -> None:
        r = self.check(*args, owner=owner)
        assert r.returncode == 0, (r.stdout, r.stderr)


@pytest.fixture
def repo(tmp_path) -> Repo:
    r = Repo(tmp_path / "repo")
    r.path.mkdir()
    (r.path / "scripts").mkdir()
    shutil.copy(ROOT / "OWNERS", r.path / "OWNERS")
    shutil.copy(ROOT / "scripts" / "check_owners.py", r.path / "scripts" / "check_owners.py")
    r.git("init", "-q", "-b", "main")
    r.git("config", "user.email", "t@example.com")
    r.git("config", "user.name", "t")
    r.git("config", "commit.gpgsign", "false")
    r.write("web/app.ts", "a\n")
    r.write("engine/e.py", "b\n")
    r.write("web/naïve.ts", "x\n")
    r.write("contracts/requests/README.md", "r\n")
    r.commit("base")
    r.git("branch", "base")
    r.git("checkout", "-qb", "work")
    return r


def test_direct_edit_of_another_lane_is_blocked(repo):
    repo.write("web/app.ts", "z\n")
    repo.commit("edit web")
    assert "web/app.ts" in repo.blocked("--range", "base..HEAD")


def test_own_lane_and_open_paths_pass(repo):
    repo.write("engine/e.py", "c\n")
    repo.write("contracts/requests/more.md", "please\n")
    repo.commit("mine")
    repo.passes("--range", "base..HEAD")
    repo.git("checkout", "-q", "base")
    repo.git("checkout", "-qb", "filip")
    repo.write("contracts/requests/filip.md", "x\n")
    repo.commit("filip asks")
    repo.passes("--range", "base..HEAD", owner="filip")


def test_non_ascii_path_is_not_hidden_by_quoting(repo):
    repo.write("web/naïve.ts", "hacked\n")
    repo.commit("edit web/naïve.ts")
    assert "web/naïve.ts" in repo.blocked("--range", "base..HEAD")


def test_rename_out_of_another_lane_checks_the_source_too(repo):
    repo.git("mv", "web/app.ts", "engine/app.ts")
    repo.commit("move")
    assert "web/app.ts" in repo.blocked("--range", "base..HEAD")


def test_edit_hidden_in_a_merge_commit_is_blocked(repo):
    repo.git("checkout", "-qb", "other", "base")
    repo.write("engine/o.py", "o\n")
    repo.commit("other")
    repo.git("checkout", "-q", "work")
    repo.write("engine/m.py", "m\n")
    repo.commit("mine")
    repo.git("merge", "-q", "--no-commit", "other")
    repo.write("web/app.ts", "evil\n")
    repo.git("add", "web/app.ts")
    repo.git("commit", "-qm", "merge other")
    assert "web/app.ts" in repo.blocked("--range", "base..HEAD")


def test_merging_main_into_the_branch_is_not_a_violation(repo):
    repo.git("checkout", "-q", "main")
    repo.write("web/app.ts", "justin's change on main\n")
    repo.commit("justin lands")
    repo.git("checkout", "-q", "work")
    repo.write("engine/e.py", "mine\n")
    repo.commit("mine")
    repo.git("merge", "-q", "--no-edit", "main")
    repo.passes("--range", "main..HEAD")          # only this branch's own changes count


def test_staged_rename_is_blocked(repo):
    repo.git("mv", "web/app.ts", "engine/app2.ts")
    assert "web/app.ts" in repo.blocked("--staged")


def test_staged_merge_of_main_passes_but_a_hand_edit_during_it_is_blocked(repo):
    repo.git("checkout", "-q", "main")
    repo.write("web/app.ts", "justin's change\n")
    repo.commit("justin lands")
    repo.git("checkout", "-q", "work")
    repo.write("engine/e.py", "mine\n")
    repo.commit("mine")
    repo.git("merge", "-q", "--no-commit", "--no-ff", "main")
    repo.passes("--staged")                          # web/app.ts is exactly main's version
    repo.write("web/app.ts", "smuggled in the merge\n")
    repo.git("add", "web/app.ts")
    assert "web/app.ts" in repo.blocked("--staged")


def test_unowned_paths_are_denied_by_default(repo):
    repo.write("conftest.py", "import pytest\n")          # a root conftest could skip every test
    repo.commit("sneaky conftest")
    err = repo.blocked("--range", "base..HEAD")
    assert "conftest.py" in err and "no owner" in err


def test_odd_file_names_are_checked(repo):
    name = "web/a b\tc.ts"
    repo.write(name, "x\n")
    repo.commit("odd name")
    assert "web/a b" in repo.blocked("--range", "base..HEAD")


def test_missing_owner_env_fails():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "check_owners.py"), "--staged"], cwd=ROOT,
                       capture_output=True, text=True, env={k: v for k, v in os.environ.items()
                                                            if k != "STORMCHECK_OWNER"})
    assert r.returncode == 1 and "STORMCHECK_OWNER" in r.stderr


def test_every_tracked_path_has_an_owner():
    """Deny-by-default must not make anything already on main un-landable."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("check_owners", ROOT / "scripts" / "check_owners.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    rules = mod.load_owners()
    out = subprocess.run(["git", "-c", "core.quotePath=false", "ls-files", "-z"], cwd=ROOT, capture_output=True,
                         check=True).stdout
    tracked = [p.decode("utf-8", "surrogateescape") for p in out.split(b"\0") if p]
    assert tracked, "git ls-files returned nothing"
    unowned = [p for p in tracked if mod.owner_of(p, rules) is None]
    assert unowned == [], f"paths with no owner in OWNERS: {unowned[:20]}"
