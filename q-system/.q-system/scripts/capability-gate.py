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

Manifest: q-system/.q-system/capability-manifest.json (canonical, synced).
Overlay:  <repo-root>/capability-manifest.local.json (instance-local, ADD-only).

Exit codes: 0 green, 1 red, 3 refused (worktree copy).
"""

import argparse
import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

SCHEMA_VERSION = 1
ALLOWED_TOP_KEYS = {
    "schema_version", "expected_tests", "required_data",
    "skeleton_only", "declared_inert", "uncovered_known",
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
)
WIRING_SURFACE_GLOBS = (
    "plugins/*/hooks/hooks.json",
    "plugins/*/hooks.json",
    ".github/workflows/*.yml",
    "kipi*",
    "*.sh",
    "q-system/.q-system/scripts/*.sh",
    "q-system/hooks/*",
    ".claude/**/*.md",
    "plugins/**/*.md",
    "q-system/.q-system/**/*.md",
    "q-system/.q-system/**/*.py",
    "q-system/.q-system/*.py",
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
    path = root / "q-system/.q-system/capability-manifest.json"
    if not path.is_file():
        errors.append(f"manifest missing: {path.relative_to(root)}")
        return None
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        errors.append(f"manifest malformed JSON: {exc}")
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


def validate_test_entry(entry, seen, errors):
    """One validator for canonical AND overlay entries (finding: overlay
    entries were appended after validation and never validated themselves)."""
    p = entry.get("path", "")
    if unsafe_path(p):
        errors.append(f"unsafe or non-relative path in expected_tests: {p!r}")
        return
    if entry.get("runner") not in ("python3", "bash"):
        errors.append(f"expected_tests entry needs runner python3|bash: {p}")
    if p in seen:
        errors.append(f"duplicate expected_tests path: {p}")
    seen.add(p)
    t = entry.get("timeout_s", DEFAULT_TIMEOUT_S)
    if not (isinstance(t, int) and TIMEOUT_MIN_S <= t <= TIMEOUT_MAX_S):
        errors.append(f"timeout_s out of bounds [{TIMEOUT_MIN_S},{TIMEOUT_MAX_S}]: {p}")
    validate_quarantine(entry, errors)


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
    seen = set()
    for entry in data.get("expected_tests", []):
        validate_test_entry(entry, seen, errors)
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
    seen = set(canonical)
    for entry in data.get("expected_tests", []):
        if entry.get("path") in canonical:
            errors.append(f"overlay collides with canonical entry: {entry.get('path')}")
        elif entry.get("quarantine"):
            errors.append(f"overlay may not quarantine: {entry.get('path')}")
        else:
            validate_test_entry(entry, seen, errors)
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
        # top-level .q-system: non-recursive, or scripts/ would double-scan
        for p in (root / SCAN_ROOTS[1]).glob(pattern):
            if p.is_file():
                found.add(str(p.relative_to(root)))
    return found


def in_scan_scope(path):
    if path.startswith(SCAN_ROOTS[0] + "/"):
        return True
    return path.startswith(SCAN_ROOTS[1] + "/") and "/" not in path[len(SCAN_ROOTS[1]) + 1:]


def diff_declared_vs_actual(root, manifest, errors):
    """The two-direction diff. One direction alone would miss F3 (an artifact
    that appears without a declaration) or mask a vanished test."""
    declared = {e["path"] for e in manifest.get("expected_tests", []) if e.get("path")}
    discovered = discover_tests(root)
    in_scope_declared = {p for p in declared if in_scan_scope(p)}
    for missing in sorted(in_scope_declared - discovered):
        errors.append(f"declared-but-missing: {missing}")
    for extra in sorted(discovered - declared):
        errors.append(f"present-but-undeclared: {extra} — add to expected_tests "
                      "in capability-manifest.json")
    for outside in sorted(declared - in_scope_declared):
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
        cmd = ["python3", str(full)] if entry["runner"] == "python3" else ["bash", str(full)]
        timeout = entry.get("timeout_s", DEFAULT_TIMEOUT_S)
        try:
            r = subprocess.run(cmd, cwd=root, env=env, capture_output=True,
                               text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            errors.append(f"test-timeout ({timeout}s): {path}")
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


def check_inert_engines(root, manifest, errors, notes):
    """F2 class: a runnable .py with zero textual references across the wiring
    surfaces and no declared_inert entry is a silently-dead engine.

    Wired-closure: an unwired engine cannot wire its sibling (two dead engines
    citing each other stayed invisible for months). Start from non-candidate
    surfaces; a candidate that proves wired joins the surface set; repeat to
    fixed point so hook -> script A -> script B chains still count."""
    declared = {e["path"]: e for e in manifest.get("declared_inert", [])}
    base = root / "q-system/.q-system"
    candidates = set()
    for p in list(base.glob("*.py")) + list((base / "scripts").rglob("*.py")):
        if not p.is_file() or p.name.startswith(("test_", "test-")):
            continue
        if any(part in ("test", "tests") for part in p.parts):
            continue
        # runnable contract: exec bit or a __main__ guard; a pure library
        # module with neither is not an "engine" (standard-review minor)
        text = p.read_text(errors="ignore")
        if os.access(p, os.X_OK) or "__main__" in text:
            candidates.add(p)
    surface = gather_wiring_text(root, {p.name for p in candidates})
    wired = set()
    changed = True
    while changed:
        changed = False
        for p in sorted(candidates - wired):
            if p.name in surface:
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
    # counts note BEFORE the structural early-exit: an expired quarantine is a
    # structural error, and exiting first meant exactly those runs lost the
    # quarantine count the contract promises in EVERY summary (codex,
    # sag-quarantine-expiry)
    expected = manifest.get("expected_tests", [])
    q_count = sum(1 for e in expected if isinstance(e, dict) and e.get("quarantine"))
    notes.append(f"declared: {len(expected)} tests ({q_count} quarantined), "
                 f"{len(manifest.get('skeleton_only', []))} skeleton-only, "
                 f"{len(manifest.get('declared_inert', []))} declared-inert")
    if errors:  # fail closed on structural problems before trusting the sets
        report(mode, errors, notes)
        sys.exit(1)
    if q_count and args.check_only:
        for e in expected:
            q = e.get("quarantine")
            if q:
                notes.append(f"QUARANTINED (until {q['expires']}, {q['spillover_id']}): "
                             f"{e['path']} — {q['reason']}")
    diff_declared_vs_actual(root, manifest, errors)
    check_required_data(root, manifest, mode, errors)
    check_inert_engines(root, manifest, errors, notes)
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
