#!/usr/bin/env python3
"""probe_guard.py -- reproducer for Layer 1 (claude-path-write-guard.py). ASK-291.

WHAT IT PROVES
The guard must block writes into `.claude/` (ATTACK) while leaving alone the
ordinary work of an agent session whose cwd is a gitignored scratch subtree of
`.claude/` (LOOP), and normal reads (BENIGN).

THE DEFECT IT WAS WRITTEN FOR (sp-2b9372f6)
`expand()` resolves every bare argv token against cwd. So from a session inside
`.claude/worktrees/<name>/`, the literal word `commit` in `git commit` resolves
to `<cwd>/commit`, which is "inside .claude", and the command is blocked:

    BLOCKED: git commit targets .claude/: /Users/.../.claude/worktrees/opus-fallback/commit

Two live registered worktrees sit under that path (`git worktree list`). Layer 2
already treats `worktrees/`, `state/`, `plans/`, `backups/` as volatile scratch
and does not watch them. Layer 1 had no such exclusion, so the two layers
disagreed about what the protected set even is.

HOW IT RUNS
Hermetic. Each case invokes the REAL guard script as a subprocess with a real
PreToolUse hook payload on stdin. `cwd` is carried IN THE PAYLOAD (that is what
the guard reads), so no directory has to exist and the probe never touches the
live tree. The exit code is the whole contract: 2 = block, 0 = allow.

NEGATIVE SELF-TEST
`--self-test` runs one case with a deliberately WRONG expectation and requires
the runner to report MISMATCH. A harness that cannot fail proves nothing; this
is the case that proves it can. It runs by default, before the real cases.
"""

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# repro/ -> claude-changes/ -> output/ -> q-system/ -> <root>
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
GUARD = os.path.join(ROOT, "q-system", ".q-system", "scripts",
                     "claude-path-write-guard.py")

# A plausible agent worktree under .claude/, matching the live registered ones.
WT = os.path.join(os.path.expanduser("~"), "projects", "kipi-system",
                  ".claude", "worktrees", "opus-fallback")
REPO = os.path.join(os.path.expanduser("~"), "projects", "kipi-system")

BLOCK, ALLOW = 2, 0

