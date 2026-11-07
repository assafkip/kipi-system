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
     the source dressed up as one? Given the item's context it also checks the
     receipt BELONGS to the item: it names a file in the repo (one of the issue's
     allowed files when there are any), it ran after the item existed, and no
     other row already holds it.

This file is mirrored byte-for-byte into plugins/kipi-dsse/scripts/: that plugin
stays import-independent of prd-os (the same contract as
SPILLOVER_REFUSED_SEVERITIES). `test_runtime_receipt_gate.py` pins the two copies
equal, so the term list below is still ONE list.

Producing a receipt: `python3 runtime_receipt.py capture --out r.json -- <cmd...>`
runs the command and records what it printed, so the output is observed rather
than typed.

LIVE receipts (ASK-3830) are the same file and the same loader with `live=True`.
A spec's checked "Live:" deliverable names a record the RUNNING system writes
(a ledger row, a status line, a delivered message). 15 of the 23 closed chief gp-* specs
(measured 2026-11-06) closed with that box checked and "PENDING" in its text; none got its
record afterwards. A live receipt may READ (tail, grep) because reading the
running system's own record is the observation; what it may not do is read only
repo source, or name nothing at all.
"""
from __future__ import annotations

import hashlib
import json
import re
import shlex
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from fnmatch import fnmatch
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
           "--out receipt.json -- <the real caller, e.g. python3 path/to/the/changed/job.py>")
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


# Anything that could be a path. Quotes, `=` and `:` split tokens, so
# `--repo-root=/x`, `'README.md'` inside a `python3 -c` script and `x.py:12` all
# yield the bare path.
_PATHISH_RE = re.compile(r"[A-Za-z0-9_.~/+@-]+")


def _repo_files_named(command: str, repo_root: Path) -> list[str]:
    """Repo-relative posix paths of the existing files INSIDE repo_root that the
    command names. The interpreter (/usr/bin/python3) sits outside the repo, so
    it never counts; only the code under the repo does."""
    root = repo_root.resolve()
    found: list[str] = []
    for tok in _PATHISH_RE.findall(command or ""):
        if tok in (".", ".."):
            continue
        p = Path(tok).expanduser()
        try:
            rp = (p if p.is_absolute() else root / p).resolve()
            rel = rp.relative_to(root).as_posix()
        except (ValueError, OSError):
            continue
        if rel not in found and rp.is_file():
            found.append(rel)
    return found


def _records_named(command: str, repo_root: Path) -> list[str]:
    """Existing paths OUTSIDE repo_root that the command names past each
    segment's program word: the running system's records (~/.config/x/log.jsonl).
    The program itself (/usr/bin/python3, /bin/cat) is skipped, so an absolute
    interpreter path is never mistaken for a record."""
    root = repo_root.resolve()
    found: list[str] = []
    for seg in _segments(command or ""):
        for arg in seg[1:]:
            for tok in _PATHISH_RE.findall(arg):
                if not tok.startswith(("/", "~")) or tok in ("/", "~", "~/"):
                    continue
                try:
                    rp = Path(tok).expanduser().resolve()
                except (OSError, RuntimeError):
                    continue
                try:
                    rp.relative_to(root)
                    continue  # inside the repo: source, not a record
                except ValueError:
                    pass
                if rp.exists() and str(rp) not in found:
                    found.append(str(rp))
    return found


def _parse_ts(raw: str) -> datetime:
    ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def load_receipt(path: str | None, terms: list[str], *,
                 repo_root: str | Path | None = None,
                 bind_to: list[str] | None = None,
                 not_before: str | None = None,
                 used: dict[str, str] | None = None,
                 live: bool = False) -> dict:
    """Validate a receipt file and return the reference to store on the row.

    The keyword arguments bind the receipt to the item, and both runners always
    pass them. repo_root: the command must name a file in that repo; bind_to:
    and that file must be one of these (the issue's allowed files, globs
    allowed); not_before: the receipt must not predate the item; used: sha256 ->
    id of every OTHER row already holding a receipt. live: a Live-deliverable
    receipt (see the module docstring): bind_to is not applied, and a read is
    accepted when it reads a record outside the repo.

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
    # `!= 0`, not `not in (0, None)`: exit_code is optional, and a missing one
    # switched this check off for exactly the receipts nobody captured, so a
    # hand-written traceback passed as proof (PR #610 review, major 2).
    if code in (126, 127) or (code != 0 and _CRASH_RE.search(str(data["output"]))):
        raise ReceiptError(
            f"runtime receipt {path}: the caller crashed before it could exercise the "
            f"control (exit {code}). A crash is not runtime proof. Fix the run, then "
            f"capture again:\n  {EXAMPLE}")
    command = str(data["command"])
    records = _records_named(command, Path(repo_root)) if live and repo_root is not None else []
    if live and repo_root is not None and not records and not _repo_files_named(
            command, Path(repo_root)):
        raise ReceiptError(
            f"live receipt {path}: its command names no record of the running system "
            f"and no file in this repo ({command!r}), so it observed nothing. Read "
            f"or run the real record, e.g. tail -1 ~/.config/<app>/<ledger>.jsonl:\n"
            f"  {EXAMPLE}")
    if command_is_source_only(command) and not records:
        raise ReceiptError(
            f"runtime receipt {path} only reads source ({data['command']!r}). grep, "
            "rg, cat, sed, an ast parse, git show/diff, or a test run that only "
            "imports cannot prove a runtime control fires. Run the real caller "
            f"and record what it did:\n  {EXAMPLE}")
    # BINDING (PR #610 review, major 1). Everything above checks the receipt's
    # shape; nothing tied it to the item. `date` resolved a token-quota row, one
    # file resolved two unrelated rows, and a receipt dated 2020 passed. The bar
    # is ASK-1810's: this makes a junk receipt a deliberate act, not impossible.
    # A live receipt reads a record, not the changed code, so the allowed-files
    # binding does not apply to it; the record check above stands in for it.
    if repo_root is not None and not live:
        named = _repo_files_named(command, Path(repo_root))
        if bind_to:
            if not any(f == b or fnmatch(f, b) for f in named for b in bind_to):
                raise ReceiptError(
                    f"runtime receipt {path}: its command names none of this issue's "
                    f"allowed files ({', '.join(bind_to)}), so it cannot show the "
                    f"changed code ran ({command!r}). Run the real caller by its "
                    f"path:\n  {EXAMPLE}")
        elif not named:
            raise ReceiptError(
                f"runtime receipt {path}: its command names no file in this repo "
                f"({command!r}), so nothing it ran is the code the fix changed. "
                f"Run the real caller by its path:\n  {EXAMPLE}")
    if not_before:
        try:
            floor = _parse_ts(not_before)
        except ValueError:
            floor = None  # a malformed legacy timestamp must not wedge the close
        if floor is not None and ran_at < floor:
            raise ReceiptError(
                f"runtime receipt {path} ran at {data['ran_at']}, before this item "
                f"existed ({not_before}). It cannot prove a fix made since. Capture "
                f"a fresh run:\n  {EXAMPLE}")
    sha = hashlib.sha256(blob).hexdigest()
    if used and sha in used:
        raise ReceiptError(
            f"runtime receipt {path} was already used to close {used[sha]}. One "
            f"receipt proves one item. Capture a fresh run for this one:\n  {EXAMPLE}")
    return {
        "path": str(p),
        "sha256": sha,
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
