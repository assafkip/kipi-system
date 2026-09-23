#!/usr/bin/env python3
"""change-size.py -- reads a diff, prints the ceremony that diff earns (ASK-1749).

WHY THIS EXISTS. Every change paid the same price. Measured 2026-09-19 on CI run
35478270323: the capability gate step ran every declared test artifact, serially,
and took 17m41s of a 19m36s job, on every push of every PR. A
review round that changes three lines waits that long for `validate` before it
can merge, and a converge run has up to four rounds. The founder's words the same
night: "make sure you dont run full sweeps on small issues like line changes.
They should not run 6000+ tests." An earlier scar, same shape: 18 full sweeps in
one day. A written rule about this is one people drift from, so this is a script.

WHAT IT DECIDES, from the diff alone. Never from a description, a commit body or
an agent's opinion of its own change:

  tier  S   at most 20 changed lines of app code
        M   at most 150
        L   anything larger, or ANY escalator below
        The tier is the HUMAN ceremony: how much review the change earns.
  tests every declared test that SCANS the tree (72 of 236 today: it reads files
        nobody named, so no selection can be trusted to include it); plus the
        declared test artifacts that name a changed file, or name a script
        that uses it, one step out (an edge is a mention on a line that executes;
        a comment that talks about a script does not run it); for a fixture, the
        tests that name its directory; plus any changed or newly declared test.

ESCALATORS force the FULL SUITE (and tier L) whatever the line count says. Line
count alone never does: a large diff names more files, so it selects more tests,
and it becomes a full run through the last escalator when it truly is suite-wide.
  * the machinery that decides what runs (this file, the gate, the manifest
    assembler, CI workflows, lefthook, verify.sh, any conftest.py)
  * a file CI installs from or every test loads (requirements*.txt,
    pyproject.toml, pytest.ini, tox.ini, setup.cfg, any conftest.py)
  * a capability declaration other than an expected_tests entry
  * a new third-party import in app code (a test importing pytest is not one)
  * a selection so wide that it is the suite anyway (more than MAX_SELECTED,
    counted WITHOUT the always-run scanners: a fixed floor is not evidence that
    this diff is suite-wide)

NOT AN ESCALATOR: a changed file no declared test names. "The full suite" means
the declared tests, so when none of them can see the file, running all of them
exercises it exactly as much as running none. Escalating there buys no coverage;
measured on the last 80 commits of main it bought 17 minutes. The missing owner
is a real finding and it has its own issue; it is not this script's job.

THE ASYMMETRY. Everything uncertain resolves UPWARD. An unreadable diff, a
missing base ref, a crash in here: the caller runs the FULL suite. This script can
make a run cheaper only when it can name exactly why that is safe. And the full
suite still runs on every push to main, so a selection that was too narrow is
caught at merge, by the same gate, not never.

It prints and exits 0 (2 on an unreadable diff). It enforces nothing by itself:
capability-gate.py --diff-base is the caller that acts on it, and CI passes that
flag on pull requests only.

NO --head FLAG, ON PURPOSE. The declared tests are read from the checkout on
disk, so the diff has to end at that same checkout. Pointed at another ref it
diffed one tree and searched another: it called a new script UNTESTED BY NAME
while the test that names it sat on the ref it was not reading (tried on the
ASK-1888 branch, 2026-09-19).

Usage:  change-size.py --base origin/main [--repo-root .] [--json]
"""
from __future__ import annotations

import argparse
import functools
import json
import re
import subprocess
import sys
from pathlib import Path

S_MAX_LINES = 20
M_MAX_LINES = 150
# Above this the "selection" is most of the suite, and the honest name for that
# is a full run. A change that many tests name is a shared-lib change.
MAX_SELECTED = 60

CAPABILITY_DIR = "q-system/.q-system/capability/"
EXPECTED_TESTS_DIR = CAPABILITY_DIR + "expected_tests/"

