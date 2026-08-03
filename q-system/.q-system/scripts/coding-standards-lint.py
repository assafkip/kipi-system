#!/usr/bin/env python3
"""
coding-standards-lint.py — the executable behind `.claude/rules/coding-standards.md`.

Pairs with that rule (per `.claude/rules/skill-hook-pairing.md`). The rule claimed
ENFORCED and named no executable, so all of it was prompt-only (ASK-133). This
covers the four lines that are pure regex work; the rest of the rule stays
interpretive and is marked as such in the rule file.

Rules enforced (all BLOCK-class):
  shell-strict  .sh with a shebang must set -e, -u and -o pipefail
  json-indent   .json must not indent at 3+ spaces or with tabs
  js-no-var     .js/.mjs/.cjs must not declare with `var`
  naming        scripts: no uppercase/spaces in the basename (kebab or snake)
                q-system/output/ non-scripts: kebab-case basename

Usage:
    python3 coding-standards-lint.py <file_path>   # CLI
    python3 coding-standards-lint.py               # PostToolUse hook (JSON on stdin)

Exit codes:
    0 = clean, or out of scope
    2 = a violation found (PostToolUse contract — stderr is fed back to Claude)

Override:
    Add `coding-standards-lint-skip` anywhere in the file (any comment syntax).

Scope:
    Self-scopes by extension on `tool_input.file_path` and fast-exits on
    everything else. Blast radius is fleet-wide (this file and the rule both
    propagate via `kipi update`), so out-of-scope work must cost nothing.

Coverage limits, stated rather than implied:
  - json-indent fires at 3+ spaces or a tab, NOT at 1-space under-indent. The
    compact one-record-per-line array (`skill-evals/*.json`) is a real style in
    this repo; flagging it would be noise, and 4-space/tab is the failure mode
    the rule actually guards against. Measured 2026-07-31: 0 tracked .json files
    use 4-space or tab, 5 use the compact style.
  - naming accepts BOTH kebab and snake for scripts. The rule's prose said
    "snake_case for scripts"; the repo is 85 kebab vs 35 snake in
    q-system/.q-system/scripts alone, so enforcing the prose verbatim would
    block ~70% of script edits fleet-wide. The rule text was corrected to match
    what the fleet actually does.
  - The "Test After Edit" half of the rule is a model decision, not a regex, and
    is deliberately not covered here.
"""

import json
import os
import re
import subprocess
import sys
from collections import Counter

SKIP_MARKER = "coding-standards-lint-skip"

SHELL_EXT = (".sh",)
JSON_EXT = (".json",)
JS_EXT = (".js", ".mjs", ".cjs")
SCRIPT_EXT = (".py",) + SHELL_EXT + JS_EXT
IN_SCOPE_EXT = SCRIPT_EXT + JSON_EXT

# A file under this path is an output artifact and takes kebab-case naming.
OUTPUT_DIR_RE = re.compile(r"(^|/)q-system/output/")

# `var x`, `var {a}`, `for (var i` — a declaration, not a word that ends in "var".
VAR_DECL_RE = re.compile(r"(?:^|[^\w$.])var\s+[A-Za-z_$\[{]")

SET_E_RE = re.compile(r"^\s*set\s+-[a-zA-Z]*e", re.MULTILINE)
SET_U_RE = re.compile(r"^\s*set\s+-[a-zA-Z]*u", re.MULTILINE)
# `-o pipefail` and the folded `-euo pipefail` are the same guarantee.
SET_PIPEFAIL_RE = re.compile(r"^\s*set\s+-[a-zA-Z]*o\s+pipefail", re.MULTILINE)

KEBAB_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*(\.[a-z0-9]+)*$")
# Scripts: lowercase, with `-` `_` `.` free-standing so Python's `__init__.py`
# and `_private.py` pass. What this catches is camelCase, PascalCase and spaces.
SCRIPT_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$|^_[a-z0-9._-]*$")


def has_skip_marker(text):
    return SKIP_MARKER in text


