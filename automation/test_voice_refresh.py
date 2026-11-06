"""Tests for the voice-refresh orchestrator (issue voice-refresh-orchestrator).

Deterministic: never calls real claude -p or the harness scripts. Exercises the
enforced contract directly (contamination gate, headless stop, idempotency, and
that the delta never writes voice-dna.md).
"""
import importlib.util
import json
import os
import tempfile

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("voice_refresh", os.path.join(_HERE, "voice_refresh.py"))
vr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vr)


@pytest.fixture(autouse=True)
def _isolate_state_files(tmp_path, monkeypatch):
    """Point every repo-root state file at a temp dir, for EVERY test here.

    Per-test discipline is what failed (review round 2, ASK-3405):
    test_idempotent_noop called refresh() without setting VOICE_REFRESH_STAMP and
    stamped this checkout's live .voice-refresh-last while the suite reported 24
    passed. Measured 2026-10-30, the stamp moved 15:36:11Z -> 15:48:58Z with no
    real refresh behind it, and /voice-refresh step 1 reads that file as its
    lookback bound. Module-wide isolation is the fix; the fail-closed branch in
    vr._state() is the backstop, so a future test that escapes this fixture
    raises instead of writing real state.

    Derived from vr.STATE_FILES rather than a local copy of the env names: a new
    state file is isolated by its registry row, not by editing this fixture. The
    floor matters -- an empty registry would make this a no-op that reads green.
    """
    assert vr.STATE_FILES, "state-file registry is empty: isolation would be a no-op"
    for env in vr.STATE_FILES.values():
        monkeypatch.setenv(env, str(tmp_path / env.lower()))


def _corpus(tmp, flagged=False):
    open(os.path.join(tmp, "me-corpus.txt"), "w").write("some words " * 50)
    ranking = [{"title": "m1", "utterances": 5, "words": 100, "max_turn_words": 200}]
    if flagged:
        ranking.append({"title": "bad", "utterances": 1, "words": 5000,
                        "max_turn_words": 5000, "review_flag": "degraded diarization"})
    json.dump({"ranking": ranking, "skipped": []}, open(os.path.join(tmp, "talk-ranking.json"), "w"))


def test_contamination_or_headless_gate():
    # Contamination: a review-flagged corpus is refused (enforcing, not advisory).
    with tempfile.TemporaryDirectory() as tmp:
        _corpus(tmp, flagged=True)
        try:
            vr.contamination_gate(tmp)
            assert False, "expected refusal on flagged corpus"
        except vr.RefreshError as e:
            assert e.cause_type == "latent-defect"

    # Headless: with claude absent, refresh stops as environmental-trigger.
    with tempfile.TemporaryDirectory() as tmp:
        _corpus(tmp, flagged=False)
        old = vr.claude_available
        vr.claude_available = lambda: False
        try:
            try:
                vr.refresh(tmp)
                assert False, "expected environmental stop when claude absent"
            except vr.RefreshError as e:
                assert e.cause_type == "environmental-trigger"
        finally:
            vr.claude_available = old


def test_refresh_refuses_flagged_corpus_before_stage2():
    # Proves the contamination gate runs BEFORE any idempotency/Stage-2 path:
    # a flagged corpus is refused and Stage 2 (_run) is never invoked, even with
    # claude present.
    with tempfile.TemporaryDirectory() as tmp:
        _corpus(tmp, flagged=True)
        called = {"run": False}
        old_run, old_av = vr._run, vr.claude_available
        vr._run = lambda *a, **k: called.__setitem__("run", True)
        vr.claude_available = lambda: True
        try:
            try:
                vr.refresh(tmp)
                assert False, "flagged corpus must be refused"
            except vr.RefreshError as e:
                assert e.cause_type == "latent-defect"
            assert not called["run"], "Stage 2 must NOT run on a flagged corpus"
        finally:
            vr._run, vr.claude_available = old_run, old_av


def test_orchestrator_never_opens_voice_dna_for_write():
    # A regression that writes the REAL voice-dna.md would pass a tmp-only check.
    # Assert no open() call in the orchestrator targets voice-dna (the delta may
    # NAME voice-dna.md in its human-readable content; that is not a write to it).
    import re
    src = open(os.path.join(_HERE, "voice_refresh.py")).read()
    opens = re.findall(r"open\([^)]*\)", src)
    assert not any("voice-dna" in o for o in opens), "orchestrator must not open voice-dna.md"


