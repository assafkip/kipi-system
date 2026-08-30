#!/usr/bin/env python3
"""ASK-1144: `git push origin +main` is a force push and the hook allowed it.

PR #279 codex major. The push arm checked only FLAGS -- every spelling of
--force, --force-with-lease and a short f cluster -- and missed the form that
needs no flag at all. A leading-plus refspec rewrites remote history exactly as
--force does. Measured before the fix: three of these eight cases came back
`allow`.

Same shape ASK-1131 already found once: a rule that reads how the dangerous
thing is usually WRITTEN rather than what it DOES.

The four allow-cases are not padding. A push guard that denies every push is an
outage, and `echo a+b` pins that a `+` outside refspec position does not trip it.
"""
import json
import os
import subprocess
import sys
import tempfile

import os.path as _p
_HERE = _p.dirname(_p.abspath(__file__))
HOOK = (sys.argv[1] if len(sys.argv) > 1
        else _p.join(_p.dirname(_HERE), "hooks", "destructive-op-deny.sh"))

CASES = [
    ("git push origin +main", "deny"),
    ("git push origin +refs/heads/main:refs/heads/main", "deny"),
    ("git push --atomic origin +main", "deny"),
    ("git push origin " + "--force", "deny"),
    ("git push origin main", "allow"),
    ("git push -u origin feature/x", "allow"),
    ("git push origin HEAD:branch", "allow"),
    # `+` that is not a refspec position must not trip it.
    ("echo a+b", "allow"),
]


def drive(command):
    home = tempfile.mkdtemp()
    os.makedirs(os.path.join(home, ".claude", "audit"), exist_ok=True)
    env = dict(os.environ)
    env["HOME"] = home
    env.pop("ALLOW_DESTRUCTIVE", None)
    payload = {"tool_name": "Bash", "tool_input": {"command": command},
               "cwd": "/tmp"}
    proc = subprocess.run(["bash", HOOK], input=json.dumps(payload),
                          capture_output=True, text=True, env=env, timeout=30)
    if proc.returncode == 2:
        return "deny"
    out = (proc.stdout or "").strip()
    if not out:
        return "allow"
    try:
        return json.loads(out)["hookSpecificOutput"]["permissionDecision"]
    except Exception:
        return "error"


bad = 0
for command, want in CASES:
    got = drive(command)
    mark = "ok  " if got == want else "FAIL"
    if got != want:
        bad += 1
    print("  %s %-52s want=%-5s got=%s" % (mark, command, want, got))
print("\n%d wrong" % bad)
sys.exit(1 if bad else 0)
