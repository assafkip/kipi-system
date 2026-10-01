#!/usr/bin/env python3
"""full_suite_doors.py -- where can a WHOLE test suite run on a PR, a push or a
local hook? (RULE-2026-10-01-A)

One detector, three readers: test_ci_workflows.py (this repo's own workflows),
fleet-full-suite-scan.py (every repo of the account, plus local hooks on this
machine), and its own fixture test. A detector copied into each reader is how
two of them disagree about what a door is.

WHY THIS EXISTS. Founder bar, 2026-10-01: "no 6000-test runs on small changes".
The full suite kept coming back through doors nobody listed: a validate push
branch, `verify.sh --full` on every PR (12.5 min), an unscoped prd-os step, then
other repos nobody had scanned. Each was found by hand, one at a time.

WHAT A DOOR IS, in a step's CODE (comment lines are ignored, so a why-comment may
name the shape it forbids; a step's `name:` label is not code either):
  * verify.sh as the command with no mode or --full (its default IS --full)
  * capability-gate.py with neither --diff-base nor --check-only
  * pytest as the command over a directory, or over nothing (the whole rootdir)
  * validate-separation.py as a command without CAPABILITY_GATE_SKIP "1"
  * `kipi check`
  * npm/yarn/pnpm `test`, bare jest or vitest, `make test`, `flutter test`,
    `go test ./...`, `cargo test`, each with no file filter
  * a call to a reusable workflow (`uses: ./.github/workflows/x.yml` or
    `owner/repo/.github/workflows/x.yml@ref`): this text cannot see inside it,
    so it reads as a door until the caller resolves it (resolve_local)

NOT a door:
  * a selector that falls back to the full suite on a change it cannot vouch
    for. That is conditional, and the fallback is the safety.
  * a workflow whose triggers include neither push nor any pull_request event:
    that is the nightly class, the one place the full suite belongs.
  * a workflow carrying a MEASURED exemption line:
        # full-suite-exempt: 23s measured on run 1234567890 (2026-10-01)
    honoured only when the seconds are under EXEMPT_MAX_S. Running a whole
    suite that takes less than a minute is fine; the line keeps that a
    measurement with a run id, never a guess.

HONEST LIMITS. A step that runs its suite inside a script it calls (a build
gate, a Makefile target under another name) is invisible to text. The fleet
scanner adds a second estimator from measured step durations, but it reads only
steps whose NAME looks like a test (test, suite, gate, verify, ...). A suite in
a called script under a non-test step name is missed by both.
A pytest argument built from a shell variable is not judged (a
selector-built list is the normal shape of that). A hook that calls a script
is judged by the hook's own text, not the script's. Neither the trigger reader
nor the step splitter is a YAML parser; both are pinned by fixtures.
"""
from __future__ import annotations

import re
import shlex

EXEMPT_MAX_S = 60
EXEMPT_RE = re.compile(r"(?m)^\s*#\s*full-suite-exempt:\s*(\d+)s measured on run (\d+)")
PR_OR_PUSH = ("push", "pull_request", "pull_request_target", "merge_group")

# Options whose NEXT token is a value, not a test path.
_PYTEST_VALUE_OPTS = {"-m", "-k", "-o", "-p", "-c", "-n", "--rootdir", "--ignore",
                      "--deselect", "--junitxml", "--maxfail", "--confcutdir", "-W"}
_CMD_START = r"(?:^|[;&|(]\s*|\bthen\s+|\bdo\s+|\bexec\s+|\btime\s+)"


def code_lines(text: str) -> str:
    return "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))


def triggers(text: str) -> set[str]:
    """The event names under the top-level `on:` (or the quoted forms)."""
    code = code_lines(text)
    # A trailing comment on the `on:` line zeroed every trigger (PR #492 review).
    m = re.search(r"""(?m)^(?:on|"on"|'on'|true):[ \t]*([^#\n]*)(?:#.*)?$""", code)
    if not m:
        return set()
    inline = m.group(1).strip()
    if inline:
        return set(re.findall(r"[A-Za-z_]+", inline))
    out, started = set(), False
    for line in code[m.end():].splitlines():
        if not line.strip():
            continue
        if not line.startswith((" ", "\t")):
            break                         # the next top-level key
        k = re.match(r"^(\s+)(?:-\s*)?([A-Za-z_]+)\s*:?", line)
        if not k:
            continue
        indent = len(k.group(1))
        if not started:
            base, started = indent, True
        if indent == base:
            out.add(k.group(2))
    return out


