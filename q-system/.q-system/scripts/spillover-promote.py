#!/usr/bin/env python3
"""Turn a confirmed spillover finding into a fully-scoped Linear issue (ASK-344).

why: the ratchet delivers a note to the agent editing its file, and the agent
confirms it is still true. Then what? Before this, nothing -- a confirmed note
stayed a note. Triage with no address is just re-reading the pile.

This is the address. A confirmed finding becomes a Linear issue the autonomous
worker can actually pick up, and the ledger row stops firing.

THE BAR: no Definition of Ready, no issue. `linear-worker.sh` refuses any issue
without one, so promoting without a DoR would file something nothing can work --
the 137-issue queue that started this whole PRD. Refusing here is the only place
that cannot be forgotten later.

The DoR is written by the agent that CONFIRMED the finding, because it has the
file open and the context loaded. Nobody will ever be cheaper.

The row moves to `promoted`, not `resolved`. Resolution still requires the
Linear issue to actually close -- promoting is not fixing, and a status that
claimed otherwise would let the pile launder itself clean.

Usage:
  spillover-promote.py <id> --title "..." --dor-file dor.md
  spillover-promote.py <id> --title "..." --dor "..." --dry-run
"""
import argparse
import contextlib
import fcntl
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve()
SKELETON = HERE.parents[3]
TEAM_KEY = os.environ.get("KIPI_LINEAR_TEAM", "ASK")

# The sections a DoR must carry for linear-worker to have anything to act on.
# Not cosmetic: an issue missing "what files" or "how do I know it is done" is
# one the worker either refuses or guesses at, and guessing is worse.
REQUIRED_DOR = ("allowed files", "acceptance")

# THE ISSUE MUST BE SELECTABLE, NOT MERELY CREATED (ASK-451).
# linear-worker.sh `ready()` refuses anything without `owner:sana`, and its
# `in_this_repo()` treats an UNSET project as "not this repo" -- deliberately,
# because "target unknown" and "target is here" are different claims. This
# script filed issues with neither for its whole life, so every promotion
# landed in a queue that structurally could not see it. Both halves were
# individually tested and individually fine; nothing tested the handoff.
REQUIRED_LABELS = ("owner:sana",)

LABEL_BY_NAME = 'query($name:String!){issueLabels(filter:{name:{eq:$name}}){nodes{id name}}}'
PROJECT_BY_NAME = 'query($name:String!){projects(filter:{name:{eq:$name}}){nodes{id name}}}'
# The dedup read. Scoped to the team we create into, because an identifier from
# another team is not a promotion of this finding.
ISSUE_BY_MARKER = ('query($q:String!,$team:String!){issues(filter:{'
                   'team:{key:{eq:$team}},description:{contains:$q}},first:5)'
                   '{nodes{identifier}}}')


def ledger_root(repo_root: Path) -> Path:
    """Resolve the ledger root the way prd_runner does -- by CALLING prd_runner.

    why: `*.jsonl` is gitignored, so the spillover ledger is never shared through
    git. Resolving it from the per-worktree root gives every worktree its own
    private ledger: 26 of them holding 71 findings the main checkout could not
    see, measured 2026-07-30. prd_runner._ledger_root resolves via
    `git rev-parse --git-common-dir` instead, which is the same directory from
    every worktree in the set.

    This script had exactly that bug. Run from a worktree it read a ledger that
    does not exist, so `load_rows` came back empty and EVERY promotion exited 2
    with "unknown finding". An automatic caller would have done nothing forever
    while looking healthy -- silent absence, which is worse than the visible
    unlabelled issue this file was fixed for.

    IMPORTED, never reimplemented. Two derivations of one rule is how the ledger
    got split in the first place, and a private copy here would drift the same
    way. On failure we fall back to repo_root, which is safe because it fails
    LOUD: the finding is not found and nothing is written.
    """
    # Located next to THIS SCRIPT first, not under repo_root. repo_root may be a
    # worktree that never checked the plugin out, and looking for the resolver
    # inside the tree whose identity we are trying to resolve is the same
    # chicken-and-egg the bug came from -- it fell back to the per-worktree root
    # and looked fixed. repo_root stays as the fallback for an odd layout.
    m = prd_runner(repo_root)
    if m is None:
        return Path(repo_root)
    try:
        return Path(m._ledger_root(Path(repo_root)))
    except Exception:
        return Path(repo_root)


