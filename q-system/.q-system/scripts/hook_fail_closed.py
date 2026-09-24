#!/usr/bin/env python3
"""hook_fail_closed -- a blocking hook that CRASHES refuses inside its jurisdiction.

## The defect class (ASK-1180)

A blocking hook refuses only if one specific line runs: `sys.exit(2)`, or a
`print` of permissionDecision deny JSON. An uncaught exception exits 1, which is
neither, so the tool call proceeds. Any hook whose decision path can raise
therefore reports "checked and fine" by construction.

Measured through the real stdin interface, not argued:

  merge-bypass-gate (ASK-1179)  a NameError on `gh pr merge <n> --squash`, the one
                                form the gate exists to refuse: EXIT=1, no deny.
  claude-path-write-guard       a crash injected as the first statement of
                                analyse(): rc=1, blocks=False, while the live
                                guard returns rc=2 on the same payload.

## Why split by JURISDICTION and not "deny on every exception"

Several of these gates are PreToolUse on Bash, so they run on every shell command
in the session. A blanket deny lets one bug brick every command, including the
ones needed to fix it. ASK-1179's shape is the one worth copying: a crash on
input the gate GOVERNS is refused, because "I could not tell" and "it is safe"
are different answers. A crash on input it never had an opinion about is
allowed. The traceback goes to stderr either way, because the failure being
repaired is a gate that broke quietly.

## Why the refusal is exit 2 on every event, never deny JSON

Exit 2 blocks PreToolUse, feeds stderr back on PostToolUse, and blocks a Stop.
A deny JSON on stdout only works if stdout is ONE clean JSON document, and a gate
that crashed half way may already have printed to it. Two documents on stdout
parse as neither, and an unparseable PreToolUse stdout is an allow. The crash
path must not depend on how far the crashed code got.

## Contract

    run(call, gate="name", in_jurisdiction=fn)

`call` is the hook's existing entry point, called with no arguments. stdin is
read ONCE here and handed back to it unchanged as a StringIO, so the entry point
reads its payload exactly as before. `in_jurisdiction(payload_dict)` must be
trivially safe: raw substrings and dict lookups, no parsing, because it runs
only after the gate's own code has already raised. If it raises too, the answer
is refuse: this module cannot tell, so it does not say safe.

SystemExit passes through untouched: a gate's own `sys.exit(2)` is its refusal,
and its own `sys.exit(0)` is its verdict. Only an unexpected exception is ours.
"""
from __future__ import annotations

import io
import json
import sys
import traceback

REFUSE = 2


def _payload(raw: str) -> dict:
    try:
        data = json.loads(raw) if raw.strip() else {}
    except Exception:  # noqa: BLE001 - a malformed payload has no fields to judge
        return {}
    return data if isinstance(data, dict) else {}


def crash_verdict(gate: str, raw: str, in_jurisdiction, exc: BaseException) -> int:
    """The exit code for a gate whose own code raised. Traceback already printed."""
    try:
        inside = bool(in_jurisdiction(_payload(raw)))
    except Exception:  # noqa: BLE001
        traceback.print_exc(file=sys.stderr)
        inside = True
    if not inside:
        sys.stderr.write(
            f"{gate}: crashed on input outside its jurisdiction; allowed. "
            "The traceback above is a real bug in the gate (ASK-1180).\n")
        return 0
    sys.stderr.write(
        f"{gate}: CRASHED ({type(exc).__name__}: {exc}) on input it governs, so it "
        "cannot say this is safe. Refusing rather than guessing (ASK-1180). The "
        "traceback above is the bug to fix; the refusal lifts when the gate runs "
        "again without raising.\n")
    return REFUSE


def run(call, *, gate: str, in_jurisdiction) -> int:
    raw = "" if sys.stdin is None or sys.stdin.isatty() else sys.stdin.read()
    sys.stdin = io.StringIO(raw)
    try:
        rc = call()
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - converting a crash IS the job
        traceback.print_exc(file=sys.stderr)
        return crash_verdict(gate, raw, in_jurisdiction, exc)
    return 0 if rc is None else rc