def runs_on_pr_or_push(text: str) -> bool:
    return bool(triggers(text) & set(PR_OR_PUSH))


def exemption(text: str) -> tuple[int, str] | None:
    m = EXEMPT_RE.search(text)
    if m and int(m.group(1)) < EXEMPT_MAX_S:
        return int(m.group(1)), m.group(2)
    return None


def _steps(text: str) -> list[str]:
    """Every list item under a `steps:` key, plus each job block (a job-level
    `uses:` is a reusable-workflow call with no steps). Splitting on ANY list
    item, not only name/uses/run (PR #491 review: an `if:`-first step or an
    `env:`-first step was read as part of the step before it)."""
    code = code_lines(text)
    blocks = []
    for sm in re.finditer(r"(?m)^(\s*)steps:\s*(?:#.*)?$", code):
        ind = len(sm.group(1))
        body = []
        for line in code[sm.end():].splitlines()[1:]:
            li = len(line) - len(line.lstrip())
            # YAML lets a list sit at its key's own indent (`steps:` then `- run:`
            # in the same column). Stopping there read zero steps (PR #492 review).
            if line.strip() and (li < ind or (li == ind and not line.lstrip().startswith("- "))):
                break
            body.append(line)
        cur: list[str] = []
        item_ind = None
        for line in body:
            mm = re.match(r"^(\s*)-\s", line)
            if mm and (item_ind is None or len(mm.group(1)) <= item_ind):
                item_ind = len(mm.group(1))
                if cur:
                    blocks.append("\n".join(cur))
                cur = [line]
            else:
                cur.append(line)
        if cur:
            blocks.append("\n".join(cur))
    for jm in re.finditer(r"(?m)^    uses:\s*(\S+)", code):
        blocks.append(f"uses: {jm.group(1)}")
    return blocks


def _pytest_door(line: str) -> bool:
    m = re.search(_CMD_START + r"(?:(?:uv|poetry|pipenv|hatch|pdm)\s+run\s+)?(?:python3?\s+-m\s+)?"
                  r"(?:py\.test|pytest)(?![\w:.-])(.*)$", line)
    if not m:
        return False
    rest = m.group(1)
    try:
        toks = shlex.split(rest)
    except ValueError:
        toks = rest.split()
    paths, skip = [], False
    for t in toks:
        if t in ("|", "||", "&&", ";") or t.startswith((">", "2>")):
            break
        if skip:
            skip = False
            continue
        if t in _PYTEST_VALUE_OPTS:
            skip = True
            continue
        if t.startswith("-") or t == "\\":
            continue
        paths.append(t)
    if not paths:
        return True
    return any(not p.startswith("$") and not (p.endswith(".py") or ".py::" in p) for p in paths)


_JS_RUNNER = re.compile(_CMD_START + r"(?:npx\s+)?(jest|vitest)(?:\s+(run))?\s*(.*)$")
_PKG_TEST = re.compile(_CMD_START + r"(?:npm|yarn|pnpm)\s+(?:run\s+)?test(?=\s|$)(.*)$")
_OTHER = (
    (re.compile(_CMD_START + r"make\s+test\b"), "make test"),
    (re.compile(_CMD_START + r"flutter\s+test\s*(?:$|[;&|]|--)"), "flutter test over the package"),
    (re.compile(_CMD_START + r"go\s+test\s+(?:\S+\s+)*\./\.\.\."), "go test ./..."),
    (re.compile(_CMD_START + r"cargo\s+test\b"), "cargo test"),
    (re.compile(_CMD_START + r"kipi\s+check\b"), "kipi check runs the full gate"),
    # PR #492 review: each of these runs a whole suite by default.
    (re.compile(_CMD_START + r"tox(?:\s+(?:-e\s+\S+|-p|-q|-v))*\s*(?:$|[;&|])"), "tox over every env"),
    (re.compile(_CMD_START + r"(?:\./)?gradlew\s+(?:\S+\s+)*test\b(?!.*--tests)"), "gradle test"),
    (re.compile(_CMD_START + r"mvn\s+(?:\S+\s+)*test\b(?!.*-Dtest=)"), "mvn test"),
    (re.compile(_CMD_START + r"dotnet\s+test\b(?!.*--filter)"), "dotnet test"),
    (re.compile(_CMD_START + r"(?:bundle\s+exec\s+)?rspec\s*(?:$|[;&|]|--)"), "rspec over the suite"),
)