def prd_runner(repo_root):
    """Load prd_runner, or None when it is not on disk. Never raises."""
    candidates = [SKELETON / "plugins" / "prd-os" / "scripts" / "prd_runner.py",
                  Path(repo_root) / "plugins" / "prd-os" / "scripts" / "prd_runner.py"]
    runner = next((c for c in candidates if c.is_file()), None)
    if runner is None:
        return None
    try:
        spec = importlib.util.spec_from_file_location("prd_runner_root", runner)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m
    except Exception:
        return None


@contextlib.contextmanager
def ledger_lock(repo_root: Path):
    """Serialize check -> create -> append against every other ledger writer.

    why (Codex major, PR #120): those three steps were unserialized, so two runs
    both read `open`, both called issueCreate, and both appended. The ratchet
    makes that ordinary rather than exotic -- it fires PostToolUse in every agent
    session, and since the git-common-dir fix every worktree in the set shares
    ONE ledger. A duplicate Linear issue is permanent: nothing downstream
    de-duplicates, and the worker would dispatch two runs at one fix.

    IMPORTED from prd_runner, never reimplemented -- same rule as `ledger_root`
    above, and for the same reason. `_spillover_lock` already guards
    resolve/reclassify on the SAME `spillover.jsonl.lock` path, so importing it
    (rather than opening a private second lock) is what makes promote serialize
    against a concurrent resolve too. A second lock file would serialize
    promotions against each other and against nothing else.

    It only reads `cfg.repo_root`, so a namespace carrying that one field is the
    whole contract; building a real Config here would couple this script to a
    constructor it has no other use for.

    AN UNIMPORTABLE MODULE IS NOT AN UNLOCKABLE DIRECTORY (Codex major, PR #136).
    This used to inherit `_spillover_lock`'s degrade for both, and warned its way
    into an unlocked promotion whenever `prd_runner()` came back None -- which it
    does for a plugin that is not checked out, has a syntax error, or is missing
    a dependency, none of which say anything about whether a lock can be taken.
    The directory is writable in every one of those cases and `flock` is in the
    standard library, so the fallback below takes the SAME lock file directly.
    Not a second lock path: a private one would serialize promotions against each
    other and against nothing else, while a concurrent `resolve` holds this one.
    """
    m = prd_runner(repo_root)
    if m is not None and hasattr(m, "_spillover_lock"):
        with m._spillover_lock(SimpleNamespace(repo_root=Path(repo_root))):
            yield
        return
    sys.stderr.write(
        "WARNING: prd_runner._spillover_lock is unavailable; locking the ledger "
        "directly instead.\n")
    with direct_ledger_lock(ledger_root(repo_root) / ".prd-os" / "spillover.jsonl"):
        yield


@contextlib.contextmanager
def direct_ledger_lock(ledger: Path):
    """flock `<ledger>.lock`, or warn and proceed when it cannot be taken.

    Byte-for-byte the mechanism `_spillover_lock` uses -- same sibling `.lock`
    path, same `LOCK_EX` -- so the two interoperate: a promotion holding this one
    blocks a `resolve` holding that one, because they are the same file.

    DEGRADES, NEVER REFUSES, and here the reason actually applies: taking the
    lock must CREATE a file, so it needs write permission on the DIRECTORY, while
    appending to an existing ledger needs it only on the FILE. Read-only sandboxes
    are routine (every Codex round this session ran in one), and a promotion that
    cannot lock still beats a conveyor that stops. The re-read under the lock in
    `promote_locked` closes the window for every sequential caller regardless.
    """
    lock_path = ledger.with_name(ledger.name + ".lock")
    fh = None
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fh = lock_path.open("w")
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
    except OSError as exc:
        if fh is not None:
            fh.close()
            fh = None
        sys.stderr.write(
            f"WARNING: cannot lock {lock_path} ({exc}); promoting UNLOCKED. Two "
            "concurrent promotions could file two issues for one finding.\n")
    try:
        yield
    finally:
        if fh is not None:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            finally:
                fh.close()