# The machinery that decides what runs. A change here can make every OTHER
# selection wrong, so it never gets to vouch for itself with a narrow run.
FULL_RUN_PATHS = (
    "q-system/.q-system/scripts/change-size.py",
    "q-system/.q-system/scripts/capability-gate.py",
    "q-system/.q-system/scripts/capability_manifest.py",
    "q-system/.q-system/verify.sh",
    "lefthook.yml",
)
FULL_RUN_PREFIXES = (".github/workflows/",)
# Files that configure or are installed into EVERY test run. pytest.ini was the
# one this list missed (codex, PR #377 round 5): it sets the options for every
# pytest invocation in the repo, so a PR editing it ran 72 of 236 and went green.
# tox.ini and setup.cfg are here because pytest reads its config from whichever
# of the four it finds first, so which file is authoritative can change without
# this list changing.
FULL_RUN_BASENAMES = ("conftest.py", "pyproject.toml", "pytest.ini", "tox.ini", "setup.cfg")
FULL_RUN_BASENAME_RE = re.compile(r"^requirements[\w.-]*\.txt$")

CODE_SUFFIXES = (".py", ".sh")
# A real import STATEMENT, not a sentence that starts with "from". The first cut
# matched `+    from that point on...` inside a docstring and called `that` a new
# dependency (measured on the last 40 commits of main, 2026-09-19).
# `import THIS file into the fixture` is prose too, so the WHOLE line has to parse
# as an import statement, and every module on it is read (`import json, torch`).
_MODULE = r"[A-Za-z_][\w.]*(?:\s+as\s+\w+)?"
_IMPORT_LINE_RE = re.compile(r"^\+\s*import\s+(" + _MODULE + r"(?:\s*,\s*" + _MODULE + r")*)\s*(?:#.*)?$")
_FROM_LINE_RE = re.compile(r"^\+\s*from\s+([A-Za-z_]\w*)(?:\.\w+)*\s+import\s+[\w*(]")
_DIFF_FILE_RE = re.compile(r"^\+\+\+ b/(.+)$")


def is_test_path(path: str) -> bool:
    p = Path(path)
    return (p.name.startswith(("test_", "test-")) or p.name.endswith("_test.py")
            or any(part in ("test", "tests", "fixtures") for part in p.parts[:-1]))


def is_code(path: str) -> bool:
    return path.endswith(CODE_SUFFIXES) and not is_test_path(path)


def machinery_reason(path: str) -> str | None:
    name = Path(path).name
    if path in FULL_RUN_PATHS or path.startswith(FULL_RUN_PREFIXES):
        return f"{path} decides what runs"
    if name in FULL_RUN_BASENAMES or FULL_RUN_BASENAME_RE.match(name):
        return f"{path} is a file CI installs from or every test loads"
    if path.startswith(CAPABILITY_DIR) and not path.startswith(EXPECTED_TESTS_DIR):
        return f"{path} is a capability declaration other than an expected_tests entry"
    return None


def names(path: str) -> list[str]:
    """The strings that count as 'this text names that file'. The basename always.
    For a .py file also its stem, because Python imports by stem (the ASK-517
    scar: a module wired only by `import` was invisible to a basename match)."""
    p = Path(path)
    out = [p.name]
    if p.suffix == ".py" and len(p.stem) >= 5:
        out.append(p.stem)
    return out


def mentions(text: str, path: str) -> bool:
    return any(re.search(r"(?<![\w.-])" + re.escape(n) + r"(?![\w-]|\.\w)", text) for n in names(path))


# Directory names too generic to identify an owner. `fixtures/` names every
# fixture in the repo, so matching on it would select every test that has one.
_GENERIC_DIRS = frozenset({"test", "tests", "fixtures", "fixture", "scripts", "data", "lib", "src",
                           "q-system", ".q-system", "plugins", "templates", "hooks", "."})