def test_idempotent_noop():
    with tempfile.TemporaryDirectory() as tmp:
        _corpus(tmp, flagged=False)
        json.dump({"durable_kept": []}, open(os.path.join(tmp, "voice-findings.json"), "w"))
        json.dump({}, open(os.path.join(tmp, "voice-fingerprint.json"), "w"))
        open(os.path.join(tmp, "voice-delta.md"), "w").write("# delta\n")
        open(os.path.join(tmp, ".voice-refresh-hash"), "w").write(vr.corpus_hash(tmp))
        assert vr.refresh(tmp) == "noop"


def test_stale_delta_forces_rerun():
    # A missing/stale delta must NOT no-op: the founder-gated proposal has to be
    # regenerated. With claude stubbed absent, refresh proceeds past idempotency
    # and stops at the environmental gate (proving it did not short-circuit).
    with tempfile.TemporaryDirectory() as tmp:
        _corpus(tmp, flagged=False)
        json.dump({"durable_kept": []}, open(os.path.join(tmp, "voice-findings.json"), "w"))
        json.dump({}, open(os.path.join(tmp, "voice-fingerprint.json"), "w"))
        open(os.path.join(tmp, ".voice-refresh-hash"), "w").write(vr.corpus_hash(tmp))
        # note: no voice-delta.md
        old = vr.claude_available
        vr.claude_available = lambda: False
        try:
            try:
                vr.refresh(tmp)
                assert False, "missing delta must force a rerun, not a no-op"
            except vr.RefreshError as e:
                assert e.cause_type == "environmental-trigger"
        finally:
            vr.claude_available = old


if __name__ == "__main__":
    import subprocess
    import sys
    sys.exit(subprocess.call(["python3", "-m", "pytest", os.path.abspath(__file__), "-q"]))


def test_emit_delta_never_writes_voice_dna():
    """2026-10-30 (ASK-3405): this asserted the delta header read "NOT
    auto-merged", a blanket claim over both halves. The DoR's Pick retires it for
    the routine half on purpose -- routine style patterns now merge through a
    reviewed PR and do not wait on him, which is the whole point of the issue. The
    property worth pinning was never that header; it is that THIS FILE never
    writes voice-dna.md, and that each half names the path it takes. A header
    string is not that property, so the assertion moved to the property.
    """
    with tempfile.TemporaryDirectory() as tmp:
        json.dump({"durable_kept": [{"pattern": "p1"}, {"pattern": "p2"}]},
                  open(os.path.join(tmp, "voice-findings.json"), "w"))
        vr.emit_delta(tmp)
        delta = os.path.join(tmp, "voice-delta.md")
        assert os.path.exists(delta)
        body = open(delta).read()
        assert "never writes voice-dna.md itself" in body
        assert "p1" in body and "p2" in body
        # the orchestrator dir has no voice-dna.md write path
        assert not os.path.exists(os.path.join(tmp, "voice-dna.md"))


def test_missing_corpus_is_latent_defect():
    with tempfile.TemporaryDirectory() as tmp:
        try:
            vr.contamination_gate(tmp)
            assert False, "expected error on missing ranking"
        except vr.RefreshError as e:
            assert e.cause_type == "latent-defect"


# --- ASK-3405: the stamp must not wait on founder approval -------------------
# Before this issue the only instruction to write .voice-refresh-last lived in
# step 6 of the founder-gated /voice-refresh command, so it fired only "on a
# completed run" and no run was complete until the founder merged. Measured
# 2026-10-29: the stamp did not exist, .voice-refresh-hash was dated Jul 23, and
# the 2026-10-22 delta sat unreviewed. With no stamp the lookback falls back to
# "last 30 days" every run, so the same meetings are re-harvested forever.

def _finding(pattern, category="rhythm", quotes=None, why="distinctive"):
    """A durable_kept row in the shape granola-voice-synthesize.py emits."""
    return {"category": category, "pattern": pattern, "classification": "durable",
            "evidence_quotes": quotes or ["q1", "q2"], "why_distinctive": why,
            "critic": {"verdict": "keep", "reason": "distinctive"}}


def _kept(tmp, *findings):
    json.dump({"durable_kept": list(findings), "durable_rejected": [], "spoken_only": []},
              open(os.path.join(tmp, "voice-findings.json"), "w"))


