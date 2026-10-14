"""voice-dna-loader honours scope_exclude for a lane passed by environment.

PR #519 round 4: the hook rendered `voice.active_corrections()` raw, so a row
lifted for `scheduled-x` (scope_exclude) still reached that lane through the
hook while `assemble.voice_section` dropped it. Both now call
`assemble.corrections_for`. Runs the real hook as a subprocess, the way Claude
Code does, against a throwaway corpus. No model call, no live path.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HOOK = ROOT / "q-system" / ".q-system" / "scripts" / "voice-dna-loader.py"

LIFTED = "Never end a post on a question LIFTEDMARK."
KEPT = "Short sentences KEPTMARK."
LI_ONLY = "LinkedIn only rule LIONLYMARK."


def _corpus(tmp_path):
    vd = tmp_path / "voice"
    vd.mkdir()
    (vd / "identity.md").write_text("A practitioner.\n")
    (vd / "exemplars.jsonl").write_text(json.dumps(
        {"id": "e1", "text": "one real row of his", "status": "active",
         "channel": "x", "weight": 1}) + "\n")
    rows = [
        {"id": "c1", "date": "2026-10-01", "instruction": LIFTED, "status": "active",
         "scope_exclude": ["scheduled-x"]},
        {"id": "c2", "date": "2026-10-02", "instruction": KEPT, "status": "active"},
        {"id": "c3", "date": "2026-10-03", "instruction": LI_ONLY, "status": "active",
         "scope": ["linkedin"]},
    ]
    (vd / "corrections.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return vd


def _run(tmp_path, **env_extra):
    env = {k: v for k, v in os.environ.items()
           if k not in ("KIPI_VOICE_LANE", "KIPI_VOICE_CHANNEL")}
    env.update(CLAUDE_PROJECT_DIR=str(ROOT), KIPI_VOICE_DIR=str(_corpus(tmp_path)),
               HOME=str(tmp_path), **env_extra)
    proc = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(
        {"prompt": "write a post about testing"}), capture_output=True, text=True,
        env=env, timeout=30)
    assert proc.returncode == 0, proc.stderr
    ctx = json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]
    # Failed setup relocates the test: prove the corpus path rendered, not the legacy dump.
    assert "=== CORRECTIONS" in ctx, ctx[:400]
    return ctx


def test_the_lifted_lane_does_not_get_the_lifted_row(tmp_path):
    ctx = _run(tmp_path, KIPI_VOICE_LANE="scheduled-x", KIPI_VOICE_CHANNEL="x")
    assert "LIFTEDMARK" not in ctx
    assert "KEPTMARK" in ctx


def test_a_channel_drops_rows_scoped_to_another_channel(tmp_path):
    ctx = _run(tmp_path, KIPI_VOICE_LANE="scheduled-x", KIPI_VOICE_CHANNEL="x")
    assert "LIONLYMARK" not in ctx


def test_no_lane_keeps_every_row_as_before(tmp_path):
    ctx = _run(tmp_path)
    for mark in ("LIFTEDMARK", "KEPTMARK", "LIONLYMARK"):
        assert mark in ctx


def test_another_lane_keeps_the_lifted_row(tmp_path):
    ctx = _run(tmp_path, KIPI_VOICE_LANE="scheduled-linkedin")
    assert "LIFTEDMARK" in ctx