# A filesystem walk, in the spellings this repo's declared tests actually use.
# This is deliberately NOT a pattern parser. Four review rounds on PR #377 were one
# class -- "the selection can miss a test that matters" -- and each round named
# another text form the parser did not know: a fixture reached by directory, a
# `rglob`, a caller's test, then iterdir / os.walk / os.listdir / a shell glob. A
# parser that must recognise every spelling has a fifth gap waiting. So the question
# changes from WHICH FILES does this test scan, which needs the spelling per pattern,
# to DOES THIS TEST SCAN AT ALL, which needs one spelling per WALKING TOOL.
#
# FEWER SPELLINGS, NOT ZERO, and the difference is the whole honest claim (claude
# review of PR #377, minor 1). The earlier wording here said the detector "does not
# need the spelling", which is what made `grep -r` invisible: two declared tests walk
# the tree with recursive grep and sat off the always-run floor, silently, for exactly
# the reason a missing spelling always does. A tool this misses is a scanner being
# skipped, and ASK-1918's `covers` mechanism is built on this function, so the gap
# propagates -- a test the detector cannot see can never be taken off a floor it was
# never on, and never gets the floor's protection either.
#
# WIDENED AGAINST THE CORPUS, NEVER SPECULATIVELY
# (count-the-shape-in-the-corpus-before-you-widen-a-pattern-for-it). Measured over
# the 278 declared tests, 2026-09-20: `grep -r` appears in 5, of which 2 were
# invisible here. An `rg` INVOCATION appears in 0 -- the only `rg` token in the
# corpus is a local variable in test_dc_reader_verdicts.py -- so ripgrep is
# deliberately NOT in this pattern. Add it the day a declared test runs it, with the
# count that says so.
_SCAN_RE = re.compile(
    r"\b(?:r?glob|iterdir|listdir|scandir|walk|fnmatch)\b"
    r"|\bfind\s+[\"\'$./]|\bls\s+[-\"\'$./]|git\s+ls-files"
    r"|\bgrep\s+(?:-\w+\s+)*-[A-Za-z]*r"
    r"|\bfor\s+\w+\s+in\s+[^\n]*\*")


def scans_the_tree(text: str) -> bool:
    return _SCAN_RE.search(text) is not None


def _segment_re(seg: str) -> str:
    """One path segment's glob, as regex. `*` and `?` STOP AT A SEPARATOR, which
    is the whole reason `**` has something left to mean."""
    out, i, n = [], 0, len(seg)
    while i < n:
        c = seg[i]
        if c == "*":
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        elif c == "[":
            j = i + 1
            if j < n and seg[j] in "!^":
                j += 1
            if j < n and seg[j] == "]":
                j += 1
            while j < n and seg[j] != "]":
                j += 1
            if j >= n:
                out.append(r"\[")                  # unclosed: a literal bracket
            else:
                body = seg[i + 1:j].replace("\\", r"\\")
                out.append("[" + ("^" + body[1:] if body[:1] in "!^" else body) + "]")
                i = j + 1
                continue
        else:
            out.append(re.escape(c))
        i += 1
    return "".join(out)


@functools.lru_cache(maxsize=512)
def _covers_re(pattern: str) -> re.Pattern:
    """A coverage glob compiled ONCE. covers-lint runs every declared glob against
    every tracked path, so this is O(globs x files) calls on one small set."""
    segs = pattern.split("/")
    out = []
    for i, seg in enumerate(segs):
        last = i == len(segs) - 1
        if seg == "**":
            # ZERO OR MORE SEGMENTS. The `+` inside and the `*` outside are the
            # bug: `[^/]+/` alone is "at least one", which is exactly what
            # fnmatch did and exactly what missed depth zero, twice.
            out.append(".*" if last else "(?:[^/]+/)*")
        else:
            out.append(_segment_re(seg))
            if not last:
                out.append("/")
    return re.compile("".join(out))