def _stamped_refresh(tmp, stamp_path, pending_path=None):
    """Run refresh(tmp) to completion with Stage 2/3 stubbed."""
    old_run, old_av = vr._run, vr.claude_available
    saved = {k: os.environ.get(k) for k in ("VOICE_REFRESH_STAMP", "VOICE_DELTA_PENDING")}
    vr._run = lambda *a, **k: None
    vr.claude_available = lambda: True
    os.environ["VOICE_REFRESH_STAMP"] = stamp_path
    os.environ["VOICE_DELTA_PENDING"] = pending_path or os.path.join(tmp, "pending")
    try:
        return vr.refresh(tmp)
    finally:
        vr._run, vr.claude_available = old_run, old_av
        for k, v in saved.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


def test_refresh_stamps_without_waiting_for_a_merge():
    """The DoR's named check: red before ASK-3405, green after."""
    with tempfile.TemporaryDirectory() as tmp:
        _corpus(tmp, flagged=False)
        _kept(tmp, _finding("colon-ending setup line before a numbered list"))
        stamp = os.path.join(tmp, "stamp")
        assert _stamped_refresh(tmp, stamp) == "refreshed"
        assert os.path.exists(stamp), "refresh must stamp .voice-refresh-last itself"
        # Step 1 of the command reads this back as a lookback bound.
        body = open(stamp).read().strip()
        assert body.endswith("Z") and body[4] == "-", f"stamp must be ISO-8601 UTC, got {body!r}"


def test_noop_run_also_stamps():
    """An unchanged corpus still ends stamped, or the lookback widens on every
    no-op run and re-harvests the same meetings."""
    with tempfile.TemporaryDirectory() as tmp:
        _corpus(tmp, flagged=False)
        _kept(tmp)
        json.dump({}, open(os.path.join(tmp, "voice-fingerprint.json"), "w"))
        open(os.path.join(tmp, "voice-delta.md"), "w").write("# delta\n")
        open(os.path.join(tmp, ".voice-refresh-hash"), "w").write(vr.corpus_hash(tmp))
        stamp = os.path.join(tmp, "stamp")
        assert _stamped_refresh(tmp, stamp) == "noop"
        assert os.path.exists(stamp), "a no-op run must stamp too"


def test_a_refused_run_does_not_stamp():
    """A stop is not a completed run. Stamping a refusal advances the lookback
    past meetings that were never processed, which loses them silently."""
    with tempfile.TemporaryDirectory() as tmp:
        _corpus(tmp, flagged=True)
        stamp = os.path.join(tmp, "stamp")
        try:
            _stamped_refresh(tmp, stamp)
            assert False, "flagged corpus must still be refused"
        except vr.RefreshError:
            pass
        assert not os.path.exists(stamp), "a refused run must NOT stamp"


# --- ASK-3405: routine vs personal ------------------------------------------
# voice-dna.md fans out to every instance, so a pattern mined from a meeting
# about layoffs or a mental-health leave is a real founder call. The other
# patterns are not, and nothing separated the two before this issue.

def test_a_personal_pattern_is_routed_to_the_founder():
    assert vr.classify_finding(_finding("how he frames the layoffs")) == "personal"
    assert vr.classify_finding(_finding("pacing of a hard disclosure",
                                        quotes=["when I was on mental health leave"])) == "personal"
    assert vr.classify_finding(_finding("a recurring scar", category="story-scar",
                                        why="rooted in his divorce")) == "personal"


def test_a_routine_pattern_needs_no_founder_yes_no():
    for text in ("colon-ending setup line before a numbered list",
                 "opens on the claim, never on a question",
                 "leaves slight ESL flow unpolished"):
        assert vr.classify_finding(_finding(text)) == "routine", f"{text!r} is routine"


def test_the_classifier_reads_the_quotes_not_only_the_pattern_line():
    """The one-line pattern description is written by the extractor and can be
    neutral while the cited speech carries the disclosure."""
    f = _finding("rhythm of a long explanation", quotes=["so then they laid off the whole team"])
    assert vr.classify_finding(f) == "personal"


def test_delta_splits_the_two_and_names_each_path():
    with tempfile.TemporaryDirectory() as tmp:
        _kept(tmp, _finding("colon-ending setup line"), _finding("how he frames the layoffs"))
        vr.emit_delta(tmp)
        body = open(os.path.join(tmp, "voice-delta.md")).read()
        assert "## Routine" in body and "## Personal" in body, "delta must split the two"
        routine, personal = body.split("## Personal", 1)
        assert "colon-ending setup line" in routine, "routine pattern in the wrong section"
        assert "layoffs" in personal, "personal pattern in the wrong section"
        assert "reviewed PR" in routine, "routine section must name its merge path"
        assert "yes/no" in personal, "personal section must name the founder gate"