# (kind, command, cwd, expected_exit)
CASES = [
    # ---- ATTACK: the write shapes the guard exists to stop. 7 cases.
    ("ATTACK", "touch .claude/_probe.txt", REPO, BLOCK),
    ("ATTACK", 'echo pwned > ".claude/settings.json"', REPO, BLOCK),
    ("ATTACK", "cd .claude && touch evil.txt", REPO, BLOCK),
    ("ATTACK", "D=.claude; touch $D/x", REPO, BLOCK),
    ("ATTACK", "python3 -c \"open('.claude/settings.json','w')\"", REPO, BLOCK),
    ("ATTACK", "echo .claude/rules/x | xargs touch", REPO, BLOCK),
    ("ATTACK", "cp /tmp/x $HOME/projects/kipi-system/.claude/settings.json", REPO, BLOCK),
    # A MULTI-LINE interpreter payload. Newline-carrying tokens stopped being
    # treated as path candidates (so a commit message stops false-blocking), so
    # this pins the shape that must NOT ride through on that: an interpreter is
    # matched against the raw segment, never via path resolution.
    ("ATTACK",
     'python3 -c "import io\nopen(\'.claude/settings.json\',\'w\').write(\'x\')"',
     REPO, BLOCK),
    # Same for a multi-line redirect: matched by regex on the segment.
    ("ATTACK", 'printf "line one\nline two" > .claude/rules/security.md', REPO, BLOCK),

    # ---- LOOP: ordinary agent work from a worktree that happens to live under
    # .claude/worktrees/. Every one of these was blocked before the fix, because
    # the bare subcommand token resolved to a path under cwd.
    ("LOOP", 'git commit -m "ASK-291: fix"', WT, ALLOW),
    ("LOOP", "python3 -m pytest tests/", WT, ALLOW),
    ("LOOP", "gh pr create --fill", WT, ALLOW),
    ("LOOP", "git push origin HEAD", WT, ALLOW),
    # Same watch-set question stated directly rather than via a bare token: a
    # write to a path INSIDE the scratch subtree. Layer 2 does not watch it, so
    # Layer 1 must not block it either.
    ("LOOP", "touch %s" % os.path.join(WT, "scratch.txt"), REPO, ALLOW),

    # Committing a sanctioned apply. `git add` reads the worktree and writes the
    # INDEX; it cannot alter a file under .claude/. Blocking it means the founder
    # can arm the guards but never commit the arming -- measured live 2026-08-03:
    #   BLOCKED: git add targets .claude/: .../.claude/settings.json
    # A guard that blocks the legitimate path is a different outage.
    ("LOOP", "git add .claude/settings.json", REPO, ALLOW),
    # ...and committing it with a message that DESCRIBES the change. The message
    # quotes the guard's own stderr, whose first line begins ".claude/ wires
    # every hook". A quote-blind statement split turned that line into a fake
    # statement with a bare `.claude` in program position, so the guard blocked
    # the commit of its own arming (measured live 2026-08-03). The `|` and `;`
    # inside the message are data, not operators.
    ("LOOP",
     'git commit -m "arm the guards (ASK-291)\n\n'
     'BLOCKED: git add targets .claude/: /repo/.claude/settings.json\n'
     '.claude/ wires every hook, rule and agent; an agent that writes there\n'
     'reverted 1 | quarantined at q-system/output/claude-integrity/quarantine\n"',
     REPO, ALLOW),

    # ---- BENIGN: reads and the sanctioned write path. Must stay allowed.
    ("BENIGN", "cat .claude/settings.json", REPO, ALLOW),
    ("BENIGN", "git status .claude/", REPO, ALLOW),
    # The write-capable git subcommands stay blocked. `add` is allowed because it
    # writes the index; `checkout` and `restore` write the worktree.
    ("ATTACK", "git checkout -- .claude/settings.json", REPO, BLOCK),
    ("ATTACK", "git restore .claude/rules/security.md", REPO, BLOCK),
    ("BENIGN", "ls -la /tmp", REPO, ALLOW),
    # HEREDOC BODIES ARE DATA, NOT STATEMENTS (2026-08-03, the second false block
    # in a row on the legitimate path). This exact shape -- a commit message
    # describing the guard, quoting its own stderr -- was shredded line by line
    # and a prose line became a bare command with `.claude` in argument position.
    ("BENIGN",
     "git commit -F - <<'MSG'\nfix(guard): arm it\n\n.claude/ wires every hook;\n"
     "the run would write inside .claude/ and touch .claude/rules/x\nMSG",
     REPO, ALLOW),
    # The negative half: dropping the BODY must not drop the REDIRECT. A heredoc
    # aimed INTO .claude/ is still the write the guard exists to stop.
    ("ATTACK", "cat > .claude/settings.json <<'EOF'\n{\"hooks\":{}}\nEOF", REPO, BLOCK),
    ("BENIGN",
     "bash q-system/.q-system/scripts/apply-claude-changes.sh "
     "q-system/output/claude-changes/arm-claude-write-path-guards.json",
     REPO, ALLOW),
]


def run_case(command, cwd):
    """Invoke the real guard with a real hook payload. Returns (exit, stderr)."""
    payload = json.dumps({
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": cwd,
    })
    proc = subprocess.run([sys.executable, GUARD], input=payload,
                          capture_output=True, text=True, timeout=30)
    return proc.returncode, proc.stderr.strip()


def report(kind, command, cwd, expected):
    got, err = run_case(command, cwd)
    ok = got == expected
    print("%-7s %-6s exit=%d expected=%d  %s"
          % (kind, "ok" if ok else "MISMATCH", got, expected, command))
    if not ok and err:
        print("        %s" % err.splitlines()[0])
    return ok


def self_test():
    """Prove the runner can report a failure. Asserts a KNOWN block is reported
    as a mismatch when the expectation is deliberately wrong."""
    got, _ = run_case("touch .claude/_probe.txt", REPO)
    if got == ALLOW:
        print("SELF-TEST FAILED: the guard allowed a write it must block")
        return False
    if got != BLOCK:
        print("SELF-TEST FAILED: unexpected exit %d from the guard" % got)
        return False
    print("SELF-TEST ok: a wrong expectation (expected=0) on `touch "
          ".claude/_probe.txt` reports exit=2, i.e. this harness can fail")
    return True


def main():
    if not os.path.isfile(GUARD):
        print("guard not found: %s" % GUARD)
        return 2
    print("guard: %s\n" % os.path.relpath(GUARD, ROOT))

    if not self_test():
        return 2
    print()

    results = [report(*c) for c in CASES]
    bad = [c for c, ok in zip(CASES, results) if not ok]
    print("\n%d/%d cases match" % (len(results) - len(bad), len(results)))
    for kind, command, _cwd, _exp in bad:
        print("  MISMATCH %s: %s" % (kind, command))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