def covers_matches(pattern: str, path: str) -> bool:
    """Does a DECLARED coverage glob claim this path? (ASK-1918, ASK-1922)

    NOT THE PARSER THAT WAS REJECTED. Rounds 1-4 of PR #377 tried to INFER what a
    test covers by reading globs out of its own source, and each round named
    another spelling the parser did not know, until round 4 gave up and made
    every scanner always-run. That rejection stands and this does not reopen it:
    the pattern here is WRITTEN DOWN by someone who knows the test, in its own
    capability fragment, so there is no source to mis-read and no fifth spelling.

    ONE MATCHER, NOT A PILE OF BRANCHES (ASK-1922). The first cut was `fnmatch`
    with special cases bolted on, and `fnmatch` has no concept of `**` at all --
    it only appeared to work because its `*` crosses `/`. PR #385 round 1 found
    that a LEADING `**/` missed all 39 root-level scripts; round 2 found the same
    defect one position over, on an INTERIOR `**/`. Same finding class twice
    means the fix SHAPE was wrong, so every position is handled by one translate
    rather than by a third branch waiting for a fourth.

    The semantics, all pinned by `DOUBLE_STAR_CASES` in the paired test:
      * `**` as a whole segment is ZERO OR MORE segments, at any position.
      * `*` and `?` stop at `/`. Under fnmatch they did not, which made `*` and
        `**` synonyms and left `**` as decoration. `a/*/b` is now one level.
      * a trailing `**` is everything BELOW that directory.
      * a pattern with no `/` matches the BASENAME, the way `find -name` and a
        bare pathspec do.
      * the match is ANCHORED at the repo root. The old third branch also tried
        `*/<pattern>`, so `scripts/*.py` silently claimed any `scripts/` in the
        tree; write the leading `**/` when that is what you mean.

    A `**` that is NOT a whole segment (`**.py`, `a**b`) is not a `**` here; it
    degrades to `*`. covers-lint refuses such a glob rather than let the matcher
    guess -- see its `_bad_double_star`."""
    subject = path if "/" in pattern else Path(path).name
    return _covers_re(pattern).fullmatch(subject) is not None


def owning_dirs(path: str) -> list[str]:
    """The directory names that identify whose fixture this is: every ancestor
    that is not a generic container name."""
    return [d for d in Path(path).parts[:-1] if d not in _GENERIC_DIRS and len(d) >= 4]


def mentions_dir(text: str, name: str) -> bool:
    return re.search(r"(?<![\w.-])" + re.escape(name) + r"(?![\w.-])", text) is not None


def executable_text(text: str) -> str:
    """The lines that RUN: whole-line `#` comments dropped. Docstrings and inline
    comments stay, so this errs toward keeping an edge, never toward losing one."""
    return "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))


_TOKEN_RE = re.compile(r"[A-Za-z0-9_][\w.-]*")


def name_index(texts: dict[str, str]) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """ONE PASS PER FILE, then set lookups. The first closure ran the `mentions`
    regex for every (file, frontier) pair and took over ten minutes to classify 80
    commits, which is not a thing CI can afford on every pull request.

    Two maps from a name to the files that carry it: whole tokens (`converge.sh`,
    never `test-converge.sh` or `converge.sh.bak`, which are different tokens) and
    dot-pieces (`loops_path` out of `loops_path.resolve`), because Python reaches
    a module by its stem."""
    whole, pieces = {}, {}
    for path, text in texts.items():
        for tok in set(_TOKEN_RE.findall(text)):
            tok = tok.rstrip(".-")
            whole.setdefault(tok, set()).add(path)
            for piece in tok.split("."):
                pieces.setdefault(piece, set()).add(path)
    return whole, pieces


def files_naming(path: str, index: tuple[dict, dict]) -> set[str]:
    whole, pieces = index
    p = Path(path)
    found = set(whole.get(p.name, ()))
    if p.suffix == ".py" and len(p.stem) >= 5:
        found |= pieces.get(p.stem, set())
    return found


def dependents(path: str, index: tuple[dict, dict]) -> list[str]:
    """The code files that use <path>: ONE step out, always.

    Depth is a measured choice, not a default. On the last 80 commits of main
    (classifier only, 2026-09-19), against 236 declared tests:
      one step, only when nothing names the file   57 selected runs   <- round 1, and
                                                    it skipped a real downstream test
      one step, always                             45 selected runs   <- this
      the full transitive walk                     30 selected runs
    A few hub scripts (the worker, the dispatcher, converge) use almost everything
    and are used by almost everything, so the transitive walk reaches the width cap
    on most changes and IS the full suite. One step closes the case the review
    named, a lib with its own test plus a caller whose test breaks with it. A break
    two steps out is caught by the full run on the push to main."""
    return sorted(c for c in files_naming(path, index) if c != path)


