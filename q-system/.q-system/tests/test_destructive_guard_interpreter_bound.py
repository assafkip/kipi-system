"""ASK-1247: the destructive-op guard covers direct invocation only, and says so.

RULE-2026-09-13-A (canonical/decisions.md) accepts the bound instead of adding
interpreter patterns. These cases pin that decision to the guard's behaviour and
to the sentence in its header, so neither can drift away from the other:

  - the controls prove the guard is running at all, so an ALLOW is not a dead hook;
  - each interpreter form is ALLOWED, exactly as the decision says. If one starts
    being denied, the header's stated bound is false and this goes red;
  - the header of the repo fixture quotes every interpreter form the probe
    drives. The list is read from probe_hook.py, never restated here;
  - the apply-claude-changes proposal for the live hook inserts exactly the text
    the fixture carries, so the fixture shows what the live guard will say.
"""
import json
import pathlib

import pytest

import probe_hook

HOOK = probe_hook.resolve_hook()
PROPOSAL = (pathlib.Path(__file__).resolve().parents[1]
            / "proposals" / "destructive-guard-state-interpreter-bound.json")
BOUND_MARKER = "WHAT THIS GUARD COVERS: DIRECT INVOCATION ONLY"


def header(path):
    """The comment block above the first line of code."""
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("set "):
            break
        lines.append(line)
    return "\n".join(lines)


def test_the_probe_has_rows_to_check():
    """A derivation that returned nothing would turn every case below into a no-op."""
    assert len(probe_hook.CONTROLS) >= 2
    assert len(probe_hook.INTERPRETER_FORMS) >= 5


@pytest.mark.parametrize("row", probe_hook.CONTROLS, ids=lambda r: r["label"])
def test_the_guard_denies_the_shape_it_was_built_for(tmp_path, row):
    assert probe_hook.decide(HOOK, row["command"], tmp_path) == "deny", (
        "%s is ALLOWED: the guard at %s is not running, so every interpreter "
        "ALLOW in this file proves nothing" % (row["label"], HOOK))


@pytest.mark.parametrize("row", probe_hook.INTERPRETER_FORMS, ids=lambda r: r["label"])
def test_an_interpreter_form_is_handled_as_decided(tmp_path, row):
    assert probe_hook.decide(HOOK, row["command"], tmp_path) == row["expect"], (
        "the guard at %s no longer %ss %r. Its header and RULE-2026-09-13-A both "
        "state the old bound: rewrite them, then update expect in probe_hook.py"
        % (HOOK, row["expect"], row["label"]))


def test_the_guard_header_states_its_bound():
    """Reads the FIXTURE, the copy this repo owns, never the live hook.

    The first cut read the live hook and the pre-commit verify refused its own
    commit: on the one machine with a live hook, every commit touching this
    suite would stay blocked until someone with ~/.claude access applied the
    proposal, which fails the people who cannot fix it. Whether the live hook
    carries these bytes is the drift test's question in
    test_destructive_op_deny_anchor.py, and it stays red there until then.
    """
    text = header(probe_hook.FIXTURE)
    assert BOUND_MARKER in text, (
        "the guard fixture does not state that it covers direct invocation only")
    missing = [r["label"] for r in probe_hook.INTERPRETER_FORMS
               if "ALLOW  " + r["label"] not in text]
    assert not missing, "the header does not list these ALLOW rows: %r" % missing


def test_the_live_proposal_inserts_what_the_fixture_carries():
    proposal = json.loads(PROPOSAL.read_text(encoding="utf-8"))
    (edit,) = proposal["edits"]
    assert edit["file"] == ".claude/hooks/destructive-op-deny.sh"
    assert edit["op"] == "insert_after"
    fixture = probe_hook.FIXTURE.read_text(encoding="utf-8")
    assert fixture.count(edit["anchor"]) == 1, "anchor must hit exactly once"
    cut = fixture.index(edit["anchor"]) + len(edit["anchor"])
    assert fixture[cut:].startswith(edit["insert"]), (
        "the fixture and the proposal disagree: applying the proposal to the live "
        "hook would not produce the fixture's bytes")
