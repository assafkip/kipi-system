"""Runtime-receipt gate: a runtime-control fix cannot close on source-only evidence.

The scar (RCA 2026-10-02, recurrence 2026-10-06): a token gate and a scanner were
marked built because the source READ correctly. Neither had ever fired on the real
caller, and the burn they were built to stop came straight back. A gate, cap,
meter, budget, ledger, guard, limit, rate or quota is a RUNTIME property, so its
fix is only evidence once something has watched it act on a real call.

So both close chokepoints (prd-os `spillover resolve` / `promoted-audit`, and
kipi-dsse `issue_runner.py close`) ask this module two questions:

  1. `claims_runtime_control(text)`: does the item claim such a fix?
  2. `load_receipt(path)`: is there a receipt of a REAL call, and not a read of
     the source dressed up as one?

This file is mirrored byte-for-byte into plugins/kipi-dsse/scripts/: that plugin
stays import-independent of prd-os (the same contract as
SPILLOVER_REFUSED_SEVERITIES). `test_runtime_receipt_gate.py` pins the two copies
equal, so the term list below is still ONE list.

Producing a receipt: `python3 runtime_receipt.py capture --out r.json -- <cmd...>`
runs the command and records what it printed, so the output is observed rather
than typed.
"""
from __future__ import annotations

import hashlib
import json
import re
import shlex
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# THE one list. Whole words only, with the inflections people actually write
# ("capped", "metering", "rate-limit"), so "gatekeeper", "capture", "capital",
# "generate" and "accurate" never classify: a gate that fires on copy edits gets
# switched off, and an off gate protects nothing.
RUNTIME_CONTROL_TERMS = (
    "gate", "gates", "gated", "gating",
    "cap", "caps", "capped", "capping",
    "meter", "meters", "metered", "metering",
    "budget", "budgets", "budgeted",
    "ledger", "ledgers",
    "guard", "guards", "guarded", "guarding",
    "limit", "limits", "limited", "limiting", "limiter",
    "rate-limit", "rate-limits", "rate-limited", "rate-limiting",
    "rate", "rates",
    "quota", "quotas",
)
_TERM_RE = re.compile(
    r"(?<![A-Za-z0-9_])(" + "|".join(
        re.escape(t) for t in sorted(RUNTIME_CONTROL_TERMS, key=len, reverse=True)
    ) + r")(?![A-Za-z0-9_])",
    re.IGNORECASE,
)

RECEIPT_FIELDS = ("command", "output", "ran_at")

# Commands that only READ source. Any one of them alone is a belief about the
# code, never an observation of it running. The 2026-10-02 "proof" was exactly
# this: grep the ledger writer, read the gate, call it built.
SOURCE_ONLY_COMMANDS = frozenset({
    "grep", "egrep", "fgrep", "rg", "ag", "ack", "cat", "bat", "sed", "awk",
    "head", "tail", "less", "more", "wc", "nl", "find", "ls", "tree", "diff",
    "file", "stat", "strings", "read", "view", "echo", "printf", "true",
})
# git subcommands that read history or text without running anything.
SOURCE_ONLY_GIT = frozenset({"grep", "show", "diff", "log", "blame", "cat-file",
                             "ls-files", "status"})
# Wrappers whose real command is their argument.
_WRAPPERS = frozenset({"env", "time", "command", "nice", "nohup", "timeout",
                       "sudo", "xargs", "exec"})

# Built from this file's own location, so the kipi-dsse mirror names its own copy.
EXAMPLE = (f"python3 {Path(__file__).resolve()} capture "
           "--out receipt.json -- <the real caller, e.g. the job's own entry point>")
# git global options that take a VALUE: `git -C <path> grep` read the path as the
# subcommand and walked a pure source read through (PR #529 review, major 2).
_GIT_VALUE_OPTS = frozenset({"-C", "-c", "--git-dir", "--work-tree", "--namespace",
                             "--exec-path", "--super-prefix", "--config-env"})
