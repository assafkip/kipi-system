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
DEFAULT_REPLICATED = (
    "plugins/prd-os/scripts/prd_runner.py",
    "plugins/kipi-core/scripts/rca-lint.py",
    "kipi-update.sh",
)


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


def scan(roots: list[str], rel_paths: tuple[str, ...]) -> list[dict]:
    report = []
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
    return report


def scan_claims(roots: list[str], claims: list[str]) -> list[dict]:
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
    """
    report = []
    for spec in claims:
        parts = spec.split("::")
        if len(parts) != 3:
            sys.stderr.write(f"--claim must be 'claim::enforcer::needle'; got {spec!r}\n")
            continue
        claim_rel, enforcer_rel, needle = parts
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
        report.append({
            "claim": claim_rel, "enforcer": f"{enforcer_rel}:{needle}",
            "claim_roots": len(claim_roots), "enforcer_roots": len(enforcer_roots),
            "unenforced": sorted(set(claim_roots) - set(enforcer_roots)),
        })
    return report


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
        return 2

    # An explicit --claim run checks ONLY claims. Mixing the two silently would
    # make `--claim X` also red on unrelated replica drift, and a check whose
    # failure does not name the thing you asked about gets read as noise.
    if args.claims:
        claims = scan_claims(roots, args.claims)
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
        return 1 if unenforced else 0

    report = scan(roots, rel_paths)
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

    return 1 if diverged else 0


if __name__ == "__main__":
    sys.exit(main())
