#!/usr/bin/env python3
"""sp-9166e58a: `kipi update` is the one FLEET_DENY pattern that is not anchored.

READ-ONLY on ~/.claude. This test reads the live hook, copies it into a tmp dir,
patches the COPY, and drives both. It never writes inside .claude/ -- that is
claude-path-write-guard's line and it is the right line: an agent that can edit
destructive-op-deny.sh can disable its own gates. Nothing here proposes that an
agent apply this patch. It exists so the founder's decision is backed by a
measurement instead of an argument.

THE DEFECT. A git commit whose MESSAGE contains the two words is blocked, so
every commit about the updater has to be written to a file and passed with -F.

WHY THIS IS NOT THE FIX THE HOOK ALREADY REJECTED. The comment above emit_deny
(2026-08-07) decides that the hook does NOT try to tell prose from invocation,
and it is right: stripping heredoc bodies would open `bash <<'EOF'`, and any
parser deciding "this string is only prose" is a new bypass surface. This patch
does none of that. It anchors at COMMAND POSITION -- which is the discipline the
other three FLEET_DENY entries already follow, and which the hook's own comment
introduced after an unanchored pattern blocked `sed -n '1,20p' kipi-update.sh`:

    "Anchored at COMMAND POSITION on purpose: a first attempt matched the script
     name anywhere in the line and blocked `sed -n '1,20p' kipi-update.sh`, but
     reading a file is not running it. A gate that blocks reads is a gate someone
     switches off."

Pattern 138 is the only entry that never got that treatment. This is finishing a
change the file already made, not loosening a rule it deliberately set.

THE RISK, STATED PLAINLY. Anchoring means the pattern can no longer match the
phrase in an arbitrary position. The shapes that matter -- bare, chained after
&& ; | , env-var-prefixed, and inside command substitution -- are each asserted
below to STILL be denied. A message containing "; kipi update" would still false-
positive; that is accepted, and is the same residue the other three entries carry.
"""
import json
import os
import pathlib
import re
import shutil
import subprocess

import pytest

HOOK = pathlib.Path(os.environ.get("HOME", "")) / ".claude/hooks/destructive-op-deny.sh"

CURRENT = "'kipi[[:space:]]+update'"
# Command position, allowing an env-var assignment prefix and command
# substitution, because those really do invoke it.
ANCHORED = (
    r"'(^|[;&|]|\$\(|`)[[:space:]]*"
    r"([A-Za-z_][A-Za-z0-9_]*=[^[:space:]]*[[:space:]]+)*kipi[[:space:]]+update'"
)

pytestmark = pytest.mark.skipif(
    not HOOK.is_file(), reason="destructive-op-deny.sh is machine-local; not present here")


def variants(tmp_path):
    """(live copy, patched copy). The live hook is READ, never written."""
    live = tmp_path / "live.sh"
    shutil.copy(HOOK, live)
    text = live.read_text(encoding="utf-8")
    assert CURRENT in text, (
        "the unanchored pattern is gone from the live hook -- either this was "
        "fixed (delete this test and say so) or the pattern was respelled")
    patched = tmp_path / "patched.sh"
    patched.write_text(text.replace(CURRENT, ANCHORED, 1), encoding="utf-8")
    for p in (live, patched):
        p.chmod(0o755)
    return live, patched


def decide(hook, command, home):
    """Run the hook the way Claude Code does and return 'deny' or 'allow'."""
    payload = json.dumps({
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(home),
    })
    env = dict(os.environ)
    env["HOME"] = str(home)          # keep the audit log out of the real one
    env.pop("ALLOW_DESTRUCTIVE", None)
    proc = subprocess.run([str(hook)], input=payload, capture_output=True,
                          text=True, env=env)
    out = proc.stdout.strip()
    if not out:
        return "allow"
    return json.loads(out)["hookSpecificOutput"]["permissionDecision"]


# The commit message that actually got blocked, and the ones like it.
PROSE = [
    'git commit -m "feat(fleet): the kipi update path never shipped this"',
    'git commit -m "note: kipi update rsyncs the skeleton into every instance"',
]

# Every shape that really does invoke it. None of these may ever be allowed.
REAL = [
    "kipi update",
    "cd ~/projects/kipi-system && kipi update",
    "echo hi; kipi update",
    "false || kipi update",
    "ALLOW_DESTRUCTIVE_NOT_REALLY=1 kipi update",
    "FOO=bar BAZ=qux kipi update",
    "echo $(kipi update)",
    "true | kipi update",
]


class TestTheLiveHookHasTheDefect:
    """Red. Documents the behaviour that is on the machine right now."""

    @pytest.mark.parametrize("command", PROSE)
    def test_a_commit_message_is_denied_today(self, tmp_path, command):
        live, _ = variants(tmp_path)
        assert decide(live, command, tmp_path) == "deny", (
            "the false positive is gone from the live hook; this test has "
            "outlived the defect it documents")


class TestTheAnchoredPatternFixesItWithoutOpeningAHole:

    @pytest.mark.parametrize("command", PROSE)
    def test_a_commit_message_is_allowed(self, tmp_path, command):
        _, patched = variants(tmp_path)
        assert decide(patched, command, tmp_path) == "allow"

    @pytest.mark.parametrize("command", REAL)
    def test_every_real_invocation_is_still_denied(self, tmp_path, command):
        _, patched = variants(tmp_path)
        assert decide(patched, command, tmp_path) == "deny", (
            f"ANCHORING OPENED A HOLE: {command!r} now runs the fleet-wide "
            "delete unchallenged. Do not apply this patch.")

    @pytest.mark.parametrize("command", REAL)
    def test_the_live_hook_denies_them_too_so_nothing_regressed(self, tmp_path, command):
        """Negative control for the pair above: if the live hook already allowed
        one of these, 'still denied' would be proving nothing."""
        live, _ = variants(tmp_path)
        assert decide(live, command, tmp_path) == "deny"

    def test_a_dry_run_stays_exempt_either_way(self, tmp_path):
        live, patched = variants(tmp_path)
        for hook in (live, patched):
            assert decide(hook, "kipi update --dry-run", tmp_path) == "allow"

    def test_the_other_destructive_patterns_are_untouched(self, tmp_path):
        """The patch must not reach outside FLEET_DENY."""
        _, patched = variants(tmp_path)
        for command in ("rm -rf /tmp/whatever", "git reset --hard",
                        "git push --force", "git clean -fd"):
            assert decide(patched, command, tmp_path) == "deny", command


class TestTheProposedPatchIsWhatTheFileAlreadyDoes:
    """The argument for applying it, checked rather than asserted in prose."""

    def test_the_other_fleet_patterns_are_already_command_anchored(self, tmp_path):
        live, _ = variants(tmp_path)
        text = live.read_text(encoding="utf-8")
        block = re.search(r"declare -a FLEET_DENY=\(\n(.*?)\n  \)", text, re.S)
        assert block, "FLEET_DENY block not found; the hook was restructured"
        entries = [l.strip() for l in block.group(1).splitlines() if l.strip()]
        anchored = [e for e in entries if e.startswith("'(^|[;&|")]
        assert len(entries) == 4, entries
        assert len(anchored) == 3, (
            "the anchoring split changed; re-read the hook before trusting "
            "this test's argument")
        assert CURRENT in entries, (
            "the unanchored entry is not the kipi-update one any more")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
