#!/usr/bin/env python3
"""Mutation check: prove that a test which guards a safety property can FAIL.

WHY (ASK-316, RCA rca-tests-that-pin-nothing-2026-08-02). PR #74 shipped nine
tests written reproducer-first -- each observed RED before the fix, green after.
A reviewer then gutted the implementation on copies and the suite stayed green
on almost every mutant: both shipped round-1 fixes had zero coverage, five of
six MD_INVOCATION_RE arms were untested, SURFACE_NAMES could be deleted
entirely, `_is_test_file` could be replaced with always-True.

Red-before-green proves a test responds to the ORIGINAL defect. It proves
nothing about whether the test fails when the fix is later REMOVED. Those are
different properties, and only the second one survives the author leaving.

"Mutation-check every test that asserts a safety property" was already written
down in reference-review-tooling-2026-07 from three prior occurrences. It was in
context and it did not run, because prose does not run. This is the executable.

THE VALIDATION STEP IS THE POINT, NOT AN EXTRA. A mutation that silently failed
to apply produces a green that looks like coverage, which is the same defect one
level up. So before any suite result is trusted, every mutant must be proven
  (1) APPLIED   -- the `find` text existed and was replaced,
  (2) DIFFERING -- the resulting bytes differ from the original,
  (3) PARSING   -- python3 compiles it / bash -n accepts it.
A mutant failing any of those is reported ERROR, never SURVIVED and never KILLED.

CALL-SITE MUTANTS (ASK-312 one layer up). A mutant may target the CALLER rather
than the library: delete the line where linear-worker.sh invokes the helper and
the suite must go red. A correct helper nobody invokes is exactly the review-gate
defect, and a test that exercises the helper through the library cannot see it.
Declare those with "kind": "call-site"; the report counts them separately.

PERIODIC, NOT PER-COMMIT. Every mutant is a full suite run; test-severity-floor
alone is budgeted 420s. A per-commit cost gets a gate switched off, and a gate
that is off protects nothing. Wired weekly via com.kipi.mutation-check.plist.

Manifest contract -- a `mutants` list on an expected_tests entry:

    {
      "path": "q-system/.q-system/scripts/test/test-x.sh",
      "runner": "bash",
      "mutants": [
        {
          "id": "x-drop-guard",
          "target": "q-system/.q-system/scripts/x.sh",
          "find": "  [ -n \"$tok\" ] || return 1\n",
          "replace": "",
          "kind": "logic",            # or "call-site"
          "why": "removing the empty-token guard must break the suite"
        }
      ]
    }

Exit codes: 0 every declared mutant was killed, 1 a mutant survived or a suite
is registered with no mutants at all, 2 the run could not be trusted (baseline
red, a mutant that would not apply, a bad declaration).
"""

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
MANIFEST = REPO / "q-system/.q-system/capability-manifest.json"
DEFAULT_TIMEOUT_S = 60
MUTANT_KINDS = ("logic", "call-site")

# Copied per run, once. Everything here is either the generator's own scratch,
# a review tree, or bulk we never mutate; copying it multiplies the run cost for
# nothing. .git is excluded because the copy is never committed from.
COPY_EXCLUDES = (".git", "node_modules", "__pycache__", ".venv")


class Refusal(Exception):
    """The run cannot be trusted. Never downgraded to a survived/killed verdict."""


# --------------------------------------------------------------------------
# declaration reading
# --------------------------------------------------------------------------

def load_entries(manifest_path: Path) -> list:
    with open(manifest_path, encoding="utf-8") as fh:
        data = json.load(fh)
    return data.get("expected_tests", [])


def validate_mutant(entry_path: str, mutant: dict) -> None:
    """A malformed declaration is REFUSED, never skipped.

    Skipping is how a mutation suite reports all-clear while checking nothing --
    the same silent-absence class the capability gate exists for.
    """
    for key in ("id", "target", "find", "why"):
        if not isinstance(mutant.get(key), str) or not mutant.get(key):
            raise Refusal(f"{entry_path}: mutant needs a non-empty {key!r}: {mutant!r}")
    if not isinstance(mutant.get("replace", ""), str):
        raise Refusal(f"{entry_path}: mutant {mutant['id']} replace must be a string")
    kind = mutant.get("kind", "logic")
    if kind not in MUTANT_KINDS:
        raise Refusal(
            f"{entry_path}: mutant {mutant['id']} kind must be one of {MUTANT_KINDS}, "
            f"got {kind!r}")
    target = mutant["target"]
    if target.startswith(("/", "~")) or ".." in target.split("/"):
        raise Refusal(f"{entry_path}: mutant {mutant['id']} target escapes the repo: {target}")
    if mutant["find"] == mutant.get("replace", ""):
        raise Refusal(
            f"{entry_path}: mutant {mutant['id']} find == replace, so it mutates nothing")


def select_entries(entries: list, only: str | None) -> list:
    picked = [e for e in entries if e.get("mutants")]
    if only:
        picked = [e for e in picked if only in e["path"]]
    for entry in picked:
        for mutant in entry["mutants"]:
            validate_mutant(entry["path"], mutant)
    return picked


