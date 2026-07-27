"""Re-run the drafter under launchd's actual environment: the minimal PATH that
`/bin/bash -lc` produced under launchd (no ~/.local/bin, because -l sources bash
login files and the founder's shell is zsh). This is the condition that killed
8 of 8 drafts on 2026-07-27.
"""
import os
import subprocess
import sys

env = dict(os.environ)
env["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"

r = subprocess.run(
    [sys.executable, "q-system/.q-system/scripts/linear-dor-drafter.py",
     "--limit", "1", "--apply"],
    env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL,
)
print("PATH used:", env["PATH"])
print("rc:", r.returncode)
print("--- stdout ---")
print(r.stdout.strip())
print("--- stderr ---")
print(r.stderr.strip() or "(empty)")
