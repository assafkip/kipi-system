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
    python3 linear-bypass-sweep.py --no-fetch          # read the local ref as-is

A remote-tracking ref is fetched first by default, because it is a LOCAL cache and
a commit pushed from another checkout is otherwise invisible. The fetch result is
reported (`fetched`), never swallowed: a failed fetch means the answer may be low,
which the daily detector treats as blind rather than clean.

The ledger's read-then-append runs under an exclusive flock on a sidecar lock
file, so two overlapping sweeps cannot both record the same commit.

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
import re
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
GATE_PATH = HERE / "linear-issue-ref-check.py"

# git log field separator. NUL between fields, RS between records.
#
# ONE of those two bytes is actually impossible inside a commit message, and the
# earlier claim that both were is false. \x1e passes through argv, so
# `git commit -m $'subject\x1ebody'` stores it verbatim -- measured, not reasoned.
# NUL is the impossible one: `subprocess` raises `ValueError: embedded null byte`
# before git ever runs, so no argv-fed message can carry it.
#
# That is why the record boundary below is ANCHORED rather than bare. Splitting
# on \x1e alone cut a message AT the separator and dropped the rest of it,
# including the `(ASK-nnn)` that made the commit accounted -- so a gate-accounted
# commit was reported as a bypass (PR #720 round 12).
#
# The FORMAT STRING uses git's own `%x00`/`%x1e` escapes rather than the literal
# bytes, because git has to be the one that emits them, into its output where
# they are legal.
FIELD_SEP = "\x00"
RECORD_SEP = "\x1e"
FIELD_SEP_FMT = "%x00"
RECORD_SEP_FMT = "%x1e"
# A real boundary is the separator followed by the NEXT record's full sha and a
# field separator. A message cannot fake that: it would have to carry a NUL.
# 40 hex for sha1, 64 for a sha256 repo.
#
# The `\n?` is load-bearing, measured not reasoned: `git log --format=X` appends
# its OWN newline after each formatted entry, so the real byte sequence between
# records is `\x1e\n<sha>\x00`, never `\x1e<sha>\x00`. Without it the lookahead
# never matched, the whole walk collapsed into ONE record, and every count in
# the suite came back as 1. The newline is left on the front of the next record
# and removed by that record's own `strip("\n")`.
SHA_PATTERN = r"[0-9a-f]{40}(?:[0-9a-f]{24})?"
RECORD_BOUNDARY = re.compile(
    RECORD_SEP + r"(?=\n?" + SHA_PATTERN + FIELD_SEP + r")")
SHA_RE = re.compile(SHA_PATTERN + r"\Z")

DEFAULT_MAX_COUNT = 500
# The ceiling on automatic growth. It exists so an --all-history scan of a repo
# with a million commits cannot walk forever; it is NOT a correctness boundary,
# because a scan that hits it still reports `truncated` and the detector goes
# blind rather than clean.
MAX_AUTO_COUNT = 100_000
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


def short_ref(ref: str) -> str:
    """`refs/remotes/origin/main` -> `origin/main`. ONE spelling per ref.

    Cosmetic to git, which accepts either and resolves both to the same commit.
    Load-bearing to everything downstream: this string is interpolated into a
    PERMANENT Linear issue body, and `_refresh_one` compares that body's hash to
    decide whether anything changed.

    `@{u}` answers with the long spelling and `origin/HEAD` with the short one.
    Every launchd job runs from a checkout pinned to origin/main (detached, so
    no `@{u}`) while the founder's checkout tracks its upstream, so alternating
    runs rewrote the standing issue and earned a Slack line with nothing
    changed. Worse: reopen is wired to `body_stale`, so the flip reopened an
    issue the operator had triaged and closed, which is the one thing the
    round-9 `close_is_acknowledgement` fix exists to prevent (PR #720 round 12).

    Only `refs/remotes/` is stripped. A `refs/heads/` upstream (a branch tracking
    a LOCAL branch) is left alone: it is a different ref, not a different
    spelling of this one, and `remote_of` has to keep reading it as local.
    """
    prefix = "refs/remotes/"
    return ref[len(prefix):] if ref.startswith(prefix) else ref