def check_shell(text):
    """A shebang-bearing .sh must be strict. A sourced fragment must not be.

    `set -e` inside a sourced fragment changes the CALLER's shell, so requiring
    it there would be wrong, not merely noisy.
    """
    if not text.startswith("#!"):
        return []
    missing = []
    if not SET_E_RE.search(text):
        missing.append("-e")
    if not SET_U_RE.search(text):
        missing.append("-u")
    if not SET_PIPEFAIL_RE.search(text):
        missing.append("-o pipefail")
    if not missing:
        return []
    return [
        {
            "rule": "shell-strict",
            "line": 2,
            "detail": (
                "shell script does not set " + ", ".join(missing)
                + ". Add `set -euo pipefail` under the shebang."
            ),
        }
    ]


def check_json_indent(text):
    """Flag a dominant indent increment of 3+ spaces, or any leading tab.

    Increment rather than absolute depth: absolute leading-space counts cannot
    tell a 2-space file nested four deep from a 4-space file nested twice.
    """
    leads = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        match = re.match(r"^([ \t]+)\S", line)
        if not match:
            leads.append((lineno, 0))
            continue
        lead = match.group(1)
        if "\t" in lead:
            return [
                {
                    "rule": "json-indent",
                    "line": lineno,
                    "detail": "JSON indented with a tab. Use 2 spaces.",
                }
            ]
        leads.append((lineno, len(lead)))

    deltas = Counter()
    first_line = {}
    for (_, prev), (lineno, cur) in zip(leads, leads[1:]):
        step = cur - prev
        if step > 0:
            deltas[step] += 1
            first_line.setdefault(step, lineno)
    if not deltas:
        return []
    step, _ = deltas.most_common(1)[0]
    if step < 3:
        return []
    return [
        {
            "rule": "json-indent",
            "line": first_line[step],
            "detail": f"JSON indented {step} spaces per level. Use 2.",
        }
    ]


def _strip_js_noise(text):
    """Blank out strings, template literals and comments, keeping line count.

    Scanned character by character because a regex pass cannot tell a `//`
    inside a string from a real comment, and that is exactly the false positive
    that would block a fleet-wide write.
    """
    out = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if ch == "/" and nxt == "/":
            while i < n and text[i] != "\n":
                out.append(" ")
                i += 1
            continue
        if ch == "/" and nxt == "*":
            while i < n and not (text[i] == "*" and text[i + 1 : i + 2] == "/"):
                out.append("\n" if text[i] == "\n" else " ")
                i += 1
            out.append("  ")
            i += 2
            continue
        if ch in "\"'`":
            quote = ch
            out.append(" ")
            i += 1
            while i < n and text[i] != quote:
                if text[i] == "\\":
                    out.append(" ")
                    i += 1
                    if i < n:
                        out.append("\n" if text[i] == "\n" else " ")
                        i += 1
                    continue
                out.append("\n" if text[i] == "\n" else " ")
                i += 1
            out.append(" ")
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def check_js(text):
    violations = []
    for lineno, line in enumerate(_strip_js_noise(text).splitlines(), start=1):
        if VAR_DECL_RE.search(line):
            violations.append(
                {
                    "rule": "js-no-var",
                    "line": lineno,
                    "detail": "`var` declaration. Use const or let (ES modules).",
                }
            )
    return violations


def check_naming(file_path):
    base = os.path.basename(file_path)
    if base.startswith("."):
        return []
    ext = os.path.splitext(base)[1].lower()
    if ext in SCRIPT_EXT:
        if SCRIPT_NAME_RE.match(base):
            return []
        return [
            {
                "rule": "naming",
                "line": 1,
                "detail": (
                    f"script `{base}` is not kebab-case or snake_case "
                    "(lowercase, `-` or `_` separators)."
                ),
            }
        ]
    if OUTPUT_DIR_RE.search(file_path.replace(os.sep, "/")) and not KEBAB_RE.match(base):
        return [
            {
                "rule": "naming",
                "line": 1,
                "detail": f"output file `{base}` is not kebab-case.",
            }
        ]
    return []


