#!/usr/bin/env python3
"""
fable-discipline-lint.py — Deterministic test-isolation enforcer.

Pairs with the fable-discipline skill (SKILL.md). Enforces the one mechanically
checkable slice of that skill's "verify against a copy, never the live resource"
rule: a TEST file must not name a real data path. Tests use a temp copy, a
tempfile, or :memory:.

This is the graded-good Fable habit (it migrated a COPY of the live prod DB to
prove idempotency) turned into a consistent guardrail, because an independent
Codex review caught a sibling test risking mutation of the live founder DB.

Usage:
    python3 fable-discipline-lint.py <file_path>   # CLI mode
    (no args)                                 # hook mode: PostToolUse JSON on stdin

Exit codes:
    0 = clean (or out of scope)
    2 = violation (a test names a non-isolated data path)

Override:
    Add  # fable-discipline-lint-skip  anywhere in the file to bypass.

Detector coverage (enumerated on purpose, per the hook-blind-spots rule):
    CATCHES  a quoted literal that is a real DB path — has a path separator AND a
             DB extension (.db/.sqlite/.sqlite3/.duckdb) — and is not isolated,
             in ANY use except a comparison/assertion. That covers a direct
             connect("...")/open("..."), every assignment form (plain, augmented
             +=, walrus :=, dict/subscript/attr target), and a literal nested
             inside an f-string. The path-separator requirement is what lets
             `tmp_path / "t.db"` through: the bare filename "t.db" has no
             separator, and isolation lives in the temp variable.
    SKIPS    comparison/assertion lines (assert ..., ==, !=), where the literal
             is being checked, not used — e.g. an OSS-secrets audit test
             asserting the live path is NAMED in a report.
    MISSES   (documented deferrals, each a low-likelihood shape that would add
             false-positive risk to catch):
             - a no-argument default db.connect() (no literal to see; left to the
               skill's monkeypatch-the-default convention)
             - adjacent string concatenation: connect('/dir/' 'x.db')
             - a triple-quoted one-line DB path
             - pathlib bare-segment joins: Path('/abs/data') / 'x.db'
             - em-dash narration (not a tool call; lives in the skill + style)

Deferral-capture detector coverage (second detector, same enumeration rule):
    CATCHES  deferral language written into a CODE file (suffix allowlist below):
             "out of scope"/"out-of-scope", "fix (it) later", "defer(red) this",
             "leave (this) for later", "won't fix (now)", "punt(ed/ing) on" —
             case-insensitive, comments and strings alike — unless the file
             acks a captured item with # spillover-skip.
    SKIPS    non-code files (docs/PRDs legitimately discuss scope), and any
             file containing the ack marker.
    MISSES   (documented deferrals): synonym phrasings with no listed verb
             ("not in scope", "TODO later", "handle this another day",
             "skip for now", "future work"), deferrals split across lines,
             and non-English phrasing. Your standing gate / CI is the
             enforcement of last resort; this detector is the write-time nudge.

Outbound-channel detector coverage (third detector, same enumeration rule):
    WHY      The DB-path detector above reads "live data path" as "a file on
             disk". A test that fires the founder's real Slack webhook is the
             same defect through a different resource, and this lint missed it:
             test-worker-project-scope.sh drove the worker into its MISCONFIG
             branch, reached the real slack-notify.sh, and paged the founder's
             phone twice on 2026-08-01 while reporting 14/14 green. A live
             channel is a live resource.
    CATCHES  a file under a test directory that (a) names a runner script which
             resolves on disk and itself reaches slack-notify.sh, and (b) hands
             that runner to an interpreter, with (c) no notifier stub anywhere
             in its non-comment lines. The notify-capable set is DERIVED by
             reading the referenced runner, never hardcoded, so a new
             pager-capable script is covered the day it is written and there is
             no list to remember to update.
    SKIPS    a test that only greps/parses the runner (no interpreter line), and
             any test that stubs the notifier one of the three ways the fleet
             actually uses: KIPI_NOTIFY=... (the env seam), a NOTIFY_SCRIPT
             rebind (the Python seam), or writing its own slack-notify.sh into a
             sandbox skeleton (the seam for runners like lessons-daily.sh that
             hardcode $SKEL/.../slack-notify.sh and expose no env override).
             `bash -n` parses without executing and is not an invocation.
    MISSES   (documented deferrals): a stub named only in a COMMENT does not
             count, but a bare mention on a live line does, so an unused
             KIPI_NOTIFY assignment reads as isolation; a runner reached only
             through a PATH-shadowed binary, or one whose filename the test
             never spells out; a runner imported as a Python MODULE instead of
             executed (no interpreter line to see); a runner living somewhere
             other than the test's own directory or its parent; and outbound
             channels other than slack-notify.sh (a raw curl to a webhook,
             sendmail, gh) -- this detector is scoped to the one channel that
             actually wakes a human.

Scope (fast-exit otherwise, token discipline):
    Three detectors, three scopes, evaluated in this order:
    1. Deferral capture runs on ANY code file (suffix allowlist in
       _CODE_SUFFIXES) and can exit 2 on its own.
    2. Outbound-channel isolation runs on any .sh/.py file under a TEST
       directory (or named test-* / test_*), so it covers SHELL suites, which
       the Python-only detector below structurally cannot see. That blind spot
       is why the 2026-08-01 leak lived in a .sh file this lint already ran on.
    3. Test isolation then runs only on a Python TEST file, detected by
       basename test_*.py / *_test.py or a path under a /tests/ directory.
    A non-code, non-test edit (markdown, JSON, config) exits 0 untouched.
"""