def default_rev(cwd: Path) -> str:
    """The branch's own upstream if it has one, else origin's default branch.

    'Reached origin' is the property that matters: a commit still sitting in a
    local branch is inside the founder's control and outside this ledger's job.

    Normalized through `short_ref` at this ONE site, so every consumer -- the
    issue body, stdout, `remote_of`, the JSON result -- reads one spelling.
    """
    code, out = git(["rev-parse", "--symbolic-full-name", "@{u}"], cwd)
    if code == 0 and out.strip():
        return short_ref(out.strip())
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


def gate_live_since(rev: str, cwd: Path) -> str:
    """COMMITTER date of the commit that ADDED the commit-msg gate, ON `rev`.

    Asked of the ref being SWEPT, not of HEAD. It used to run `git log` with no
    rev, so it answered about whatever was checked out while the sweep read
    origin/main. Check out anything predating the gate — a bisect, a detached CI
    checkout, an old tag — and the floor silently became "" for a scan of a ref
    carrying the gate right there in its history (PR #66 round 5).

    A commit made before the gate existed did not bypass anything, so counting it
    as a bypass makes the ledger lie in the opposite direction — the first real
    run reported 246 when the true number was 3. The floor is derived from git,
    not hardcoded, so it stays right if the gate is ever re-added or moved.

    Committer, not author, on BOTH sides of the comparison. The question the floor
    answers is "did this commit object enter this history after the gate went
    live", and a cherry-pick or rebase writes a brand-new object carrying the
    ORIGINAL author date. Comparing author dates meant pre-gate work replayed onto
    a post-gate branch was skipped forever, even though it reached origin after
    activation and no hook ever saw it. Committer dates also stay order-preserving
    under a rebase, which rewrites both the floor commit and everything above it.

    Empty string when it cannot be derived. That is NOT "no floor" any more — the
    caller refuses. An unfloored scan of a repo whose gate is unknown wrote 240
    rows into a permanent, sha-deduped ledger whose entire job is a true count,
    and a row written once is never re-evaluated. Refusing is the recoverable
    direction: the operator picks `--all-history` or `--since`.
    """
    rel = GATE_PATH.name
    code, out = git(
        ["log", "--diff-filter=A", "--format=%cI", rev, "--", f"*{rel}"], cwd,
    )
    if code != 0 or not out.strip():
        return ""
    # --diff-filter=A can list several adds (a move re-adds the path); the FIRST
    # time it existed is the floor, and git log is newest-first.
    return out.strip().splitlines()[-1].strip()


def iso_text(value: str) -> str:
    """git's ISO-8601 spelling, in the one form every `fromisoformat` accepts.

    `%cI` emits a trailing `Z` whenever the offset is exactly +00:00, and
    `datetime.fromisoformat` only learned to read that in Python 3.11. Below
    that it raises, and this module is reached through a bare `python3` from
    `fleet-health-daily.py` and a `#!/usr/bin/env python3` shebang, so WHICH
    interpreter runs it is a PATH fact, not a guarantee.

    Measured on this repo 2026-11-10: of the 723 commits in the swept range, 243
    carry `Z` and 480 carry a numeric offset. On an interpreter that rejects `Z`
    the old code dropped all 243 out of `within_floor` silently, while `status`
    stayed `ok` and `truncated` stayed false — a third of history unread and
    every blindness signal quiet (PR #720 round 13).

    Normalizing here rather than catching the error at each call site is what
    makes the answer interpreter-INDEPENDENT: the parse no longer depends on a
    tolerance that arrived in 3.11.
    """
    text = (value or "").strip()
    if text.endswith(("Z", "z")):
        return text[:-1] + "+00:00"
    return text


