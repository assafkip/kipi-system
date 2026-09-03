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

THE RATCHET (--baseline) is how the repo-wide result is actually ENFORCED. The
detector on its own measures 173 findings and nothing can fail on that number:
a brand-new SS001 committed today moved the sweep 173 -> 174 and left the
required suite fully green (PR #230 review round 3, major). Demanding zero is
not available -- 173 is the real floor and a gate that is red on every PR the
day it lands gets bypassed within a day, which is why the DoR scopes CI arming
to "only if the baseline is clean". So the gate is per-file and directional:
the committed baseline pins how many findings of each code each file is allowed
to carry, and the check fails when any file GAINS one. Pre-existing debt stays
green; a new defect goes red. Cleanup and a zero-tolerance CI line remain
sp-b1be7b6d.

  python3 silent-success-lint.py --baseline <file>        # check, exit 2 on a gain
  python3 silent-success-lint.py --baseline-write <file>  # re-pin after a real fix
  python3 silent-success-lint.py --baseline <file> --baseline-ref <sha>   # on a PR

--baseline-ref is what stops the ratchet certifying itself. Read from the working
tree, the allowance and the code it constrains travel in the SAME commit, so a
branch that adds a defect and re-pins in one push clears the required check
(codex major, PR #230 r4). Pointed at the PR's base sha, the allowance comes from
a commit the PR cannot edit, so the re-pin buys nothing.

HONEST BOUNDARY ON THE RATCHET, specifically: it compares COUNTS per (code,
path). Deleting one SS101 from a file and adding a different SS101 to that same
file nets zero and passes. It is a floor against growth, not a fingerprint of
which findings are which, and a per-finding fingerprint would key on line
numbers that churn on every unrelated edit.

EXIT CODES
  0  no findings (or --report / --json / a held-or-improved ratchet, all exit 0)
  1  findings present
  2  usage / scan error, or a ratchet regression
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


# A `#` that opens a comment is at line start or follows whitespace. `${#arr}`
# and `$#` follow `{`/`$`, so they survive; a `#` inside a quoted string does
# not, which costs a false NEGATIVE at worst and never a false positive.
SHELL_COMMENT_RE = re.compile(r"(?m)(^|\s)#.*$")


def _strip_shell_comments(text):
    return SHELL_COMMENT_RE.sub(r"\1", text)


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
            # Notification has to be CODE. Scanning the raw body let a comment
            # carry the proof, so `# nothing here will notify anyone` cleared
            # the branch it was documenting as broken (codex minor, PR #230 r4).
            if _has(_strip_shell_comments(body_text), NOTIFY_TOKENS):
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


LOUD_STEMS = (
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


def _call_name_parts(func):
    """The dotted callee spelled out: logging.error -> ('logging', 'error')."""
    parts = []
    while isinstance(func, ast.Attribute):
        parts.append(func.attr)
        func = func.value
    name = getattr(func, "id", None) or getattr(func, "attr", None)
    if name:
        parts.append(name)
    return tuple(reversed(parts))


def _is_loud_name(part):
    """A name token that STARTS with a loud stem, never one that merely contains
    it. The old test matched the substring over ast.dump(func), so `catalog()`
    ('...Name(id=\'catalog\'...' contains "log") certified a silent handler as
    loud and suppressed the SS103 finding under it (codex minor, PR #230 r3).
    Word-start matching keeps logger/logging/warning/writelines loud while
    catalog/backlog/dialog/analog stay silent."""
    for token in re.split(r"[^a-z0-9]+", part.lower()):
        if any(token.startswith(stem) for stem in LOUD_STEMS):
            return True
    return False


def _is_indistinguishable_empty(node):
    """The RETURN half of SS102, and deliberately narrower than the ASSIGN half.

    The defect is that a caller cannot tell a failed read from a real empty
    result, so the test is not "is this falsy" but "does this collide with a
    legitimate value". `return {}` / `[]` / `""` / `0` / `False` collide and
    are the data-loss shape. `return None` does NOT: it is a sentinel the
    caller has to unwrap, which is the ordinary optional-lookup idiom.

    Measured before narrowing, not guessed: flagging every falsy return took
    the repo sweep from 173 findings to 351 (SS102 31 -> 209). At that rate the
    check is bypassed within a day and protects nothing, which the issue's
    blast-radius line names as worse than no check. Excluding the None sentinel
    lands it at a reviewable number while keeping every collision case.
    """
    if node is None:
        return False
    if isinstance(node, ast.Constant) and node.value is None:
        return False
    return _is_empty_default(node)


def _handler_is_loud(handler):
    """Does this handler tell anyone? raise / log / warn / notify / write."""
    for n in ast.walk(handler):
        if isinstance(n, ast.Raise):
            return True
        if isinstance(n, ast.Call):
            if any(_is_loud_name(p) for p in _call_name_parts(n.func)):
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
        # A RETURN of the empty default is the same defect as an ASSIGN of it,
        # and is the commoner spelling: `except OSError: return {}` hands the
        # caller an empty result that is indistinguishable from a real empty
        # one. Matching only ast.Assign missed every function-shaped instance
        # of the class this code exists to catch (codex major, PR #230 r4).
        rebinds = [
            s
            for s in body
            if (isinstance(s, ast.Assign) and _is_empty_default(s.value))
            or (isinstance(s, ast.Return) and _is_indistinguishable_empty(s.value))
        ]
        # The hatch has to be reachable where the defect is WRITTEN. skipped()
        # is keyed on the `except` line, which works for a marker above the
        # handler and misses one sitting on the offending statement inside it --
        # the natural place to put it, and where the py_green fixture already
        # had one. Check both.
        if rebinds and any(skipped(s.lineno) for s in rebinds):
            continue
        if rebinds and len(rebinds) == len(body) and not _handler_is_loud(node):
            first = rebinds[0]
            tgt = first.targets[0] if isinstance(first, ast.Assign) else None
            findings.append(
                Finding(
                    path,
                    node.lineno,
                    "SS102",
                    "handler rebuilds state from an empty default and continues",
                    "`%s` is set to an empty value on failure and execution "
                    "continues, so a corrupt or unreadable input becomes an "
                    "empty one -- the --reset-rounds shape, which is silent "
                    "DATA LOSS. Refuse to write what you could not read, or "
                    "declare it with `# silent-success-ok: <why>`."
                    % ("the return value" if tgt is None
                       else getattr(tgt, "id", ast.dump(tgt)[:40])),
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


# A file this scanner could not read yielded [] -- indistinguishable from "read
# it, found nothing". On the repo-wide sweep that is fine and deliberate (a
# tracked-but-deleted path, a symlink, a submodule dir), but on a path the caller
# NAMED it is this lint committing SS002 against itself: a typo'd argument came
# back "0 finding(s)" with rc=0, which reads as a clean bill of health for a file
# nothing ever opened (PR #230 review, minor). Unreadable is now a distinct
# outcome, and the caller decides what it means.
class Unreadable:
    def __init__(self, rel, why):
        self.rel = rel
        self.why = why


def scan_path(root, rel):
    full = os.path.join(root, rel)
    try:
        with open(full, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except (OSError, IsADirectoryError) as exc:
        return Unreadable(rel, exc.strerror or exc.__class__.__name__)
    if SKIP_RE.search(text.split("\n", 1)[0]):
        return []
    if rel.endswith(".py"):
        return scan_python(rel, text)
    return scan_shell(rel, text)


# --- the ratchet -------------------------------------------------------------
# Keyed on (code, path) and NOT on line number: a finding's line moves on every
# unrelated edit above it, so a line-keyed baseline would be red constantly and
# would teach people to re-pin reflexively, which is the same as no baseline.
def tally(findings):
    out = {}
    for f in findings:
        out.setdefault(f.code, {})
        out[f.code][f.path] = out[f.code].get(f.path, 0) + 1
    return out


def ratchet_diff(current, baseline):
    """-> (regressions, improvements), each [(code, path, was, now), ...]."""
    regressions, improvements = [], []
    for code in sorted(set(current) | set(baseline)):
        cur, base = current.get(code, {}), baseline.get(code, {})
        for path in sorted(set(cur) | set(base)):
            now, was = cur.get(path, 0), base.get(path, 0)
            if now > was:
                regressions.append((code, path, was, now))
            elif now < was:
                improvements.append((code, path, was, now))
    return regressions, improvements


class BaselineError(Exception):
    """A baseline that could not be established. Never degrades to 'held'."""


def load_baseline(path, root, ref=None):
    """The pinned allowance, from the working tree or from a git ref.

    -> (counts, note). `note` is a line to PRINT when the source is not the one
    the caller asked for; None when it is. Silence about a substituted source is
    exactly SS002, so the substitution is always spoken.
    """
    if ref is None:
        return _read_baseline_file(path), None

    rel = os.path.relpath(os.path.abspath(path), root)
    if subprocess.run(
        ["git", "-C", root, "rev-parse", "--verify", "--quiet", ref + "^{commit}"],
        capture_output=True,
    ).returncode:
        raise BaselineError("cannot resolve --baseline-ref %s" % ref)

    # Absent-at-ref and broken-ref are SEPARATE outcomes on purpose. The commit
    # resolving is what makes "the file is not in it" a fact rather than a
    # failure to look -- so the PR that INTRODUCES a baseline is not permanently
    # red, while a typo'd ref still cannot read as clean.
    if subprocess.run(
        ["git", "-C", root, "cat-file", "-e", "%s:%s" % (ref, rel)],
        capture_output=True,
    ).returncode:
        return (
            _read_baseline_file(path),
            "silent-success-lint: baseline absent at %s -- this commit introduces "
            "it, so the ratchet is checked against the working-tree copy for this "
            "run only." % ref[:12],
        )

    shown = subprocess.run(
        ["git", "-C", root, "show", "%s:%s" % (ref, rel)],
        capture_output=True,
        text=True,
    )
    if shown.returncode:
        raise BaselineError(
            "cannot read baseline %s at %s: %s" % (rel, ref, shown.stderr.strip())
        )
    try:
        return json.loads(shown.stdout).get("counts", {}), None
    except ValueError as exc:
        raise BaselineError("baseline at %s is not valid JSON: %s" % (ref, exc))


def _read_baseline_file(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh).get("counts", {})
    except (OSError, ValueError) as exc:
        raise BaselineError("cannot read baseline %s: %s" % (path, exc))


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
    ap.add_argument(
        "--baseline",
        metavar="FILE",
        help="ratchet the repo-wide sweep against a committed per-file baseline; "
        "exit 2 if any file gained a finding",
    )
    ap.add_argument(
        "--baseline-ref",
        metavar="REF",
        help="read the baseline from this git ref instead of the working tree "
        "(pass the PR's base sha, so the branch cannot raise its own allowance)",
    )
    ap.add_argument(
        "--baseline-write",
        metavar="FILE",
        help="write the current repo-wide sweep as a new baseline",
    )
    args = ap.parse_args(argv)

    # The ratchet is a statement about the whole repo. Handed a path list it
    # would compare a two-file sweep against a 173-finding baseline and read
    # every unscanned file as fixed -- a releasing outcome derived from an
    # absent input, which is the exact class this script exists to catch.
    if args.baseline_ref and not args.baseline:
        sys.stderr.write(
            "silent-success-lint: --baseline-ref selects the SOURCE of --baseline; "
            "it does nothing on its own\n"
        )
        return 2

    if (args.baseline or args.baseline_write) and args.paths:
        sys.stderr.write(
            "silent-success-lint: --baseline/--baseline-write is repo-wide; "
            "drop the path arguments\n"
        )
        return 2

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
        findings, unreadable = [], []
        for rel in rels:
            got = scan_path(root, rel)
            (unreadable if isinstance(got, Unreadable) else findings).extend(
                [got] if isinstance(got, Unreadable) else got
            )
        # A named path that could not be opened is an error, never a clean scan.
        # rc=2 (not 1) keeps it distinct from "scanned it, found findings" so a
        # caller can tell a broken invocation from a real result.
        if unreadable:
            for u in unreadable:
                sys.stderr.write(
                    "silent-success-lint: cannot read %s: %s\n" % (u.rel, u.why)
                )
            sys.stderr.write(
                "silent-success-lint: %d requested path(s) unread -- NOT a clean "
                "scan. Fix the path, or drop it from the argument list.\n"
                % len(unreadable)
            )
            return 2
    else:
        # The sweep is the opposite case: `git ls-files` lists tracked paths that
        # may legitimately not be openable right now, and skipping those is the
        # intended behaviour rather than an error.
        findings = []
        for rel in tracked_files(root):
            if not included(rel):
                continue
            got = scan_path(root, rel)
            if not isinstance(got, Unreadable):
                findings.extend(got)

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

    if args.baseline_write:
        with open(args.baseline_write, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "_comment": "silent-success-lint ratchet. Per (code, path) "
                    "counts of pre-existing findings. The check fails when a "
                    "file GAINS one; it does not demand zero. Re-pin with "
                    "--baseline-write only after actually removing findings.",
                    "total": len(findings),
                    "counts": tally(findings),
                },
                fh,
                indent=2,
                sort_keys=True,
            )
            fh.write("\n")
        print(
            "silent-success-lint: wrote baseline %s (%d finding(s))"
            % (args.baseline_write, len(findings))
        )
        return 0

    if args.baseline:
        try:
            base, note = load_baseline(args.baseline, root, args.baseline_ref)
        except BaselineError as exc:
            # An unreadable baseline must never read as "nothing regressed".
            sys.stderr.write("silent-success-lint: %s\n" % exc)
            return 2
        if note:
            print(note)
        regressions, improvements = ratchet_diff(tally(findings), base)
        for code, path, was, now in improvements:
            print("  fixed  %s: %s %d -> %d" % (path, code, was, now))
        for code, path, was, now in regressions:
            print("  GAINED %s: %s %d -> %d" % (path, code, was, now))
        if regressions:
            sys.stderr.write(
                "\nsilent-success-lint: %d file/code pair(s) gained a finding "
                "against %s.\nThis is a NEW failure path that succeeds quietly. "
                "Fix it, or declare it in place with "
                "`# silent-success-ok: <why>`.\nRe-pinning the baseline is only "
                "correct after the finding is genuinely gone.\n"
                % (len(regressions), args.baseline)
            )
            return 2
        print(
            "\nsilent-success-lint: ratchet held (%d finding(s), %d fixed since "
            "the baseline)" % (len(findings), len(improvements))
        )
        if improvements:
            print(
                "  re-pin with: python3 %s --baseline-write %s"
                % (os.path.basename(__file__), args.baseline)
            )
        return 0

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
