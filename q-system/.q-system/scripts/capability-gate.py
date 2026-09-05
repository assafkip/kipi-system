#!/usr/bin/env python3
"""Capability gate: diff DECLARED capabilities against ACTUAL repo state, both
directions, then run every in-scope test artifact.

Why this exists (scar, 2026-07-23, prd-silent-absence-capability-gate): 38 test
artifacts existed under q-system/.q-system/scripts while CI ran 4 by hardcoded
allowlist — 89.5% never executed anywhere; an 802-line stat-verify engine
sat unwired for months; a skeleton-only test shipped to 24 instances and
crashed in 23. Nothing declared what was supposed to exist, so nothing could
detect what was missing. Silent absences are invisible to exit codes; this
gate makes absence loud in both directions.

Manifest: q-system/.q-system/capability/ (canonical, synced) -- one JSON
          fragment per declaration, assembled by capability_manifest.py.
Overlay:  <repo-root>/capability-manifest.local.json (instance-local, ADD-only).

Exit codes: 0 green, 1 red, 3 refused (worktree copy).
"""

import argparse
import datetime
import json
import os
import re
import signal
import subprocess
import sys
import threading
from pathlib import Path

# Same directory, and this script is invoked by path from several
# roots (lefthook, kipi check, CI), so the parent dir is put on the
# path explicitly rather than relying on the caller's cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import capability_manifest  # noqa: E402

SCHEMA_VERSION = 1
ALLOWED_TOP_KEYS = {
    "schema_version", "expected_tests", "required_data",
    "skeleton_only", "declared_inert", "uncovered_known", "scope_exempt",
}
OVERLAY_ALLOWED_KEYS = {"expected_tests", "required_data"}
TEST_PATTERNS = ("test_*.py", "test-*.py", "test-*.sh")
# Both contracted roots: scripts/ recursive, plus top-level .q-system test
# files (finding-9/adversarial: token-guard-adjacent tests may land there).
SCAN_ROOTS = ("q-system/.q-system/scripts", "q-system/.q-system")
DEFAULT_TIMEOUT_S = 60
TIMEOUT_MIN_S, TIMEOUT_MAX_S = 5, 600

# Wiring surfaces for the inert-engine check (F2 class). Textual-reference
# heuristic, declared as such in the PRD: a false "inert" is resolved by a
# declared_inert entry or a real call site — both loud, neither silent.
WIRING_SURFACES = (
    ".claude/settings.json",
    "settings-template.json",
    "validate-separation.py",
    # lefthook is this repo's pre-commit enforcement layer (gitleaks,
    # blocked-paths, instruction-budget, linear-issue-ref). A script wired ONLY
    # there was reported inert, which is backwards: a commit-blocking hook is
    # the strongest wiring a script can have. Added 2026-07-26 when
    # receipts-ledger-check.py, wired in lefthook and nowhere else, was flagged.
    "lefthook.yml",
)
WIRING_SURFACE_GLOBS = (
    "plugins/*/hooks/hooks.json",
    "plugins/*/hooks.json",
    ".github/workflows/*.yml",
    "kipi*",
    "*.sh",
    "q-system/.q-system/scripts/*.sh",
    # A launchd plist template IS wiring, and for a SCHEDULED job it is the only
    # wiring there is. Measured 2026-08-30 (ASK-1178): morning-brief.py and
    # morning-brief-deadman.py were reported inert while both had a committed
    # plist naming them and both were loaded and firing on this Mac. The gate was
    # telling a scheduled job to justify itself as dead code. install-plist.sh
    # renders these into ~/Library/LaunchAgents, so a name appearing here is a
    # job that actually runs.
    "q-system/.q-system/scripts/*.plist",
    "q-system/hooks/*",
    ".claude/**/*.md",
    "plugins/**/*.md",
    "q-system/.q-system/**/*.md",
    "q-system/.q-system/**/*.py",
    "q-system/.q-system/*.py",
    # The MCP server's source tree is where an agent-facing tool gets wired
    # (wiring-check.md: "any new MCP tool is registered in the server"). Without
    # it reddit_read.py, called only from kipi-mcp's web_read.py, was reported
    # inert on CI (PR #294, 2026-09-02).
    "plugins/*/kipi-mcp/src/**/*.py",
)


def refuse_if_worktree(root):
    """A .claude/worktrees copy is a parallel checkout; gating it double-reports
    and its registry state is not authoritative. Refuse, do not guess."""
    if "/.claude/worktrees/" in str(root.resolve()) + "/":
        print("REFUSED: run the capability gate from the primary checkout, "
              "not a .claude/worktrees copy.", file=sys.stderr)
        sys.exit(3)


