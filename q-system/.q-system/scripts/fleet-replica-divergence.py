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


def written_roots(registry: Path) -> list[str]:
    """The roots `kipi-update.sh` actually writes: its own filter, not every path.

    ASK-2387 (PR #460 review, HIGH). With no --only, the population was every path
    anywhere in the registry, so drift in an `eliminated` or `standalone` node --
    roots the updater never rsyncs -- aborted the whole fleet sync. The updater's
    loop (kipi-update.sh, the `for i in d['instances']` reader) writes only
    `instances` entries and skips `status: merged*`; its guard
    `[ "$itype" = "standalone" ] || [ -z "$prefix" ]` then skips standalone and
    prefix-less entries. `skeleton_managed: false` only labels that skip, so an
    opted-out entry WITH a prefix is still rsynced and stays in (PR #499 round 1).
    test_fleet_replica_divergence pins both the snippet and the guard's text.

    A registry with no `instances` key falls back to every path, for the scar in
    registry_roots: a shape change must widen the population, never zero it.
    """
    try:
        data = json.loads(registry.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"cannot read registry {registry}: {exc}\n")
        return []
    if not isinstance(data, dict) or not isinstance(data.get("instances"), list):
        return registry_roots(registry)
    out = set()
    for i in data["instances"]:
        if not isinstance(i, dict) or not isinstance(i.get("path"), str):
            continue
        if str(i.get("status", "")).startswith("merged"):
            continue
        if i.get("type", "subtree") == "standalone" or not (i.get("subtree_prefix") or ""):
            continue
        out.add(os.path.expanduser(i["path"]))
    return sorted(out)


def registry_named_roots(registry: Path) -> dict[str, str]:
    """name -> path, for every registry node carrying BOTH a name and a path.

    Exists so `--only <instance>` resolves here rather than in the caller.
    `kipi-update.sh` already knows the name; teaching bash to parse the registry
    a second time would put two readers on one file, which is how the two
    reshapes cited above silently desynced the last pair of readers.
    """
    try:
        data = json.loads(registry.read_text())
    except (OSError, json.JSONDecodeError):
        return {}

    named: dict[str, str] = {}

    def walk(node):
        if isinstance(node, dict):
            name = node.get("name")
            path = next((node[k] for k in ("path", "root", "dir")
                         if isinstance(node.get(k), str)), None)
            if isinstance(name, str) and path:
                named[name] = os.path.expanduser(path)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(data)
    return named


def registry_skeleton(registry: Path) -> str | None:
    """The SOURCE root: the one copy `kipi update` rsyncs FROM.

    Direction is the whole question (see `classify_direction`), and a hash can
    never answer it: two files that differ tell you nothing about which one is
    the origin. The registry names the skeleton explicitly, so that is what is
    read. Returns None when the registry does not, and every caller treats that
    as "direction undeterminable" rather than guessing.
    """
    try:
        data = json.loads(registry.read_text())
    except (OSError, json.JSONDecodeError):
        return None

    node = data.get("skeleton") if isinstance(data, dict) else None
    if isinstance(node, str):
        return os.path.expanduser(node)
    if isinstance(node, dict):
        for key in ("path", "root", "dir"):
            if isinstance(node.get(key), str):
                return os.path.expanduser(node[key])
    return None


def _git_blob_sha(path: Path) -> str | None:
    """git's own object id for a file's bytes, computed without invoking git.

    The comparison below is against blob ids out of the skeleton's history, so
    the local side has to speak the same identifier. Shelling out per copy would
    be one process per file across 29 roots for the same 20 lines of hashing.
    """
    try:
        data = path.read_bytes()
    except OSError:
        return None
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


# The branch the fleet fans out FROM. Must stay equal to `SKELETON_BRANCH` in
# kipi-update.sh, which is the script that does the rsyncing.
SKELETON_BRANCH = "main"


