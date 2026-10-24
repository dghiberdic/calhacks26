"""The Makefile loads .env for every target, an already-set variable wins, and `make live-llm` needs a key.

Black-box and offline: the real Makefile is copied next to a temp `.env` and run with `make -n` (dry run), so no
recipe executes and nothing touches the network. Keys here are fake and short on purpose (the pre-commit hook
refuses anything that looks like a real `sk-ant-` key).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = ROOT / "Makefile"
EXAMPLE = ROOT / ".env.example"
PROBE = "include Makefile\nprobe:\n\t@printf '%s|%s|%s|%s\\n' \"$$ANTHROPIC_API_KEY\" \"$$LLM_MODE\" \"$$LLM_CAP_USD\" \"$$STORMCHECK_OWNER\"\n"
LIVE_COMMANDS = [
    "LLM_MODE=live uv run python -m llm.recordings --live",
    "LLM_MODE=live uv run python -m llm.drafter --live",
    "LLM_MODE=live uv run python -m eval.baseline --prepare",
    "LLM_MODE=live uv run python -m eval.baseline --live",
    "LLM_MODE=offline STORMCHECK_MODE=offline uv run python -m eval.run",
    "uv run python -m eval.run --from-cache",
]
ENV_NAMES = ("ANTHROPIC_API_KEY", "LLM_MODE", "STORMCHECK_MODE", "LLM_CAP_USD", "STORMCHECK_OWNER")

pytestmark = pytest.mark.skipif(shutil.which("make") is None, reason="make not installed")


def clean_env(ceiling: Path, **extra: str) -> dict[str, str]:
    """The caller's environment minus anything that could leak a real key, a mode or a parent make's flags."""
    env = {k: v for k, v in os.environ.items()
           if k not in ENV_NAMES and not k.startswith(("GIT_", "MAKE", "MFLAGS"))}
    env["GIT_CEILING_DIRECTORIES"] = str(ceiling)   # a temp dir is never inside some enclosing checkout
    env.update(extra)
    return env


@pytest.fixture
def work(tmp_path):
    """A temp dir with a copy of the real Makefile, a probe rule and no .env."""
    d = tmp_path / "work"
    d.mkdir()
    shutil.copy(MAKEFILE, d / "Makefile")
    (d / "probe.mk").write_text(PROBE)
    return d


def make(cwd: Path, *args: str, ceiling: Path | None = None, **env: str) -> subprocess.CompletedProcess:
    return subprocess.run(["make", "-s", *args], cwd=cwd, env=clean_env(ceiling or cwd.parent, **env),
                          capture_output=True, text=True, timeout=60)


def probe(cwd: Path, **env: str) -> list[str]:
    r = make(cwd, "-f", "probe.mk", "probe", **env)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip().split("|")


# ---- make live-llm


def test_live_llm_with_an_empty_key_fails_with_a_clear_message(work):
    (work / ".env").write_text("ANTHROPIC_API_KEY=\nLLM_MODE=cache\n")
    r = make(work, "-n", "live-llm")
    assert r.returncode != 0
    assert "ANTHROPIC_API_KEY is empty" in r.stderr
    assert ".env" in r.stderr
    assert "uv run" not in r.stdout          # nothing after the check is even printed


def test_live_llm_without_any_env_file_fails_too(work):
    r = make(work, "-n", "live-llm")
    assert r.returncode != 0 and "ANTHROPIC_API_KEY is empty" in r.stderr


def test_live_llm_prints_the_whole_pipeline_when_the_key_is_in_dot_env(work):
    (work / ".env").write_text("ANTHROPIC_API_KEY=sk-ant-test\nLLM_MODE=cache\n")
    r = make(work, "-n", "live-llm")
    assert r.returncode == 0, r.stderr
    lines = [ln.strip() for ln in r.stdout.splitlines()]
    assert [ln for ln in lines if ln.startswith(("LLM_MODE=", "uv run"))] == LIVE_COMMANDS
    assert "sk-ant-test" not in r.stdout + r.stderr   # the dry run never echoes the key


def test_live_llm_is_listed_in_help_and_phony(work):
    assert "live-llm" in make(work, "help").stdout
    assert re.search(r"^\.PHONY:.*\blive-llm\b", MAKEFILE.read_text().replace("\\\n", " "), re.M)


# ---- .env loading


def test_dot_env_values_reach_recipes_in_all_syntaxes(work):
    (work / ".env").write_text(
        "# comment\nANTHROPIC_API_KEY=\"sk-ant-test\"  \nLLM_MODE=live # inline comment\n"
        "export STORMCHECK_OWNER=david\r\nLLM_CAP_USD='7'\nNOT_LISTED=nope\n")
    assert probe(work) == ["sk-ant-test", "live", "7", "david"]


def test_an_already_set_environment_variable_is_not_overridden_by_dot_env(work):
    (work / ".env").write_text("ANTHROPIC_API_KEY=sk-ant-file\nLLM_MODE=live\nLLM_CAP_USD=30\n")
    key, mode, cap, _ = probe(work, LLM_MODE="offline", ANTHROPIC_API_KEY="sk-ant-env")
    assert (key, mode, cap) == ("sk-ant-env", "offline", "30")      # env wins; unset names still come from .env


def test_a_command_line_variable_beats_dot_env(work):
    (work / ".env").write_text("LLM_CAP_USD=30\n")
    r = make(work, "-f", "probe.mk", "probe", "LLM_CAP_USD=2")
    assert r.stdout.strip().split("|")[2] == "2"


def test_the_last_assignment_wins_and_missing_names_stay_empty(work):
    (work / ".env").write_text("LLM_MODE=cache\nLLM_MODE=offline\n")
    assert probe(work) == ["", "offline", "", ""]


def test_without_dot_env_nothing_is_exported(work):
    assert probe(work) == ["", "", "", ""]


def test_a_worktree_falls_back_to_the_main_checkouts_dot_env(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("git not installed")
    main, wt = tmp_path / "main", tmp_path / "wt"
    main.mkdir()
    env = clean_env(tmp_path)

    def run(*cmd: str, cwd: Path) -> None:
        subprocess.run(cmd, cwd=cwd, env=env, check=True, capture_output=True)

    quiet = ("git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false",
             "-c", "core.hooksPath=/dev/null")
    run("git", "init", "-q", cwd=main)
    run(*quiet, "commit", "-q", "--allow-empty", "-m", "init", cwd=main)
    run(*quiet, "worktree", "add", "-q", str(wt), cwd=main)
    shutil.copy(MAKEFILE, wt / "Makefile")
    (wt / "probe.mk").write_text(PROBE)
    (main / ".env").write_text("ANTHROPIC_API_KEY=sk-ant-main\nLLM_MODE=cache\n")

    assert probe(wt)[:2] == ["sk-ant-main", "cache"]                       # no .env here: the main checkout's
    (wt / ".env").write_text("ANTHROPIC_API_KEY=sk-ant-wt\n")
    assert probe(wt)[:2] == ["sk-ant-wt", ""]                              # a local .env replaces it, not merges


# ---- .env.example


def test_env_example_is_tracked_not_ignored_and_never_switches_to_fakes():
    text = EXAMPLE.read_text()
    assert not re.search(r"_IMPL\s*=\s*fake", text, re.I)                  # server/config.py defaults to "real"
    assert not re.search(r"sk-ant-[A-Za-z0-9_-]{4,}", text)                # a template, never a key
    assert re.search(r"^ANTHROPIC_API_KEY=$", text, re.M)
    if shutil.which("git") is None or not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    tracked = subprocess.run(["git", "ls-files", ".env.example"], cwd=ROOT, capture_output=True, text=True)
    assert tracked.stdout.strip() == ".env.example"
    assert subprocess.run(["git", "check-ignore", "-q", ".env.example"], cwd=ROOT).returncode == 1
    for secret in (".env", ".env.local", ".env.production"):                # real env files stay ignored
        assert subprocess.run(["git", "check-ignore", "-q", secret], cwd=ROOT).returncode == 0, secret


def test_every_variable_the_makefile_loads_is_documented_in_env_example():
    names = re.findall(r"^([A-Z][A-Z0-9_]*)=", EXAMPLE.read_text(), re.M)
    listed = re.search(r"^ENV_VARS\s*:=\s*(.+)$", MAKEFILE.read_text(), re.M).group(1).split()
    assert sorted(listed) == sorted(names) == sorted(ENV_NAMES)