# A caller that never got going. Exit 126/127 is "could not run"; a traceback or
# import error means the control under test was never reached (review, major 1).
# A plain nonzero exit is NOT refused: a gate that refuses exits nonzero on purpose.
_CRASH_RE = re.compile(r"Traceback \(most recent call last\)|ModuleNotFoundError|"
                       r"ImportError|SyntaxError|command not found|"
                       r"No such file or directory")


class ReceiptError(ValueError):
    """A receipt that is missing, malformed, or only reads source."""


def claims_runtime_control(text: str | None) -> list[str]:
    """The runtime-control words the text uses, lower-cased and deduped.

    Empty means the item makes no such claim and the gate does not apply."""
    seen: list[str] = []
    for m in _TERM_RE.finditer(text or ""):
        w = m.group(1).lower()
        if w not in seen:
            seen.append(w)
    return seen


def _python_is_source_only(argv: list[str]) -> bool:
    rest = argv[1:]
    if not rest:
        return False
    if rest[0] == "-c" and len(rest) > 1:
        # A one-liner whose statements are all imports (or an ast parse) has only
        # proven the module loads. Anything else is a call.
        stmts = [s.strip() for s in re.split(r"[;\n]", rest[1]) if s.strip()]
        return bool(stmts) and all(
            s.startswith(("import ", "from ")) or "ast." in s
            or re.fullmatch(r"print\(\s*open\(.*\)\.read\w*\(.*\)\s*\)", s)
            for s in stmts)
    if rest[0] == "-m" and len(rest) > 1:
        if rest[1] in ("py_compile", "compileall", "ast", "tokenize", "pyclbr"):
            return True
        if rest[1] == "pytest":
            return _pytest_is_collect_only(rest[2:])
    return False


def _pytest_is_collect_only(args: list[str]) -> bool:
    return any(a in ("--collect-only", "--co") for a in args)


def _segment_is_source_only(argv: list[str]) -> bool:
    while argv and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", argv[0]) or
                    Path(argv[0]).name in _WRAPPERS):
        argv = argv[1:]
        # `timeout 30 cmd`: drop the duration too.
        if argv and re.match(r"^\d+[smhd]?$", argv[0]):
            argv = argv[1:]
    if not argv:
        return True
    name = Path(argv[0]).name
    if name in ("bash", "sh", "zsh"):
        # `-c`, `-lc`, `-ec`...: any short-flag cluster carrying c takes the script.
        for i, a in enumerate(argv[1:-1], start=1):
            if re.fullmatch(r"-[a-z]*c[a-z]*", a):
                return command_is_source_only(argv[i + 1])
    if name in SOURCE_ONLY_COMMANDS:
        return True
    if name == "git":
        rest, sub = argv[1:], ""
        while rest:
            a = rest.pop(0)
            if a in _GIT_VALUE_OPTS:
                rest = rest[1:]
            elif not a.startswith("-"):
                sub = a
                break
        return sub in SOURCE_ONLY_GIT
    if re.match(r"^python[0-9.]*$", name):
        return _python_is_source_only(argv)
    if name in ("pytest", "py.test"):
        return _pytest_is_collect_only(argv[1:])
    return False


def command_is_source_only(command: str) -> bool:
    """True when EVERY segment of the command only reads source.

    One real invocation anywhere in a pipeline makes it a runtime receipt:
    `job.sh && grep row ledger.jsonl` ran the job and then looked at its row."""
    segs = _segments(command or "")
    return all(_segment_is_source_only(s) for s in segs) if segs else True


def _segments(command: str) -> list[list[str]]:
    """Split on | || && ; and newlines OUTSIDE quotes. A plain regex split cut
    `python3 -c 'import ast; ast.parse(...)'` in half and called it a real call."""
    lex = shlex.shlex(command.replace("\n", ";"), posix=True, punctuation_chars=";&|")
    lex.whitespace_split = True
    segs: list[list[str]] = [[]]
    try:
        for tok in lex:
            if tok and set(tok) <= set(";&|"):
                segs.append([])
            else:
                segs[-1].append(tok)
    except ValueError:
        return [command.split()]
    return [s for s in segs if s]


