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
import importlib.util
import json
import os
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

    DEGRADES, NEVER REFUSES, inherited deliberately: `_spillover_lock` warns to
    stderr and proceeds unlocked when the directory is read-only (Codex sandboxes
    are read-only here routinely). A promotion that cannot lock is still better
    than a conveyor that stops; the re-read below still closes the window for
    every sequential caller.
    """
    m = prd_runner(repo_root)
    if m is None or not hasattr(m, "_spillover_lock"):
        sys.stderr.write(
            "WARNING: prd_runner._spillover_lock is unavailable; promoting "
            "UNLOCKED. Two concurrent promotions could file two issues for one "
            "finding.\n")
        yield
        return
    with m._spillover_lock(SimpleNamespace(repo_root=Path(repo_root))):
        yield


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

    # Same derivation ORDER as linear-worker.sh: explicit env override, then the
    # checkout basename. The worker has a third step (instance-registry lookup)
    # that this does not replicate -- duplicating that rule would give one
    # decision two writers and they would drift. See the spillover item filed
    # with this change: on the three instances whose project name is not their
    # basename, set KIPI_LINEAR_PROJECT until the derivation is shared.
    project_name = os.environ.get("KIPI_LINEAR_PROJECT") or root.name
    pid = resolve_one(ls, PROJECT_BY_NAME, project_name, "projects")
    if not pid:
        sys.stderr.write(
            f"refused: no Linear project named '{project_name}'.\n"
            "in_this_repo() treats an unset or foreign project as NOT this repo,\n"
            "so this issue would never be picked by any worker. Set\n"
            "KIPI_LINEAR_PROJECT to the project this checkout maps to.\n")
        return 2

    res = ls.graphql(ls.ISSUE_CREATE, {"input": {
        "teamId": tid, "title": args.title, "description": body,
        "priority": args.priority,
        "labelIds": label_ids, "projectId": pid}})
    ident = ((res.get("issueCreate") or {}).get("issue") or {}).get("identifier")
    if not ident:
        sys.stderr.write(f"Linear create failed: {json.dumps(res)[:300]}\n")
        return 1
    return ident


if __name__ == "__main__":
    sys.exit(main())