import json
import re
import sys
from pathlib import Path

SKIP_MARKER = "fable-discipline-lint-skip"

# Spillover capture: a deferral written into CODE (a "# TODO: out of scope" that
# nobody tracks) is the silent-drop scar. Block it unless the finding was
# captured and the line is acked with `# spillover-skip`. Scoped to code files so
# docs/PRDs that legitimately discuss scope are never tripped. The GATE
# your standing gate / CI is the enforcement; this lint is the write-time nudge.
SPILL_SKIP_MARKER = "spillover-skip"
_CODE_SUFFIXES = {".py", ".js", ".ts", ".jsx", ".tsx", ".sh", ".rb", ".go",
                  ".rs", ".java", ".c", ".cpp", ".h", ".mjs", ".cjs"}
_DEFERRAL = re.compile(
    r"out[- ]of[- ]scope|fix (?:it )?later|defer(?:red)? this|"
    r"leave (?:this )?for later|won'?t fix(?: now)?|punt(?:ed|ing)? on",
    re.IGNORECASE,
)


def is_code_file(file_path):
    return Path(str(file_path)).suffix in _CODE_SUFFIXES


def find_deferral_lines(text):
    if SPILL_SKIP_MARKER in text:
        return []
    hits = []
    for i, line in enumerate(text.splitlines(), 1):
        if _DEFERRAL.search(line):
            hits.append((i, line.strip()[:80]))
    return hits


def format_deferral_report(file_path, hits):
    lines = [f"fable-discipline-lint: {len(hits)} uncaptured deferral(s) in {file_path}:"]
    for ln, snippet in hits:
        lines.append(f"  line {ln}: {snippet}")
    lines.append(
        "An out-of-scope deferral in code must be CAPTURED, never just written and "
        "forgotten. Record it in your tracked backlog (an issue/ticket/ledger your "
        "gate reads), then add  # spillover-skip  to this file to ack."
    )
    return "\n".join(lines)

# A path literal is isolated (safe in a test) if it names any of these.
ISOLATION_TOKENS = (
    ":memory:", "tmp", "temp", "fixture", "fixtures", "mock", "sample",
    "testdata", "test_data", "golden", "mktemp", "temporarydirectory",
    "tmp_path", "tmpdir", "/var/folders", "getfixturevalue", "monkeypatch",
)

# A quoted literal that is a real DB path: contains a path separator AND ends in
# a DB extension. Matches inside f-strings too (the inner quote is a real match).
_DBPATH = re.compile(r"""(['"])([^'"]*[/\\][^'"]*\.(?:db|sqlite|sqlite3|duckdb))\1""")


def _is_isolated(p):
    low = p.lower()
    return any(tok in low for tok in ISOLATION_TOKENS)


def is_test_file(file_path):
    p = Path(str(file_path))
    if p.suffix != ".py":
        return False
    name = p.name
    if name.startswith("test_") or name.endswith("_test.py"):
        return True
    return "/tests/" in str(file_path).replace("\\", "/")


def find_violations(text):
    violations = []
    in_doc = False
    delim = None
    seen = set()
    for i, line in enumerate(text.splitlines(), 1):
        if in_doc:
            if delim in line:
                in_doc = False
                delim = None
            continue
        s = line.lstrip()
        if s.startswith("#"):
            continue
        # enter a triple-quoted block if one opens and does not close this line
        for q in ('"""', "'''"):
            if line.count(q) % 2 == 1:
                in_doc = True
                delim = q
                break
        # skip comparisons/assertions: the literal is being checked, not used
        if s.startswith("assert") or "==" in line or "!=" in line:
            continue
        for m in _DBPATH.finditer(line):
            path = m.group(2)
            if _is_isolated(path):
                continue
            key = (i, path)
            if key not in seen:
                seen.add(key)
                violations.append((i, path))
    return violations


# --- Detector 3: outbound-channel isolation ---------------------------------
# A test that reaches slack-notify.sh rings the founder's actual phone. That is
# a live resource in exactly the sense the DB-path detector already guards, so
# it belongs in this lint rather than in a second one.
NOTIFIER_BASENAME = "slack-notify.sh"
_TEST_DIR_NAMES = {"test", "tests", "testing"}
_TEST_SUFFIXES = {".sh", ".py"}