def third_party_imports(diff_text: str, local_stems: set[str]) -> list[str]:
    """New imports in APP code only. A test file importing pytest is not a new
    dependency of the product: CI already installs it, and 9 of the last 40
    commits on main were called L for exactly that before this was scoped."""
    std = set(getattr(sys, "stdlib_module_names", ()))
    found, current = [], ""
    for line in diff_text.splitlines():
        f = _DIFF_FILE_RE.match(line)
        if f:
            current = f.group(1)
            continue
        if line.startswith("+++") or is_test_path(current):
            continue
        m, f2 = _IMPORT_LINE_RE.match(line), _FROM_LINE_RE.match(line)
        mods = [part.split()[0].split(".")[0] for part in m.group(1).split(",")] if m else []
        if f2:
            mods.append(f2.group(1))
        for mod in mods:
            if mod not in std and mod not in local_stems and mod not in found:
                found.append(mod)
    return found


def plan(changed: list[tuple[str, int]], declared: dict[str, str], code_texts: dict[str, str],
         diff_text: str = "", local_stems: set[str] | None = None,
         fragments: dict[str, str] | None = None,
         covers: dict[str, list[str]] | None = None) -> dict:
    """PURE. changed = [(path, changed_line_count)] (both sides of a rename listed);
    declared = {declared test path: its text}; code_texts = {non-test code path:
    its text}, used for the one-hop dependents; covers = {declared test path: the
    path globs its fragment says it covers}. Returns the whole verdict."""
    reasons, escalators, selected = [], [], set()
    app_lines = sum(n for p, n in changed if is_code(p))

    for path, _ in changed:
        why = machinery_reason(path)
        if why:
            escalators.append(why)
        if path in (fragments or {}):
            # A newly declared test has to run on the PR that declares it. The
            # path comes from the fragment's own `path` key, never from its
            # filename, so the declaration has one reader.
            selected.add(fragments[path])
        if path in declared:
            selected.add(path)

    for mod in third_party_imports(diff_text, local_stems or set()):
        escalators.append(f"new third-party import: {mod}")

    # A SCANNER ALWAYS RUNS, UNLESS IT HAS SAID WHAT IT COVERS (ASK-1918). It
    # reads files nobody named, so absent a declaration no selection can be
    # trusted to include it. Measured 2026-09-19: 72 of 236 declared tests scan,
    # and they cost 699s of the full suite's 822s (runs 35488448685 /
    # 35486006414) -- 31% of the artifacts carrying 85% of the time, which is why
    # no SELECTOR alone ever got under 15%.
    #
    # A fragment that declares a non-empty `covers` list takes that test OFF the
    # floor and puts it on ordinary selection. The default stays the floor, so
    # zero declarations reproduce the old behaviour exactly and this lands one
    # fragment at a time. They are excluded from the width cap below -- a fixed
    # floor is not evidence that THIS diff is suite-wide.
    declared_covers = {t: pats for t, pats in (covers or {}).items() if pats}
    scanners = {t for t, text in declared.items() if scans_the_tree(text)}
    always = {t for t in scanners if t not in declared_covers}
    live = name_index({c: executable_text(text) for c, text in code_texts.items()}) if code_texts else ({}, {})
    test_index = name_index(declared) if declared else ({}, {})

    # A DECLARED COVERAGE GLOB SELECTS (ASK-1918), and only for a test that
    # actually scans. `covers` may take a test OFF the always-run floor; it may
    # never put one ON, or a declaration would be a second way to select and a
    # typo could aim it anywhere.
    #
    # ITS OWN PASS OVER EVERY CHANGED PATH (claude review of PR #385, minor 2).
    # It used to live inside the loop below, AFTER that loop's `continue` for a
    # path that is itself a declared test -- so a glob naming another declared
    # test's path was silently not honoured, and covers-lint could not see it
    # either, because such a glob does match a tracked file.
    for path, _ in changed:
        selected |= {t for t, pats in declared_covers.items()
                     if t in scanners and any(covers_matches(p, path) for p in pats)}

    for path, _ in changed:
        if path in declared or path in (fragments or {}) or machinery_reason(path):
            continue        # handled above: a test runs itself, a fragment runs its test
        direct = {t for t, text in declared.items() if mentions(text, path)}
        # NO PATTERN PARSER HERE, ON PURPOSE. A test that ENUMERATES its inputs
        # never names them (codex, PR #377 round 1, major 2: test-install-jobs-
        # coverage.py globs `com.kipi.*.plist`). Round 1 answered that by reading
        # globs out of the test's text; rounds 2-4 each named another spelling it
        # did not know, and round 4 deleted the line that made it select anything,
        # because a test that enumerates ALSO walks the tree, so `always` below
        # already covers every one of them. The parser was 40 lines that chose
        # nothing. `scans_the_tree` is the answer to that class, at ONE spelling per
        # walking tool instead of one per pattern -- see its comment for what that
        # does and does not buy.
        #
        # (`covers` is handled in its own pass above, over every changed path.)
        if is_test_path(path) or not is_code(path):
            # A FIXTURE, A HELPER, OR A DATA FILE (same review, major 1). The first
            # cut skipped everything under test/ and fixtures/ before matching, so
            # a PR that broke only a tracked fixture ran ZERO tests while the test
            # that owns the fixture was red. A fixture is usually reached by its
            # DIRECTORY (`$HERE/fixtures/receipt-carry`), so that counts as a name.
            # Only for files that live under a test tree. Applied to every data
            # file it matched `.claude/rules/x.md` against every test that says
            # "rules", which is most of them.
            if is_test_path(path):
                direct |= {t for t, text in declared.items()
                           if any(mentions_dir(text, d) for d in owning_dirs(path))}
            # AND WHEN NOTHING NAMES IT, NOTHING EXTRA RUNS. Round 1 escalated to
            # the full suite here. Measured against the last 80 commits of main it
            # fired on 34, and what it fired on was mostly test files CI runs in
            # their own steps, never through this gate. "The full suite" means the
            # DECLARED tests: when none of them can see the file, running all 236
            # exercises it exactly as much as running none. It bought 17 minutes.
            selected |= direct
            continue
        # THE CALLERS' TESTS RUN TOO, WHETHER OR NOT THE FILE HAS ITS OWN (codex, PR
        # #377 round 2). The second cut looked one step out only when nothing named
        # the file directly, so a lib with its own unit test never reached the test
        # of the script that sources it. See `dependents` for why one step.
        #
        # An edge is a mention on a line that EXECUTES. This repo's scripts carry
        # long why-comments naming other scripts by their scars; a script that
        # only talks about another script does not run it.
        hop = set()
        for dep in dependents(path, live):
            hop |= files_naming(dep, test_index)
        selected |= direct | hop

    selected = {t for t in selected if t in declared} | always
    # THE CAP COUNTS WHAT THE DIFF PULLED IN, NOT THE FLOOR. The always-run
    # scanners are the same set on every PR, so counting them would push every
    # change over the cap and back to a full run.
    pulled = selected - always
    if len(pulled) > MAX_SELECTED:
        escalators.append(f"{len(pulled)} tests name the changed files, more than {MAX_SELECTED}: that is the suite")

    # TWO ANSWERS, NOT ONE. Size decides the human ceremony (how much review a
    # change earns). ESCALATORS decide whether the whole suite runs. The first cut
    # welded them, so a 304-line change that exactly 2 declared tests name ran all
    # 235 -- and because CI diffs the whole PR against main, it ran them again on
    # every 3-line review round. A bigger diff touches more files, names more
    # tests, and reaches MAX_SELECTED by itself when it really is suite-wide.
    full_suite = bool(escalators)
    if escalators:
        tier = "L"
        reasons = escalators
    elif app_lines > M_MAX_LINES:
        tier = "L"
        reasons = [f"{app_lines} changed lines of app code, more than {M_MAX_LINES}"]
    elif app_lines > S_MAX_LINES:
        tier = "M"
        reasons = [f"{app_lines} changed lines of app code, at most {M_MAX_LINES}"]
    else:
        tier = "S"
        reasons = [f"{app_lines} changed lines of app code, at most {S_MAX_LINES}"]

    # NO COVERAGE-GAP REPORT HERE. Rounds 1-4 grew one: every changed file no
    # declared test owned was listed by name and floored the tier at M. It fired
    # on 36 of the last 80 commits with no triage path, and a selector is the
    # wrong place for it. It is a real finding and it has its own issue.
    return {"tier": tier, "full_suite": full_suite, "reasons": reasons, "app_lines": app_lines,
            "changed_files": len({p for p, _ in changed}), "declared_tests": len(declared),
            "selected_tests": sorted(selected)}