def parse_floor(value: str, strict: bool = True):
    """Parse an ISO-8601 date or timestamp into an aware datetime.

    `strict` callers get a RuntimeError on junk. A floor that cannot be parsed
    must never degrade into "no floor" — that is the failure mode that made
    `git log --since` unusable here.
    """
    text = iso_text(value)
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


def within_floor(commit: dict, floor) -> bool:
    """Did this commit object enter history at or after the floor?

    Committer date, matching gate_live_since: a replayed pre-gate commit keeps
    its author date but is a NEW object that entered after the gate.

    An unparseable date RAISES. It used to return False, which reads as "outside
    the floor" and is the same silent false zero the round-10 and round-12 fixes
    in this file already refused: git RETURNED this commit, so dropping it means
    a bypass can hide inside a scan that still reports `status: ok`, and
    `truncated` is derived from this same call so even the blindness signal goes
    quiet. Blind is the recoverable direction; the raise names the sha and the
    byte string so the next step is a lookup rather than a guess.

    After `iso_text`, both spellings git actually emits parse on every supported
    interpreter, so this is a backstop that should never fire on real history,
    not a filter doing day-to-day work.
    """
    if floor is None:
        return True
    raw = commit.get("committed_at", "")
    when = parse_floor(raw, strict=False)
    if when is None:
        raise RuntimeError(
            f"commit {commit.get('sha', '?')} has a committer date this parser "
            f"cannot read ({raw!r}), so its position against the activation "
            "floor is unknown and excluding it would be a silent false zero."
        )
    return when >= floor


def read_commits(rev: str, max_count: int, cwd: Path, since: str = "") -> tuple:
    """(commits newest-first, truncated).

    `truncated` says the CAP stopped the walk while commits inside the floor
    were still unread. It has to be reported because a capped scan that finds
    nothing describes its window, not the range: one unaccounted commit followed
    by max_count accounted ones read as clean, and the ledger — whose whole job
    is a true count — never learned (PR #66 round 3).

    Asking git for one MORE than the cap is what makes that answer exact instead
    of "we happened to fill the window". The extra record is the proof something
    was left unread, and its committer date says whether it was even in range.
    """
    fmt = FIELD_SEP_FMT.join(["%H", "%aI", "%cI", "%B"]) + RECORD_SEP_FMT
    # The floor is applied in Python, NOT via `git log --since`. Git's approxidate
    # parser silently IGNORES a value it cannot handle and returns the whole range
    # (`--since=2999-01-01` returned every commit), so a bad floor would quietly
    # disable the filter — the exact silent-no-op shape this ledger exists to stop.
    floor = parse_floor(since) if since else None
    code, out = git(
        ["log", f"--max-count={max_count + 1}", f"--format={fmt}", rev], cwd,
    )
    if code != 0:
        # NEVER ([], False). That shape is indistinguishable from "the walk read
        # the whole range and found nothing", and it defeats both blindness
        # signals at once: `truncated` is derived from the records git returned
        # (none), and `fetched` describes the fetch, which succeeded. The sweep
        # would print scanned 0 with status ok over history it never read — the
        # silent false zero this whole ledger exists to stop (PR #66 round 10).
        # main() maps RuntimeError to exit 1, and the daily detector already
        # treats a non-zero sweeper as blind, so both ends of the handshake hold.
        raise RuntimeError(
            f"the history walk failed: git log exited {code} on {rev!r}. "
            "The scan read nothing, so its count would be a false zero."
        )
    raw = []
    # git appends the separator after the LAST record too, and then its own
    # newline, so drop the trailing newlines first and then EXACTLY ONE
    # separator. One, not `rstrip(RECORD_SEP)`, because a commit message is
    # allowed to end with that byte itself and must keep it.
    body_out = out.rstrip("\n")
    if body_out.endswith(RECORD_SEP):
        body_out = body_out[:-1]
    for record in RECORD_BOUNDARY.split(body_out):
        record = record.strip("\n")
        if not record.strip():
            continue
        parts = record.split(FIELD_SEP)
        if len(parts) < 4 or not SHA_RE.match(parts[0].strip()):
            # NOT `continue`. A record the anchored split produced always starts
            # with a sha and carries four fields, so reaching here means the
            # parse desynced and the commits in this record were never
            # classified. Skipping them is a count that silently omits history
            # the walk DID read -- the same false-zero shape as the round-10
            # finding, one layer in. Blind is the recoverable direction.
            raise RuntimeError(
                "the history walk returned a record this parser cannot read "
                f"({len(parts)} field(s)); its commits were never classified, "
                "so the count would silently omit them."
            )
        sha, authored_at = parts[0].strip(), parts[1].strip()
        committed_at, message = parts[2].strip(), parts[3]
        body = message.strip()
        raw.append({
            "sha": sha,
            "authored_at": authored_at,
            "committed_at": committed_at,
            "message": body,
            "subject": body.splitlines()[0].strip() if body else "",
        })

    beyond = raw[max_count:]
    truncated = bool(beyond) and within_floor(beyond[0], floor)
    commits = [c for c in raw[:max_count] if within_floor(c, floor)]
    return commits, truncated