def test_delta_writes_a_pending_marker_only_when_something_needs_an_answer():
    with tempfile.TemporaryDirectory() as tmp:
        pending = os.path.join(tmp, "pending")
        os.environ["VOICE_DELTA_PENDING"] = pending
        try:
            _kept(tmp)  # nothing kept -> nothing to answer
            vr.emit_delta(tmp)
            assert not os.path.exists(pending), "an empty delta must not create a pending marker"

            _kept(tmp, _finding("talking about his mental health leave"))
            vr.emit_delta(tmp)
            assert os.path.exists(pending), "a personal pattern must leave a pending marker"
            rec = json.load(open(pending))
            assert rec["personal"] == 1 and rec["routine"] == 0
            assert rec["generated_at"].endswith("Z")
        finally:
            os.environ.pop("VOICE_DELTA_PENDING", None)


def test_a_routine_only_delta_leaves_no_pending_marker():
    """Routine patterns merge through a reviewed PR; they are not waiting on him,
    so they must not raise an unanswered-delta alert 7 days later."""
    with tempfile.TemporaryDirectory() as tmp:
        pending = os.path.join(tmp, "pending")
        os.environ["VOICE_DELTA_PENDING"] = pending
        try:
            _kept(tmp, _finding("colon-ending setup line"))
            vr.emit_delta(tmp)
            assert not os.path.exists(pending), "routine-only delta waits on nobody"
        finally:
            os.environ.pop("VOICE_DELTA_PENDING", None)


# --- ASK-3405: an unanswered delta is visible after 7 days ------------------

def _write_pending(path, days_ago, personal=1, routine=0):
    import datetime
    when = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days_ago)
    json.dump({"generated_at": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
               "personal": personal, "routine": routine}, open(path, "w"))


def test_stale_check_is_silent_before_seven_days():
    with tempfile.TemporaryDirectory() as tmp:
        pending = os.path.join(tmp, "pending")
        _write_pending(pending, days_ago=3)
        assert vr.stale_delta_line(pending, os.path.join(tmp, "answered"),
                                   os.path.join(tmp, "alerted")) == ""


def test_stale_check_fires_after_seven_days_then_stays_quiet():
    with tempfile.TemporaryDirectory() as tmp:
        pending = os.path.join(tmp, "pending")
        answered, alerted = os.path.join(tmp, "answered"), os.path.join(tmp, "alerted")
        _write_pending(pending, days_ago=9)
        line = vr.stale_delta_line(pending, answered, alerted)
        assert "voice delta" in line.lower() and "9 day" in line, f"unhelpful alert: {line!r}"
        # Alert once per generation: a monitor that repeats every run becomes noise.
        assert vr.stale_delta_line(pending, answered, alerted) == ""


def test_an_answered_delta_is_not_stale():
    import datetime
    with tempfile.TemporaryDirectory() as tmp:
        pending = os.path.join(tmp, "pending")
        answered, alerted = os.path.join(tmp, "answered"), os.path.join(tmp, "alerted")
        _write_pending(pending, days_ago=30)
        now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        open(answered, "w").write(now)
        assert vr.stale_delta_line(pending, answered, alerted) == ""


def test_an_answer_older_than_the_delta_does_not_count():
    """He answered the PREVIOUS delta. A newer one is still unanswered."""
    with tempfile.TemporaryDirectory() as tmp:
        pending = os.path.join(tmp, "pending")
        answered, alerted = os.path.join(tmp, "answered"), os.path.join(tmp, "alerted")
        _write_pending(pending, days_ago=10)
        open(answered, "w").write("2026-01-01T00:00:00Z")
        assert vr.stale_delta_line(pending, answered, alerted) != ""


def test_no_pending_marker_means_no_alert():
    with tempfile.TemporaryDirectory() as tmp:
        assert vr.stale_delta_line(os.path.join(tmp, "nope"), os.path.join(tmp, "a"),
                                   os.path.join(tmp, "b")) == ""


# --- ASK-3405: the nudge is what makes the staleness visible ----------------
# Asserted on what the nudge SENDS, not on what the script contains. The sink is
# swapped for a recorder, so nothing reaches the live alert path, and the pending
# marker comes from its producer (emit_delta) rather than hand-rolled.

NUDGE = os.path.join(_HERE, "voice-refresh-nudge.sh")