# ------------------------------------------------------------------ git + disk
def _git(root: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()[:300]}")
    return r.stdout


def read_changed(root: Path, base: str, head: str) -> tuple[list[tuple[str, int]], str]:
    """Three-dot: what the branch changed since it left base, which is what a PR
    is. --no-renames so a rename is a delete plus an add and BOTH names are
    searched for; a moved file's tests still name the old path."""
    rng = f"{base}...{head}"
    changed = []
    for line in _git(root, "diff", "--numstat", "--no-renames", rng).splitlines():
        a, d, path = line.split("\t", 2)
        n = (0 if a == "-" else int(a)) + (0 if d == "-" else int(d))   # "-" = binary
        changed.append((path, n))
    return changed, _git(root, "diff", "-U0", "--no-renames", rng, "--", "*.py")


def read_declared(root: Path) -> tuple[dict[str, str], dict[str, str], dict[str, list[str]]]:
    """({declared test path: text}, {fragment file: the test path it declares},
    {declared test path: its `covers` globs}).

    A malformed `covers` (not a list, or holding non-strings) is DROPPED WHOLE
    rather than repaired: the asymmetry says an unreadable declaration leaves the
    test on the always-run floor, which is the expensive answer and the safe one.

    WHOLE is the word the first cut did not honour (claude review of PR #385,
    minor 3). It kept the good entries and dropped only the bad ones, so
    `["**/*.plist", null]` still took the test OFF the floor on a declaration
    nobody could read -- the docstring claimed the safe posture and the code did
    the unsafe one. One bad entry now voids the list. covers-lint refuses such a
    fragment at commit time, so this is the second line of defence, not the
    first."""
    out, fragments, covers = {}, {}, {}
    for frag in sorted((root / EXPECTED_TESTS_DIR).glob("*.json")):
        try:
            entry = json.loads(frag.read_text())
            path = entry.get("path", "")
        except (OSError, ValueError):
            continue
        full = root / path
        if path and full.is_file():
            out[path] = full.read_text(errors="ignore")
            fragments[EXPECTED_TESTS_DIR + frag.name] = path
            pats = entry.get("covers")
            if isinstance(pats, list) and pats and all(isinstance(p, str) and p for p in pats):
                covers[path] = list(pats)
    return out, fragments, covers