def skeleton_ship_ref(skeleton_root: str, run) -> str | None:
    """The ref whose history counts as "shipped to the fleet".

    SHIPPED IS THE FAN-OUT BRANCH, NOT EVERY REF IN THE CLONE (review finding,
    PR #460 round 2, major). The first armed version walked `rev-list --all`, so
    any blob on any local branch -- unmerged feature work, another session's WIP,
    a stale bisect ref -- counted as proof that a replica holding those bytes was
    merely BEHIND, and the gate greenlit rsync --delete over content that was
    never fanned out to anything. Measured on the live skeleton for
    prd_runner.py: 75 blobs via `--all`, 33 via `origin/main`. 56% of what the
    gate would have called safe had never shipped.

    This repo had already retired that exact predicate 600 lines into
    kipi-update.sh (`fleet_authored_blob`, and the comment above it), for the
    same reason, after the same finding on PR #151. Same resolution order is used
    here deliberately: origin's ref is the one with a proven meaning, and the
    local fallbacks exist for fixtures and clones with no origin, where there is
    no remote to disagree with.
    """
    for ref in (f"refs/remotes/origin/{SKELETON_BRANCH}",
                f"refs/heads/{SKELETON_BRANCH}", "HEAD"):
        probe = run(["rev-parse", "--verify", "--quiet", ref])
        if probe is not None and probe.returncode == 0:
            return ref
    return None


def skeleton_revisions(skeleton_root: str, rel: str) -> set[str] | None:
    """Every blob the skeleton has SHIPPED at `rel`. None when git cannot say.

    None is not an empty set and the difference decides the verdict: an empty
    set means "the skeleton has no history for this path, so nothing a replica
    holds can be a past version of it", while None means "this question was not
    answerable here" and the caller must fall back to direction-blind.
    """
    import subprocess

    def run(args: list[str], stdin: str | None = None):
        try:
            return subprocess.run(
                ["git", "-C", skeleton_root, *args], input=stdin,
                capture_output=True, text=True, timeout=60,
            )
        except (OSError, subprocess.SubprocessError):
            return None

    probe = run(["rev-parse", "--is-inside-work-tree"])
    if probe is None or probe.returncode != 0:
        return None
    ship_ref = skeleton_ship_ref(skeleton_root, run)
    if ship_ref is None:
        return None
    commits = run(["rev-list", ship_ref, "--", rel])
    if commits is None or commits.returncode != 0:
        return None
    wanted = [f"{sha}:{rel}" for sha in commits.stdout.split()]
    if not wanted:
        return set()
    batch = run(["cat-file", "--batch-check=%(objectname) %(objecttype)"],
                stdin="\n".join(wanted) + "\n")
    if batch is None or batch.returncode != 0:
        return None
    return {
        line.split()[0] for line in batch.stdout.splitlines()
        if line.split()[1:2] == ["blob"]
    }


def classify_direction(entry: dict, skeleton_root: str | None) -> str:
    """"behind" | "ahead" | "unknown" for one path that hashed as diverged.

    WHY THIS EXISTS (review finding, PR #460 round 1, major). The first armed
    version red on ANY hash difference. The normal state immediately before an
    update is precisely a hash difference -- the skeleton carries the new bytes
    and the replicas still carry the old ones -- so the gate aborted the very
    run that would have resolved it, with no way through. A gate that is red on
    the state it exists to end is not strict, it is an outage, and an outage
    gets switched off (the plan-lint grandfathering lesson, again).

    The dangerous direction is unchanged and is the only one still red: bytes
    that live ONLY in a replica are what `rsync --delete` destroys. A replica
    holding a blob the skeleton has held before is simply BEHIND; the update
    moves it forward and nothing unique is lost.

    "unknown" is returned, and treated as red, whenever the question could not
    be answered -- no skeleton in the registry, no git, or the skeleton has no
    copy of this path. Fail closed: an unanswered direction question must not
    read as the safe answer.

    ANSWERED PER GROUP, NOT ONCE PER PATH (review finding, PR #460 round 2,
    minor). The first version short-circuited on the first `ahead` root and
    returned one verdict for the whole path, so a path with one root ahead and
    another behind printed two identical single-root lines while the abort said
    "named above". Each group carries its own `direction` now and the printer
    labels it, so "reconcile the direction" names which copy. A group containing
    the skeleton itself is `source`: those copies ARE the bytes being rsynced out.
    """
    groups = entry["groups"]
    if not skeleton_root:
        return "unknown"
    rel = rel_of(entry)
    sk_file = Path(skeleton_root) / rel
    if not sk_file.is_file():
        return "unknown"
    revisions = skeleton_revisions(skeleton_root, rel)
    if revisions is None:
        return "unknown"
    for group in groups:
        if skeleton_root in group["roots"]:
            group["direction"] = "source"
            continue
        # Every root in a group holds the same bytes by construction (the group
        # key IS the content hash), so one blob id answers for all of them.
        blob = _git_blob_sha(Path(group["roots"][0]) / rel)
        group["direction"] = "behind" if blob is not None and blob in revisions else "ahead"
    return "ahead" if any(g["direction"] == "ahead" for g in groups) else "behind"


