"""The founder's own words never sit on a ban list, in ANY copy of it.

"robust" and "foster" left voice-lint's BANNED_WORDS on 2026-09-06 after the
instance holding his corpus measured them there: whole-word, which is what
every copy matches, "robust" is in 5 corpus rows, "foster" in 5, and
"fosters" / "fostering" in 11 more that the whole-word match never saw. The
change that dropped them from the hook left the same two words in three other
hand-kept copies (scan-draft.py, compliance-check.py, and the MCP DraftScanner
behind kipi_voice_lint and kipi_scan_draft), so the drafting path still
rewrote his word after the hook had let it through (PR #315 review). This pins
the calibrated size of the hook list and refuses the dropped words in every
copy, so the next removal cannot land in one place.

The size below matches the instance's own pin (its
pipeline/tests/test_voice_list_audit.py); a calibrated change touches both.

Round 2 of the same review found the words in five model-facing prose copies
(the skill files that tell the model what kipi_voice_lint bans) and in the
monthly voice-refresh fingerprint's absence list, so those are pinned here as
well: a divergence check, because prose cannot be derived from the code.
"""
import importlib.util
import pathlib
import re
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[3]
SCRIPTS = REPO / "q-system" / ".q-system" / "scripts"
MCP_SRC = REPO / "plugins" / "kipi-core" / "kipi-mcp" / "src"
SKILLS = REPO / "plugins" / "kipi-core" / "skills"
PROSE_COPIES = [
    SKILLS / "founder-voice" / "SKILL.md",
    SKILLS / "founder-voice" / "references" / "voice-dna.md",
    SKILLS / "linkedin-brand" / "SKILL.md",
    SKILLS / "linkedin-brand" / "references" / "voice-check.md",
    SKILLS / "headline-engineering" / "SKILL.md",
]

DROPPED_FROM_CORPUS = {"robust", "foster"}
DROPPED_RE = re.compile(r"\b(" + "|".join(sorted(DROPPED_FROM_CORPUS)) + r")\b", re.I)
CALIBRATED_SIZE = 46
HIS_SENTENCE = "a robust understanding of the attackers is what fosters a broad discussion"
SLOP = "Let's delve into how we leverage synergy to unlock a paradigm shift."


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def mcp():
    sys.path.insert(0, str(MCP_SRC))
    from kipi_mcp import draft_scanner, linter
    return draft_scanner, linter.Linter()


@pytest.fixture(scope="module")
def script_matchers():
    """The compiled word patterns of the two script copies, so a case runs
    against what they MATCH, not only against their list sizes."""
    scan = _load(SCRIPTS / "scan-draft.py", "scan_draft_under_test")
    compliance = _load(SCRIPTS / "compliance-check.py", "compliance_check_under_test")
    assert scan.WORD_PATTERNS and compliance.WORD_PATTERNS, "a derivation floor"
    return {"scan-draft.py": scan.WORD_PATTERNS, "compliance-check.py": compliance.WORD_PATTERNS}


def test_the_hook_list_is_the_calibrated_one():
    lint = _load(SCRIPTS / "voice-lint.py", "voice_lint_under_test")
    assert len(lint.BANNED_WORDS) == CALIBRATED_SIZE
    assert not DROPPED_FROM_CORPUS & set(lint.BANNED_WORDS)
    assert "leverage" in lint.BANNED_WORDS


def test_no_other_copy_bans_a_word_the_corpus_dropped(mcp):
    draft_scanner, _linter = mcp
    scan = _load(SCRIPTS / "scan-draft.py", "scan_draft_under_test")
    compliance = _load(SCRIPTS / "compliance-check.py", "compliance_check_under_test")
    scanner = draft_scanner.DraftScanner
    copies = {
        "scan-draft.py": set(scan.ALL_BANNED),
        "compliance-check.py": set(compliance.BANNED_WORDS),
        "DraftScanner": set(scanner.TIER1_WORDS) | set(scanner.TIER1_VERBS) | set(scanner.TIER1_ADVERBS),
    }
    leaks = {name: sorted(DROPPED_FROM_CORPUS & words)
             for name, words in copies.items() if DROPPED_FROM_CORPUS & words}
    assert not leaks, leaks


def test_the_two_mcp_tools_pass_his_sentence(mcp, script_matchers):
    """kipi_scan_draft and kipi_voice_lint share DraftScanner; both returned
    pass:false on his sentence after the hook had stopped refusing it. The two
    script copies are run on the same sentence through their own matchers."""
    draft_scanner, linter = mcp
    scanned = draft_scanner.DraftScanner().scan({"text": HIS_SENTENCE})
    assert scanned["pass"] is True, scanned
    linted = linter.voice_lint(HIS_SENTENCE)
    flagged = [v for v in linted.get("violations", []) if any(
        word in str(v).lower() for word in DROPPED_FROM_CORPUS)]
    assert not flagged, linted
    for name, patterns in script_matchers.items():
        hits = [p.pattern for p in patterns if p.search(HIS_SENTENCE)]
        assert not hits, (name, hits)


def test_slop_still_fails_every_copy(mcp, script_matchers):
    """The negative control: dropping two words did not soften any list. Each
    copy is exercised through what it matches, so an emptied script list goes
    red here (PR #315 review, round 2)."""
    draft_scanner, linter = mcp
    assert draft_scanner.DraftScanner().scan({"text": SLOP})["pass"] is False
    assert linter.voice_lint(SLOP).get("pass") is False
    for name, patterns in script_matchers.items():
        assert any(p.search(SLOP) for p in patterns), name


def test_no_model_facing_copy_names_a_dropped_word():
    """The skill files tell the model what the lint bans. Five of them listed
    the two words after the code had stopped banning them, so the model kept
    rewriting his word before the lint ever saw it."""
    hits = {}
    for path in PROSE_COPIES:
        assert path.is_file(), path
        lines = [n for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
                 if DROPPED_RE.search(line)]
        if lines:
            hits[str(path.relative_to(REPO))] = lines
    assert not hits, hits


def test_the_voice_refresh_absence_list_does_not_count_a_dropped_word():
    """granola-voice-fingerprint.py feeds voice-dna.md monthly; a word he
    writes is not a corporate cliche whose absence proves his voice."""
    fingerprint = _load(SCRIPTS / "granola-voice-fingerprint.py", "granola_fingerprint_under_test")
    assert fingerprint.CORPORATE_CLICHE, "a derivation floor"
    assert not DROPPED_FROM_CORPUS & set(fingerprint.CORPORATE_CLICHE)