def _git(args, cwd, timeout=3):
    """One place that shells git. Returns (rc, stdout). Never raises: a lint
    that dies because git was slow or absent would block an edit for a reason
    that has nothing to do with coding standards."""
    try:
        proc = subprocess.run(
            ["git"] + args, cwd=cwd, timeout=timeout,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        return proc.returncode, proc.stdout.decode("utf-8", "replace").strip()
    except (OSError, subprocess.SubprocessError):
        return 1, ""


def existed_at_baseline(file_path):
    """True when this file was already tracked before the current line of work.

    Grandfathering, and why it is not a loophole: armed against every tracked
    file, this lint refuses edits to 36 of 400 -- including linear-worker.sh,
    kipi-dispatch.sh, converge.sh and slack-notify.sh, the scripts the
    autonomous loop runs ON. A gate whose first act is to refuse the hot path
    gets switched off within a day, and a switched-off gate still reads as a
    live one, which is strictly worse than never shipping it. So the rule binds
    NEW files only: full forward value (no new violation ever lands), near-zero
    blast radius, and it can arm today instead of sitting quarantined.
    Backfilling the 36 is its own bounded issue that blocks nobody.

    The two failure directions are NOT the same, so they are split:

    * No git repo at all -> ENFORCE. A file with no history has nothing to be
      grandfathered against, so it is new by definition. Returning "skip" here
      instead made the lint a silent no-op for every tmpdir fixture and turned
      12 of its own behavior tests red -- caught only because those tests
      assert violations rather than assert "no crash".
    * Repo known but git could not answer (transient: slow fs, detached
      origin, timeout) -> GRANDFATHER. We already know the file lives in a
      tracked repo, and a flaky `git cat-file` must never be the thing that
      starts blocking linear-worker.sh. Flipping to enforce on a transient
      would recreate exactly the hot-path wedge this narrowing exists to avoid.
    """
    directory = os.path.dirname(os.path.abspath(file_path)) or "."
    rc, root = _git(["rev-parse", "--show-toplevel"], directory)
    if rc != 0 or not root:
        return False

    rel = os.path.relpath(os.path.abspath(file_path), root).replace(os.sep, "/")

    # merge-base first: on a PR branch the baseline is where the branch left
    # main, so a file this branch ADDS is correctly seen as new even after it
    # is committed. Plain HEAD would grandfather it the moment it landed.
    for ref_args in (["merge-base", "HEAD", "origin/main"],
                     ["rev-parse", "origin/main"],
                     ["rev-parse", "HEAD"]):
        rc, ref = _git(ref_args, root)
        if rc == 0 and ref:
            return _git(["cat-file", "-e", f"{ref}:{rel}"], root)[0] == 0
    return True


def lint_file(file_path):
    ext = os.path.splitext(file_path)[1].lower()
    in_output = OUTPUT_DIR_RE.search(file_path.replace(os.sep, "/"))
    if ext not in IN_SCOPE_EXT and not in_output:
        return []
    if existed_at_baseline(file_path):
        return []
    try:
        with open(file_path, encoding="utf-8") as handle:
            text = handle.read()
    except (OSError, UnicodeDecodeError):
        return []
    if has_skip_marker(text):
        return []

    violations = check_naming(file_path)
    if ext in SHELL_EXT:
        violations += check_shell(text)
    elif ext in JSON_EXT:
        violations += check_json_indent(text)
    elif ext in JS_EXT:
        violations += check_js(text)
    violations.sort(key=lambda v: (v["line"], v["rule"]))
    return violations


def format_report(file_path, violations):
    lines = [f"coding-standards-lint: {len(violations)} violation(s) in {file_path}:"]
    for violation in violations:
        lines.append(
            f"  line {violation['line']} [{violation['rule']}] {violation['detail']}"
        )
    lines.append("")
    lines.append(
        f"Rule: .claude/rules/coding-standards.md. Fix in place, or add "
        f"`{SKIP_MARKER}` in a comment to bypass this file (intentional exception only)."
    )
    return "\n".join(lines)


def hook_mode():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    if payload.get("tool_name") not in ("Edit", "Write", "MultiEdit"):
        sys.exit(0)
    file_path = payload.get("tool_input", {}).get("file_path", "")
    if not file_path or not os.path.isfile(file_path):
        sys.exit(0)
    violations = lint_file(file_path)
    if violations:
        print(format_report(file_path, violations), file=sys.stderr)
        sys.exit(2)
    sys.exit(0)


def cli_mode(file_path):
    violations = lint_file(file_path)
    if not violations:
        print(f"coding-standards-lint: clean ({file_path})")
        sys.exit(0)
    print(format_report(file_path, violations))
    sys.exit(2)


if __name__ == "__main__":
    if len(sys.argv) == 1:
        hook_mode()
    elif len(sys.argv) == 2:
        cli_mode(sys.argv[1])
    else:
        print("Usage: coding-standards-lint.py <file_path>", file=sys.stderr)
        sys.exit(1)
