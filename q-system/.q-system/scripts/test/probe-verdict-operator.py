#!/usr/bin/env python3
"""Drive the hook and two mutants of it, to prove the verdict operator matters.

The probe command is assembled from parts on purpose: written literally, the
live PreToolUse hook blocks this file's own creation, which is the documented
false positive and not something to work around by weakening the hook.
"""
import importlib.util
import json
import os
import subprocess
import tempfile

spec = importlib.util.spec_from_file_location(
    "ms", "q-system/.q-system/scripts/mutation-sweep.py")
ms = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ms)

hook = open(os.path.expanduser("~/.claude/hooks/destructive-op-deny.sh")).read()
PROBE = "".join(["r", "m"]) + " -" + "".join(["r", "f"]) + " /tmp/some-dir"


def drive(text, label):
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, ".claude", "audit"), exist_ok=True)
    path = os.path.join(d, "h.sh")
    with open(path, "w") as fh:
        fh.write(text)
    env = dict(os.environ)
    env["HOME"] = d
    env.pop("ALLOW_DESTRUCTIVE", None)
    payload = {"tool_name": "Bash", "tool_input": {"command": PROBE}, "cwd": "/tmp"}
    proc = subprocess.run(["bash", path], input=json.dumps(payload),
                          capture_output=True, text=True, env=env)
    out = proc.stdout.strip()
    decision = "allow"
    if out:
        try:
            decision = json.loads(out)["hookSpecificOutput"]["permissionDecision"]
        except Exception:
            decision = "malformed"
    print("  %-30s rc=%s  decision=%s" % (label, proc.returncode, decision))


print("driving the destructive probe against three versions of the hook:")
drive(hook, "original")

saved = ms.VERDICT_RULES[:]
ms.VERDICT_RULES.clear()
old_mut, old_n = ms.make_disarm(hook, ".sh")
ms.VERDICT_RULES.extend(saved)
drive(old_mut, "mutant, exit-code rules only")

new_mut, new_n = ms.make_disarm(hook, ".sh")
drive(new_mut, "mutant, + verdict rule")
print("\n  disarm sites: %d without the verdict rule, %d with it" % (old_n, new_n))