def rel_of(entry: dict) -> str:
    return entry["path"]


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
    ap.add_argument("--only", default=None,
                    help="restrict the population to this registered instance "
                         "plus the skeleton, mirroring `kipi-update.sh --only`")
    ap.add_argument("--skeleton", default=None,
                    help="the SOURCE tree direction is answered against; defaults "
                         "to the registry's skeleton key. kipi-update.sh passes "
                         "its own $SCRIPT_DIR, because that is what it rsyncs from")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    here = Path(__file__).resolve()
    # BASH_SOURCE-style rooting: derive the repo from THIS file, never from the
    # caller's cwd. A gate invoked from a worktree or a launchd job with a
    # different cwd must still measure the skeleton it belongs to.
    repo_root = here.parents[3]
    registry = Path(args.registry) if args.registry else repo_root / "instance-registry.json"
    rel_paths = tuple(args.paths) if args.paths else DEFAULT_REPLICATED

    # Claims compare reach across the whole registry, so they keep every root. The
    # replica scan protects DESTINATIONS, so it measures only what the updater
    # writes (ASK-2387); the skeleton is added below, as the source.
    roots = registry_roots(registry) if args.claims else written_roots(registry)
    # THE CALLER DECLARES THE SOURCE (review finding, PR #460 round 2, minor).
    # The gate read the registry's `skeleton` key while `kipi-update.sh` defines
    # the skeleton as its own `$SCRIPT_DIR` and never reads that key, so run from
    # any other checkout the two measured different trees -- reproduced against a
    # 137-commit unmerged branch's working tree, which answered "behind" for a
    # fleet the updater would have rsynced from somewhere else entirely. The
    # rsyncing script is the one that knows, so it says. The registry key stays
    # as the default for a standalone run, where there is no caller to ask.
    skeleton_root = (os.path.expanduser(args.skeleton) if args.skeleton
                     else registry_skeleton(registry))
    # written_roots holds destinations only; the source joins as the comparison,
    # exactly as the --only branch below does. Only when a destination exists:
    # zero destinations is the EMPTY_POPULATION refusal below, and the source alone
    # would let a gate that measured nothing report green (preflight test, case
    # "an empty population names itself").
    if not args.claims and skeleton_root and roots:
        roots = sorted(set(roots) | {skeleton_root})

    # SCOPE THE POPULATION TO WHAT THE RUN WILL ACTUALLY WRITE (review finding,
    # PR #460 round 1, major). `kipi-update.sh --only <name>` touches one
    # instance; the gate measured all 29 and aborted the staged rollout over
    # drift in a root the run was never going to write. The reach preflight
    # directly above it already scopes by --only, so this was the odd one out.
    # The skeleton stays in the population unconditionally -- it is the source
    # being compared against, not a destination being protected.
    if args.only:
        named = registry_named_roots(registry)
        target = named.get(args.only)
        if not target:
            sys.stderr.write(
                f"--only names {args.only!r}, which is not a registered "
                f"instance in {registry}\n"
            )
            verdict(f"REFUSED (--only {args.only} is not a registered instance)")
            return EXIT_MISCONFIGURED
        roots = sorted({target} | ({skeleton_root} if skeleton_root else set()))

    # LISTED BUT NOTHING WRITTEN IS NOT AN EMPTY POPULATION (PR #499 round 1). A
    # registry whose every instance is standalone or prefix-less is one this run
    # rsyncs into nowhere: nothing to protect, so OK. Refusing it aborted the whole
    # updater (test-kipi-update-unmanaged-instance.sh went red). An `instances`
    # list that is EMPTY, or a registry that cannot be read, is still the refusal.
    if not roots and not args.claims and not args.only:
        try:
            listed = json.loads(registry.read_text()).get("instances") or []
        except (OSError, ValueError, AttributeError):
            listed = []
        if listed:
            verdict(f"OK ({len(listed)} registered instance(s), none written by this run)")
            return 0

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
    #
    # MEASURED OVER THE DESTINATIONS, NOT THE SOURCE. The disarm test used to be
    # "no declared path resolves in ANY root", and the skeleton is a root. Once
    # the caller began declaring the source (--skeleton, round 2 above), a
    # `--only <instance>` run against a synthetic population armed the gate on
    # ONE copy: the skeleton's own kipi-update.sh, which is a declared replicated
    # path and is necessarily present in the tree running the update. The other
    # two then resolved nowhere, that read as partial coverage, and the gate
    # refused -- caught by test-kipi-update-safety.sh's `--only aaa` case, which
    # stopped updating aaa at all.
    #
    # A single copy cannot disagree with anything. Divergence needs at least one
    # NON-skeleton copy, because a replica-only line is the thing rsync --delete
    # destroys, so that is what decides whether there is anything here to
    # protect. The partial-coverage refusal below still fires the moment one real
    # replica copy exists, which is the state the live defect was found in.
    comparable = [
        e for e in report
        if any(r != skeleton_root for g in e["groups"] for r in g["roots"])
    ]
    if not comparable:
        print(
            f"no declared replicated path exists in any non-skeleton root of "
            f"{len(roots)}; this population carries no replicated content to compare"
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

    # A hash difference is a QUESTION, not yet a finding. Only the answer to
    # "which side has bytes the other has never had" decides.
    for entry in report:
        entry["direction"] = (
            classify_direction(entry, skeleton_root) if entry["distinct"] > 1
            else "same"
        )
    diverged = [r for r in report if r["direction"] in ("ahead", "unknown")]
    behind = [r for r in report if r["direction"] == "behind"]

    if args.json:
        print(json.dumps({"roots": len(roots), "checked": report,
                          "behind": [r["path"] for r in behind],
                          "diverged": [r["path"] for r in diverged]}, indent=2))
    else:
        print(f"roots: {len(roots)}   replicated paths checked: {len(rel_paths)}")
        for entry in report:
            mark = {"same": "ok", "behind": "behind",
                    "ahead": "DIVERGED", "unknown": "DIVERGED"}[entry["direction"]]
            print(f"[{mark}] {entry['path']}  copies={entry['copies']} distinct={entry['distinct']}")
            if entry["distinct"] > 1:
                if entry["direction"] == "behind":
                    print("    every differing copy is a past skeleton revision "
                          "of this path; the update moves them forward")
                elif entry["direction"] == "unknown":
                    print("    direction undeterminable (no skeleton root, no git, "
                          "or no skeleton copy of this path); refusing to assume safe")
                elif entry["direction"] == "ahead":
                    print("    the [ahead] copies below hold bytes the skeleton "
                          "never shipped; those are the ones rsync --delete destroys")
                for group in entry["groups"]:
                    label = ", ".join(group["roots"]) if group["n"] <= 3 else f"{group['n']} roots"
                    # The per-group direction, not one verdict for the path: a
                    # mixed path used to print ahead and behind roots identically
                    # (PR #460 round 2, minor). Blank-padded to a fixed width so
                    # the root column still lines up.
                    mark = f"[{group.get('direction', 'unknown')}]"
                    print(f"    {group['sha']}  n={group['n']:3d}  {mark:<9} {label}")
        if diverged:
            print(
                "\nkipi update rsyncs plugins/ from the skeleton WITH --delete. "
                "Every line that exists only in a non-skeleton copy above is "
                "destroyed by the next update run. Reconcile the direction before "
                "updating; do not resolve this by running an update."
            )

    if diverged:
        verdict(f"DIVERGED {len(diverged)}/{len(report)} path(s)")
    elif behind:
        # Named, never folded into OK. A silent pass here would be
        # indistinguishable from "nothing differed", and the operator would have
        # no way to tell the gate ran on a fleet that is genuinely out of date.
        verdict(f"OK ({len(report)} path(s), {len(roots)} roots; "
                f"{len(behind)} behind the skeleton, which is what an update fixes)")
    else:
        verdict(f"OK ({len(report)} path(s), {len(roots)} roots)")
    return EXIT_DIVERGED if diverged else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