# A script filename as it appears anywhere in a test: in a VAR= assignment, in a
# quoted path, or bare on an interpreter line.
_SCRIPT_NAME = re.compile(r"[\w][\w.-]*\.(?:sh|py)")

# Interpreter words that actually RUN a file. `env` is in the set because the
# 2026-08-01 leak shipped as `env KIPI_SKEL=... bash "$WORKER"`.
#
# The interpreter must be a COMMAND WORD: preceded by start-of-line, whitespace
# or a shell separator, and FOLLOWED BY WHITESPACE. A plain \b...\b here matches
# the "sh" inside the extension of `AGENT="$DIR/pr-review-agent.sh"`, which made
# every line that merely NAMES a .sh runner look like an invocation and flagged
# three grep-only suites. Caught by cross-checking the detector against a
# measured run rather than trusting its own output.
_INTERP = re.compile(r"(?:^|[;&|(]|\s)(?:bash|sh|zsh|python3|python|env)\s")

# `bash -n` parses a script without executing it, so it cannot page anyone.
_SYNTAX_ONLY = re.compile(r"\b(?:bash|sh|zsh)\s+-n\b")

# VAR=... on a line that also names the runner. Covers plain, exported and
# ${FOO:-default} forms alike, because the name only has to appear on the line.
_ASSIGN = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=")

# The three stub shapes the fleet actually uses.
_NOTIFY_STUB = re.compile(r"KIPI_NOTIFY|NOTIFY_SCRIPT|slack-notify\.sh")


_ENV_ASSIGN_TOK = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_INTERP_WORDS = {"bash", "sh", "zsh", "python3", "python", "env"}


def _interpreter_args(line):
    """The FIRST real argument handed to each interpreter on this line.

    Being NAMED on an interpreter line is not being RUN by it. The discriminator
    is position: `bash "$WORKER"` runs the worker, while
    `bash -c '... grep "$AGENT" ...'` hands $AGENT to grep. Skipping leading
    env-assignments and flags is what makes `env A=B bash "$WORKER"` resolve to
    "$WORKER" rather than to `bash`.
    """
    args = []
    for m in _INTERP.finditer(line):
        for tok in line[m.end():].split():
            bare = tok.strip("\"'")
            if _ENV_ASSIGN_TOK.match(bare) or bare in _INTERP_WORDS:
                continue
            if tok.startswith("-"):
                continue
            args.append(tok)
            break
    return args


def is_test_dir_file(file_path):
    p = Path(str(file_path))
    if p.suffix not in _TEST_SUFFIXES:
        return False
    posix = p.as_posix()
    if any(part in _TEST_DIR_NAMES for part in posix.split("/")[:-1]):
        return True
    name = p.name
    return name.startswith(("test-", "test_")) or "_test." in name


def _live_lines(text):
    """(line_no, line) for every line that is not a whole-line comment.

    A stub named only in a comment is prose, not isolation. That distinction is
    what stops a test whose ONLY mention of slack-notify.sh is an explanatory
    comment from certifying itself clean.
    """
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("#"):
            continue
        out.append((i, line))
    return out


def _notifier_reachable(test_path, name):
    """True when `name` resolves next to the test and itself reaches the notifier.

    Derived, never hardcoded: the day someone writes a new pager-capable runner,
    the tests that drive it are covered without editing a list in this file.
    """
    if name == NOTIFIER_BASENAME:
        return False
    d = Path(str(test_path)).resolve().parent
    for cand in (d.parent / name, d / name):
        try:
            if cand.is_file():
                # Non-comment lines only. linear-sync.py NAMES slack-notify.sh in
                # a comment about an unrelated defect and never invokes it; a
                # whole-text match made two innocent suites look like leaks.
                body = cand.read_text(encoding="utf-8", errors="replace")
                return any(NOTIFIER_BASENAME in line
                           for _, line in _live_lines(body))
        except Exception:
            return False
    return False


def find_notify_leaks(file_path, text):
    """[(line_no, runner_name)] per notify-capable runner this test EXECUTES
    while stubbing nothing."""
    live = _live_lines(text)
    if any(_NOTIFY_STUB.search(line) for _, line in live):
        return []                      # isolated by one of the three seams

    self_name = Path(str(file_path)).name
    reachable = {}                     # runner name -> bool, resolved once
    var_to_runner = {}                 # shell var -> runner name assigned to it

    for _, line in live:
        for name in _SCRIPT_NAME.findall(line):
            if name == self_name:
                continue
            if name not in reachable:
                reachable[name] = _notifier_reachable(file_path, name)
            if not reachable[name]:
                continue
            m = _ASSIGN.match(line)
            if m:
                var_to_runner[m.group(1)] = name

    hits = []
    seen = set()
    for ln, line in live:
        if _SYNTAX_ONLY.search(line):
            continue
        for tok in _interpreter_args(line):
            for name in _SCRIPT_NAME.findall(tok):
                if name != self_name and reachable.get(name) and name not in seen:
                    seen.add(name)
                    hits.append((ln, name))
            for var, name in var_to_runner.items():
                if name in seen:
                    continue
                if re.search(r"\$\{?" + re.escape(var) + r"\b", tok):
                    seen.add(name)
                    hits.append((ln, name))
    return hits


