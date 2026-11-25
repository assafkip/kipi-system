#!/usr/bin/env python3
"""Pins voice-dna-loader.py as advisory supply (inventory row H-voice-dna-loader, ASK-5398 ruling).

why this exists: the 2026-11-16 voice-loop inventory listed this hook next to the exits.
It is not one. It adds the voice corpus to context and must never block a prompt: a
loader that refused would hold up every turn that says "post", and a loader that claimed
to check would read as coverage (the ASK-4637 census, "checked means some check ran").
So two things are pinned: it exits 0 and never emits a block decision on any input, and
its docstring names it advisory and says no exit counts it.

CONTROL FIRST: test_the_block_detector_can_fire proves the checker catches a block.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "voice-dna-loader.py"


def run(stdin, tmp_path):
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_PROJECT_DIR")}
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path)  # an empty instance: no corpus, no plugins
    env["HOME"] = str(tmp_path)
    return subprocess.run([sys.executable, str(SCRIPT)], input=stdin, capture_output=True,
                          text=True, env=env, cwd=str(tmp_path), timeout=60)


def blocks(stdout):
    try:
        out = json.loads(stdout) if stdout.strip() else {}
    except ValueError:
        return False
    return out.get("decision") == "block" or out.get("continue") is False


def test_the_block_detector_can_fire():
    assert blocks('{"decision": "block"}')
    assert not blocks('{"hookSpecificOutput": {"additionalContext": "x"}}')


def test_it_exits_zero_and_never_blocks_on_any_input(tmp_path):
    inputs = [
        "not json",
        "[]",
        "42",
        json.dumps({"prompt": ""}),
        json.dumps({"prompt": "what time is it"}),
        json.dumps({"prompt": "draft a linkedin post about detection debt"}),
    ]
    for stdin in inputs:
        r = run(stdin, tmp_path)
        assert r.returncode == 0, (stdin, r.returncode, r.stderr[-400:])
        assert not blocks(r.stdout), stdin


def test_it_says_it_is_advisory_and_not_the_voice_loop():
    head = SCRIPT.read_text()[:2500]
    assert "Advisory supply, not the voice loop" in head
    assert "no exit counts it" in head


# --- ASK-5669: the context names the writer lane and does not order a draft -----------
# why: PR #656 round 1 (consulting) found the injected text still read "You MUST apply
# the founder's voice DNA below before drafting", an order to draft, on every writing
# turn, while RULE-2026-11-18-WRITER-ENTRY says text in his voice comes from the lane.
# Both branches are pinned: the corpus branch is the one production takes (PR #878
# review, minor: the empty-instance run above never executes it).

REPO = Path(__file__).resolve().parents[4]
WRITING = json.dumps({"prompt": "draft a linkedin post about detection debt"})


def corpus_env(tmp_path):
    proj = tmp_path / "proj"
    (proj / "plugins").mkdir(parents=True)
    (proj / "plugins" / "kipi-core").symlink_to(REPO / "plugins" / "kipi-core")
    voice = tmp_path / "voice"
    voice.mkdir()
    rows = [{"id": f"r{i}", "channel": "x", "kind": "post", "status": "active", "weight": 1,
             "text": f"fixture row {i} about a queue that dropped work", "words": 8}
            for i in range(4)]
    (voice / "exemplars.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    (voice / "identity.md").write_text("fixture identity line\n")
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_PROJECT_DIR")}
    env.update(CLAUDE_PROJECT_DIR=str(proj), HOME=str(tmp_path), KIPI_VOICE_DIR=str(voice))
    return env, proj


def context_of(stdout):
    return json.loads(stdout)["hookSpecificOutput"]["additionalContext"]


def lane_problems(context):
    """[] when the context names both lane commands and gives no order to draft."""
    out = []
    for needle in ("python3 -m pipeline.social idea", "python3 -m pipeline.draft_email",
                   "RULE-2026-11-18-WRITER-ENTRY", "HAND-WRITTEN"):
        if needle not in context:
            out.append(f"missing {needle}")
    for order in ("before drafting any text", "You MUST apply"):
        if order in context:
            out.append(f"orders a draft: {order}")
    return out


def test_the_lane_checker_can_fire():
    assert lane_problems("You MUST apply the voice before drafting any text") != []
    assert lane_problems(LANE_TEXT_FOR_CONTROL) == []


LANE_TEXT_FOR_CONTROL = ("python3 -m pipeline.social idea / python3 -m pipeline.draft_email "
                         "RULE-2026-11-18-WRITER-ENTRY HAND-WRITTEN")


def test_the_corpus_branch_names_the_lane_and_exits_zero(tmp_path):
    env, proj = corpus_env(tmp_path)
    r = subprocess.run([sys.executable, str(SCRIPT)], input=WRITING, capture_output=True,
                       text=True, env=env, cwd=str(proj), timeout=60)
    assert r.returncode == 0, r.stderr[-400:]
    ctx = context_of(r.stdout)
    assert "fixture identity line" in ctx, "the corpus branch did not run"
    assert lane_problems(ctx) == [], lane_problems(ctx)


def test_the_corpus_branch_exits_zero_on_a_broken_corpus(tmp_path):
    env, proj = corpus_env(tmp_path)
    (Path(env["KIPI_VOICE_DIR"]) / "exemplars.jsonl").write_text("{not json\n")
    r = subprocess.run([sys.executable, str(SCRIPT)], input=WRITING, capture_output=True,
                       text=True, env=env, cwd=str(proj), timeout=60)
    assert r.returncode == 0, r.stderr[-400:]
    assert not blocks(r.stdout)


def test_the_legacy_branch_names_the_lane(tmp_path):
    r = run(WRITING, tmp_path)
    assert r.returncode == 0
    assert lane_problems(context_of(r.stdout)) == [], lane_problems(context_of(r.stdout))
