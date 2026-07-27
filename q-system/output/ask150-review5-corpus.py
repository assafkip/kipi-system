#!/usr/bin/env python3
"""Re-run the fifth review's OWN corpora against the reworked matcher.

Two jobs: prove the 3 MISSes are now caught, and prove nothing the reviewer said
it could NOT break got broken by the widening. Not a substitute for the suite --
the suite is where these live permanently; this is the reviewer-facing evidence.
"""
import importlib.util
from pathlib import Path

HEALTH = Path(__file__).resolve().parents[1] / ".q-system/scripts/fleet-health-daily.py"
spec = importlib.util.spec_from_file_location("fh", HEALTH)
fh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fh)

bad = []


def expect(command, want, label):
    got = fh._shells_claude(command)
    mark = "ok  " if got == want else "BAD "
    if got != want:
        bad.append(f"{command!r}: got {got}, want {want}")
    print(f"  {mark} [{label}] {command!r} -> {got}")


print("== review 5 finding 3: the 12-shape corpus (3 were MISS) ==")
for cmd in [
    'claude -p "x" >> ~/log 2>&1',
    'cd /x && claude -p "x" >> ~/log 2>&1',
    '/bin/bash -lc "source ~/.zshrc; claude -p x" >> ~/log 2>&1',
    'OUT=$(claude -p "x"); echo "$OUT"',
    'echo hi | claude -p "x"',
    '{ claude -p x ; }',
    'claude --print x',
    'nohup claude -p x &',
    'command claude -p x',
    '/usr/bin/env claude -p x',
    'sh -c "claude -p x" ; true',
    'if claude -p x ; then true ; fi',
]:
    expect(cmd, True, "invocation")

print("== review 5 finding 2: bundled short flags ==")
for cmd in ["sudo -Hu claude /opt/svc/run.sh", "sudo -nu claude /opt/svc/run.sh",
            "sudo -iu claude /opt/svc/run.sh", "sudo -u claude /opt/svc/run.sh"]:
    expect(cmd, False, "service account")

print("== NOT broken: the false-positive corpus every round has held ==")
for cmd in [
    "0 3 * * * tar -czf ~/backup.tgz ~/projects/claude",
    "0 4 * * * rsync -a ~/projects/claude/ ~/backup/claude/",
    "0 5 * * * du -sh ~/projects/claude",
    "0 6 * * * cd ~/projects/claude && git gc --prune=now",
    "0 7 * * * chmod -R u+rw ~/projects/claude",
]:
    expect(fh._cron_command(cmd), False, "housekeeping")
for cmd in ['notify-send "run claude -p tomorrow"',
            'echo "step one; claude -p x"',
            "bash ~/.claude/hooks/rotate-logs.sh",
            "claude-code --version",
            "flock -n /tmp/claude.lock /opt/svc/run.sh",
            "ssh claude@mini ./run.sh"]:
    expect(cmd, False, "not an invocation")

print("== NOT broken: shapes the widening could plausibly have cost ==")
expect("timeout 1800 claude -p 'x' </dev/null", True, "the fleet's real shape")
expect("flock -n /tmp/x.lock claude -p 'x'", True, "flock")
expect("sudo -uH claude -p 'x'", True, "-u's value is H, claude runs")
expect("timeout -sKILL 1800 claude -p 'x'", True, "-s's value is attached")
expect("command -v claude", False, "lookup, not a run")
expect("if [ -d ~/projects/claude ]; then ./run.sh; fi", False, "keyword, benign body")
expect("{ tar czf ~/projects/claude.tgz ~/p ; }", False, "group, benign body")
expect("find ~/projects/claude -name '*.log' -exec rm {} \\;", False, "find's {}")
expect("cp ~/a/{x,y} ~/projects/claude/", False, "brace expansion")

print()
if bad:
    print("REGRESSIONS:")
    for line in bad:
        print(f"  - {line}")
    raise SystemExit(1)
print("PASS: 3 MISSes now caught, 0 regressions across the reviewer's corpora")
