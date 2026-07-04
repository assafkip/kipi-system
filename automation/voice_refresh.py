#!/usr/bin/env python3
"""voice_refresh.py — Stage 2-3 orchestrator for the monthly voice refresh.

PRD prd-voice-refresh-monthly-2026-07-04, issue voice-refresh-orchestrator.

Repo-root automation (NOT the synced q-system/ tree). WRAPS the existing harness
scripts (granola-voice-synthesize.py, granola-voice-fingerprint.py); it never
modifies them. Headless-safe: Stage 1 harvest (the MCP-dependent pull) is done
upstream by the interactive /voice-refresh command, so this orchestrator runs on
a corpus that already exists.

Enforced contract:
- Contamination gate (ENFORCING): refuse to run if the corpus contains a
  review-flagged (>700-word turn) meeting. The harvest warn-flag becomes a block.
- Headless dependency: stop with an environmental-trigger diagnosis if `claude`
  is not on PATH (Stage 2 synthesize needs it). Never emit a stale merge silently.
- Idempotent: a second run on an unchanged corpus is a no-op.
- Logs each step. Emits voice-delta.md (a founder-gated proposal); NEVER writes
  voice-dna.md.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.environ.get(
    "VOICE_REFRESH_SCRIPTS",
    os.path.join(_HERE, "..", "q-system", ".q-system", "scripts"),
)
CLAUDE = os.environ.get("VOICE_REFRESH_CLAUDE", "claude")


class RefreshError(Exception):
    """Carries an rca-taxonomy cause_type (environmental-trigger | latent-defect)."""

    def __init__(self, cause_type, msg):
        super().__init__(msg)
        self.cause_type = cause_type


def log(step, msg):
    print(f"[voice-refresh] {step}: {msg}")


def contamination_gate(corpus_dir):
    """Raise RefreshError if any meeting in talk-ranking.json is review-flagged."""
    rank_path = os.path.join(corpus_dir, "talk-ranking.json")
    if not os.path.exists(rank_path):
        raise RefreshError("latent-defect", f"missing {rank_path}; run Stage 1 harvest first")
    data = json.load(open(rank_path))
    flagged = [r for r in data.get("ranking", []) if "review_flag" in r]
    if flagged:
        titles = ", ".join(r.get("title", "?") for r in flagged)
        raise RefreshError(
            "latent-defect",
            f"contamination gate: {len(flagged)} review-flagged meeting(s) [{titles}]. "
            "Exclude or hand-rescue them before Stage 2.",
        )
    return True


def claude_available():
    return shutil.which(CLAUDE) is not None


def corpus_hash(corpus_dir):
    p = os.path.join(corpus_dir, "me-corpus.txt")
    return hashlib.sha256(open(p, "rb").read()).hexdigest() if os.path.exists(p) else ""


def _run(script, corpus_dir):
    subprocess.run(["python3", os.path.join(SCRIPTS, script), corpus_dir], check=True)


def emit_delta(corpus_dir):
    """Write voice-delta.md: kept patterns proposed for merge. Never touches voice-dna.md."""
    fp = os.path.join(corpus_dir, "voice-findings.json")
    kept = []
    if os.path.exists(fp):
        kept = [f.get("pattern", "") for f in json.load(open(fp)).get("durable_kept", [])]
    lines = [
        "# Voice delta proposal (founder-gated; NOT auto-merged)\n",
        f"\n{len(kept)} durable pattern(s) proposed for voice-dna.md:\n",
    ]
    lines += [f"- {p}\n" for p in kept]
    lines.append(
        "\nReview, then merge via the commit + plugin-version-bump + marketplace-pull flow. "
        "This file never writes voice-dna.md itself.\n"
    )
    open(os.path.join(corpus_dir, "voice-delta.md"), "w").write("".join(lines))


def refresh(corpus_dir):
    log("start", corpus_dir)
    h = corpus_hash(corpus_dir)
    stamp = os.path.join(corpus_dir, ".voice-refresh-hash")
    outputs_present = os.path.exists(os.path.join(corpus_dir, "voice-findings.json")) and \
        os.path.exists(os.path.join(corpus_dir, "voice-fingerprint.json"))
    if h and outputs_present and os.path.exists(stamp) and open(stamp).read().strip() == h:
        log("idempotent", "corpus unchanged and outputs present; no-op")
        return "noop"

    contamination_gate(corpus_dir)
    log("contamination", "clean")

    if not claude_available():
        raise RefreshError(
            "environmental-trigger",
            f"'{CLAUDE}' not on PATH; Stage 2 synthesize needs it. Not producing a stale merge.",
        )

    log("stage2", "synthesize")
    _run("granola-voice-synthesize.py", corpus_dir)
    log("stage3", "fingerprint")
    _run("granola-voice-fingerprint.py", corpus_dir)
    emit_delta(corpus_dir)
    if h:
        open(stamp, "w").write(h)
    log("done", "delta emitted")
    return "refreshed"


def main():
    if len(sys.argv) != 2:
        sys.exit("usage: voice_refresh.py <corpus_dir>")
    try:
        print(json.dumps({"result": refresh(sys.argv[1])}))
    except RefreshError as e:
        log("STOP", f"[{e.cause_type}] {e}")
        sys.exit(2)


if __name__ == "__main__":
    main()
