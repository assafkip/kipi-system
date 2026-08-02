#!/usr/bin/env python3
"""Post-hoc sweep: count the bypasses that skipped the commit-msg gate (ASK-284).

Pairs with `linear-issue-ref-check.py` (the commit-msg gate) and
`.claude/rules/linear-first.md`.

WHY THIS EXISTS
---------------
The gate's escape hatch is deliberately countable: `[no-issue: reason]` appends a
row to `q-system/output/linear-bypass.jsonl` so work landing outside Linear is a
number rather than a rumour. But `git commit --no-verify` skips lefthook entirely,
so the gate never runs and the ledger never learns. On 2026-08-01 three commits
(`7b5061f`, `56aaab7`, `4b06dd3`) reached origin that way. The ledger's last row
predated all three. It reported a lower number than the truth and read as clean.

That is the exact shape of `q-system/lessons/split-the-act-path-from-the-verify-path.md`:
the ACT path (block the commit) and the VERIFY path (count it) both hung off one
capability — lefthook running. Disable it and both die at once. So the verify path
here reads git directly. `--no-verify` cannot turn git log off.

WHAT IT DOES NOT DO
-------------------
It does not rewrite history, does not block anything, and does not weaken the
gate. Prevention still lives in the commit-msg hook, which works. This is the
accounting that survives the hook being skipped.

CLASSIFICATION IS NOT REIMPLEMENTED HERE
----------------------------------------
The regexes, the skip-prefix list, and the comment stripper are IMPORTED from the
gate module, not copied. Two copies of a rule drift, and the drift shows up as a
sweep that disagrees with the gate about what counts as accounted — which is a
worse failure than the hole it was built to close.

IDEMPOTENCE
-----------
A commit is recorded at most once, deduped on its full sha against the shas
already in the ledger. So the sweep can run on every cycle and only a genuinely
NEW occurrence produces a new row (and therefore a new alert). That is the
`detect-act-learn` constraint: one line per new occurrence, never one per cycle.

A commit that went through the hook carries `[no-issue:]`, so it is `accounted`
and the sweep never touches it. Hook rows and sweep rows cannot describe the same
commit by construction; there is no double-count to guard against.

USAGE
-----
    python3 linear-bypass-sweep.py                     # sweep the tracked upstream
    python3 linear-bypass-sweep.py --rev origin/main
    python3 linear-bypass-sweep.py --dry --json        # report, write nothing

Exit code is 0 whenever the sweep itself ran. This is an accountant, not a gate:
a non-zero exit would make the daily job that calls it look broken on the days it
found something, which is exactly backwards.
"""
from __future__ import annotations

import argparse
import fcntl
import importlib.util
import json
import os
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
GATE_PATH = HERE / "linear-issue-ref-check.py"

# git log field separator. NUL between fields, RS between records: neither can
# appear inside a commit message, so a multi-line body cannot fake a new record.
#
# The FORMAT STRING uses git's own `%x00`/`%x1e` escapes rather than the literal
# bytes. A literal NUL cannot be passed in argv at all -- `subprocess` raises
# `ValueError: embedded null byte` before git ever runs -- so git has to be the
# one that emits the byte, into its output where it is legal.
FIELD_SEP = "\x00"
RECORD_SEP = "\x1e"
FIELD_SEP_FMT = "%x00"
RECORD_SEP_FMT = "%x1e"

DEFAULT_MAX_COUNT = 500
SWEEP_REASON = "unaccounted: reached origin with no issue ref and no [no-issue:] tag"