def _parse_ts(raw: str) -> datetime:
    ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def load_receipt(path: str | None, terms: list[str]) -> dict:
    """Validate a receipt file and return the reference to store on the row.

    Raises ReceiptError with a message naming what is missing and an example."""
    claim = ", ".join(terms)
    if not path:
        raise ReceiptError(
            f"this item claims a runtime-control fix ({claim}), so it needs a "
            "runtime receipt: --runtime-receipt <file> holding the exact command "
            "run against the REAL caller, its observed output and a timestamp. "
            f"Reading the source is not evidence (RCA 2026-10-02). Make one with:\n  {EXAMPLE}")
    p = Path(path)
    if not p.is_file():
        raise ReceiptError(f"runtime receipt not found: {path}. Make one with:\n  {EXAMPLE}")
    blob = p.read_bytes()
    try:
        data = json.loads(blob)
    except ValueError as exc:
        raise ReceiptError(f"runtime receipt {path} is not JSON ({exc}). "
                           f"Make one with:\n  {EXAMPLE}") from exc
    if not isinstance(data, dict):
        raise ReceiptError(f"runtime receipt {path} must be a JSON object")
    missing = [f for f in RECEIPT_FIELDS if not str(data.get(f) or "").strip()]
    if missing:
        raise ReceiptError(
            f"runtime receipt {path} is missing {', '.join(missing)}: it must carry "
            "the command, its observed output and when it ran. "
            f"Make one with:\n  {EXAMPLE}")
    try:
        ran_at = _parse_ts(data["ran_at"])
    except ValueError as exc:
        raise ReceiptError(f"runtime receipt {path}: ran_at is not an ISO "
                           f"timestamp ({data['ran_at']!r})") from exc
    if ran_at > datetime.now(timezone.utc) + timedelta(minutes=5):
        raise ReceiptError(f"runtime receipt {path}: ran_at is in the future")
    code = data.get("exit_code")
    if code in (126, 127) or (code not in (0, None) and _CRASH_RE.search(str(data["output"]))):
        raise ReceiptError(
            f"runtime receipt {path}: the caller crashed before it could exercise the "
            f"control (exit {code}). A crash is not runtime proof. Fix the run, then "
            f"capture again:\n  {EXAMPLE}")
    if command_is_source_only(str(data["command"])):
        raise ReceiptError(
            f"runtime receipt {path} only reads source ({data['command']!r}). grep, "
            "rg, cat, sed, an ast parse, git show/diff, or a test run that only "
            "imports cannot prove a runtime control fires. Run the real caller "
            f"and record what it did:\n  {EXAMPLE}")
    return {
        "path": str(p),
        "sha256": hashlib.sha256(blob).hexdigest(),
        "command": str(data["command"]),
        "ran_at": str(data["ran_at"]),
        "exit_code": data.get("exit_code"),
        "claim_terms": terms,
    }


def capture(out: str, argv: list[str]) -> int:
    """Run argv, and write a receipt of what it printed. Returns argv's exit code."""
    if not argv:
        sys.stderr.write("capture needs a command after --\n")
        return 2
    ran_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        proc = subprocess.run(argv, capture_output=True, text=True)
        code, output = proc.returncode, (proc.stdout + proc.stderr)[-8000:]
    except OSError as exc:
        code, output = 127, f"could not run: {exc}"
    # A real run that prints nothing is still an observation; record that it was
    # silent rather than writing an empty field the loader would refuse.
    output = output or f"(no output; exit {code})"
    Path(out).write_text(json.dumps({
        "command": shlex.join(argv), "output": output,
        "exit_code": code, "ran_at": ran_at,
    }, indent=2) + "\n")
    sys.stdout.write(output)
    return code


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) >= 3 and args[0] == "capture" and args[1] == "--out":
        rest = args[3:]
        if rest and rest[0] == "--":
            rest = rest[1:]
        return capture(args[2], rest)
    if len(args) == 2 and args[0] == "classify":
        print(json.dumps(claims_runtime_control(args[1])))
        return 0
    sys.stderr.write("usage: runtime_receipt.py capture --out <file> -- <cmd...>\n"
                     "       runtime_receipt.py classify '<item text>'\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
