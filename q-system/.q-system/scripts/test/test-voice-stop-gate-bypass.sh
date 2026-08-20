#!/usr/bin/env bash
# ASK-140 / PR #48 Codex finding: .claude/rules/voice-enforcement.md documented the
# Stop gate as honoring NO bypass marker. Measured, it honors the same
# `<!-- voice-lint-skip -->` the two PostToolUse lints do, because voice-stop-gate.py
# lints the extracted draft by shelling voice-lint.py at it and that marker is read
# out of the draft text.
#
# This pins the real behavior so the rule's claim about it stops being prose. It is
# deliberately a CHARACTERIZATION test: it asserts what the gate does today, both
# halves. If someone makes the Stop path strip the marker (the open spillover
# decision -- the marker is the one bypass an agent reaches without touching a file),
# this test goes red and has to be updated in the same change as the rule text.
#
# Pairs with .claude/rules/voice-enforcement.md and test-voice-enforcement-rule-wired.sh.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
GATE="$ROOT/q-system/.q-system/scripts/voice-stop-gate.py"
fail() { echo "FAIL: $1" >&2; exit 1; }

[ -f "$GATE" ] || fail "voice-stop-gate.py missing at $GATE"

# voice-stop-gate.py can reach slack-notify.sh, and a test that pages the founder's
# real phone is a defect, not a passing test (scar: 2026-08-01, a 14/14-green suite
# paged him twice). Stubbed here at the shell layer and re-applied to the child env
# inside the driver below, so neither layer can leak a real notification.
export KIPI_NOTIFY=/usr/bin/true

python3 - "$GATE" <<'PY'
import json, os, subprocess, sys, tempfile

gate = sys.argv[1]

# Publish framing ("Here's the post") is what makes the gate treat this as a draft
# rather than founder-facing chat, and the banned words are what make it violate.
DRAFT = (
    "Here's the post:\n\n```markdown\n"
    "{marker}We leverage cutting-edge innovative solutions to unlock game-changing "
    "synergy. It's not just a tool, it's a revolution. Simply put, this is a "
    "paradigm shift that will transform how you think about scale at speed.\n"
    "```\n"
)


def run(marker):
    """Drive the gate exactly as the Stop hook does: JSON on stdin naming a
    transcript. Each transcript line wraps the message under a "message" key --
    a flat {role, content} record parses to {} and yields an empty draft, which
    passes for the wrong reason."""
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False,
                                     encoding="utf-8") as f:
        f.write(json.dumps({"message": {"role": "user",
                                        "content": "write me a linkedin post"}}) + "\n")
        f.write(json.dumps({"message": {"role": "assistant",
                                        "content": DRAFT.format(marker=marker)}}) + "\n")
        path = f.name
    # voice-stop-gate.py can reach slack-notify.sh. A test that pages the
    # founder's real phone is a defect, not a passing test (scar: 2026-08-01, a
    # 14/14-green suite paged him twice), so the notifier is stubbed here.
    env = dict(os.environ, KIPI_NOTIFY="/usr/bin/true")
    try:
        proc = subprocess.run(
            ["python3", gate],
            input=json.dumps({"transcript_path": path}),
            capture_output=True, text=True, timeout=90, env=env,
        )
    finally:
        os.unlink(path)
    return proc.returncode, (proc.stderr or "")


# The control. If this does not block, the fixture stopped reaching the lint and
# the marker half below would pass for a reason that has nothing to do with the
# marker.
rc, err = run("")
if rc != 2:
    print("FAIL: control draft was not blocked (exit %d). The fixture no longer "
          "reaches the voice lint, so this test proves nothing.\nstderr: %s"
          % (rc, err.strip()[:400]), file=sys.stderr)
    sys.exit(1)
if "voice violations" not in err:
    print("FAIL: control blocked (exit 2) but not for a voice violation.\nstderr: %s"
          % err.strip()[:400], file=sys.stderr)
    sys.exit(1)

# The same draft, one marker added, is let through.
rc_marked, err_marked = run("<!-- voice-lint-skip -->\n")
if rc_marked != 0:
    print("FAIL: the documented bypass did not apply -- identical draft carrying "
          "<!-- voice-lint-skip --> still exited %d.\nstderr: %s"
          % (rc_marked, err_marked.strip()[:400]), file=sys.stderr)
    sys.exit(1)

print("PASS: voice-stop-gate.py blocks a violating draft (exit 2) and honors "
      "<!-- voice-lint-skip --> in that same draft (exit 0)")
PY
