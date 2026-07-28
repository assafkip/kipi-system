#!/usr/bin/env python3
"""RED/GREEN probe for the PR #27 review findings (ASK-215). Drives the
classifier directly so each finding's before/after is observable in one run.
Run: python3 q-system/output/ask215-red-probe.py
"""
import importlib.util
import os
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GUARD = os.path.join(REPO, "q-system/.q-system/token-guard.py")
spec = importlib.util.spec_from_file_location("tg", GUARD)
tg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tg)

LOCK = ("fatal: Unable to create '/tmp/r/.git/index.lock': File exists.\n\n"
        "Another git process seems to be running in this repository, or the "
        "lock file may be stale\n")
REFLOCK = ("fatal: cannot lock ref 'HEAD': Unable to create "
           "'/tmp/r/.git/refs/heads/main.lock': File exists.\n")
GPG = ("error: gpg failed to sign the data:\n(no gpg output)\n"
       "fatal: failed to write commit object\n")

print("F1 index.lock        ->", repr(tg._commit_gate_refusal(
    "git commit -m x", {"stderr": LOCK, "error": "Exit code 128"})))
print("F1 cannot lock ref   ->", repr(tg._commit_gate_refusal(
    "git commit -m x", {"stderr": REFLOCK, "error": "Exit code 128"})))
print("F1 gpg sign failure  ->", repr(tg._commit_gate_refusal(
    "git commit -m x", {"stderr": GPG, "error": "Exit code 128"})))
print("F1 unenumerated 128  ->", repr(tg._commit_gate_refusal(
    "git commit -m x", {"stderr": "fatal: nobody enumerated this\n",
                        "error": "Exit code 128"})))
print("F2 failing grep      ->", repr(tg._commit_gate_refusal(
    'grep -rn "git commit" q-system/canonical/', {"stderr": "", "error": "Exit code 1"})))
print("F2 grep resets vol   ->", tg._is_successful_commit(
    'grep -rn "git commit" q-system/canonical/', {"stdout": "a hit\n"}))

msg = os.path.join(tempfile.mkdtemp(), "msg.txt")
with open(msg, "w") as fh:
    fh.write("chore: no issue id here\n")
run = subprocess.run(
    [sys.executable, os.path.join(REPO, "q-system/.q-system/scripts/linear-issue-ref-check.py"), msg],
    capture_output=True, text=True)
print("F4 real gate name    ->", repr(tg._refusing_gate_name(run.stdout + run.stderr)))

print("F5 exit_code-only    ->", repr(tg._commit_gate_refusal(
    "git commit -m x", {"stderr": "BLOCK: bump plugin.json\n", "exit_code": 1})))
print("-- must still work --")
print("   real refusal      ->", repr(tg._commit_gate_refusal(
    "git commit -m x", {"stderr": "\U0001f94a plugin-version-bump: bump it. (0.1s)\n",
                        "error": "Exit code 1"})))
print("   real commit       ->", tg._is_successful_commit(
    "git commit -m 'fix (ASK-215)'", {"stdout": "[b abc] fix\n 1 file changed"}))
print("   nothing to commit ->", repr(tg._commit_gate_refusal(
    "git commit -m x", {"stdout": "nothing to commit, working tree clean",
                        "error": "Exit code 1"})))