def test_stale_check_entry_point_is_silent_with_nothing_pending():
    """Every monthly nudge runs this. A stray line files a junk ticket into
    Sana's triage, which is how an alert channel stops being read."""
    import subprocess
    with tempfile.TemporaryDirectory() as d:
        env = dict(os.environ, VOICE_DELTA_PENDING=os.path.join(d, "none"),
                   VOICE_DELTA_ANSWERED=os.path.join(d, "a"),
                   VOICE_DELTA_ALERTED=os.path.join(d, "b"))
        r = subprocess.run(["python3", os.path.join(_HERE, "voice_refresh.py"), "--stale-check"],
                           capture_output=True, text=True, env=env, timeout=60)
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip() == "", f"expected silence, got {r.stdout!r}"


def test_nudge_sends_both_lines_past_a_nonzero_sink():
    """slack-notify.sh exits NON-ZERO on ordinary states (3 = no Linear key,
    4 = fixture run, 1 = send failed). Under the nudge's `set -euo pipefail` an
    unguarded send aborts the script, so a machine with no key configured would
    lose the staleness alert entirely -- the exact silence this issue is about.
    """
    import shutil
    import subprocess
    with tempfile.TemporaryDirectory() as d:
        pending = os.path.join(d, "pending")
        os.environ["VOICE_DELTA_PENDING"] = pending
        try:
            _kept(d, _finding("how he frames the layoffs", category="story-scar"))
            vr.emit_delta(d)
            assert os.path.exists(pending), "producer must leave a pending marker"
            rec = json.load(open(pending))
            rec["generated_at"] = "2026-01-01T00:00:00Z"   # age it past the threshold
            json.dump(rec, open(pending, "w"))
        finally:
            os.environ.pop("VOICE_DELTA_PENDING", None)

        root = os.path.join(d, "root")
        os.makedirs(os.path.join(root, "q-system", ".q-system", "scripts"))
        os.makedirs(os.path.join(root, "automation"))
        sink = os.path.join(root, "q-system", ".q-system", "scripts", "slack-notify.sh")
        open(sink, "w").write('#!/bin/bash\nprintf "%s\\n" "$1" >> "$KIPI_TEST_OUTBOX"\nexit 3\n')
        os.chmod(sink, 0o755)
        shutil.copy(os.path.join(_HERE, "voice_refresh.py"),
                    os.path.join(root, "automation", "voice_refresh.py"))
        shutil.copy(NUDGE, os.path.join(root, "automation", "voice-refresh-nudge.sh"))

        outbox = os.path.join(d, "outbox")
        env = dict(os.environ, KIPI_TEST_OUTBOX=outbox, VOICE_DELTA_PENDING=pending,
                   VOICE_DELTA_ANSWERED=os.path.join(d, "ans"),
                   VOICE_DELTA_ALERTED=os.path.join(d, "alr"))
        r = subprocess.run(["bash", os.path.join(root, "automation", "voice-refresh-nudge.sh")],
                           capture_output=True, text=True, env=env, timeout=60)
        assert r.returncode == 0, f"nudge must survive a non-zero sink: {r.stderr}"
        sent = open(outbox).read()
        assert "Voice refresh due" in sent, "the monthly due-line must still go out"
        assert "unanswered" in sent, f"the staleness line must be sent; got {sent!r}"


def test_command_doc_no_longer_tells_the_agent_to_stamp_by_hand():
    """Load-path note: this pins the SKELETON copy. The running /voice-refresh
    loads the marketplace clone, so this is the source the fleet ships from, not
    proof of what a live session executed today."""
    cmd = os.path.join(_HERE, "..", "plugins", "kipi-core", "commands", "voice-refresh.md")
    body = open(cmd).read()
    assert "Do not stamp by hand" in body, "step 6 must stop instructing a manual stamp"
    assert ".voice-delta-answered" in body, "the doc must say what clears the 7-day alert"
    assert "Routine" in body and "Personal" in body, "step 5 must ship the two halves apart"


# --- ASK-3405 review round 2: the suite must not touch live founder state ----
# Codex/claude review of PR #567, major: "test_idempotent_noop silently
# overwrites the real automation/.voice-refresh-last because it doesn't stub
# VOICE_REFRESH_STAMP". Confirmed on disk before the fix -- the two leaked files
# were sitting untracked in this worktree, and a suite run advanced the stamp
# from 15:36:11Z to 15:48:58Z while reporting 24 passed.

def _live_state_snapshot():
    """Contents of this checkout's real state files, keyed by path."""
    snap = {}
    for name in vr.STATE_FILES:
        p = os.path.join(_HERE, name)
        snap[p] = open(p).read() if os.path.exists(p) else None
    return snap


