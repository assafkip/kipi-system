#!/usr/bin/env python3
"""Tests for voice-banned-list-duplication-check.py.

Runs under the capability gate's bare `python3 <file>` invocation (capability-gate.py
line 645), NOT pytest -- hence the explicit __main__ that executes every case and
exits non-zero. A pytest-style file with no __main__ exits 0 here having run zero
tests, which is what a passing suite and a dead suite have in common.

The load-bearing case is `test_detector_can_fail`: a duplication checker that
cannot go red on a real restatement is decoration. It builds its fixture FROM the
enforcer, so the fixture cannot drift away from what the checker looks for.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
CHECK = REPO / "q-system" / ".q-system" / "scripts" / "voice-banned-list-duplication-check.py"
SCANNER_SRC = REPO / "plugins" / "kipi-core" / "kipi-mcp" / "src"


def _checker_module():
    """Import the checker by path (its filename has hyphens) so the tests measure
    exactly what it measures, rather than a re-implementation that can disagree."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("vbldc", CHECK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run(*args):
    r = subprocess.run([sys.executable, str(CHECK), *args],
                       capture_output=True, text=True, cwd=str(REPO), timeout=120)
    return r.returncode, r.stdout + r.stderr


def owned():
    sys.path.insert(0, str(SCANNER_SRC))
    from kipi_mcp.draft_scanner import DraftScanner
    return DraftScanner


def _fixture(tmp, body):
    d = Path(tmp) / "skills" / "fake"
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(body, encoding="utf-8")
    return str(Path(tmp) / "skills")


def test_detector_can_fail():
    """The negative control. Build a restatement out of the enforcer's own words."""
    words = owned().TIER1_WORDS[:10]
    with tempfile.TemporaryDirectory() as tmp:
        root = _fixture(tmp, "# Fake\n\nBanned: " + ", ".join(words) + ".\n")
        rc, out = run(root)
    assert rc == 1, f"checker did not flag a 10-word restatement (rc={rc}):\n{out}"
    assert "10 banned terms in a row" in out, out


def test_bulleted_restatement_also_fails():
    """The drifted copy was a markdown bullet list, not a comma run."""
    words = owned().TIER1_WORDS[:8]
    with tempfile.TemporaryDirectory() as tmp:
        root = _fixture(tmp, "# Fake\n\n" + "\n".join(f"- {w}" for w in words) + "\n")
        rc, out = run(root)
    assert rc == 1, f"bulleted restatement not caught (rc={rc}):\n{out}"


def test_naming_a_few_terms_in_prose_stays_legal():
    """MAX_RUN=3 exists so founder-voice can name Furthermore/Moreover/Additionally
    to explain what `structural_opener` catches. If this goes red the threshold
    became stricter than the real prose it has to allow."""
    body = ('# Fake\n\nThe linter flags "Furthermore," "Moreover," "Additionally" '
            'as paragraph openers.\n')
    with tempfile.TemporaryDirectory() as tmp:
        rc, out = run(_fixture(tmp, body))
    assert rc == 0, f"three terms in explanatory prose should pass:\n{out}"


def test_skip_marker_needs_a_reason():
    """A marker with nothing after the colon is a mute button, not a decision."""
    words = owned().TIER1_WORDS[:10]
    run_line = "Banned: " + ", ".join(words) + ".\n"
    with tempfile.TemporaryDirectory() as tmp:
        rc_ok, _ = run(_fixture(
            tmp, "# Fake\n\n<!-- banned-list-skip: corpus measurement -->\n" + run_line))
        rc_bare, _ = run(_fixture(
            tmp, "# Fake\n\n<!-- banned-list-skip: -->\n" + run_line))
    assert rc_ok == 0, "a marker carrying a reason should suppress the finding"
    assert rc_bare == 1, "a reasonless marker must NOT suppress the finding"


def test_checker_derives_its_vocabulary_and_does_not_copy_it():
    """The checker must not become a fifth copy of the list it polices.
    Dogfood: run the checker's own source through its own rule."""
    mod = _checker_module()
    runs = mod.find_runs(CHECK.read_text(encoding="utf-8"),
                         mod._term_pattern(mod.owned_terms()))
    assert not runs, f"checker transcribes the list it polices: {runs}"
    src = CHECK.read_text(encoding="utf-8")
    assert "TIER1_WORDS" in src, "checker must derive from DraftScanner, not copy it"


def test_live_tree_is_clean():
    rc, out = run()
    assert rc == 0, f"live skill tree restates the banned list:\n{out}"


def test_the_four_audited_files_no_longer_restate():
    """S-5 / S-13: each of these carried its own copy on 2026-09-02."""
    mod = _checker_module()
    pat = mod._term_pattern(mod.owned_terms())
    for rel in [
        "plugins/kipi-core/skills/founder-voice/SKILL.md",
        "plugins/kipi-core/skills/linkedin-brand/SKILL.md",
        "plugins/kipi-core/skills/linkedin-brand/references/voice-check.md",
    ]:
        text = (REPO / rel).read_text(encoding="utf-8")
        assert not mod.find_runs(text, pat), f"{rel} still transcribes the list"
        assert "draft_scanner.py" in text, f"{rel} must point at the owner"


def test_ending_rule_does_not_name_a_symbol_this_repo_lacks():
    """S-6: the skeleton ships fleet-wide; it may not name an enforcer only the
    consulting instance has as though every instance had it."""
    text = (REPO / "plugins/kipi-core/skills/founder-voice/SKILL.md").read_text()
    assert "_closing_question_signals" not in text, "names a symbol absent from this repo"
    assert "end on a VERDICT" in text, "the rule itself must survive the fix"
    assert "1 of 27" in text, "the corpus evidence for the rule must survive the fix"


def test_opener_rule_is_not_restated_against_the_measured_rule():
    """S-5(a): voice-check.md told drafts to open with "I" and never the
    recipient's name. The founder's measured rule (30 sent emails, 2026-08-19)
    is the opposite for known contacts, and a line carrying only "I" measured 0%."""
    text = (REPO / "plugins/kipi-core/skills/linkedin-brand/references/voice-check.md").read_text()
    assert "never the recipient's name" not in text
    assert "Hey Sarah" not in text


def test_the_capability_fragment_declares_this_suite():
    frag = (HERE.parent / "capability" / "expected_tests"
            / "q-system__.q-system__tests__test_voice_banned_list_duplication.py.json")
    assert frag.exists(), f"no capability fragment at {frag}"
    data = json.loads(frag.read_text())
    assert data["path"].endswith("tests/test_voice_banned_list_duplication.py")
    assert data["runner"] == "python3"


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {t.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