def read_code(root: Path) -> tuple[dict[str, str], set[str]]:
    texts, stems = {}, set()
    for path in _git(root, "ls-files", "*.py", "*.sh").splitlines():
        stems.add(Path(path).stem)
        if is_code(path):
            try:
                texts[path] = (root / path).read_text(errors="ignore")
            except OSError:
                pass
    # Every directory name is local too: `from pipeline import x` inside a
    # package resolves to a sibling folder, not to PyPI.
    for path in texts:
        stems |= set(Path(path).parts[:-1])
    return texts, stems


def plan_for_repo(root: Path, base: str, head: str = "HEAD") -> dict:
    changed, diff_text = read_changed(root, base, head)
    code_texts, stems = read_code(root)
    declared, fragments, covers = read_declared(root)
    return plan(changed, declared, code_texts, diff_text, stems, fragments, covers)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", required=True)
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    try:
        verdict = plan_for_repo(Path(args.repo_root).resolve(), args.base)
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"change-size: could not read the diff ({exc}). Treat as L: run the full suite.", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(verdict, indent=1))
        return 0
    print(f"change-size: tier {verdict['tier']} ({verdict['changed_files']} files, {verdict['app_lines']} app-code lines)")
    for r in verdict["reasons"]:
        print(f"  because: {r}")
    if verdict["full_suite"]:
        print(f"  tests: the FULL suite ({verdict['declared_tests']} declared)")
    else:
        print(f"  tests: {len(verdict['selected_tests'])} of {verdict['declared_tests']} declared")
        for t in verdict["selected_tests"]:
            print(f"    {t}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