def test_refresh_without_an_override_refuses_instead_of_writing_live_state(monkeypatch):
    """The mistake test_idempotent_noop made, now asserted on.

    RED before the fix: refresh() returned "refreshed", stamped the real
    automation/.voice-refresh-last and rewrote the real .voice-delta-pending.
    The second assertion is the property that actually protects him -- not that a
    particular test stubs a particular var, but that running this suite leaves
    the lookback bound exactly as it found it.
    """
    before = _live_state_snapshot()
    for env in vr.STATE_FILES.values():
        monkeypatch.delenv(env, raising=False)
    with tempfile.TemporaryDirectory() as tmp:
        _corpus(tmp, flagged=False)
        _kept(tmp, _finding("colon-ending setup line"))
        monkeypatch.setattr(vr, "_run", lambda *a, **k: None)
        monkeypatch.setattr(vr, "claude_available", lambda: True)
        with pytest.raises(RuntimeError) as e:
            vr.refresh(tmp)
        assert "VOICE_" in str(e.value), f"the refusal must name the var to set: {e.value}"
    assert _live_state_snapshot() == before, "the suite must not touch live state files"


def test_every_registered_state_file_is_fail_closed_under_pytest(monkeypatch):
    """Derived from the registry: a new state file added without an isolation
    story goes red here instead of writing to the real automation/ dir."""
    assert vr.STATE_FILES, "empty registry would make this loop a no-op"
    for name, env in vr.STATE_FILES.items():
        monkeypatch.delenv(env, raising=False)
        with pytest.raises(RuntimeError):
            vr._state(name)
        monkeypatch.setenv(env, "/tmp/x")
        assert vr._state(name) == "/tmp/x", f"{env} must still override"


# --- ASK-3405 review round 2: hyphenated personal phrasing -------------------
# Review major: classify_finding missed "mental-health leave" and "laid-off",
# routing a real disclosure to the half that merges WITHOUT his yes/no. The
# spaced spelling was in the list; the hyphenated one matched nothing.

def test_hyphenated_personal_phrasing_is_personal():
    for text in ("how he paces a mental-health leave",
                 "the laid-off framing",
                 "burned-out register",
                 "a nervous-breakdown story",
                 "writes about a leave-of-absence"):
        assert vr.classify_finding(_finding(text)) == "personal", f"{text!r} must be personal"


def test_both_spellings_of_every_multi_word_term_are_personal():
    """Derived from the module's own tuples, so a term added to either list is
    covered without editing this test, and a boundary or separator change that
    stops matching one spelling goes red here."""
    assert vr.PERSONAL_STEMS and vr.PERSONAL_WORDS, "empty tuples would read green"
    for term in vr.PERSONAL_STEMS + vr.PERSONAL_WORDS:
        for spelling in (term.replace("-", " "), term.replace(" ", "-")):
            f = _finding(f"how he frames the {spelling} in a long turn")
            assert vr.classify_finding(f) == "personal", f"{spelling!r} (from {term!r})"


# --- ASK-3405 review round 2: the trailing boundary --------------------------
# Review minor: _PERSONAL_RE had no trailing boundary, so "chronic" matched
# inside "chronicle" and "debt" inside "debtor" while the comment claimed
# word-boundary matching. These four now route ROUTINE, which means they merge
# without his yes/no -- justified because each is ordinary English in a style
# description and none of them was ever a disclosure.

def test_an_ordinary_word_is_not_a_disclosure():
    for text in ("a chronicle of a long explanation",
                 "a sobering number in the opener",
                 "speaks like a debtor to the reader",
                 "builds a visage of authority",
                 "a hospitality-industry anecdote",
                 "rehabilitation of a stale draft"):
        assert vr.classify_finding(_finding(text)) == "routine", f"{text!r} over-matched"


def test_closing_the_boundary_did_not_break_the_inflections():
    """The expensive direction. All nine classified personal BEFORE the boundary
    fix (measured 2026-10-30) and a blanket trailing \\b would have silently
    stopped every one of them: a false routine fans a disclosure fleet-wide,
    which is the asymmetry the term list is built around."""
    for text in ("alcoholics anonymous", "two lawsuits", "chronically ill",
                 "his debts", "antidepressants", "a note from his psychiatrist",
                 "suicidal ideation", "the pregnancy", "foreclosure",
                 "after the hospital stay", "he was hospitalized", "in rehab"):
        assert vr.classify_finding(_finding(text)) == "personal", f"{text!r} regressed to routine"