# --------------------------------------------------------------------------
# the copy
# --------------------------------------------------------------------------

def materialize_tree(dest: Path, ref: str | None) -> None:
    """A copy of the repo to mutate. Never the working tree itself.

    With --at, the copy comes from a git ref, which is what makes the ASK-316
    reproducer expressible: run today's declarations against the tree as it
    stood at d20f412 and watch the mutants survive.
    """
    dest.mkdir(parents=True, exist_ok=True)
    if ref:
        archive = subprocess.run(
            ["git", "-C", str(REPO), "archive", ref],
            capture_output=True, check=False)
        if archive.returncode != 0:
            raise Refusal(
                f"git archive {ref} failed: {archive.stderr.decode('utf-8', 'replace')[:300]}")
        extract = subprocess.run(
            ["tar", "-x", "-C", str(dest)], input=archive.stdout,
            capture_output=True, check=False)
        if extract.returncode != 0:
            raise Refusal(f"tar extract failed: {extract.stderr.decode('utf-8', 'replace')[:300]}")
        return
    shutil.copytree(
        REPO, dest, dirs_exist_ok=True,
        ignore=shutil.ignore_patterns(*COPY_EXCLUDES), symlinks=True)


# --------------------------------------------------------------------------
# the three validations
# --------------------------------------------------------------------------

def parses(path: Path, text: str) -> tuple[bool, str]:
    """Syntax check by extension. A mutant that does not parse kills every test
    for the wrong reason, so it is an ERROR and not evidence of coverage."""
    if path.suffix == ".py":
        try:
            compile(text, str(path), "exec")
        except SyntaxError as exc:
            return False, f"python syntax error: {exc}"
        return True, ""
    if path.suffix == ".sh" or path.suffix == "":
        proc = subprocess.run(["bash", "-n", str(path)], capture_output=True, check=False)
        if proc.returncode != 0:
            return False, f"bash -n: {proc.stderr.decode('utf-8', 'replace')[:200]}"
        return True, ""
    if path.suffix == ".json":
        try:
            json.loads(text)
        except ValueError as exc:
            return False, f"json parse error: {exc}"
        return True, ""
    return True, ""


def apply_mutant(tree: Path, mutant: dict) -> tuple[str, str]:
    """Write the mutated target into the copy.

    Returns (original_text, mutated_text). Raises Refusal unless the mutation is
    proven applied and differing -- the two failures that would otherwise look
    exactly like a well-covered fix.
    """
    target = tree / mutant["target"]
    if not target.is_file():
        raise Refusal(f"mutant {mutant['id']}: target does not exist in the tree: {mutant['target']}")
    original = target.read_text(encoding="utf-8")
    occurrences = original.count(mutant["find"])
    if occurrences == 0:
        raise Refusal(
            f"mutant {mutant['id']}: find text is absent from {mutant['target']}, "
            "so the mutation would silently not apply")
    mutated = original.replace(mutant["find"], mutant.get("replace", ""))
    if mutated == original:
        raise Refusal(f"mutant {mutant['id']}: replacement left the file unchanged")
    target.write_text(mutated, encoding="utf-8")
    ok, detail = parses(target, mutated)
    if not ok:
        target.write_text(original, encoding="utf-8")
        raise Refusal(f"mutant {mutant['id']}: mutated {mutant['target']} does not parse -- {detail}")
    return original, mutated


# --------------------------------------------------------------------------
# running a suite
# --------------------------------------------------------------------------

def _load_run_contained():
    """Borrow the gate's contained runner instead of writing a second one.

    OBSERVED HERE, NOT REASONED ABOUT (ASK-316): the first version of this file
    used subprocess.run(capture_output=True, timeout=...). Two suites hung for
    ~40 minutes past their deadline, because run() waits on pipe EOF rather than
    on child exit and, on timeout, kills only the direct child --
    test-review-invoker-provenance.sh's verify-codex-review-live.sh grandchild
    survived holding the pipe. capability-gate.py already closed exactly this
    (its ASK-190 scar), so the fix is to use that one rather than to grow a
    second copy that will drift.
    """
    gate = Path(__file__).resolve().parent / "capability-gate.py"
    spec = importlib.util.spec_from_file_location("capability_gate", gate)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.run_contained


run_contained = _load_run_contained()


def run_suite(tree: Path, entry: dict) -> tuple[int, str]:
    full = tree / entry["path"]
    if not full.is_file():
        raise Refusal(f"suite missing from the tree: {entry['path']}")
    cmd = ["python3", str(full)] if entry["runner"] == "python3" else ["bash", str(full)]
    timeout = entry.get("timeout_s", DEFAULT_TIMEOUT_S)
    env = dict(os.environ)
    env["KIPI_MUTATION_CHECK"] = "1"
    res = run_contained(cmd, str(tree), env, timeout)
    tail = (res.stdout + res.stderr)[-600:]
    if res.timed_out:
        # A timeout is NOT a kill. The suite may be slow, wedged, or genuinely
        # failing, and treating "it did not finish" as "the mutant was caught"
        # is the flattering wrong answer this whole file exists to refuse.
        raise Refusal(
            f"{entry['path']}: suite hit its {timeout}s deadline, so nothing about "
            f"this mutant is known. Raise timeout_s or fix the hang.\n{tail}")
    return res.returncode, tail


