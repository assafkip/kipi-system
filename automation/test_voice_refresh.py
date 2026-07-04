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


def test_idempotent_noop():
    with tempfile.TemporaryDirectory() as tmp:
        _corpus(tmp, flagged=False)
        json.dump({"durable_kept": []}, open(os.path.join(tmp, "voice-findings.json"), "w"))
        json.dump({}, open(os.path.join(tmp, "voice-fingerprint.json"), "w"))
        open(os.path.join(tmp, ".voice-refresh-hash"), "w").write(vr.corpus_hash(tmp))
        assert vr.refresh(tmp) == "noop"


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