def linear_module():
    spec = importlib.util.spec_from_file_location("ls", HERE.parent / "linear-sync.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def load_rows(ledger: Path) -> dict:
    rows = {}
    if not ledger.is_file():
        return rows
    for line in ledger.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "id" in r:
                rows[r["id"]] = r
    return rows


def validate_dor(text: str) -> list:
    """Missing required sections. Empty list means the DoR is workable."""
    low = (text or "").lower()
    missing = [s for s in REQUIRED_DOR if s not in low]
    if len((text or "").strip()) < 120:
        missing.append("substance (under 120 chars is not a scope)")
    return missing


def resolve_one(ls, query: str, name: str, kind: str):
    """Look up a Linear id by name. Returns None when the name does not exist.

    Refusing on a miss (rather than dropping the field) is the whole point: an
    issue created without the label or project is INVISIBLE to the worker, and
    an invisible issue reads exactly like an empty board. A loud refusal here
    costs one promotion; a silent one costs the conveyor.
    """
    nodes = (ls.graphql(query, {"name": name}) or {}).get(kind, {}).get("nodes") or []
    return nodes[0]["id"] if nodes else None


def promotion_marker(finding_id: str) -> str:
    """The string that makes a Linear issue self-identify as this promotion.

    build_body OPENS with it, so the issue itself carries the dedup key. That is
    the point: the ledger row is a local file that can fail to be written, the
    Linear issue is the permanent thing. Ask the permanent record.
    """
    return f"Promoted from spillover `{finding_id}`"


def existing_issue(ls, finding_id: str):
    """Identifier of an issue ALREADY filed for this finding, or None.

    why (Codex major, PR #136): the create and the ledger append are two writes
    to two systems and only one of them can be rolled back. When the append
    failed the row stayed `open`, so the next run passed the status check and
    filed a SECOND permanent issue for one finding -- the exact invariant the
    lock was added to protect, reached by a different door. A lock serializes
    concurrent runs; it says nothing about a run that already finished halfway.

    So the check that decides is a read of Linear, not of the ledger. It makes
    the whole promotion idempotent: crash, kill, or failed append, a re-run finds
    its own issue and repairs the ledger instead of duplicating.

    RAISES on a query failure, deliberately, and main lets that refuse the run.
    Failing closed costs one promotion; failing open costs a permanent duplicate,
    and nothing downstream de-duplicates.
    """
    res = ls.graphql(ISSUE_BY_MARKER,
                     {"q": promotion_marker(finding_id), "team": TEAM_KEY})
    nodes = ((res or {}).get("issues") or {}).get("nodes") or []
    return nodes[0].get("identifier") if nodes else None


def build_body(rec: dict, dor: str, repo: str) -> str:
    return (
        f"{promotion_marker(rec['id'])} (severity: {rec.get('severity')}, "
        f"source: `{rec.get('source')}`, repo: `{repo}`).\n\n"
        f"## The finding\n\n{rec.get('description', '')}\n\n"
        f"## Definition of Ready\n\n{dor}\n\n"
        f"---\n*Confirmed still-true at the moment its file was edited, then "
        f"promoted. Resolve the ledger row with "
        f"`prd_runner.py spillover resolve {rec['id']} --resolution-ref <this issue>` "
        f"once this closes.*"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("finding_id")
    ap.add_argument("--title", required=True)
    ap.add_argument("--dor", help="Definition of Ready, inline")
    ap.add_argument("--dor-file", help="Definition of Ready, from a file")
    ap.add_argument("--repo-root", default=str(SKELETON))
    ap.add_argument("--priority", type=int, default=3)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    root = Path(args.repo_root).resolve()
    ledger = ledger_root(root) / ".prd-os" / "spillover.jsonl"
    rows = load_rows(ledger)
    rec = rows.get(args.finding_id)
    if not rec:
        # Name the ledger. "unknown finding" against a ledger that does not
        # exist and "unknown finding" against the right one are different
        # problems, and the first is how the worktree bug stayed invisible.
        sys.stderr.write(
            f"unknown finding: {args.finding_id}\n"
            f"  ledger: {ledger} ({'exists' if ledger.is_file() else 'MISSING'}, "
            f"{len(rows)} findings)\n")
        return 2
    if rec.get("status") != "open":
        sys.stderr.write(f"{args.finding_id} is '{rec.get('status')}', not open\n")
        return 2

    dor = args.dor or ""
    if args.dor_file:
        dor = Path(args.dor_file).read_text()
    missing = validate_dor(dor)
    if missing:
        sys.stderr.write(
            f"refused: the Definition of Ready is missing {', '.join(missing)}.\n\n"
            "linear-worker.sh will not touch an issue without a workable DoR, so\n"
            "promoting without one files something nothing can work. That is the\n"
            "137-issue queue this whole effort started from.\n\n"
            "A DoR needs at least:\n"
            "  **Allowed files** -- explicit paths the fix may touch\n"
            "  **Acceptance**    -- checkboxes, including how a failure would show\n"
            "You have the file open. You are the cheapest person to write this.\n")
        return 2

    args._dor = dor      # the transaction rebuilds the body from the FRESH row
    body = build_body(rec, dor, root.name)
    if args.dry_run:
        print(f"WOULD CREATE in team {TEAM_KEY}: {args.title}\n")
        print(body[:900])
        print(f"\nDRY RUN. {ledger} unchanged.")
        return 0

    # EVERYTHING FROM HERE IS ONE TRANSACTION. The status re-read, the create
    # and the append are the three steps Codex found unserialized on PR #120;
    # a lock around the append alone still lets two runs both pass the check.
    with ledger_lock(root):
        return promote_locked(args, root, ledger, rec)


def promote_locked(args, root: Path, ledger: Path, rec: dict) -> int:
    """The transaction. Called ONLY with the ledger lock held.

    Split out rather than indented in place so the lock's span is one line to
    read: everything this function does happens inside it, and nothing outside
    it writes.
    """
    # RE-READ UNDER THE LOCK. The pre-lock check above is a fast refusal for the
    # ordinary case; it is not the decision. Between it and here another run may
    # have promoted this same finding, and its ledger append is the only record
    # of that. Trusting the earlier read is precisely the check-then-act the
    # duplicate came from.
    fresh = load_rows(ledger).get(args.finding_id)
    if not fresh or fresh.get("status") != "open":
        status = (fresh or {}).get("status", "gone from the ledger")
        sys.stderr.write(
            f"refused: {args.finding_id} is '{status}', not open.\n"
            "Another run promoted or resolved it while this one was starting.\n"
            "One finding gets ONE issue; nothing downstream de-duplicates.\n")
        return 2
    rec = fresh
    ls = linear_module()

    # ASK THE PERMANENT RECORD BEFORE WRITING TO IT. An earlier run may have
    # created the issue and then failed to append -- the ledger cannot show that,
    # only Linear can. Read first, and the whole promotion becomes idempotent.
    ident = existing_issue(ls, rec["id"])
    if ident:
        # The REPAIR path. It resolves no label and no project on purpose: the
        # issue already exists, so a missing project name must not be able to
        # block the ledger from catching up with it. That would leave the row
        # `open` forever against an issue that is already on the board.
        sys.stderr.write(
            f"{rec['id']} already has issue {ident}; a previous run created it "
            "and did not record it.\nRecording it now, creating nothing.\n")
    else:
        ident = create_issue(ls, args, root, build_body(rec, args._dor, root.name))
        if not isinstance(ident, str):
            return ident      # a refusal/failure code from the create path

    # `promoted`, never `resolved`. Promoting is not fixing; a status claiming
    # otherwise would let the pile launder itself clean without a single fix.
    promoted = dict(rec)
    promoted.update({"status": "promoted", "linear_ref": ident,
                     "promoted_from_ratchet": True})
    try:
        with ledger.open("a") as fh:
            fh.write(json.dumps(promoted) + "\n")
            fh.flush()
    except OSError as exc:
        # LOUD, and it names the recovery. The issue is already permanent; the
        # row is not. Silence here is what made the duplicate: the next run had
        # no way to learn that this one had already filed.
        sys.stderr.write(
            f"issue {ident} EXISTS but the ledger append failed: {exc}\n"
            f"  ledger: {ledger}\n"
            f"{rec['id']} is still 'open'. Re-run this exact command once the "
            f"ledger is writable;\nit will find {ident} and record it rather "
            "than filing a second issue.\n")
        return 1
    print(json.dumps({"finding": rec["id"], "linear": ident, "status": "promoted"}))
    return 0


def _main_checkout(root: Path) -> str:
    """The registered checkout path for `root`, resolving a git WORKTREE to it.

    the finding (codex, PR #260): matching realpath(root) against the registry
    rejected every real worktree. instance-registry.json records ONE path per
    instance, the main checkout, and a worktree lives somewhere else entirely,
    often under /private/tmp. No row matched, the derivation fell through to the
    worktree's basename, and the promotion refused.

    That is precisely the UNATTENDED path: linear-worker.sh does its work in
    worktrees. The rung would have worked every time a human ran it by hand in
    the checkout and failed every time the worker ran it. Same by-hand-versus-
    real split verify.sh hit with the hook environment, one repo over, which is
    why it was worth taking the finding seriously rather than arguing scope.

    `--git-common-dir` is the resolution: inside a worktree it points at the MAIN
    repo's .git, whose parent is the registered path. In an ordinary checkout it
    is that checkout's own .git, so this is a no-op there. Any failure falls back
    to realpath(root), the previous behaviour.
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "rev-parse",
             "--path-format=absolute", "--git-common-dir"],
            capture_output=True, text=True)
        common = (out.stdout or "").strip()
        if out.returncode == 0 and common and os.path.basename(common) == ".git":
            return os.path.realpath(os.path.dirname(common))
    except Exception:
        pass
    return os.path.realpath(str(root))


def registry_project(root: Path) -> str:
    """The board project this checkout maps to, per instance-registry.json.

    THE THIRD RUNG. linear-worker.sh has always had it and this script did not,
    so `project_name` fell through to the checkout basename. On the consulting
    instance that is "consulting", the board project is "ASK Consulting", and
    every promotion from that repo was refused with "no Linear project named
    'consulting'". Measured 2026-08-27 against the live board: 19 projects, no
    "consulting", and "ASK Consulting" present as 6497f378. The registry row has
    carried `linear_project: "ASK Consulting"` the whole time. Nothing was
    missing in Linear; this script was asking for the wrong name.

    The old comment here said replicating the rule would give one decision two
    writers, which was right, so this IMPORTS the decision instead of copying
    it. `_linear_project_of` in alert-to-linear.py owns the precedence
    (explicit `linear_project`, then `name`) and stays the only place that rule
    is written. What lives here is the path match, which is mechanics.

    Returns "" on any failure, so the derivation falls through to the basename
    exactly as before. A registry that cannot be read must not invent a project
    name -- filing into the wrong board is worse than refusing.
    """
    try:
        spec = importlib.util.spec_from_file_location(
            "a2l", HERE.parent / "alert-to-linear.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        rows = mod._registry_rows()
        target = _main_checkout(root)
    except Exception:
        return ""
    for row in rows:
        row_path = row.get("path")
        if not row_path:
            continue
        try:
            if os.path.realpath(row_path) == target:
                return mod._linear_project_of(row)
        except OSError:
            continue
    return ""


def create_issue(ls, args, root: Path, body: str):
    """The issue, or an int exit code when a required name does not resolve."""
    tid = ls.graphql('query{teams(filter:{key:{eq:"%s"}}){nodes{id}}}' % TEAM_KEY,
                     {})["teams"]["nodes"][0]["id"]
    # Resolved BEFORE the create, so a bad name costs nothing. Resolving after
    # would leave an unlabelled issue on the board that nothing drains and
    # nobody is looking for.
    label_ids = []
    for name in REQUIRED_LABELS:
        lid = resolve_one(ls, LABEL_BY_NAME, name, "issueLabels")
        if not lid:
            sys.stderr.write(
                f"refused: label '{name}' does not exist on this Linear workspace.\n"
                "linear-worker.sh ready() requires it, so the issue would be filed\n"
                "into a queue that cannot see it. Create the label, then re-run.\n")
            return 2
        label_ids.append(lid)

    # The SAME THREE RUNGS as linear-worker.sh, in the same order: explicit env
    # override, then the instance-registry alias, then the checkout basename.
    # The third rung used to be missing here and that was the whole bug: every
    # instance whose directory name is not its board name refused every
    # promotion, which on this fleet is 8 of 25 (measured 2026-08-15, recorded
    # in _registry_path). sp-421fa27d, sp-08fae4fc and sp-f227a6fd are three
    # ledger rows describing that one gap.
    project_name = (os.environ.get("KIPI_LINEAR_PROJECT")
                    or registry_project(root)
                    or root.name)
    pid = resolve_one(ls, PROJECT_BY_NAME, project_name, "projects")
    if not pid:
        sys.stderr.write(
            f"refused: no Linear project named '{project_name}'.\n"
            "in_this_repo() treats an unset or foreign project as NOT this repo,\n"
            "so this issue would never be picked by any worker.\n"
            f"Tried, in order: KIPI_LINEAR_PROJECT (unset), instance-registry\n"
            f"alias for {root} ({registry_project(root) or 'no row'}), "
            f"basename ({root.name}).\n"
            "Add a `linear_project` to this checkout's instance-registry row, or\n"
            "set KIPI_LINEAR_PROJECT.\n")
        return 2

    res = ls.graphql(ls.ISSUE_CREATE, {"input": {
        "teamId": tid, "title": args.title, "description": body,
        "priority": args.priority,
        "labelIds": label_ids, "projectId": pid}})
    # linear-filer: human-in-the-loop -- one confirmed finding per invocation,
    # and validate_dor refuses to create without a human-authored title and a
    # Definition of Ready carrying allowed-files + acceptance. A person decided
    # this issue exists, so needs-triage would mark work that is already routed.
    ident = ((res.get("issueCreate") or {}).get("issue") or {}).get("identifier")
    if not ident:
        sys.stderr.write(f"Linear create failed: {json.dumps(res)[:300]}\n")
        return 1
    return ident


if __name__ == "__main__":
    sys.exit(main())
