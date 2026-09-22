#!/usr/bin/env python3
"""RED FIRST. Issue mbl-roadmap-scope-paraphrase-suite (Codex finding-12 on
prd-morning-brief-learns): the boundary was proven against ONE phrase. This
suite runs a fixture file of paraphrases (none containing the literal words
'product' or 'roadmap') through roadmap_scope.classify AND through every
consumer's refusal path, so a consumer that grows its own classifier, or
forgets to refuse `unknown`, goes red here.

Consumer contract, held by this file: a consumer module exposes
`is_refused(text, declared_target) -> bool`. weekly-improve.py and
improve_ground.py land in later issues; until a consumer file exists its
cases SKIP with an explicit reason (a skip is visible; a silent pass is not).

The fixture is derived from disk, never restated here (lesson:
derive-a-value-from-its-owner-never-restate-it-in-a-test), with a floor so an
empty parse cannot turn the suite into a no-op.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent.parent  # q-system/.q-system/tests -> repo root
SCRIPTS = HERE.parent / "scripts"
FIXTURE = HERE / "fixtures" / "roadmap_scope_cases.json"
MIN_ROADMAP, MIN_SYSTEM = 12, 6

# Consumers are DERIVED from the PRD's own issue specs, never restated here, so
# a consumer that is renamed or never built cannot skip forever (both Codex
# reviewers on this issue: a skip that both consumers hit is a green that
# proves nothing). The rule: a consumer may be absent only while the issue that
# owns it is still open. Once that issue is `closed`, an absent consumer FAILS.
ISSUES = ROOT / ".prd-os" / "issues"
CONSUMER_ISSUES = {
    "weekly-improve": ("mbl-friction-artifact", "weekly-improve.py"),
    "improve_ground": ("mbl-improve-skill", "improve_ground.py"),
}


def _consumer(name):
    """(path, owning_issue_status) read from the owning issue's spec."""
    issue_id, basename = CONSUMER_ISSUES[name]
    spec = (ISSUES / f"{issue_id}.md").read_text(encoding="utf-8")
    status = next(l.split(":", 1)[1].strip() for l in spec.splitlines() if l.startswith("status:"))
    allowed = [l.strip("- ").strip() for l in spec.splitlines() if l.strip().startswith("- ") and l.strip().endswith(basename)]
    assert allowed, f"{issue_id} does not list {basename} in allowed_files; the consumer contract has no owner"
    return ROOT / allowed[0], status


def _load(stem: str, path: Path):
    assert path.is_file(), f"missing: {path}"
    spec = importlib.util.spec_from_file_location(stem, path)
    mod = importlib.util.module_from_spec(spec)
    previous = sys.modules.get(stem)
    sys.modules[stem] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        if previous is None:
            sys.modules.pop(stem, None)
        else:
            sys.modules[stem] = previous
    return mod


def _cases():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    roadmap, system = data["roadmap"], data["system"]
    # Floors: a fixture that parsed to nothing must not read as a green suite.
    assert len(roadmap) >= MIN_ROADMAP, f"fixture holds {len(roadmap)} roadmap cases, floor is {MIN_ROADMAP}"
    assert len(system) >= MIN_SYSTEM, f"fixture holds {len(system)} system cases, floor is {MIN_SYSTEM}"
    return roadmap, system


ROADMAP_CASES, SYSTEM_CASES = _cases()


@pytest.fixture(scope="module")
def scope():
    return _load("roadmap_scope", SCRIPTS / "roadmap_scope.py")


def test_roadmap_cases_avoid_the_literal_words():
    for case in ROADMAP_CASES:
        low = case["text"].lower()
        assert "product" not in low and "roadmap" not in low, case["text"]


def test_kinds_cover_all_four_roadmap_classes():
    kinds = {c["kind"] for c in ROADMAP_CASES}
    assert {"product", "pricing", "publish", "client-advice"} <= kinds, kinds


@pytest.mark.parametrize("case", ROADMAP_CASES, ids=[c["text"][:40] for c in ROADMAP_CASES])
def test_paraphrases_are_refused_by_the_classifier(scope, case):
    out = scope.classify(case["text"], case["target"])
    assert out["verdict"] == "roadmap", (case, out)


@pytest.mark.parametrize("case", SYSTEM_CASES, ids=[c["text"][:40] for c in SYSTEM_CASES])
def test_system_proposals_pass_the_classifier(scope, case):
    out = scope.classify(case["text"], case["target"])
    assert out["verdict"] == "system", (case, out)


@pytest.mark.parametrize("name", sorted(CONSUMER_ISSUES))
def test_every_consumer_refuses_every_paraphrase_and_passes_every_system_case(name):
    path, owner_status = _consumer(name)
    if not path.is_file():
        assert owner_status != "closed", (
            f"consumer {name} is absent at {path.relative_to(ROOT)} but its owning issue "
            f"{CONSUMER_ISSUES[name][0]} is closed: the contract was never met")
        pytest.skip(f"consumer {name} not built yet ({path.relative_to(ROOT)}); owning issue "
                    f"{CONSUMER_ISSUES[name][0]} is {owner_status}; this test fails the day it closes without the file")
    mod = _load(name.replace("-", "_"), path)
    assert callable(getattr(mod, "is_refused", None)), f"{name} must expose is_refused(text, target)"
    for case in ROADMAP_CASES:
        assert mod.is_refused(case["text"], case["target"]) is True, (name, case)
    for case in SYSTEM_CASES:
        assert mod.is_refused(case["text"], case["target"]) is False, (name, case)
    # unknown is a refusal everywhere: empty text, unknown target.
    assert mod.is_refused("", "rule") is True, name
    assert mod.is_refused("change the owner rule", "vibes") is True, name


def test_this_file_runs_its_own_tests_under_python3():
    import subprocess
    r = subprocess.run([sys.executable, __file__, "-k", "no_such_test_zzz"],
                       capture_output=True, text=True)
    assert r.returncode != 0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", *sys.argv[1:]]))