def load_gate():
    """Import the commit-msg gate by path (its filename has dashes).

    Single source for the classification rules. If this import fails the sweep
    refuses to run rather than falling back to its own copy of the regexes — a
    sweep that guesses is worse than a sweep that says it could not check.
    """
    spec = importlib.util.spec_from_file_location("linear_issue_ref_check", GATE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load the commit-msg gate at {GATE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(args: list, cwd: Path) -> tuple:
    """Run git, return (returncode, stdout). Never raises."""
    try:
        res = subprocess.run(
            ["git"] + args, capture_output=True, text=True, timeout=60, cwd=str(cwd),
        )
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return res.returncode, res.stdout


def repo_root(start: Path) -> Path:
    code, out = git(["rev-parse", "--show-toplevel"], start)
    if code == 0 and out.strip():
        return Path(out.strip())
    return start


def default_rev(cwd: Path) -> str:
    """The branch's own upstream if it has one, else origin's default branch.

    'Reached origin' is the property that matters: a commit still sitting in a
    local branch is inside the founder's control and outside this ledger's job.
    """
    code, out = git(["rev-parse", "--symbolic-full-name", "@{u}"], cwd)
    if code == 0 and out.strip():
        return out.strip()
    code, out = git(["symbolic-ref", "--short", "refs/remotes/origin/HEAD"], cwd)
    if code == 0 and out.strip():
        return out.strip()
    return "origin/main"


def known_remotes(cwd: Path) -> list:
    code, out = git(["remote"], cwd)
    return out.split() if code == 0 else []


def remote_of(rev: str, cwd: Path) -> str:
    """The remote a remote-tracking rev belongs to, or "" for a local ref."""
    name = rev
    if name.startswith("refs/remotes/"):
        name = name[len("refs/remotes/"):]
    head = name.split("/", 1)[0]
    return head if head and head in known_remotes(cwd) else ""


def fetch_remote(remote: str, cwd: Path) -> str:
    """Refresh the remote-tracking refs. Returns "ok" or "failed", never silence.

    A remote-tracking ref is a LOCAL cache. Nothing refreshes it on its own, so a
    commit pushed from another checkout (a worktree, another machine, a merge
    landed on the web) is invisible here until some unrelated process happens to
    fetch. The sweep would then report clean about a range it had not seen — the
    same shape as the ledger it exists to fix, one layer down.

    Failure is REPORTED rather than swallowed. `detect_unaccounted_commits` treats
    a failed fetch as a blind detector, because a possibly-stale ref answering
    "nothing unaccounted" is not a negative result, it is an unknown.
    """
    code, _ = git(["fetch", "--quiet", remote], cwd)
    return "ok" if code == 0 else "failed"


def lock_path(ledger: Path) -> Path:
    return ledger.parent / (ledger.name + ".lock")


@contextmanager
def ledger_lock(ledger: Path):
    """Hold an exclusive lock across the ledger's read-then-append.

    The dedup is "is this sha already in the file", so the read and the append are
    ONE critical section. Two sweeps overlapping between them (the daily launchd
    job and a hand run, or two repos on one machine) both read an absent sha and
    both append it, which double-counts in the one file whose entire job is to
    carry a true count. That is the `dedup-ledger-append-only-single-writer`
    lesson: a dedup ledger needs a single writer, and here the lock IS it.

    The lock is a sidecar file, never the ledger itself: locking the ledger would
    mean opening it for write to read it, and a reader must not be able to create
    or truncate the thing it is counting.

    Yields False when the lock could not be taken at all (a read-only directory).
    The sweep still runs — an unlocked count beats no count — and the caller
    reports `locked: false` so the weaker guarantee is visible, not assumed.
    """
    path = lock_path(ledger)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = path.open("a+")
    except OSError as exc:
        print(f"linear-bypass-sweep: WARNING could not open lock {path}: {exc}",
              file=sys.stderr)
        yield False
        return
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield True
    finally:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        handle.close()


def gate_live_since(cwd: Path) -> str:
    """Authored date of the commit that ADDED the commit-msg gate.

    A commit made before the gate existed did not bypass anything, so counting it
    as a bypass makes the ledger lie in the opposite direction — the first real
    run reported 246 when the true number was 3. The floor is derived from git,
    not hardcoded, so it stays right if the gate is ever re-added or moved.

    Empty string when it cannot be derived, which means no floor: better to
    over-count than to silently drop the whole window.
    """
    rel = GATE_PATH.name
    code, out = git(
        ["log", "--diff-filter=A", "--format=%aI", "--", f"*{rel}"], cwd,
    )
    if code != 0 or not out.strip():
        return ""
    # --diff-filter=A can list several adds (a move re-adds the path); the FIRST
    # time it existed is the floor, and git log is newest-first.
    return out.strip().splitlines()[-1].strip()


def parse_floor(value: str, strict: bool = True):
    """Parse an ISO-8601 date or timestamp into an aware datetime.

    `strict` callers get a RuntimeError on junk. A floor that cannot be parsed
    must never degrade into "no floor" — that is the failure mode that made
    `git log --since` unusable here.
    """
    text = (value or "").strip()
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        if strict:
            raise RuntimeError(
                f"--since must be ISO-8601 (YYYY-MM-DD or a full timestamp), got {value!r}")
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def rev_exists(rev: str, cwd: Path) -> bool:
    code, _ = git(["rev-parse", "--verify", "--quiet", rev + "^{commit}"], cwd)
    return code == 0


def read_commits(rev: str, max_count: int, cwd: Path, since: str = "") -> list:
    """Commits reachable from `rev`, newest first, as {sha, subject, message, at}."""
    fmt = FIELD_SEP_FMT.join(["%H", "%aI", "%B"]) + RECORD_SEP_FMT
    # The floor is applied in Python, NOT via `git log --since`. Git's approxidate
    # parser silently IGNORES a value it cannot handle and returns the whole range
    # (`--since=2999-01-01` returned every commit), so a bad floor would quietly
    # disable the filter — the exact silent-no-op shape this ledger exists to stop.
    floor = parse_floor(since) if since else None
    code, out = git(
        ["log", f"--max-count={max_count}", f"--format={fmt}", rev], cwd,
    )
    if code != 0:
        return []
    commits = []
    for record in out.split(RECORD_SEP):
        record = record.strip("\n")
        if not record.strip():
            continue
        parts = record.split(FIELD_SEP)
        if len(parts) < 3:
            continue
        sha, authored_at, message = parts[0].strip(), parts[1].strip(), parts[2]
        if floor is not None:
            when = parse_floor(authored_at, strict=False)
            if when is None or when < floor:
                continue
        body = message.strip()
        commits.append({
            "sha": sha,
            "authored_at": authored_at,
            "message": body,
            "subject": body.splitlines()[0].strip() if body else "",
        })
    return commits


def is_accounted(message: str, gate) -> bool:
    """True when the gate would have let this message through on its own terms.

    Mirrors `gate.main()` without its side effects: same comment stripping, same
    skip prefixes, same issue regex, same bypass regex with a non-empty reason.
    """
    body = gate.strip_comments(message).strip()
    if not body:
        return True
    subject = body.splitlines()[0].strip()
    if subject.lower().startswith(gate.SKIP_PREFIXES):
        return True
    if gate.ISSUE_RE.search(body):
        return True
    bypass = gate.BYPASS_RE.search(body)
    if bypass and bypass.group("reason").strip():
        return True
    return False


def ledger_path(root: Path) -> Path:
    override = os.environ.get("LINEAR_BYPASS_LEDGER")
    if override:
        return Path(override)
    return root / "q-system/output/linear-bypass.jsonl"


def recorded_shas(path: Path) -> set:
    """Shas already in the ledger. A malformed line is skipped, never fatal.

    Rows written by the commit-msg hook carry no `commit` field at all (the hook
    runs before the sha exists). They are simply absent from this set, which is
    correct: the hook only ever records commits the sweep classifies as accounted.
    """
    shas = set()
    if not path.is_file():
        return shas
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                sha = entry.get("commit")
                if isinstance(sha, str) and sha:
                    shas.add(sha)
    except OSError:
        return shas
    return shas


def append_entries(path: Path, entries: list) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            for entry in entries:
                fh.write(json.dumps(entry) + "\n")
    except OSError as exc:
        print(f"linear-bypass-sweep: WARNING could not write ledger: {exc}",
              file=sys.stderr)
        return False
    return True


def sweep(rev: str, max_count: int, root: Path, dry: bool, since: str = "",
          fetch: bool = True) -> dict:
    gate = load_gate()
    path = ledger_path(root)

    remote = remote_of(rev, root)
    if not remote:
        fetched = "local-ref"
    elif not fetch:
        fetched = "skipped"
    else:
        fetched = fetch_remote(remote, root)

    if not rev_exists(rev, root):
        return {"rev": rev, "since": since, "fetched": fetched, "locked": False,
                "scanned": 0, "unaccounted": 0, "recorded": 0, "commits": [],
                "status": "rev-not-found"}

    commits = read_commits(rev, max_count, root, since)

    # The read and the append are ONE critical section: the dedup asks "is this
    # sha already in the file", so a concurrent sweep landing between them
    # double-records. Everything above is a git read and holds no lock.
    with ledger_lock(path) as locked:
        known = recorded_shas(path)

        fresh = []
        unaccounted = 0
        for commit in commits:
            if is_accounted(commit["message"], gate):
                continue
            unaccounted += 1
            if commit["sha"] in known:
                continue
            fresh.append(commit)

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        entries = [{
            "at": now,
            "reason": SWEEP_REASON,
            "subject": c["subject"][:200],
            "commit": c["sha"],
            "authored_at": c["authored_at"],
            "source": "sweep",
        } for c in reversed(fresh)]  # oldest first, so the ledger reads chronologically

        written = True
        if entries and not dry:
            written = append_entries(path, entries)

    return {
        "rev": rev,
        "since": since,
        "fetched": fetched,
        "locked": locked,
        "ledger": str(path),
        "scanned": len(commits),
        "unaccounted": unaccounted,
        "recorded": 0 if (dry or not written) else len(entries),
        "commits": [c["sha"] for c in reversed(fresh)],
        "status": "dry" if dry else ("ok" if written else "ledger-write-failed"),
    }


def main(argv: list) -> int:
    parser = argparse.ArgumentParser(
        description="Record commits that reached origin without a Linear issue ref.")
    parser.add_argument("--rev", help="ref to sweep (default: tracked upstream)")
    parser.add_argument("--max-count", type=int, default=DEFAULT_MAX_COUNT,
                        help=f"how many commits back to scan (default {DEFAULT_MAX_COUNT})")
    parser.add_argument("--since", help="floor date (default: when the gate went live)")
    parser.add_argument("--all-history", action="store_true",
                        help="ignore the gate-activation floor and scan the whole window")
    parser.add_argument("--no-fetch", dest="fetch", action="store_false",
                        help="do not refresh remote-tracking refs before reading them")
    parser.add_argument("--dry", "-n", action="store_true",
                        help="report what would be recorded, write nothing")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv[1:])

    root = repo_root(Path.cwd())
    rev = args.rev or default_rev(root)

    if args.all_history:
        since = ""
    elif args.since:
        since = args.since
    else:
        since = gate_live_since(root)

    try:
        result = sweep(rev, args.max_count, root, args.dry, since, args.fetch)
    except RuntimeError as exc:
        print(f"linear-bypass-sweep: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result))
        return 0

    if result["status"] == "rev-not-found":
        print(f"linear-bypass-sweep: {rev} does not resolve; nothing swept.")
        return 0

    if result["fetched"] == "failed":
        print(f"linear-bypass-sweep: WARNING fetch of {remote_of(rev, root)} failed; "
              f"{rev} may be stale and this count may be low.", file=sys.stderr)
    print(f"linear-bypass-sweep: {rev} — scanned {result['scanned']}, "
          f"unaccounted {result['unaccounted']}, newly recorded {result['recorded']} "
          f"(fetch: {result['fetched']})")
    for sha in result["commits"]:
        print(f"  {sha[:9]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
