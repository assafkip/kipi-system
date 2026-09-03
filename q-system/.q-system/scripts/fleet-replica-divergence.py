#!/usr/bin/env python3
"""Second account for every fleet-replicated file: hash all copies, report disagreement.

WHY THIS SHAPE (scar, 2026-09-02). Six provenance errors landed in one day across
three concurrent sessions. Every one was caught the same way: two accounts of the
same artifact disagreed out loud. Two sessions quoted DIFFERENT LINE NUMBERS for
`SPILLOVER_BLOCKING_SEVERITIES` in prd_runner.py; the mismatch was the whole
detector. Nobody was being careful, and carefulness is not what found it.

Every one of those catches also depended on someone CHOOSING to re-verify instead
of accepting a report. q-system/CLAUDE.md core rule 3 forbids exactly that shape:
"a prompt or skill alone cannot enforce behavior." A coordination protocol asks
sessions to remember; comparing N replicas of a file is mechanical and survives a
tired session at 2am. So this is not a coordination mechanism. It is the cheapest
possible SECOND ACCOUNT, produced without anyone remembering to ask for one.

WHY IT IS URGENT AND NOT MERELY TIDY. `plugins/` is a `kipi update` rsync
destination WITH `--delete`, fed from the skeleton's working tree. A replica that
has drifted ahead of the skeleton is not "inconsistent", it is scheduled for
deletion: the next update run overwrites it and whatever is only in that copy is
gone with no diff, no conflict and no prompt. Divergence here is a countdown, so
this exits non-zero rather than printing a note.

WHY IT READS THE REGISTRY AND NOT A GLOB. instance-registry.json is the source of
truth for instance paths (root CLAUDE.md). Globbing ~/projects would silently
include archived and non-instance trees, and a detector whose population is wrong
reports a divergence nobody owns -- which is how a gate gets switched off.

WHY MISSING COPIES ARE NOT DIVERGENCE. Not every instance carries every plugin.
An absent file is a legitimate state; only two PRESENT copies that disagree are a
finding. Counting absence as drift would red this on ~3 roots permanently, and a
gate that is red on its own population gets ignored (the plan-lint grandfathering
lesson).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

# Paths replicated to every instance by `kipi update`. Each is relative to an
# instance root. Kept explicit rather than walked: a walk would sweep in
# instance-OWNED files (.q-system/data/, output/) whose divergence is CORRECT and
# expected, and burying real findings in expected ones is how a signal dies.
#
# EVERY ENTRY MUST RESOLVE SOMEWHERE. `plugins/kipi-core/scripts/rca-lint.py`
# sat here from the first commit and resolved to 0 of 29 roots -- the real path
# is skills/rca/scripts/. `scan()` dropped it with `if not groups: continue`, so
# the run printed "replicated paths checked: 3" and listed two. A third of the
# declared coverage was decoration, in the tool written to catch decoration.
# That is why a zero-copy path is now exit 3 and not a skipped line.
DEFAULT_REPLICATED = (
    "plugins/prd-os/scripts/prd_runner.py",
    "plugins/kipi-core/skills/rca/scripts/rca-lint.py",
    "kipi-update.sh",
)

# Distinct on purpose, so a control cannot pass for the wrong reason and the
# kipi-update preflight can tell "found drift" from "could not run".
EXIT_OK = 0
EXIT_DIVERGED = 1
EXIT_EMPTY_POPULATION = 2
EXIT_MISCONFIGURED = 3

# The one line the kipi-update preflight greps for. Proof of EXECUTION: a
# truncated or comment-only copy of this file is a valid program that exits 0
# with no output, and existence checks cannot tell it from a working gate.
VERDICT_PREFIX = "fleet replica divergence: "


def verdict(text: str) -> None:
    print(f"{VERDICT_PREFIX}{text}")


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def registry_roots(registry: Path) -> list[str]:
    """Every filesystem path named anywhere in the registry, de-duplicated.

    Walks the whole structure instead of reading a fixed key: the registry's
    shape has changed twice (flattening 2026-07-01, persona reorg 2026-07-06) and
    a detector pinned to one key silently measured ZERO roots after each move.
    A detector that measures nothing reports green.
    """
    try:
        data = json.loads(registry.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"cannot read registry {registry}: {exc}\n")
        return []

    found: list[str] = []

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ("path", "root", "dir") and isinstance(value, str):
                    found.append(value)
                else:
                    walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(data)
    return sorted({os.path.expanduser(p) for p in found})


def scan(roots: list[str], rel_paths: tuple[str, ...]) -> tuple[list[dict], list[str]]:
    """Returns (report, unresolvable) -- a path present in NO root is the second.

    Absence in SOME roots is legitimate (see the module docstring); absence in
    EVERY root is a typo in the path itself, and silently skipping it is how a
    gate reports green over coverage it never had.
    """
    report = []
    unresolvable: list[str] = []
    for rel in rel_paths:
        groups: dict[str, list[str]] = {}
        for root in roots:
            candidate = Path(root) / rel
            if not candidate.is_file():
                continue
            try:
                digest = _sha(candidate)
            except OSError:
                continue
            groups.setdefault(digest, []).append(root)
        if not groups:
            unresolvable.append(rel)
            continue
        report.append({
            "path": rel,
            "copies": sum(len(v) for v in groups.values()),
            "distinct": len(groups),
            # Majority first, so the odd copy out is the last line and reads as
            # the exception it is.
            "groups": sorted(
                ({"sha": k[:12], "n": len(v), "roots": sorted(v)} for k, v in groups.items()),
                key=lambda g: -g["n"],
            ),
        })
    return report, unresolvable


def scan_claims(roots: list[str], claims: list[str]) -> tuple[list[dict], list[str]]:
    """Does the ENFORCER travel as far as the CLAIM it enforces?

    THE DEFECT THIS EXISTS FOR (P-4, measured across the registry 2026-09-02).
    The lesson "a gate that cannot run must not pass" is present in 26 of 27
    roots. `_reject_unrunnable_gate`, the function implementing it, is present in
    1 of 26. Twenty-five instances read a rule with nothing behind it -- which is
    the exact defect the lesson describes, reproduced at fleet scale BY the
    lesson's own distribution mechanism. P-5 is the same shape:
    DEFAULT_SPILLOVER_OWNER exists in 1 of 26, so 25 instances file blocking
    spillover that routes to nobody.

    Hash-comparing replicas cannot see this: the lesson file and the code file are
    DIFFERENT paths, each perfectly self-consistent across the fleet. The
    divergence is between a claim and its enforcer, so it needs its own account.

    WHY AN INSTANCE CANNOT CATCH THIS ALONE. The session-level errors this tool's
    other half addresses were all caught by a PEER disagreeing. An instance has no
    peer: it holds a rule, believes it enforced, and there is nothing local to
    contradict it. Only a fleet-wide count can. That asymmetry is why this runs
    over the registry and not inside one repo.

    Spec form: "claim_rel::enforcer_rel::needle". RED when the claim reaches
    strictly more roots than the needle does -- an enforcer ahead of its claim is
    fine (code can ship before the doc), a claim ahead of its enforcer is the
    prompt-only-enforcement that core rule 3 forbids.

    FAIL CLOSED ON A SPEC IT CANNOT EVALUATE (2026-09-02, found while arming
    this as a kipi-update preflight). The first draft printed the usage line to
    stderr, `continue`d, reported "claims checked: 0" and RETURNED 0. A typo in
    the wiring -- one `:` instead of `::` -- would have made this gate green
    forever while announcing it had checked something. That is
    a-gate-that-cannot-run-must-not-pass occurring inside the tool built to
    detect it, which is the whole reason it is not a skipped line any more.

    Returns (report, errors). A claim path present in ZERO roots is an error for
    the same reason: it cannot be ahead of its enforcer if it does not exist, so
    it would score a permanent, meaningless green.
    """
    report = []
    errors: list[str] = []
    for spec in claims:
        parts = spec.split("::")
        if len(parts) != 3:
            errors.append(f"--claim must be 'claim::enforcer::needle'; got {spec!r}")
            continue
        claim_rel, enforcer_rel, needle = parts
        if not all(p.strip() for p in parts):
            errors.append(f"--claim has an empty field: {spec!r}")
            continue
        claim_roots, enforcer_roots = [], []
        for root in roots:
            if (Path(root) / claim_rel).is_file():
                claim_roots.append(root)
            enforcer = Path(root) / enforcer_rel
            if enforcer.is_file():
                try:
                    if needle in enforcer.read_text(errors="replace"):
                        enforcer_roots.append(root)
                except OSError:
                    pass
        if not claim_roots:
            errors.append(
                f"--claim names {claim_rel!r}, which exists in 0 of {len(roots)} "
                "roots; a claim that is nowhere can never be ahead of its "
                "enforcer and would score a permanent green"
            )
            continue
        report.append({
            "claim": claim_rel, "enforcer": f"{enforcer_rel}:{needle}",
            "claim_roots": len(claim_roots), "enforcer_roots": len(enforcer_roots),
            "unenforced": sorted(set(claim_roots) - set(enforcer_roots)),
        })
    return report, errors


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--registry", default=None)
    ap.add_argument("--path", action="append", dest="paths", default=None,
                    help="replicated path to check (repeatable); defaults to the built-in set")
    ap.add_argument("--claim", action="append", dest="claims", default=None,
                    help="'claim_rel::enforcer_rel::needle' -- red when the claim "
                         "reaches more roots than the enforcer (repeatable)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    here = Path(__file__).resolve()
    # BASH_SOURCE-style rooting: derive the repo from THIS file, never from the
    # caller's cwd. A gate invoked from a worktree or a launchd job with a
    # different cwd must still measure the skeleton it belongs to.
    repo_root = here.parents[3]
    registry = Path(args.registry) if args.registry else repo_root / "instance-registry.json"
    rel_paths = tuple(args.paths) if args.paths else DEFAULT_REPLICATED

    roots = registry_roots(registry)
    if not roots:
        sys.stderr.write(
            f"no instance roots resolved from {registry}; refusing to report green "
            "on an empty population\n"
        )
        # The verdict prints even on refusal. The preflight distinguishes "the
        # gate ran and refused" from "the gate did not run" by this line, and a
        # refusal that printed nothing would be read as the latter.
        verdict(f"REFUSED (no instance roots resolved from {registry})")
        return EXIT_EMPTY_POPULATION

    # An explicit --claim run checks ONLY claims. Mixing the two silently would
    # make `--claim X` also red on unrelated replica drift, and a check whose
    # failure does not name the thing you asked about gets read as noise.
    if args.claims:
        claims, claim_errors = scan_claims(roots, args.claims)
        if claim_errors or len(claims) != len(args.claims):
            for err in claim_errors:
                sys.stderr.write(err + "\n")
            verdict(
                f"REFUSED ({len(args.claims)} claim(s) requested, "
                f"{len(claims)} evaluable)"
            )
            return EXIT_MISCONFIGURED
        unenforced = [c for c in claims if c["enforcer_roots"] < c["claim_roots"]]
        if args.json:
            print(json.dumps({"roots": len(roots), "claims": claims,
                              "unenforced": [c["claim"] for c in unenforced]}, indent=2))
        else:
            print(f"roots: {len(roots)}   claims checked: {len(claims)}")
            for c in claims:
                mark = "UNENFORCED" if c["enforcer_roots"] < c["claim_roots"] else "ok"
                print(f"[{mark}] {c['claim']}")
                print(f"    claim reaches {c['claim_roots']} root(s); "
                      f"enforcer {c['enforcer']} reaches {c['enforcer_roots']}")
                if c["unenforced"]:
                    shown = c["unenforced"][:5]
                    more = len(c["unenforced"]) - len(shown)
                    for r in shown:
                        print(f"      no enforcer: {r}")
                    if more:
                        print(f"      (+{more} more)")
            if unenforced:
                print(
                    "\nA rule that travels further than its enforcer is prompt-only "
                    "enforcement (q-system/CLAUDE.md core rule 3). Either ship the "
                    "enforcer to the same roots or stop shipping the claim."
                )
        verdict(
            f"UNENFORCED {len(unenforced)}/{len(claims)} claim(s)"
            if unenforced else f"OK ({len(claims)} claim(s), {len(roots)} roots)"
        )
        return EXIT_DIVERGED if unenforced else EXIT_OK

    report, unresolvable = scan(roots, rel_paths)
    # ALL of them missing is a different fact from SOME of them missing, and the
    # two need opposite answers.
    #
    # Some-missing is the live defect: 2 of 3 declared paths resolved across 29
    # real roots and the third resolved nowhere, so the run reported partial
    # coverage as full. That is an error.
    #
    # None-missing-because-none-exist is a population with no replicated content
    # at all -- every kipi-update fixture in scripts/test/ builds exactly that:
    # a synthetic instance with no plugins/ tree. Refusing there would red this
    # gate on 11 existing tests for a reason that has nothing to do with
    # divergence, and a gate unsatisfiable for its own population gets switched
    # off. So it DISARMS, and says so out loud -- the same posture the skeleton
    # branch check above takes, because a silent guard is indistinguishable from
    # one that passed. The real fleet cannot reach this state unnoticed:
    # test_default_replicated_paths_all_resolve_in_the_real_fleet is the second
    # account, and it asserts against the actual registry.
    if unresolvable and len(unresolvable) == len(rel_paths):
        print(
            f"no declared replicated path exists in any of {len(roots)} root(s); "
            "this population carries no replicated content to compare"
        )
        verdict(f"DISARMED (nothing replicated across {len(roots)} roots)")
        return EXIT_OK
    if unresolvable:
        for rel in unresolvable:
            sys.stderr.write(
                f"replicated path {rel!r} exists in 0 of {len(roots)} roots; "
                "it cannot report divergence and its green means nothing\n"
            )
        verdict(f"REFUSED ({len(unresolvable)} declared path(s) resolve nowhere)")
        return EXIT_MISCONFIGURED

    diverged = [r for r in report if r["distinct"] > 1]

    if args.json:
        print(json.dumps({"roots": len(roots), "checked": report,
                          "diverged": [r["path"] for r in diverged]}, indent=2))
    else:
        print(f"roots: {len(roots)}   replicated paths checked: {len(rel_paths)}")
        for entry in report:
            mark = "DIVERGED" if entry["distinct"] > 1 else "ok"
            print(f"[{mark}] {entry['path']}  copies={entry['copies']} distinct={entry['distinct']}")
            if entry["distinct"] > 1:
                for group in entry["groups"]:
                    label = ", ".join(group["roots"]) if group["n"] <= 3 else f"{group['n']} roots"
                    print(f"    {group['sha']}  n={group['n']:3d}  {label}")
        if diverged:
            print(
                "\nkipi update rsyncs plugins/ from the skeleton WITH --delete. "
                "Every line that exists only in a non-skeleton copy above is "
                "destroyed by the next update run. Reconcile the direction before "
                "updating; do not resolve this by running an update."
            )

    verdict(
        f"DIVERGED {len(diverged)}/{len(report)} path(s)"
        if diverged else f"OK ({len(report)} path(s), {len(roots)} roots)"
    )
    return EXIT_DIVERGED if diverged else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