def detect_mode(root, errors):
    """skeleton iff instance-registry.json exists at repo root. A present but
    unparseable registry is RED, never silently instance mode (finding-13)."""
    reg = root / "instance-registry.json"
    if not reg.is_file():
        return "instance"
    try:
        json.loads(reg.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        errors.append(f"instance-registry.json present but unreadable: {exc}")
    return "skeleton"


def load_manifest(root, errors):
    """Assemble the manifest from its fragment directory, then validate it.

    The manifest used to be one hand-maintained file with one unsorted
    182-entry `expected_tests` array, so every branch that declared a test
    appended to the same lines and collided with every other branch: it was the
    conflict in 37 of 41 conflicting PRs and the ONLY conflict in 16. It is now
    one file per declaration under q-system/.q-system/capability/; two branches
    adding two declarations write two different filenames and never collide.
    Only the ASSEMBLY moved -- every rule below still reads the same dict, so
    the declared-vs-actual diff is unchanged in both directions.
    """
    data = capability_manifest.load(root, errors)
    if data is None:
        return None
    validate_manifest(data, errors)
    return data


def unsafe_path(p):
    """Manifest/overlay paths are repo-root-relative only. An absolute path or
    a .. escape would let a declaration point OUTSIDE the repo (adversarial
    finding: overlay entry naming /etc/... must be RED, not silently checked)."""
    if not isinstance(p, str) or not p:
        return True
    if p.startswith(("/", "~")) or "\\" in p:
        return True
    return ".." in p.split("/")


def validate_scope_exempt(data, errors):
    """Read `scope_exempt` and return the path prefixes it declares.

    This is the ONLY way a declaration may sit outside SCAN_ROOTS, and it exists
    because the alternative shapes both fail (ASK-972, measured 2026-08-22 on
    this repo): refusing every unscanned path outright is RED on 15 entries the
    day it ships, and widening discovery to the repo root surfaces 123
    undeclared test-pattern files. A gate red on its own population gets
    switched off, and a gate that is off protects nothing.

    So the boundary is not removed, it is made LEGIBLE: every escape is named
    with a reason in one reviewable place, counted in the summary of every run,
    and still subject to the existence check. What it buys is that a NEW escape
    can no longer happen in silence, which is the whole defect.

    What this deliberately does NOT do is close the undeclared-artifact
    direction inside an exempt tree; that population and its design call are
    captured as sp-c3d0f4d3 rather than left as a comment. # spillover-skip
    """
    prefixes = []
    for item in data.get("scope_exempt", []):
        if not isinstance(item, dict) or not item.get("prefix") or not item.get("reason"):
            errors.append(f"scope_exempt entry needs prefix+reason: {item!r}")
            continue
        if unsafe_path(item["prefix"]):
            errors.append(f"unsafe or non-relative prefix in scope_exempt: {item['prefix']!r}")
            continue
        prefixes.append(item["prefix"])
    return prefixes


def declaration_scope_error(path, exempt_prefixes):
    """The message for a declaration that neither scan root covers.

    Named separately so the refusal text is written once and both the canonical
    manifest and the instance overlay refuse with the identical wording.
    """
    if any(path.startswith(pref) for pref in exempt_prefixes):
        return None
    return (f"declared outside the scan roots and not exempt: {path} — "
            f"expected_tests paths live under {SCAN_ROOTS[0]}/ or directly in "
            f"{SCAN_ROOTS[1]}/, because the undeclared-artifact direction of the "
            "diff can only see what those roots discover. Move it, or add a "
            "scope_exempt {prefix, reason} entry saying why this tree is not "
            "scanned.")


def validate_test_entry(entry, seen, errors, exempt_prefixes=()):
    """One validator for canonical AND overlay entries (finding: overlay
    entries were appended after validation and never validated themselves)."""
    p = entry.get("path", "")
    if unsafe_path(p):
        errors.append(f"unsafe or non-relative path in expected_tests: {p!r}")
        return
    if not in_scan_scope(p):
        # ASK-972: this was the silent escape. `in_scan_scope` was consulted only
        # by the diff, which then had nothing to compare an unscanned path
        # against, so such a path skipped the undeclared-artifact direction
        # entirely and nothing said so. Refusing at DECLARATION time is the
        # earliest point the two scopes can be held equal.
        msg = declaration_scope_error(p, exempt_prefixes)
        if msg:
            errors.append(msg)
    if entry.get("runner") not in RUNNERS:
        errors.append(
            f"expected_tests entry needs runner {'|'.join(RUNNERS)}: {p}")
    if p in seen:
        errors.append(f"duplicate expected_tests path: {p}")
    seen.add(p)
    t = entry.get("timeout_s", DEFAULT_TIMEOUT_S)
    if not (isinstance(t, int) and TIMEOUT_MIN_S <= t <= TIMEOUT_MAX_S):
        errors.append(f"timeout_s out of bounds [{TIMEOUT_MIN_S},{TIMEOUT_MAX_S}]: {p}")
    validate_quarantine(entry, errors)


# A declared test's runner has to be the one that actually EXECUTES it.
#
# ASK-1145, measured 2026-08-29. 13 manifest entries declared `runner: python3`
# on pytest-shaped modules -- bare `def test_` at module level, no `__main__`
# block. `python3 <file>` imports such a module, binds the function names, and
# exits 0 having run nothing. The gate counted 13 tests, reported them green,
# and was structurally blind to the 248 real cases inside them. Three of those
# were FAILING, invisibly, in the fact-propagation leak gate on a public repo.
#
# `pytest` is added as a third runner rather than patching a `__main__` block
# into 13 files, because the 14th file would arrive without one and nothing
# would say so. The detector below is what makes that true: a python3-declared
# module that is pytest-shaped is REFUSED at declaration time, so the mistake
# cannot be made silently again.
RUNNERS = ("python3", "bash", "pytest")

# Module-level `def test_...`. Indented defs are methods on a unittest class,
# which `python3 <file>` still cannot run without a `__main__` block, so they
# count the same way.
_BARE_TEST_DEF = re.compile(r"^\s*def test_\w*\s*\(", re.M)
_HAS_MAIN = re.compile(r"^if __name__\s*==\s*[\"']__main__[\"']\s*:", re.M)


def executes_nothing(entry, full):
    """Refuse a python3-declared test that `python3 <file>` cannot execute.

    The check is deliberately narrow: it fires only on a `.py` file declared
    `python3` that DEFINES test functions and has NO `__main__` entry point.
    A script that does its work at import time (most of the bash-adjacent
    python helpers here) defines no `def test_` and is untouched.

    An unreadable file is not a pass and not a failure here -- the missing-file
    direction is already reported by the manifest diff, so this returns quietly
    rather than adding a second, differently-worded error for one cause.
    """
    if entry.get("runner") != "python3":
        return False
    if not str(full).endswith(".py"):
        return False
    try:
        text = full.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return bool(_BARE_TEST_DEF.search(text)) and not _HAS_MAIN.search(text)


def validate_data_entry(entry, errors):
    """required_data needs a safe path and a well-formed scope: a typo like
    'skeletn' must be RED, not a silently-never-applies contract (finding-3
    of the standard review)."""
    p = entry.get("path", "")
    if unsafe_path(p):
        errors.append(f"unsafe or non-relative path in required_data: {p!r}")
    scope = entry.get("scope", "all")
    ok = scope in ("all", "skeleton") or (
        isinstance(scope, list) and scope and all(isinstance(s, str) for s in scope))
    if not ok:
        errors.append(f"required_data scope must be 'all'|'skeleton'|[instance...]: {scope!r}")


def validate_manifest(data, errors):
    if not isinstance(data, dict):
        errors.append("manifest must be a JSON object")
        return
    sv = data.get("schema_version")
    # exact-int check: JSON `1.0` and `true` both == 1 in Python, so a bare
    # equality test accepted them (codex, sag-manifest-schema-validation)
    if not isinstance(sv, int) or isinstance(sv, bool) or sv != SCHEMA_VERSION:
        errors.append(f"manifest schema_version must be the integer {SCHEMA_VERSION}")
    unknown = set(data) - ALLOWED_TOP_KEYS
    if unknown:
        errors.append(f"manifest unknown top-level keys: {sorted(unknown)}")
    exempt = validate_scope_exempt(data, errors)
    seen = set()
    for entry in data.get("expected_tests", []):
        validate_test_entry(entry, seen, errors, exempt)
    for set_name in ("required_data", "skeleton_only", "declared_inert"):
        items = data.get(set_name, [])
        paths = [i if isinstance(i, str) else (i or {}).get("path", "") for i in items]
        for dup in {p for p in paths if paths.count(p) > 1}:
            errors.append(f"duplicate path in {set_name}: {dup}")
    for entry in data.get("required_data", []):
        validate_data_entry(entry, errors)
    for p in data.get("skeleton_only", []):
        if unsafe_path(p):
            errors.append(f"unsafe or non-relative path in skeleton_only: {p!r}")
    for entry in data.get("declared_inert", []):
        if not entry.get("path") or not entry.get("reason") or not entry.get("spillover_id"):
            errors.append(f"declared_inert entry needs path+reason+spillover_id: {entry}")
        elif unsafe_path(entry["path"]):
            errors.append(f"unsafe or non-relative path in declared_inert: {entry['path']!r}")


def spillover_ledger_path(root):
    """The ONE spillover ledger for this checkout and all of its worktrees.

    Mirrors prd_runner._ledger_root deliberately rather than importing it: this
    gate is synced to every instance by `kipi update` and must run where
    plugins/prd-os is absent. The rule it copies is load-bearing — `*.jsonl` is
    gitignored, so resolving the ledger from a per-worktree root gives every
    worktree a private copy, and a gate reading the wrong copy reports a safety
    it cannot provide (sp-bc42f1d3, 26 private ledgers / 71 invisible findings).
    `--git-common-dir` is shared across the worktree set, so its parent is the
    main checkout no matter which worktree calls us.

    Falls back to `root` when git cannot answer. Degraded, never fatal: the
    caller treats a missing ledger as "not mine to judge".
    """
    ledger_root = Path(root)
    try:
        out = subprocess.run(["git", "rev-parse", "--git-common-dir"],
                             cwd=str(root), capture_output=True, text=True, timeout=10)
        if out.returncode == 0 and out.stdout.strip():
            common = Path(out.stdout.strip())
            if not common.is_absolute():
                common = Path(root) / common
            parent = common.resolve().parent
            # Only trust it if it really looks like a checkout root; a bare
            # repo's parent is an arbitrary directory.
            if (parent / ".git").exists():
                ledger_root = parent
    except (OSError, subprocess.SubprocessError):
        pass
    return ledger_root / ".prd-os" / "spillover.jsonl"


# A row present with status None is not the same as an id with no row at all;
# `status.get(sid)` collapses both to None and would make a real row look absent.
_ABSENT = object()


def check_inert_spillover_live(root, manifest, errors, notes=None, mode="instance"):
    """A declared_inert entry must cite a spillover id that is still a LIVE
    decision (ASK-345).

    `validate_manifest` only checked that `spillover_id` is a non-empty string.
    So the pointer that makes "parked as inert" a tracked wire-or-retire
    decision could aim at a `resolved` ledger row, and the gate stayed GREEN
    about a silencer that now silences nothing but itself. Measured on main
    2026-08-19: memory_outcomes.py, memory_reflect.py and session_recall.py all
    cited sp-cac8540c, status `resolved`. That is the gate's own silent-absence
    class turned inward.

    `resolved` is the ONLY terminal status prd_runner writes (both the fixed and
    the voided paths land there), so it is the only one judged dead. `promoted`
    stays live on purpose: promotion creates a Linear issue that
    `spillover promoted-audit` re-reads, so the decision is still open.

    TWO SKIPS, both fleet-safety and not lenience — `kipi update` runs this gate
    in all 20+ instances:
      * no ledger file -> skip, and SAY SO in notes (see the blindness note).
      * id not in THIS ledger -> skip IN INSTANCE MODE ONLY. An instance WITH
        prd-os has its own ids, so "unknown" means "another ledger's row", not
        "dead pointer"; judging it would turn every declared_inert entry RED
        fleet-wide. In SKELETON mode the ledger is this manifest's own ledger,
        so an unknown id is a typo'd or fabricated pointer and goes RED. All 19
        real ids resolve in the skeleton ledger today (measured 2026-08-19), so
        the strict half reds nothing that exists (PR #224 review, minor).

    WHERE THIS IS BLIND, AND WHY THE SKIP IS LOUD (PR #224 review, major):
    `.gitignore:43` excludes `*.jsonl` and un-ignores only `receipts.jsonl`, so
    `.prd-os/spillover.jsonl` is never committed. Every `actions/checkout` in
    `.github/workflows/validate.yml` therefore takes the no-ledger branch, and CI
    CANNOT catch a dead pointer — do not count that step as coverage. Liveness is
    enforced wherever a ledger is readable: the founder's skeleton checkout via
    `kipi check`, any worktree of it (git-common-dir), and any instance carrying
    prd-os. The skip appends a note rather than returning quietly, because a
    silent GREEN reads as "checked, clean" when it means "not checked" — the same
    silent-absence class this whole gate exists to make loud.
    """
    path = spillover_ledger_path(root)
    if not path.is_file():
        if notes is not None:
            notes.append(
                f"inert-spillover-liveness: SKIPPED, no ledger at {path}. "
                f"{len(manifest.get('declared_inert', []))} declared_inert pointer(s) "
                "were NOT checked for a closed decision. Expected in CI (*.jsonl is "
                "gitignored) and in instances without prd-os; this run proves nothing "
                "about pointer liveness.")
        return
    status = {}
    try:
        text = path.read_text(errors="ignore")
    except OSError as exc:
        errors.append(f"spillover ledger unreadable at {path}: {exc}")
        return
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue  # append-only log; one corrupt line must not blind the rest
        if isinstance(rec, dict) and rec.get("id"):
            status[rec["id"]] = rec.get("status")  # last row wins
    for entry in manifest.get("declared_inert", []):
        sid = entry.get("spillover_id")
        if not sid:
            continue  # validate_manifest already owns the empty-string error
        st = status.get(sid, _ABSENT)
        if st == "resolved":
            errors.append(
                f"declared_inert {entry.get('path')} cites {sid}, which is RESOLVED "
                "in the spillover ledger: the wire-or-retire decision it points at "
                "is closed, so nothing tracks this script any more. Repoint it at an "
                "open item or decide the script.")
        elif st is _ABSENT and mode == "skeleton":
            errors.append(
                f"declared_inert {entry.get('path')} cites {sid}, which matches NO "
                f"row in {path}. In the skeleton that ledger IS this manifest's "
                "ledger, so an id it has never heard of is a typo or a fabricated "
                "pointer, and a pointer nothing can resolve tracks nothing. (An "
                "INSTANCE skips this: its ledger legitimately holds other ids.)")


def validate_quarantine(entry, errors):
    q = entry.get("quarantine")
    if q is None:
        return
    for key in ("reason", "spillover_id", "expires"):
        if not q.get(key):
            errors.append(f"quarantine for {entry.get('path')} missing {key}")
            return
    try:
        expires = datetime.date.fromisoformat(q["expires"])
    except ValueError:
        errors.append(f"quarantine expires not ISO date: {entry.get('path')}")
        return
    if expires < datetime.date.today():
        errors.append(f"quarantine EXPIRED {q['expires']}: {entry.get('path')} "
                      f"({q['reason']}, {q['spillover_id']})")


def load_overlay(root, manifest, errors):
    """Instance-local ADD-only overlay. It may only add expected_tests and
    required_data; colliding with or reclassifying a canonical entry is RED
    (finding-5: the overlay must not be a bypass surface)."""
    path = root / "capability-manifest.local.json"
    if not path.is_file():
        return
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        errors.append(f"overlay malformed JSON: {exc}")
        return
    unknown = set(data) - OVERLAY_ALLOWED_KEYS
    if unknown:
        errors.append(f"overlay may only ADD {sorted(OVERLAY_ALLOWED_KEYS)}; found: {sorted(unknown)}")
    canonical = {e.get("path") for e in manifest.get("expected_tests", [])}
    # The overlay reads the CANONICAL exemptions and cannot declare its own:
    # `scope_exempt` is absent from OVERLAY_ALLOWED_KEYS on purpose. An overlay
    # that could mint its own exemption would be a per-instance hatch out of the
    # scan roots, which is the bypass surface load_overlay exists to refuse.
    exempt = [i["prefix"] for i in manifest.get("scope_exempt", [])
              if isinstance(i, dict) and i.get("prefix")]
    seen = set(canonical)
    for entry in data.get("expected_tests", []):
        if entry.get("path") in canonical:
            errors.append(f"overlay collides with canonical entry: {entry.get('path')}")
        elif entry.get("quarantine"):
            errors.append(f"overlay may not quarantine: {entry.get('path')}")
        else:
            validate_test_entry(entry, seen, errors, exempt)
            manifest.setdefault("expected_tests", []).append(entry)
    canonical_data = {e.get("path") for e in manifest.get("required_data", [])}
    for entry in data.get("required_data", []):
        # a same-path overlay entry could NARROW a canonical scope (e.g.
        # canonical scope "all" shadowed by scope [nobody]) — add-only means
        # new paths only (codex, sag-overlay-add-only)
        if entry.get("path") in canonical_data:
            errors.append(f"overlay collides with canonical required_data: {entry.get('path')}")
            continue
        validate_data_entry(entry, errors)
        manifest.setdefault("required_data", []).append(entry)


def discover_tests(root):
    found = set()
    scripts_root = root / SCAN_ROOTS[0]
    for pattern in TEST_PATTERNS:
        for p in scripts_root.rglob(pattern):
            if p.is_file():
                found.add(str(p.relative_to(root)))
        # .q-system RECURSIVELY. This was `glob`, not `rglob`, and the reason
        # given was that scripts/ would otherwise be scanned twice. It is a set:
        # a second visit costs a directory walk and changes nothing. What the
        # non-recursive scan actually bought was a hole -- every subdirectory of
        # .q-system OTHER than scripts/ was invisible to the present-but-
        # undeclared direction below.
        #
        # Measured on main at 569b0ec0: ten test files in .q-system/tests/ were
        # declared nowhere and reached by no runner. 174 assertions, all green,
        # executed by nothing. A gate whose stated job is that "one direction
        # alone would miss F3 (an artifact that appears without a declaration)"
        # could not see them, because F3 detection only looks where discovery
        # looks. The check ran, passed, and was structurally blind to its own
        # subject.
        for p in (root / SCAN_ROOTS[1]).rglob(pattern):
            if p.is_file():
                found.add(str(p.relative_to(root)))
    return found


def in_scan_scope(path):
    # Mirrors discover_tests EXACTLY. When these two disagree, a declared path
    # lands in neither direction of the diff -- it is not checked for existence
    # (out of scope) and its file is not checked for a declaration (not
    # discovered), which is a declaration that means nothing and reads as fine.
    if path.startswith(SCAN_ROOTS[0] + "/"):
        return True
    return path.startswith(SCAN_ROOTS[1] + "/")


def diff_declared_vs_actual(root, manifest, errors, mode="skeleton"):
    """The two-direction diff. One direction alone would miss F3 (an artifact
    that appears without a declaration) or mask a vanished test."""
    declared = {e["path"] for e in manifest.get("expected_tests", []) if e.get("path")}
    discovered = discover_tests(root)
    in_scope_declared = {p for p in declared if in_scan_scope(p)}
    for missing in sorted(in_scope_declared - discovered):
        errors.append(f"declared-but-missing: {missing}")
    for extra in sorted(discovered - declared):
        # Name the exact file to create. The old message said "add to
        # expected_tests" and every author then appended to the same array,
        # which is what made this manifest the conflict in 37 of 41
        # conflicting PRs. A declaration is one file now, so the refusal hands
        # over its path rather than a section name.
        frag = capability_manifest.fragment_name("expected_tests", {"path": extra})
        errors.append(
            f"present-but-undeclared: {extra} — declare it by creating "
            f"{capability_manifest.FRAGMENT_DIR}/expected_tests/{frag} "
            'containing {"path": "%s", "runner": "python3"|"bash"}' % extra)
    skeleton_only = set(manifest.get("skeleton_only", []))
    for outside in sorted(declared - in_scope_declared):
        if mode == "instance" and outside in skeleton_only:
            # A skeleton-only test is ABSENT from every instance by design;
            # only run_tests consulted skeleton_only, so this check turned the
            # whole fleet RED for a file that must not exist there (codex,
            # PR #216). In skeleton mode the check still bites: the skeleton
            # is where the file must exist.
            continue
        if not (root / outside).is_file():
            errors.append(f"declared-but-missing (outside scan root): {outside}")


def instance_name(root):
    return root.resolve().name


def check_required_data(root, manifest, mode, errors):
    for entry in manifest.get("required_data", []):
        scope = entry.get("scope", "all")
        applies = (
            scope == "all"
            or (scope == "skeleton" and mode == "skeleton")
            or (isinstance(scope, list) and instance_name(root) in scope)
        )
        if applies and not (root / entry.get("path", "")).is_file():
            errors.append(f"required-data-missing: {entry.get('path')} (scope={scope})")


class ContainedResult:
    """What run_contained observed. `timed_out` is the deadline verdict; stdout /
    stderr are always populated, partial on a timeout."""

    def __init__(self, returncode, stdout, stderr, timed_out):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.timed_out = timed_out


def run_contained(cmd, cwd, env, timeout):
    """Run a test artifact so that NOTHING it spawns can outlive it or hold the
    gate past `timeout`.

    Two failures this closes (ASK-190):

    1. `subprocess.run(capture_output=True, timeout=...)` waits on pipe EOF, not
       on child exit. A test that backgrounds a child which inherits stdout keeps
       that pipe's write end open, so the gate blocks after the test is already
       gone -- reporting a PASSING test as RED with no way to tell the two apart.
    2. On timeout `run()` kills only the direct child. Grandchildren survive as
       orphans, and the next thing that reads the same pipe inherits the hang.

    `start_new_session=True` puts the child in its own process group, so the
    group signal below reaches the whole subtree. The group id is the child's
    own pid -- never this process's group -- so cleanup can never reach the gate
    itself. (A cleanup that re-raised at its own pid killed its caller once; that
    is the shape being avoided here.)
    """
    proc = subprocess.Popen(
        cmd, cwd=cwd, env=env, text=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        start_new_session=True,
    )
    # Read the pgid NOW. `start_new_session=True` makes it equal to proc.pid, but
    # once the child is reaped its pid is gone and getpgid() would raise -- so
    # looking it up during cleanup would silently skip the very orphan we are
    # here to kill.
    pgid = proc.pid

    # Drain concurrently rather than reading after the wait: a test that writes
    # more than one pipe buffer (64K) would block on write, never exit, and be
    # reported as a timeout it did not earn.
    chunks = {"out": [], "err": []}

    def drain(stream, key):
        try:
            for line in iter(stream.readline, ""):
                chunks[key].append(line)
        except (ValueError, OSError):
            pass  # closed under us by the reap; whatever we already read stands
        finally:
            try:
                stream.close()
            except (ValueError, OSError):
                pass

    readers = [
        threading.Thread(target=drain, args=(proc.stdout, "out"), daemon=True),
        threading.Thread(target=drain, args=(proc.stderr, "err"), daemon=True),
    ]
    for t in readers:
        t.start()

    # The deadline is on the CHILD'S EXIT, not on pipe EOF. That is the entire
    # fix: a leaked grandchild holding the write end can no longer make a test
    # that already exited 0 look like a hang.
    timed_out = False
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True

    # Unconditional, not timeout-only: a test that exits cleanly while leaking a
    # child is the common case here, and that orphan both holds this pipe and
    # outlives the run into whatever reads next.
    reap_group(proc, pgid)
    for t in readers:
        t.join(timeout=5)

    return ContainedResult(
        None if timed_out else proc.returncode,
        "".join(chunks["out"]), "".join(chunks["err"]), timed_out,
    )


def reap_group(proc, pgid):
    """SIGKILL the child's whole process group, then the child, then reap it.

    TERM-then-KILL is not worth the extra deadline: by the time this runs the
    process either finished or is over budget, and a test that ignores TERM
    would spend the grace period twice.
    """
    # The one line that keeps cleanup off the parent. `pgid` is a child pid, so
    # this should never match -- but a cleanup that signalled its own group once
    # killed the harness that called it, and a cheap identity check is worth
    # more than the assumption that it cannot happen.
    if pgid and pgid != os.getpgid(0):
        try:
            os.killpg(pgid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass  # already gone, or the child never got its own session
    try:
        proc.kill()
    except (ProcessLookupError, OSError):
        pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def run_tests(root, manifest, mode, errors, notes):
    skeleton_only = set(manifest.get("skeleton_only", []))
    env = dict(os.environ, QROOT=str(root / "q-system"))
    ran = quarantined = skipped = 0
    for entry in manifest.get("expected_tests", []):
        path = entry.get("path", "")
        if mode == "instance" and path in skeleton_only:
            skipped += 1
            continue
        q = entry.get("quarantine")
        if q:
            quarantined += 1
            notes.append(f"QUARANTINED (until {q['expires']}, {q['spillover_id']}): "
                         f"{path} — {q['reason']}")
            continue
        full = root / path
        if not full.is_file():
            continue  # already reported by the diff
        if executes_nothing(entry, full):
            errors.append(
                f"zero-execution test: {path} defines test functions but has "
                f"no __main__ block, so `python3 {path}` binds them and exits "
                f"0 without running one. Declare runner pytest, or add a "
                f"__main__ entry point (ASK-1145).")
            continue
        runner = entry["runner"]
        if runner == "pytest":
            # `-p no:cacheprovider` so a gate run leaves no .pytest_cache in the
            # tree it just measured; `-q` keeps the failure tail readable inside
            # the 20-line cap below.
            cmd = ["python3", "-m", "pytest", str(full), "-q", "-p", "no:cacheprovider"]
        elif runner == "python3":
            cmd = ["python3", str(full)]
        else:
            cmd = ["bash", str(full)]
        timeout = entry.get("timeout_s", DEFAULT_TIMEOUT_S)
        r = run_contained(cmd, root, env, timeout)
        if r.timed_out:
            # the partial output often names the hang (a prompt, a URL being
            # polled) — discarding it made timeouts undiagnosable (codex,
            # sag-runner-contract)
            tail = "\n".join((r.stdout + r.stderr).splitlines()[-20:])
            errors.append(f"test-timeout ({timeout}s): {path}" + (f"\n{tail}" if tail else ""))
            continue
        ran += 1
        if r.returncode != 0:
            tail = "\n".join((r.stdout + r.stderr).splitlines()[-20:])
            errors.append(f"test-failed rc={r.returncode}: {path}\n{tail}")
    notes.append(f"tests: ran={ran} quarantined={quarantined} "
                 f"skipped-skeleton-only={skipped}")


def gather_wiring_text(root, exclude_names):
    """Test artifacts are NOT wiring surfaces: an engine referenced only by its
    own test suite is exactly the F2 trap ("its own suite passes, so the code
    is fine and inert" — the stat-verify scar, 2026-07-23). Worktree copies are
    parallel checkouts, not wiring. Candidate engines are excluded here and
    only earn surface status through the wired-closure pass below."""
    chunks = []
    for rel in WIRING_SURFACES:
        p = root / rel
        if p.is_file():
            chunks.append(p.read_text(errors="ignore"))
    for pattern in WIRING_SURFACE_GLOBS:
        for p in root.glob(pattern):
            if not p.is_file():
                continue
            if "/.claude/worktrees/" in str(p) + "/":
                continue
            # test/tests DIRECTORIES too, not just test-prefixed basenames: a
            # fixture or helper under test/ referencing an engine is still the
            # its-own-suite trap (codex, sag-wiring-detector-contract)
            if any(part in ("test", "tests") for part in p.parts):
                continue
            if p.name.startswith(("test_", "test-")) or p.name in exclude_names:
                continue
            chunks.append(p.read_text(errors="ignore"))
    return "\n".join(chunks)


def references_engine(name, surface):
    """True when `surface` references this engine by FILENAME or by Python import.

    Scar (ASK-517): the matcher was `p.name in surface`, i.e. the filename WITH
    its .py extension, while a Python import names the module by its STEM. So
    q-system/.q-system/scripts/loops_path.py -- imported by
    q-system/hooks/session-start.py, which is wired in both .claude/settings.json
    and settings-template.json -- was reported as a dead engine. That reddened
    origin/main and blocked every merge in the repo until this fix. An engine
    wired by `import` was structurally invisible to the one check built to find
    dead engines.

    The import form is matched EXPLICITLY, never by bare stem. A bare stem would
    make a script called utils.py read as wired anywhere the word "utils"
    appears, which turns the check off without anyone noticing -- trading a
    false positive for a silent false negative, in the check whose whole job is
    catching things nobody noticed.
    """
    if name in surface:
        return True
    if not name.endswith(".py"):
        return False
    stem = re.escape(name[:-3])
    return re.search(r"\bimport\s+%s\b|\bfrom\s+%s\s+import\b" % (stem, stem),
                     surface) is not None


# A file the TEST RUNNER loads by name, with no import and no call site anywhere
# by design. The textual-reference model this whole check rests on structurally
# cannot express "the runner picks this up by convention", so such a file can
# only ever be a false positive here -- and the only way to silence it with a
# reference would be to write a fake one.
RUNNER_LOADED_NAMES = frozenset({"conftest.py"})

# The `__main__` guard as SYNTAX: start of a line, not anywhere in the bytes.
_MAIN_GUARD_RE = re.compile(r"^\s*if\s+__name__\s*==\s*['\"]__main__['\"]\s*:",
                            re.MULTILINE)


def is_runnable_engine(path, text):
    """True when this file RUNS, as opposed to being read or imported.

    Scar (sp-7773af84's neighbour, measured 2026-08-14; main had been red on it
    since 2026-08-10). The test used to be:

        os.access(p, os.X_OK) or "__main__" in text

    a bare substring over the whole file. `conftest.py` has no exec bit and no
    guard -- the only `__main__` in it is one line of PROSE inside its module
    docstring, advising future authors to guard their exits under
    `if __name__ == "__main__":`. That sentence alone promoted it to a candidate,
    and because pytest loads conftest by NAME it could never then prove itself
    wired, so the gate reported it inert on every run forever.

    Two separate defects, so both are closed: a substring cannot tell code from a
    comment ABOUT code, hence the guard is now matched as syntax at the start of
    a line; and a runner-loaded file is not an engine at all, hence
    RUNNER_LOADED_NAMES. Fixing only the first would have hidden the second by
    accident, because THIS conftest happens to lack an exec bit -- one that
    carried the exec bit would still be flagged wrongly.

    Deliberately NOT widened past that. The check keeps its own scar in view: it
    exists because two dead engines citing each other stayed invisible for
    months, so anything that makes it blind is a bigger cost than a false
    positive, which is loud and resolved by a declared_inert entry.
    """
    if path.name in RUNNER_LOADED_NAMES:
        return False
    return os.access(path, os.X_OK) or _MAIN_GUARD_RE.search(text) is not None


def check_inert_engines(root, manifest, errors, notes):
    """F2 class: a runnable .py with zero textual references across the wiring
    surfaces and no declared_inert entry is a silently-dead engine.

    Wired-closure: an unwired engine cannot wire its sibling (two dead engines
    citing each other stayed invisible for months). Start from non-candidate
    surfaces; a candidate that proves wired joins the surface set; repeat to
    fixed point so hook -> script A -> script B chains still count."""
    declared = {e["path"]: e for e in manifest.get("declared_inert", [])}
    base = root / "q-system/.q-system"
    # plugins/ carries the runnable scripts this fleet actually ships, and the
    # candidate scan never looked there -- a dead script under plugins/ was
    # invisible to the one check built to see dead scripts. Widened 2026-08-05
    # after an adversarial sweep whose every finding lived in that tree.
    #
    # REPORT-ONLY for now, on purpose. The change cannot be validated from a
    # .claude/worktrees copy: calling this function directly against a worktree
    # reports 28 inert errors with the UNMODIFIED gate, on a repo whose gate is
    # meant to be green, so surface gathering is unreliable there. Shipping it
    # BLOCKING on an unvalidatable measurement could red 27 plugin scripts
    # across 22 governed instances. Notes carry the signal at zero blast
    # radius; promoting to `errors` is a one-line change once a real run in the
    # primary checkout confirms the delta is zero (sp-1cb1a348).
    plugin_candidates = set()
    for p in (list(root.glob("plugins/*/scripts/**/*.py"))
              + list(root.glob("plugins/*/hooks/*.py"))
              + list(root.glob("plugins/*/skills/*/scripts/*.py"))):
        if p.is_file() and not p.name.startswith(("test_", "test-")) \
                and not any(part in ("test", "tests") for part in p.parts):
            if is_runnable_engine(p, p.read_text(errors="ignore")):
                plugin_candidates.add(p)
    candidates = set()
    for p in list(base.glob("*.py")) + list((base / "scripts").rglob("*.py")):
        if not p.is_file() or p.name.startswith(("test_", "test-")):
            continue
        if any(part in ("test", "tests") for part in p.parts):
            continue
        # runnable contract: exec bit or a __main__ guard; a pure library
        # module with neither is not an "engine" (standard-review minor).
        # One authority for that question -- see is_runnable_engine.
        if is_runnable_engine(p, p.read_text(errors="ignore")):
            candidates.add(p)
    # Plugin closure FIRST: a plugin engine that proves wired (a skill script its
    # SKILL.md names, a hook its hooks.json names) is real wiring for the skeleton
    # engines it calls, so its text joins the skeleton surface. An UNWIRED plugin
    # engine still wires nothing (the closure principle is unchanged). Before this
    # ordering lessons_recall.py, imported only by the improve skill's
    # improve_ground.py, was reported inert on CI (PR #294, 2026-09-02).
    plugin_surface = gather_wiring_text(root, {p.name for p in plugin_candidates})
    p_wired, changed = set(), True
    while changed:
        changed = False
        for p in sorted(plugin_candidates - p_wired):
            if references_engine(p.name, plugin_surface):
                p_wired.add(p)
                plugin_surface += "\n" + p.read_text(errors="ignore")
                changed = True
    surface = gather_wiring_text(root, {p.name for p in candidates})
    for p in sorted(p_wired):
        surface += "\n" + p.read_text(errors="ignore")
    wired = set()
    changed = True
    while changed:
        changed = False
        for p in sorted(candidates - wired):
            if references_engine(p.name, surface):
                wired.add(p)
                surface += "\n" + p.read_text(errors="ignore")
                changed = True
    for p in sorted(candidates - wired):
        rel = str(p.relative_to(root))
        if rel in declared:
            notes.append(f"DECLARED-INERT ({declared[rel]['spillover_id']}): {rel} "
                         f"— {declared[rel]['reason']}")
            continue
        errors.append(f"inert-engine: {rel} has no reference on any wiring surface "
                      "and no declared_inert entry")

    # Same walk over plugins/, reported not enforced (see the note above).
    for p in sorted(plugin_candidates - p_wired):
        rel = str(p.relative_to(root))
        if rel in declared:
            continue
        notes.append(f"INERT-ENGINE (report-only, plugins/): {rel} has no "
                     "reference on any wiring surface")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo-root", default=".", help="repo root (default: cwd)")
    ap.add_argument("--check-only", action="store_true",
                    help="structure/diff/wiring/data checks only; skip test execution")
    args = ap.parse_args()
    root = Path(args.repo_root).resolve()
    refuse_if_worktree(root)

    errors, notes = [], []
    mode = detect_mode(root, errors)
    manifest = load_manifest(root, errors)
    if manifest is None:
        report(mode, errors, notes)
        sys.exit(1)
    load_overlay(root, manifest, errors)
    # Needs the filesystem (the ledger), so it cannot live inside
    # validate_manifest, which is handed data only. Placed before the
    # fail-closed exit below: a declared_inert entry pointing at a closed
    # decision is a structural manifest problem, not a finding about the repo.
    check_inert_spillover_live(root, manifest, errors, notes, mode)
    # counts note BEFORE the structural early-exit: an expired quarantine is a
    # structural error, and exiting first meant exactly those runs lost the
    # quarantine count the contract promises in EVERY summary (codex,
    # sag-quarantine-expiry)
    expected = manifest.get("expected_tests", [])
    q_count = sum(1 for e in expected if isinstance(e, dict) and e.get("quarantine"))
    notes.append(f"declared: {len(expected)} tests ({q_count} quarantined), "
                 f"{len(manifest.get('skeleton_only', []))} skeleton-only, "
                 f"{len(manifest.get('declared_inert', []))} declared-inert")
    # ASK-972: say the coverage boundary out loud on EVERY run. The escape used
    # to be a property of the source you had to go read; a GREEN that silently
    # meant "some of these were only half-checked" is the same silent-absence
    # class the whole gate exists to make loud.
    n_exempt = sum(1 for e in expected
                   if isinstance(e, dict) and e.get("path")
                   and not in_scan_scope(e["path"]))
    notes.append(f"scan scope: {len(expected) - n_exempt} declared entries inside "
                 f"the scan roots (checked BOTH directions), {n_exempt} exempt "
                 "from undeclared-artifact detection (existence-checked only)")
    if errors:  # fail closed on structural problems before trusting the sets
        report(mode, errors, notes)
        sys.exit(1)
    if q_count and args.check_only:
        for e in expected:
            q = e.get("quarantine")
            if q:
                notes.append(f"QUARANTINED (until {q['expires']}, {q['spillover_id']}): "
                             f"{e['path']} — {q['reason']}")
    diff_declared_vs_actual(root, manifest, errors, mode)
    check_required_data(root, manifest, mode, errors)
    # Inert-engine detection is a SKELETON-mode check. An instance's synced
    # scripts are wired by skeleton-root surfaces (validate.yml,
    # validate-separation.py, the kipi CLI) that do not exist inside the
    # instance repo — re-judging with that subset flagged 3 false inerts in
    # all 22 instances on first propagation (sp rollout finding, 2026-07-23).
    if mode == "skeleton":
        check_inert_engines(root, manifest, errors, notes)
    else:
        notes.append("inert-engine check: skeleton-only (instance wiring is "
                     "declared and gated in the skeleton)")
    if not args.check_only:
        run_tests(root, manifest, mode, errors, notes)
    report(mode, errors, notes)
    sys.exit(1 if errors else 0)


def report(mode, errors, notes):
    print(f"capability-gate mode={mode}")
    for n in notes:
        print(f"  {n}")
    for e in errors:
        print(f"  RED: {e}")
    print(f"capability-gate: {'RED (' + str(len(errors)) + ')' if errors else 'GREEN'}")


if __name__ == "__main__":
    main()