def scan_commits(rev: str, max_count: int, cwd: Path, since: str = "",
                 grow: bool = True) -> tuple:
    """(commits, truncated, window) — the window covers the range, not a constant.

    The floor is pinned at gate activation and never advances, so the number of
    in-range commits only grows. Against a FIXED cap that is a clock rather than a
    guard: the day in-range volume passes the cap, `truncated` is true on every
    run forever, the daily detector raises, and the operator is paged with
    BLIND SPOT every morning on a repo where nothing is wrong (PR #66 round 5 —
    245 of 500 at the time, roughly ten days out).

    So `truncated` has to keep meaning "something really went unread". An unpinned
    window doubles until it covers the range. The cap survives as a bound on WORK,
    not on correctness: growth stops at MAX_AUTO_COUNT and reports truncation
    honestly if the range is genuinely larger than that.

    An explicit `--max-count` sets `grow=False`. That is a hard bound the operator
    asked for, and silently exceeding it would make the flag a lie.
    """
    window = max_count
    commits, truncated = read_commits(rev, window, cwd, since)
    while grow and truncated and window < MAX_AUTO_COUNT:
        window = min(window * 2, MAX_AUTO_COUNT)
        commits, truncated = read_commits(rev, window, cwd, since)
    return commits, truncated, window


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


