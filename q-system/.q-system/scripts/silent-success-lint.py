#!/usr/bin/env python3
"""Find failure paths that succeed quietly: a releasing outcome from a failed or
absent input, with nobody told.

ASK-213. Three instances landed on 2026-07-27, each one introduced *inside a fix
for something else*, and each caught only because a human happened to look:

  linear-worker.sh   `if ! git fetch; then say ...; exit 0` -- a dead credential
                     at 3am was byte-for-byte a healthy no-work run.
  --reset-rounds     `python3 -c ... >/dev/null 2>&1 || true` then an
                     unconditional "reset to 0" -- an unwritable ledger, a
                     missing key and a corrupt file all printed success.
  pr-verdict-lib.sh  `else printf 'APPROVE'` at the foot of a severity ladder --
                     an empty findings block released the PR, on the fleet's
                     only required review gate (2026-08-02, ASK-312).

The general shape is not "exit 0 on failure". It is A RELEASING OUTCOME DERIVED
FROM AN EMPTY OR ABSENT INPUT. Six detectors below, three per language.

PRECISION BEATS RECALL, deliberately (DoR blast radius). A false-positive rate
above roughly one per run gets a required check bypassed inside a day, and a
bypassed gate protects nothing. Every detector here is narrowed until the known
negative fixtures are quiet -- see test/fixtures/silent-success/.

HONEST BOUNDARY -- what this does NOT catch, stated so its silence is not read
as proof (evidence-ledger.md):
  * cross-file shapes. The launchd-health-check.py `errors`-bucket defect (a key
    written that no other file reads) needs a whole-repo reachability pass, not
    a per-file one. Split out on purpose, per the issue's binding Not-doing
    line; captured as its own spillover item, never dropped.
  * dynamic dispatch, `eval`, and shell inside heredocs handed to another
    interpreter. The reset-rounds fixture is caught by its SHELL shape; the
    `except Exception: d={}` inside its python3 -c string is invisible to the
    AST pass because it is a string literal to Python.
  * whether a suppression comment is TRUE. Like `# linear-filer:
    human-in-the-loop`, a declaration is accepted at face value. The gate asks
    that a permissive branch be EXPLAINED, never that the explanation is honest.
  * a failure path that is loud but wrong. Notification is checked by token, so
    `>&2 echo "all good"` clears SS001.

EXIT CODES
  0  no findings (or --report / --json, which always exit 0)
  1  findings present
  2  usage / scan error
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys

# --- suppression -------------------------------------------------------------
# One marker, no stacking (skill-hook-pairing.md "Override"). It carries a reason
# because a bare off-switch teaches nothing to the next reader.
SKIP_RE = re.compile(r"#\s*silent-success-ok:\s*\S")

# A line whose failure being ignored is the POINT and is unrecoverable anyway.
NOTIFY_TOKENS = (
    "NOTIFY",
    "slack-notify",
    "notify",
    "alert-to-linear",
    "page_once",
    "page ",
    ">&2",
)

# Words a script prints when it believes it succeeded.
SUCCESS_WORD_RE = re.compile(
    r"\b(reset to|success|succeeded|done|complete[d]?|updated|written|wrote|"
    r"synced|ok\b|all set|clean|healthy|no problems)",
    re.IGNORECASE,
)

# Values that RELEASE rather than hold, at the foot of a graded ladder.
PERMISSIVE_RE = re.compile(
    r"\b(APPROVE|APPROVED|PASS(ED)?|OK|SUCCESS|GREEN|HEALTHY|ALLOW|CLEAN|MERGE)\b"
)

# Directories that are not the repo's own running code.
EXCLUDE_DIR_PARTS = (
    "/test/fixtures/",
    "/tests/fixtures/",
    "/fixtures/",
    "/node_modules/",
    "/.git/",
    "/.venv/",
    "/site-packages/",
)
EXCLUDE_PREFIXES = (
    ".pr22rev/",
    ".pr25rev/",
    ".pr28rev/",
    ".review-scratch/",
)


class Finding:
    def __init__(self, path, line, code, title, detail):
        self.path, self.line, self.code = path, line, code
        self.title, self.detail = title, detail

    def as_dict(self):
        return {
            "path": self.path,
            "line": self.line,
            "code": self.code,
            "title": self.title,
            "detail": self.detail,
        }

    def render(self):
        return "%s:%d: %s %s\n    %s" % (
            self.path,
            self.line,
            self.code,
            self.title,
            self.detail,
        )


# =============================================================================
# shell
# =============================================================================

# `if ! <command>; then` -- a COMMAND-failure guard. `if ! [ ... ]` and
# `if ! [[ ... ]]` are excluded: those negate a condition (is the queue empty?),
# which is an ordinary branch, not a failure path.
FAIL_GUARD_RES = (
    re.compile(r"^\s*if\s+!\s+(?!\[)"),
    re.compile(r"^\s*(el)?if\s+\[+\s*[\"']?\$[\{(]?(\?|rc|RC|status)\b.*-ne\s+0"),
    re.compile(r"\|\|\s*\{\s*$"),
)

# Output-suppressing swallow: the rc is discarded AND the diagnostics with it.
SWALLOW_RE = re.compile(r"(\|\|\s*true\s*$)|(2>\s*/dev/null.*\|\|\s*true)")

REPORT_RE = re.compile(r"^\s*(say|echo|printf|log|info)\b")


def _shell_block(lines, start):
    """Body of the shell block opened at `start`, as (index, text) pairs.

    Depth-counted on if/fi and brace pairs. Cheap and wrong for exotic quoting;
    a block it cannot close is truncated at EOF rather than silently swallowing
    the rest of the file into one finding.
    """
    depth = 0
    out = []
    for i in range(start, len(lines)):
        raw = lines[i]
        stripped = raw.strip()
        if i > start:
            out.append((i, raw))
        if re.match(r"^\s*(el)?if\b", raw) and i == start:
            depth += 1
        elif re.match(r"^\s*if\b", raw):
            depth += 1
        if raw.rstrip().endswith("|| {") and i == start:
            depth += 1
        if stripped in ("fi", "}") or stripped.startswith("fi ") or stripped == "};":
            depth -= 1
            if depth <= 0:
                return out[:-1]
        if re.match(r"^\s*(else|elif)\b", raw) and i > start and depth == 1:
            return out[:-1]
    return out


def _has(text, tokens):
    return any(t in text for t in tokens)


def scan_shell(path, text):
    findings = []
    lines = text.splitlines()

    for i, raw in enumerate(lines):
        if SKIP_RE.search(raw):
            continue

        # --- SS001: a command-failure guard that exits 0 and pages nobody -----
        if any(r.search(raw) for r in FAIL_GUARD_RES):
            body = _shell_block(lines, i)
            body_text = "\n".join(b for _, b in body)
            if SKIP_RE.search(body_text):
                continue
            exits = [
                (j, b) for j, b in body if re.search(r"^\s*(exit|return)\s+0\s*$", b)
            ]
            if not exits:
                continue
            if _has(body_text, NOTIFY_TOKENS):
                continue
            # A branch that ALSO leaves non-zero somewhere is not silent.
            if re.search(r"^\s*(exit|return)\s+[1-9]", body_text, re.M):
                continue
            j, _ = exits[0]
            findings.append(
                Finding(
                    path,
                    j + 1,
                    "SS001",
                    "failure guard exits 0 without notifying",
                    "the branch opened at line %d fires when a command FAILED, "
                    "then leaves with rc=0 and no NOTIFY/stderr page. A caller "
                    "cannot tell this run from a healthy no-op. Page and exit "
                    "non-zero, or declare it with `# silent-success-ok: <why>`."
                    % (i + 1),
                )
            )

        # --- SS002: rc swallowed, then success reported ----------------------
        if SWALLOW_RE.search(raw):
            look = 0
            for j in range(i + 1, min(i + 5, len(lines))):
                nxt = lines[j]
                if not nxt.strip():
                    continue
                look += 1
                if look > 3:
                    break
                if SKIP_RE.search(nxt):
                    break
                # A block boundary means the report belongs to an OUTER scope and
                # is not this swallow's report. Measured: without this, the
                # `release ... || true` at the foot of linear-worker.sh's per-issue
                # loop paired with the run-level `say "worker: run complete"` four
                # lines later, across a `done`. Precision beats recall (DoR).
                if re.match(r"^\s*(done|fi|esac|\}|\)|;;)\s*$", nxt):
                    break
                # An rc/emptiness check between the swallow and the report means
                # the value IS inspected -- converge.sh's release_stale_claim.
                if re.search(r"^\s*\[+.*\]+", nxt) or re.search(r"\$\?", nxt):
                    break
                if REPORT_RE.match(nxt) and SUCCESS_WORD_RE.search(nxt):
                    findings.append(
                        Finding(
                            path,
                            j + 1,
                            "SS002",
                            "success reported after the rc was discarded",
                            "line %d discards the exit status, and this line "
                            "reports success anyway. Read the result back "
                            "before reporting it, or declare it with "
                            "`# silent-success-ok: <why>`." % (i + 1),
                        )
                    )
                    break
                if REPORT_RE.match(nxt):
                    break

        # --- SS003: unexplained permissive terminal else ---------------------
        m = re.match(r"^(\s*)else\b(.*)$", raw)
        if m:
            indent, tail = m.group(1), m.group(2)
            ladder_start = _ladder_start(lines, i, indent)
            if ladder_start is None:
                continue
            body = tail + "\n" + "\n".join(
                b for _, b in _shell_block(lines, i)
            )
            if SKIP_RE.search(body):
                continue
            if not PERMISSIVE_RE.search(body):
                continue
            if _attached_comment_chars(lines, i) >= 40:
                continue
            findings.append(
                Finding(
                    path,
                    i + 1,
                    "SS003",
                    "graded ladder falls through to a permissive value, unexplained",
                    "the ladder opened at line %d grades its cases, then this "
                    "terminal else releases (%s) for everything left over -- "
                    "including an EMPTY input, which is the pr-verdict-lib "
                    "shape. If that is deliberate, say why in a comment "
                    "attached to this else (>=40 chars) or "
                    "`# silent-success-ok: <why>`."
                    % (ladder_start + 1, PERMISSIVE_RE.search(body).group(0)),
                )
            )
    return findings


def _ladder_start(lines, else_idx, indent):
    """Index of the `if` this `else` closes, but only if it is a graded LADDER.

    A plain if/else is an ordinary two-way branch and is not this defect. A
    ladder (>=1 elif) is a grader, and the foot of a grader is where an
    unclassified input gets a class it did not earn.
    """
    saw_elif = False
    for j in range(else_idx - 1, -1, -1):
        raw = lines[j]
        if not raw.startswith(indent) or raw[len(indent) : len(indent) + 1] in (" ", "\t"):
            if re.match(r"^\s*(if|elif)\b", raw) is None:
                continue
        if re.match(r"^%selif\b" % re.escape(indent), raw):
            saw_elif = True
        elif re.match(r"^%sif\b" % re.escape(indent), raw):
            return j if saw_elif else None
        elif re.match(r"^%s(fi|else)\b" % re.escape(indent), raw):
            return None
    return None


def _attached_comment_chars(lines, idx):
    """Comment characters directly above line `idx`, with no blank line between.

    This is the ONE discriminator between pr-verdict-lib.sh at 4b4dd3e (the
    defect) and at 5495a9b (the same branch, deliberate) -- the two versions of
    that function differ by nothing else. Same posture as
    automated-filer-marking.md: the deterministic
    half asks whether a posture is DECLARED; whether it is true stays a
    judgment the author owns.
    """
    total = 0
    for j in range(idx - 1, -1, -1):
        s = lines[j].strip()
        if not s:
            break
        if not s.startswith("#"):
            break
        total += len(s.lstrip("# ").strip())
    return total


# =============================================================================
# python
# =============================================================================

EMPTY_DEFAULTS = ({}, [], (), set(), "", 0, None, False)


def _is_empty_default(node):
    if isinstance(node, ast.Constant):
        return node.value in ("", 0, None, False)
    if isinstance(node, (ast.Dict, ast.List, ast.Tuple, ast.Set)):
        return not (getattr(node, "elts", None) or getattr(node, "keys", None))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        return node.func.id in ("dict", "list", "set", "tuple", "str", "int") and not node.args
    return False


def _handler_is_loud(handler):
    """Does this handler tell anyone? raise / log / warn / notify / write."""
    for n in ast.walk(handler):
        if isinstance(n, ast.Raise):
            return True
        if isinstance(n, ast.Call):
            src = ast.dump(n.func)
            if any(
                k in src
                for k in (
                    "log",
                    "warn",
                    "error",
                    "critical",
                    "exception",
                    "print",
                    "notify",
                    "alert",
                    "write",
                    "append",
                )
            ):
                return True
    return False


def _exit_zero(node):
    """`sys.exit(0)` / `raise SystemExit(0)` / `os._exit(0)`, or a bare exit()."""
    if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
        f = node.exc.func
        if getattr(f, "id", None) == "SystemExit" or getattr(f, "attr", "") == "SystemExit":
            return not node.exc.args or _is_zero(node.exc.args[0])
    if isinstance(node, ast.Call):
        f = node.func
        name = getattr(f, "attr", None) or getattr(f, "id", None)
        if name in ("exit", "_exit"):
            return not node.args or _is_zero(node.args[0])
    return False


def _is_zero(node):
    return isinstance(node, ast.Constant) and node.value == 0


def scan_python(path, text):
    findings = []
    lines = text.splitlines()

    def skipped(lineno):
        for j in (lineno - 1, lineno - 2):
            if 0 <= j < len(lines) and SKIP_RE.search(lines[j]):
                return True
        return False

    try:
        tree = ast.parse(text)
    except SyntaxError:
        return findings

    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        if skipped(node.lineno):
            continue
        body = node.body

        # --- SS101: except ...: pass -----------------------------------------
        if len(body) == 1 and isinstance(body[0], ast.Pass):
            findings.append(
                Finding(
                    path,
                    node.lineno,
                    "SS101",
                    "exception swallowed whole",
                    "the handler body is `pass`, so a real failure and a clean "
                    "run are indistinguishable downstream. Log it, re-raise it, "
                    "or declare it with `# silent-success-ok: <why>`.",
                )
            )
            continue

        # --- SS102: handler rebuilds state from a default and continues ------
        rebinds = [
            s
            for s in body
            if isinstance(s, ast.Assign) and _is_empty_default(s.value)
        ]
        if rebinds and len(rebinds) == len(body) and not _handler_is_loud(node):
            tgt = rebinds[0].targets[0]
            findings.append(
                Finding(
                    path,
                    node.lineno,
                    "SS102",
                    "handler rebuilds state from an empty default and continues",
                    "`%s` is reset to an empty value on failure and execution "
                    "continues, so a corrupt or unreadable input becomes an "
                    "empty one -- the --reset-rounds shape, which is silent "
                    "DATA LOSS. Refuse to write what you could not read, or "
                    "declare it with `# silent-success-ok: <why>`."
                    % (getattr(tgt, "id", ast.dump(tgt)[:40])),
                )
            )
            continue

        # --- SS103: an error branch that leaves with rc=0 --------------------
        if _handler_is_loud(node):
            continue
        for s in ast.walk(node):
            inner = s.value if isinstance(s, ast.Expr) else s
            if _exit_zero(inner):
                findings.append(
                    Finding(
                        path,
                        getattr(inner, "lineno", node.lineno),
                        "SS103",
                        "error handler exits 0",
                        "this path is reached only because something FAILED, "
                        "and it leaves with rc=0 having told nobody. The caller "
                        "reads it as a clean run. Exit non-zero, or declare it "
                        "with `# silent-success-ok: <why>`.",
                    )
                )
                break

    return findings


# =============================================================================
# driver
# =============================================================================


def tracked_files(root):
    out = subprocess.run(
        ["git", "-C", root, "ls-files", "-z"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [p for p in out.split("\0") if p]


def included(rel):
    if rel.startswith(EXCLUDE_PREFIXES):
        return False
    probe = "/" + rel
    if any(part in probe for part in EXCLUDE_DIR_PARTS):
        return False
    return rel.endswith(".sh") or rel.endswith(".py")


def scan_path(root, rel):
    full = os.path.join(root, rel)
    try:
        with open(full, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except (OSError, IsADirectoryError):
        return []
    if SKIP_RE.search(text.split("\n", 1)[0]):
        return []
    if rel.endswith(".py"):
        return scan_python(rel, text)
    return scan_shell(rel, text)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("paths", nargs="*", help="files to scan (default: repo-wide)")
    ap.add_argument("--root", default=None, help="repo root (default: git toplevel)")
    ap.add_argument("--json", action="store_true", help="machine-readable, exit 0")
    ap.add_argument(
        "--report",
        action="store_true",
        help="print findings and the count, exit 0 (baseline measurement)",
    )
    args = ap.parse_args(argv)

    root = args.root or subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    if not root or not os.path.isdir(root):
        sys.stderr.write("silent-success-lint: no git root; pass --root\n")
        return 2

    if args.paths:
        rels = []
        for p in args.paths:
            ap_ = os.path.abspath(p)
            rels.append(os.path.relpath(ap_, root) if ap_.startswith(root) else p)
        findings = [f for rel in rels for f in scan_path(root, rel)]
    else:
        findings = [
            f
            for rel in tracked_files(root)
            if included(rel)
            for f in scan_path(root, rel)
        ]

    # Two swallow lines can point at ONE report line (break-glass-main-protection
    # .sh:179 did), and reporting the same anchor twice inflates the count a
    # gate decision is made on. One anchor, one finding.
    seen, deduped = set(), []
    for f in findings:
        key = (f.path, f.line, f.code)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(f)
    findings = deduped
    findings.sort(key=lambda f: (f.code, f.path, f.line))

    if args.json:
        print(json.dumps({"count": len(findings),
                          "findings": [f.as_dict() for f in findings]}, indent=2))
        return 0

    for f in findings:
        print(f.render())
    by_code = {}
    for f in findings:
        by_code[f.code] = by_code.get(f.code, 0) + 1
    print(
        "\nsilent-success-lint: %d finding(s)%s"
        % (
            len(findings),
            (" [" + ", ".join("%s=%d" % kv for kv in sorted(by_code.items())) + "]")
            if by_code
            else "",
        )
    )
    if args.report:
        return 0
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