# --------------------------------------------------------------------------
# the run
# --------------------------------------------------------------------------

def check_entry(tree: Path, entry: dict) -> dict:
    """Baseline first, then one mutant at a time, restoring between each."""
    result = {"path": entry["path"], "baseline": None, "mutants": []}
    code, tail = run_suite(tree, entry)
    result["baseline"] = code
    if code != 0:
        raise Refusal(
            f"{entry['path']}: baseline is RED (exit {code}) before any mutation. "
            f"Every mutant would 'kill' it for free.\n{tail}")

    for mutant in entry["mutants"]:
        record = {"id": mutant["id"], "kind": mutant.get("kind", "logic"),
                  "target": mutant["target"], "why": mutant["why"]}
        target = tree / mutant["target"]
        try:
            original, _ = apply_mutant(tree, mutant)
        except Refusal as exc:
            record["verdict"] = "ERROR"
            record["detail"] = str(exc)
            result["mutants"].append(record)
            continue
        try:
            code, tail = run_suite(tree, entry)
        finally:
            target.write_text(original, encoding="utf-8")
        record["exit"] = code
        record["verdict"] = "KILLED" if code != 0 else "SURVIVED"
        if code == 0:
            record["detail"] = "suite stayed green with the guard removed"
        else:
            record["detail"] = tail[-200:]
        result["mutants"].append(record)
    return result


def report(results: list, unmutated: list) -> int:
    survived, errored, killed = [], [], 0
    for res in results:
        print(f"\n== {res['path']} (baseline exit {res['baseline']}) ==")
        for m in res["mutants"]:
            print(f"  [{m['verdict']:8}] {m['id']} ({m['kind']}) -> {m['target']}")
            print(f"             {m['why']}")
            if m["verdict"] == "SURVIVED":
                survived.append((res["path"], m))
            elif m["verdict"] == "ERROR":
                errored.append((res["path"], m))
                print(f"             {m['detail']}")
            else:
                killed += 1

    print("\n== summary ==")
    print(f"  suites checked : {len(results)}")
    print(f"  killed         : {killed}")
    print(f"  SURVIVED       : {len(survived)}")
    print(f"  ERROR          : {len(errored)}")
    if unmutated:
        print(f"  no mutants declared ({len(unmutated)}):")
        for path in unmutated:
            print(f"    - {path}")

    if errored:
        for path, m in errored:
            print(f"\nERROR {path} :: {m['id']}\n  {m['detail']}", file=sys.stderr)
        return 2
    if survived:
        for path, m in survived:
            print(f"\nSURVIVED {path} :: {m['id']}\n  {m['why']}\n"
                  f"  the suite cannot see this fix being removed.", file=sys.stderr)
        return 1
    if unmutated:
        print("\nsuites registered for mutation with no mutants declared:", file=sys.stderr)
        for path in unmutated:
            print(f"  - {path}", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--at", metavar="GITREF",
                    help="mutate a copy of this git ref instead of the working tree")
    ap.add_argument("--only", metavar="SUBSTR",
                    help="restrict to suites whose path contains SUBSTR")
    ap.add_argument("--manifest", default=str(MANIFEST))
    ap.add_argument("--require", metavar="SUBSTR", action="append", default=[],
                    help="fail if no suite matching SUBSTR declares mutants "
                         "(guards against a gate suite quietly losing its declarations)")
    ap.add_argument("--json", metavar="PATH", help="also write the raw results here")
    args = ap.parse_args()

    try:
        entries = load_entries(Path(args.manifest))
        picked = select_entries(entries, args.only)
        missing = [r for r in args.require
                   if not any(r in e["path"] for e in picked)]
        if missing:
            raise Refusal(
                "no mutants declared for required suite(s): " + ", ".join(missing))
        if not picked:
            raise Refusal("no expected_tests entry declares a `mutants` list")
    except Refusal as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2

    results, rc = [], 0
    with tempfile.TemporaryDirectory(prefix="kipi-mutation-") as td:
        tree = Path(td) / "tree"
        try:
            materialize_tree(tree, args.at)
            for entry in picked:
                print(f"-- mutating {entry['path']} "
                      f"({len(entry['mutants'])} mutant(s))", flush=True)
                results.append(check_entry(tree, entry))
        except Refusal as exc:
            print(f"REFUSED: {exc}", file=sys.stderr)
            rc = 2

    if rc == 0:
        rc = report(results, [])
    if args.json:
        Path(args.json).write_text(
            json.dumps({"ref": args.at or "worktree", "results": results}, indent=2),
            encoding="utf-8")
    return rc


if __name__ == "__main__":
    sys.exit(main())