def line_doors(line: str) -> list[str]:
    s = re.sub(r"^(?:-\s*)?run:\s*\|?\s*", "", line.strip())
    if not s or re.match(r"^(?:-\s*)?name:", s):
        return []
    if re.match(r"^[\w.-]+:\s*(?:#.*)?$", s):
        return []                        # a YAML key (lefthook's `pytest:` command NAME)
    hits = []
    v = re.search(r"(?:^|[;&|]\s*|(?:^|\s)(?:bash|sh)\s+)(?:\S*/)?verify\.sh\b(.*)$", s)
    if v and not re.match(r"\s+--(changed|staged)\b", v.group(1)):
        hits.append(f"verify.sh runs --full: {s}")
    if "capability-gate.py" in s and "--diff-base" not in s and "--check-only" not in s:
        hits.append(f"capability gate with no diff base: {s}")
    if _pytest_door(s):
        hits.append(f"pytest over a whole suite: {s}")
    j = _JS_RUNNER.search(s)
    if j and not re.search(r"\S+\.(?:[cm]?[jt]sx?)\b|--findRelatedTests|\brelated\b|--changed", j.group(3)):
        hits.append(f"{j.group(1)} over the whole suite: {s}")
    p = _PKG_TEST.search(s)
    if p and not re.search(r"\S+\.(?:[cm]?[jt]sx?)\b|--findRelatedTests|--changed", p.group(1)):
        hits.append(f"package test script over the whole suite: {s}")
    for rx, why in _OTHER:
        if rx.search(s):
            hits.append(f"{why}: {s}")
    return hits


def _nightly_only_step(step: str) -> bool:
    """A step whose `if:` admits only schedule / workflow_dispatch runs on no PR
    and no push, so it is the nightly class even inside a push workflow (PR #492
    review: a correctly guarded full run was reported as a door, and the only
    exemption needs under 60s, which a full suite cannot meet)."""
    m = re.search(r"(?m)^\s*(?:-\s*)?if:\s*(.+)$", step)
    if not m:
        return False
    expr = m.group(1)
    allowed = re.findall(r"github\.event_name\s*==\s*'(\w+)'", expr)
    return (bool(allowed) and set(allowed) <= {"schedule", "workflow_dispatch"}
            and not re.search(r"!=|&&|\bpush\b|pull_request", expr))


def workflow_doors(text: str) -> list[str]:
    """Doors a workflow opens on PR or push. Empty for the nightly class and for
    a measured exemption under EXEMPT_MAX_S."""
    if not runs_on_pr_or_push(text) or exemption(text):
        return []
    hits = []
    for step in _steps(text):
        if _nightly_only_step(step):
            continue
        for line in step.splitlines():
            hits += line_doors(line)
        if re.search(r"python3?\s+\S*validate-separation\.py", step) and \
                not re.search(r'CAPABILITY_GATE_SKIP:\s*"?1"?', step):
            hits.append("validate-separation.py without CAPABILITY_GATE_SKIP runs the full gate")
        u = re.search(r"(?m)^\s*(?:-\s*)?uses:\s*(\S*\.github/workflows/\S+)", step)
        if u:
            hits.append(f"reusable workflow call, unresolved: {u.group(1)}")
    return hits


def resolve_local(hits: list[str], read) -> list[str]:
    """Replace an unresolved LOCAL reusable-workflow hit with that file's own
    doors. `read(path)` returns the file text or None. A remote call stays a
    door: this machine cannot vouch for another repo's ref."""
    out = []
    for h in hits:
        m = re.match(r"reusable workflow call, unresolved: \./(\.github/workflows/\S+)$", h)
        if not m:
            out.append(h)
            continue
        text = read(m.group(1))
        if text is None:
            out.append(h)
            continue
        # A called workflow's own `on:` is workflow_call, so read its steps directly.
        inner = []
        for step in _steps(text):
            for line in step.splitlines():
                inner += line_doors(line)
        out += [f"{m.group(1)}: {d}" for d in inner]
    return out


def hook_doors(text: str) -> list[str]:
    """Doors in a local hook: a git hook script or a lefthook.yml."""
    hits = []
    for line in code_lines(text).splitlines():
        hits += line_doors(re.sub(r"^\s*(?:run|script):\s*", "", line))
    return hits
