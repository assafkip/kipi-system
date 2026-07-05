"""Tests for the voice-refresh orchestrator (issue voice-refresh-orchestrator).

Deterministic: never calls real claude -p or the harness scripts. Exercises the
enforced contract directly (contamination gate, headless stop, idempotency, and
that the delta never writes voice-dna.md).
"""
import importlib.util
import json
import os
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("voice_refresh", os.path.join(_HERE, "voice_refresh.py"))
vr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vr)


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
    with tempfile.TemporaryDirectory() as tmp:
        json.dump({"durable_kept": [{"pattern": "p1"}, {"pattern": "p2"}]},
                  open(os.path.join(tmp, "voice-findings.json"), "w"))
        vr.emit_delta(tmp)
        delta = os.path.join(tmp, "voice-delta.md")
        assert os.path.exists(delta)
        body = open(delta).read()
        assert "NOT auto-merged" in body
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