def format_notify_report(file_path, hits):
    lines = [f"fable-discipline-lint: {len(hits)} unstubbed outbound-channel "
             f"invocation(s) in {file_path}:"]
    for ln, name in hits:
        lines.append(f"  line {ln}: runs {name}, which reaches {NOTIFIER_BASENAME}")
    lines.append(
        "This test can page the founder's real phone. Stub the notifier: pass "
        "KIPI_NOTIFY=/usr/bin/true in the runner's env, or rebind NOTIFY_SCRIPT, "
        "or write your own slack-notify.sh into the sandbox skeleton for runners "
        "with no env seam. Scar: 2026-08-01, a suite reporting 14/14 green paged "
        f"the founder twice. Or add  # {SKIP_MARKER}  to bypass."
    )
    return "\n".join(lines)


def lint_file(file_path):
    try:
        text = Path(file_path).read_text(encoding="utf-8")
    except Exception:
        # Never block a write on a read/infra failure; this is a content gate.
        return []
    if SKIP_MARKER in text:
        return []
    return find_violations(text)


def format_report(file_path, violations):
    lines = [f"fable-discipline-lint: {len(violations)} test-isolation violation(s) in {file_path}:"]
    for ln, path in violations:
        lines.append(f"  line {ln}: test names a live data path \"{path}\"")
    lines.append(
        "Tests must use a temp copy, a tempfile, or :memory: — never a real data "
        "resource (fable-discipline skill: verify against a copy). "
        f"Fix it, or add  # {SKIP_MARKER}  to bypass."
    )
    return "\n".join(lines)


def hook_mode():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    if payload.get("tool_name", "") not in ("Edit", "Write", "MultiEdit"):
        sys.exit(0)
    file_path = payload.get("tool_input", {}).get("file_path", "")
    if not file_path:
        sys.exit(0)
    # Deferral capture: any CODE file that defers without capture is blocked.
    if is_code_file(file_path):
        try:
            text = Path(file_path).read_text(encoding="utf-8")
        except Exception:
            text = ""
        deferrals = find_deferral_lines(text) if text else []
        if deferrals:
            print(format_deferral_report(file_path, deferrals), file=sys.stderr)
            sys.exit(2)
    # Outbound-channel isolation: any test-dir file that can reach the pager.
    if is_test_dir_file(file_path):
        try:
            text = Path(file_path).read_text(encoding="utf-8")
        except Exception:
            text = ""
        if text and SKIP_MARKER not in text:
            leaks = find_notify_leaks(file_path, text)
            if leaks:
                print(format_notify_report(file_path, leaks), file=sys.stderr)
                sys.exit(2)
    # Test isolation: only on test files.
    if not is_test_file(file_path):
        sys.exit(0)
    violations = lint_file(file_path)
    if not violations:
        sys.exit(0)
    print(format_report(file_path, violations), file=sys.stderr)
    sys.exit(2)


def cli_mode(file_path):
    if is_code_file(file_path):
        try:
            text = Path(file_path).read_text(encoding="utf-8")
        except Exception:
            text = ""
        deferrals = find_deferral_lines(text) if text else []
        if deferrals:
            print(format_deferral_report(file_path, deferrals))
            sys.exit(2)
    if is_test_dir_file(file_path):
        try:
            text = Path(file_path).read_text(encoding="utf-8")
        except Exception:
            text = ""
        if text and SKIP_MARKER not in text:
            leaks = find_notify_leaks(file_path, text)
            if leaks:
                print(format_notify_report(file_path, leaks))
                sys.exit(2)
    if not is_test_file(file_path):
        print(f"fable-discipline-lint: clean, no unstubbed outbound channel ({file_path})")
        sys.exit(0)
    violations = lint_file(file_path)
    if not violations:
        print(f"fable-discipline-lint: clean ({file_path})")
        sys.exit(0)
    print(format_report(file_path, violations))
    sys.exit(2)


if __name__ == "__main__":
    if len(sys.argv) == 1:
        hook_mode()
    elif len(sys.argv) == 2:
        cli_mode(sys.argv[1])
    else:
        print("Usage: fable-discipline-lint.py <file_path>", file=sys.stderr)
        sys.exit(1)