def sweep(rev: str, max_count: int, root: Path, dry: bool, since=None,
          fetch: bool = True, grow: bool = True) -> dict:
    """`since=None` means derive the floor from `rev`; `""` means no floor."""
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
        return {"rev": rev, "since": since or "", "fetched": fetched,
                "locked": False, "scanned": 0, "unaccounted": 0, "recorded": 0,
                "commits": [], "truncated": False, "window": max_count,
                "status": "rev-not-found"}

    # AFTER the fetch and AFTER the rev check, both deliberately: the floor is
    # read off the ref actually about to be scanned, in the state it is about to
    # be scanned in, and an unresolvable rev stays the quiet no-op it was.
    if since is None:
        since = gate_live_since(rev, root)
        if not since:
            raise RuntimeError(
                f"cannot derive the gate-activation floor: no commit on {rev} "
                f"adds {GATE_PATH.name}. Scanning unfloored would record every "
                "pre-gate commit as a bypass, permanently. Re-run with "
                "--all-history to count the whole window on purpose, or "
                "--since <ISO-8601> to set the floor yourself.")

    commits, truncated, window = scan_commits(rev, max_count, root, since, grow)

    # The read and the append are ONE critical section: the dedup asks "is this
    # sha already in the file", so a concurrent sweep landing between them
    # double-records. Everything above is a git read and holds no lock.
    with ledger_lock(path) as locked:
        known = recorded_shas(path)

        fresh = []
        seen = []
        for commit in commits:
            if is_accounted(commit["message"], gate):
                continue
            seen.append(commit)
            if commit["sha"] in known:
                continue
            fresh.append(commit)
        unaccounted = len(seen)

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        entries = [{
            "at": now,
            "reason": SWEEP_REASON,
            "subject": c["subject"][:200],
            "commit": c["sha"],
            "authored_at": c["authored_at"],
            # Recorded alongside the author date because they diverge on a replay,
            # and the committer date is the one the floor actually compared.
            "committed_at": c["committed_at"],
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
        # The cap cut the walk short with commits still in range. Everything
        # below this line is true OF THE WINDOW; it is not a statement about the
        # range, and a consumer that treats it as one is reporting a false zero.
        "truncated": truncated,
        # How far the walk actually had to go. Reported so "not truncated" is a
        # claim with a size attached rather than an unfalsifiable constant.
        "window": window,
        "unaccounted": unaccounted,
        "recorded": 0 if (dry or not written) else len(entries),
        # What this run newly ledgered. EPHEMERAL by nature: the ledger dedupes on
        # sha forever, so the same commit appears here exactly once in the life of
        # the repo, on whichever run happened to write the row.
        "commits": [c["sha"] for c in reversed(fresh)],
        # Every unaccounted sha in range, ledgered or not. A property of history,
        # so it is identical on every run over the same range — which is what lets
        # a consumer recover from dying mid-run. A consumer keyed on `commits`
        # cannot: the run that saw the sha as new was the one that died, and no
        # later run will ever call it new again (PR #66 round 7).
        "unaccounted_commits": [c["sha"] for c in reversed(seen)],
        "status": "dry" if dry else ("ok" if written else "ledger-write-failed"),
    }


def main(argv: list) -> int:
    parser = argparse.ArgumentParser(
        description="Record commits that reached origin without a Linear issue ref.")
    parser.add_argument("--rev", help="ref to sweep (default: tracked upstream)")
    parser.add_argument("--max-count", type=int, default=None,
                        help="hard cap on how many commits to scan. Unset, the "
                             f"window starts at {DEFAULT_MAX_COUNT} and grows "
                             "until it covers the range.")
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
        since = None  # sweep() derives it from rev, or refuses

    grow = args.max_count is None
    max_count = DEFAULT_MAX_COUNT if grow else args.max_count

    # A window that cannot hold a commit is not a small scan, it is no scan.
    # `--max-count=-1` asked git for `--max-count=0`, got nothing back, found
    # nothing beyond the cap either, and reported {"scanned": 0, "truncated":
    # false, "status": "ok"} — a clean bill of health from having looked at
    # nothing. `truncated` is the signal for a window that stopped early and it
    # structurally cannot fire when the window is empty, so the refusal has to
    # be here, before anything reports a status at all.
    if max_count < 1:
        print(f"linear-bypass-sweep: --max-count must be at least 1, got "
              f"{max_count}. A window of {max_count} scans no commits and would "
              f"report a clean result over nothing.", file=sys.stderr)
        return 1

    try:
        result = sweep(rev, max_count, root, args.dry, since, args.fetch, grow)
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
    if result["truncated"]:
        print(f"linear-bypass-sweep: WARNING the scan stopped at "
              f"{result['window']} commits with more still in range; this count "
              f"covers the window, not the range. Re-run with a larger "
              f"--max-count.", file=sys.stderr)
    print(f"linear-bypass-sweep: {rev} — scanned {result['scanned']}, "
          f"unaccounted {result['unaccounted']}, newly recorded {result['recorded']} "
          f"(fetch: {result['fetched']})")
    for sha in result["commits"]:
        print(f"  {sha[:9]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
