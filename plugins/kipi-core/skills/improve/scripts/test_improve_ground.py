#!/usr/bin/env python3
"""RED FIRST. Issue mbl-improve-skill (prd-morning-brief-learns, Codex
finding-11). The grounding script is offline; corpora are tmp_path
directories passed through KIPI_LESSONS_CORPORA, never a sibling checkout.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
MODULE = HERE / "improve_ground.py"
SKILL = HERE.parent / "SKILL.md"
REPO = HERE.parents[4]


@pytest.fixture(scope="module")
def ig():
    assert MODULE.is_file(), f"missing: {MODULE}"
    spec = importlib.util.spec_from_file_location("improve_ground", MODULE)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _corpus(tmp_path, name, lessons: dict):
    d = tmp_path / name
    d.mkdir()
    for slug, (title, body) in lessons.items():
        (d / f"{slug}.md").write_text(f"---\nid: {slug}\nkind: pattern\ntitle: {title}\ndate: 2026-09-01\n---\n\n{body}\n",
                                      encoding="utf-8")
    return d


def test_missing_corpus_is_named_and_the_verdict_still_prints(ig, tmp_path):
    good = _corpus(tmp_path, "good", {"a-gate-that-cannot-run-must-not-pass": ("A gate that cannot run must not pass", "gate run pass fail closed")})
    env = {"KIPI_LESSONS_CORPORA": f"{good}:{tmp_path / 'absent'}"}
    out = ig.ground("add a gate that fails closed when it cannot run", "gate", env=env)
    statuses = {c["path"]: c["status"] for c in out["corpora"]}
    assert statuses[str(good)] == "read" and statuses[str(tmp_path / 'absent')] == "missing"
    assert out["verdict"] in ("already-built", "adopt") and out["cites"]


def test_risk_scored_auto_merge_is_already_built_naming_review_tier(ig, tmp_path):
    env = {"KIPI_LESSONS_CORPORA": str(_corpus(tmp_path, "c", {}))}
    out = ig.ground("risk-scored auto-merge for low-risk PRs", "script", env=env)
    assert out["verdict"] == "already-built"
    assert any(c.endswith("review-tier.py") for c in out["cites"])


@pytest.mark.parametrize("idea,target", [
    ("sell a Notion template of the board", "skill"),
    ("charge $49 a month for the weekly pass", "job"),
    ("publish the friction log as a newsletter", "docs"),
    ("tell the client to switch CRMs", "context"),
    ("change the owner rule", "vibes"),
])
def test_roadmap_or_unknown_returns_skip_with_the_reason(ig, tmp_path, idea, target):
    env = {"KIPI_LESSONS_CORPORA": str(_corpus(tmp_path, "c", {}))}
    out = ig.ground(idea, target, env=env)
    assert out["verdict"] == "skip" and "roadmap scope" in out["reason"]
    assert "roadmap_scope.py" in out["cites"][0]


def test_a_covered_idea_cites_the_lesson_path(ig, tmp_path):
    """lessons_recall weighs only terms shared by at least two lessons
    (df > 1), so a corpus needs a sibling that shares the vocabulary before
    the target can score at all. Three lessons: the target, a sibling that
    shares launchd/plist/trigger/stages, and an unrelated one."""
    c = _corpus(tmp_path, "c", {
        "every-stage-needs-its-own-trigger": (
            "Every stage needs its own trigger",
            "a stage with no registered trigger is dead; list triggers, list stages, diff the two lists; launchd plist scheduler"),
        "a-scheduled-job-runs-in-a-bare-environment": (
            "A scheduled job runs in a bare environment",
            "a launchd plist trigger starts a job with no shell profile; test the stages under a stripped environment"),
        "verify-the-copy-the-reader-actually-reads": (
            "Verify the copy the reader actually reads",
            "the running system may load a different clone; grep the loaded copy, marketplace cache, plugin version"),
    })
    out = ig.ground("list every launchd plist trigger and diff it against the stages that should run", "script",
                    env={"KIPI_LESSONS_CORPORA": str(c)})
    assert out["verdict"] == "already-built" and any("every-stage-needs-its-own-trigger" in p for p in out["cites"])


def test_default_corpus_is_relative_to_this_repo_and_nothing_names_a_sibling(ig):
    assert ig.DEFAULT_CORPUS == REPO / "q-system" / "lessons"
    src = MODULE.read_text(encoding="utf-8")
    assert "consulting" not in src and "/Users/" not in src and "~/projects" not in src
    for banned in ("urllib", "requests", "subprocess", "claude -p"):
        assert banned not in src, banned


def test_is_refused_contract(ig):
    assert ig.is_refused("sell the brief as a product", "rule") is True
    assert ig.is_refused("", "rule") is True
    assert ig.is_refused("change the owner rule in the brief", "rule") is False


def test_skill_file_registered_with_changelog_and_cli_exit_codes(tmp_path):
    text = SKILL.read_text(encoding="utf-8")
    assert "## Changelog" in text and "improve_ground.py" in text and "name: improve" in text
    claude_md = (REPO / "CLAUDE.md").read_text(encoding="utf-8")
    assert "/improve" in claude_md, "/improve must be listed in CLAUDE.md commands"
    env = dict(os.environ, KIPI_LESSONS_CORPORA=str(tmp_path / "none"))
    r = subprocess.run([sys.executable, str(MODULE), "--target", "skill", "sell a Notion template"],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 2 and json.loads(r.stdout)["verdict"] == "skip"


def test_this_file_runs_its_own_tests_under_python3():
    if os.environ.get("KIPI_SELFTEST_INNER"):
        pytest.skip("inner run")
    env = dict(os.environ, KIPI_SELFTEST_INNER="1")
    ok = subprocess.run([sys.executable, __file__], capture_output=True, text=True, env=env)
    assert ok.returncode == 0 and "passed" in ok.stdout, ok.stdout[-600:]
    none = subprocess.run([sys.executable, __file__, "-k", "no_such_test_zzz"], capture_output=True, text=True, env=env)
    assert none.returncode != 0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", *sys.argv[1:]]))
