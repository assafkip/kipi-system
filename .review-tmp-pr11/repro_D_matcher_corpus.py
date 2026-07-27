"""FINDING D: adversarial corpus against `_shells_claude`.

Each row is (cron command, what a human reading the crontab would say).
Printed as MATCH / miss so both directions are visible.
"""
from repro_common import fh

TRUE_POSITIVES = [
    # shapes a real crontab in this fleet would use
    ("claude -p 'x'", "bare"),
    ("timeout 1800 claude -p 'x' </dev/null", "timeout wrapper (shipped shape)"),
    ("cd ~/p && claude -p 'x'", "cd && claude"),
    ("bash -lc 'claude -p \"x\"'", "login shell"),
    ("/bin/zsh -lc 'cd ~/p && claude -p \"x\"'", "login shell + cd, inner dquote"),
    ("bash -lc \"cd ~/p && claude -p 'x'\"", "login shell + cd, inner squote"),
    ("nohup claude -p 'x' &", "nohup"),
    ("caffeinate -i claude -p 'x'", "caffeinate"),
    ("/usr/bin/env bash -lc 'claude -p x'", "env + login shell"),
    ("claude -p \"summarize what's new\"", "apostrophe inside double quotes"),
    ("bash -lc \"claude -p 'summarize what's new'\"", "apostrophe, nested"),
    ("bash -lc \"cd ~/p && claude -p 'what's new'\"", "apostrophe, nested + cd"),
    ("flock -n /tmp/x.lock claude -p 'x'", "flock lock wrapper"),
    ("ssh mini claude -p 'x'", "remote invocation"),
    ("sh -c 'sh -c \"sh -c \\\"claude -p x\\\"\"'", "3-deep nesting"),
]

TRUE_NEGATIVES = [
    ("cd ~/projects/claude && ./run.sh", "cd into a dir named claude"),
    ("bash ~/.claude/hooks/rotate-logs.sh", "script under ~/.claude"),
    ("claude-code --version", "claude-prefixed binary"),
    ("tar -czf /b/claude.tgz ~/projects/claude --exclude=node_modules", "tar backup"),
    ("du -sh ~/projects/claude --block-size=M >> ~/disk.log", "du"),
    ("echo 'migrate claude -p jobs to launchd' >> ~/todo.txt", "prose in quotes"),
    ("sudo -u claude /opt/svc/run.sh", "sudo -u <user named claude>"),
    ("sudo -u claude -H /opt/svc/run.sh", "sudo -u <user> -H"),
    ("rsync -a ~/projects/claude/ /Volumes/b/ --checksum", "rsync"),
    ("find ~/projects -name claude -type d", "find -name claude"),
]

print("=== lines a human would call REAL claude invocations ===")
missed = []
for cmd, why in TRUE_POSITIVES:
    hit = fh._shells_claude(cmd)
    print(f"  {'MATCH' if hit else 'miss '}  {why:38s}  {cmd}")
    if not hit:
        missed.append((cmd, why))

print()
print("=== lines a human would call BENIGN (a match here files a PERMANENT issue) ===")
false_pos = []
for cmd, why in TRUE_NEGATIVES:
    hit = fh._shells_claude(cmd)
    print(f"  {'MATCH' if hit else 'miss '}  {why:38s}  {cmd}")
    if hit:
        false_pos.append((cmd, why))

print()
print(f"SILENT FALSE NEGATIVES: {len(missed)}/{len(TRUE_POSITIVES)}")
for cmd, why in missed:
    print(f"   - {why}: {cmd}")
print(f"FALSE POSITIVES (permanent Linear issue): {len(false_pos)}/{len(TRUE_NEGATIVES)}")
for cmd, why in false_pos:
    print(f"   - {why}: {cmd}")
