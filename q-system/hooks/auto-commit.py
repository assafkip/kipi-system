#!/usr/bin/env python3
"""Auto-commit hook - groups changed files by area and creates organized commits.

Runs on Stop (async). Creates one commit per area with conventional commit messages.
Never pushes. Skips if no uncommitted changes.
"""
import calendar
import hashlib
import json
import subprocess
import sys
import os
import time
from collections import defaultdict

PROJ_DIR = os.environ.get("CLAUDE_PROJECT_DIR", ".")

# Map file paths to commit areas
AREA_MAP = [
    ("q-system/canonical/",           "content",  "update canonical files"),
    ("q-system/my-project/",          "content",  "update project state"),
    ("q-system/marketing/",           "content",  "update marketing content"),
    ("q-system/memory/",              "chore",    "update session memory"),
    # Append-only ledgers the system writes for itself (spillover, gates,
    # findings). ASK-605: these were unclassified, so cole-gtm's dirty
    # .prd-os/spillover.jsonl blocked its sync with no path out -- the updater
    # would not take it and no rule said who should.
    (".prd-os/",                      "chore",    "update prd-os ledgers"),
    # skip - gitignored. That claim is now TESTED against `git check-ignore`
    # rather than trusted: it used to be FALSE for any extension the .gitignore
    # did not list (*.md was not listed), and such a file is never committed,
    # never ignored and never even reported, so it blocks the fleet sync
    # invisibly. cole-gtm sat stuck on two of them.
    ("q-system/output/",              None,       None),
    ("q-system/hooks/",               "chore",    "update hooks"),
    ("q-system/.q-system/agent-pipeline/", "feat", "update agent pipeline"),
    ("q-system/.q-system/",           "chore",    "update system infrastructure"),
    ("plugins/",                      "feat",     "update plugins"),
    (".claude/rules/",                "chore",    "update rules"),
    (".claude/agents/",               "chore",    "update agent definitions"),
    (".claude/output-styles/",        "chore",    "update output styles"),
    (".claude/settings",              "chore",    "update settings"),
    # sp-097d2e23. The updater writes a managed never-commit block into every
    # instance's root .gitignore. Every instance HAS one already (70-76 lines)
    # and it is TRACKED, so the writer MODIFIES a tracked file -- measured on a
    # real copy of an instance, where it lands as ` M .gitignore`.
    #
    # (An earlier version of this comment said instances have no root .gitignore
    # at all. That was a misread of a malformed `grep -c` check, corrected the
    # same day by copying a real instance and looking. The fix below was right;
    # the reason written beside it was not, which is worse than no reason --
    # a wrong scar comment is read as coverage, so nobody goes looking.)
    #
    # This classifier answered `unclassified` for .gitignore, which means
    # REPORTED and never committed (ASK-498). So every one of the 22 instances
    # would carry a permanently modified, never-committable tracked file and
    # print the same unclassifiable path on every run, forever.
    #
    # It does NOT block the sync: the dirty-tree guard is scoped to
    # `$prefix/ .claude/ plugins/` (kipi-update.sh ~L2012) and root .gitignore
    # is in none of them. Checked rather than assumed, because the first guess
    # was that this self-blocked the whole fleet.
    #
    # `chore`, so the fleet sync may take it: system exhaust, not authored
    # content. Config, never source, so the executable-source refusal above
    # does not reach it.
    (".gitignore",                    "chore",    "update gitignore"),
    ("sites/",                        "feat",     "update site pages"),
    ("memory/",                       "chore",    "update auto-memory"),
]

# NO FALLBACK. An unclassified path is REPORTED, never committed (2026-08-07, ASK-498).
#
# This used to be `("chore", "update project files")`, so every path not named in
# AREA_MAP above -- an instance's own source tree, its tests, its config -- was swept
# into one unattended commit with a generic subject and no issue id.
#
# Measured cost in a single session on the consulting instance: three sweeps
# (d96e621, 7a252f4, f0a3183) carried real feature work onto `main` under
# "chore: update project files". Two of them also RACED the agent writing the files:
# a `git add` of new files reported success and staged nothing, because the hook had
# already committed them a moment earlier, and the agent's own commit then silently
# contained only half its change.
#
# The hook's purpose is a safety net for GENERATED STATE -- canonical files, session
# memory, marketing content -- that nobody would otherwise commit. Source code is the
# opposite case: it is exactly what an agent commits deliberately, with a real message
# and a Linear id. Sweeping it is not a safety net, it is a second writer to the same
# branch.
#
# Uncommitted is not lost: the files are on disk. What is removed here is an
# unattended commit nobody asked for. `report_skipped` makes the remainder loud
# rather than silent, so the safety net becomes a NOTICE for source code and stays a
# COMMIT for the generated state it was built for.


def run(cmd, **kwargs):
    return subprocess.run(
        cmd, capture_output=True, text=True, cwd=PROJ_DIR, **kwargs
    )


def get_changed_files():
    """Get all uncommitted files (staged + unstaged + untracked)."""
    # Staged and unstaged
    r = run(["git", "diff", "--name-only", "HEAD"])
    files = set(r.stdout.strip().splitlines()) if r.stdout.strip() else set()

    # Untracked
    r = run(["git", "ls-files", "--others", "--exclude-standard"])
    if r.stdout.strip():
        files.update(r.stdout.strip().splitlines())

    # THE `--cached` READ IS GONE AS REDUNDANCY, FOR THE SHAPE THAT MOTIVATED IT.
    #
    # MEASURED 2026-09-06 before removing it, because the obvious story was wrong.
    # It was believed to be the line that swept another session's staged work into
    # this hook's commit (sp-78728ff1). It is not. `git diff --name-only HEAD` on the
    # line above ALREADY reports a staged-but-uncommitted new file: in a scratch repo,
    # `git add b` on a new file makes `git diff --name-only HEAD` print `b`. That is
    # sp-78728ff1's shape, so deleting this line fixes nothing.
    #
    # IT IS NOT UNIVERSALLY REDUNDANT, and the first draft of this comment claimed it
    # was ("added nothing any other probe missed"). Re-measured 2026-09-07 across six
    # staging shapes: `--cached` names two paths that `diff --name-only HEAD` and
    # `ls-files --others` both miss -- a file staged and then DELETED from the
    # worktree, and a file staged and then edited back to its HEAD content.
    #
    # Removing it is still right, and that reason is measured too, not reasoned:
    # commit_group runs a PATHSPEC commit, and `git commit -m x -- <path>` in BOTH of
    # those shapes exits 1 with "nothing to commit" and writes no commit. (The first
    # guess written here was that the delete shape would commit a DELETION of another
    # writer's staged file. It does not; the staged entry survives untouched.) So the
    # two extra paths only ever bought a spurious `skipped:` line. What this removal
    # gets is a narrower changed-file set, not a bug fix. Do not re-add it expecting
    # one, and do not cite it as coverage for sp-78728ff1.
    #
    # sp-78728ff1 IS THEREFORE STILL OPEN and needs a different fix than deleting a
    # line. Git cannot tell WHO staged a path, so the only honest lever is to treat
    # "staged" as "a writer has claimed this" and skip it, reporting it as skipped.
    # That trades away part of the safety net (work staged at session death would no
    # longer be committed for you) and is a deliberate design call, not a cleanup.

    # Filter out empty strings and gitignored patterns
    return {f for f in files if f and not f.startswith("q-system/output/")}


# AREA_MAP's prefixes all start `q-system/`, which is the SKELETON. In an INSTANCE the
# real content lives one segment over -- q-consult/canonical, q-consult/my-project and
# so on -- so none of it matched any row. Measured on the consulting instance: 1047 of
# 2099 tracked files unclassified, including my-project (the system of record) and
# marketing. Removing the fallback without this would have disabled the safety net for
# exactly the generated state it exists to protect (adversarial review finding-2).
#
# Matched against the path with its FIRST segment stripped, so one row covers every
# instance without reading a registry. Source trees (pipeline/, email-watch/) are
# deliberately absent: code is what an agent commits deliberately, and sweeping it is
# the defect this whole change removes.
INSTANCE_AREAS = [
    ("canonical/",   "content", "update canonical files"),
    ("my-project/",  "content", "update project state"),
    ("marketing/",   "content", "update marketing content"),
    ("memory/",      "chore",   "update session memory"),
    ("output/",      None,      None),   # generated churn; never committed
]


SKIP_DECLARED = "declared-skip"       # matched AREA_MAP with commit_type None
SKIP_UNCLASSIFIED = "unclassified"    # matched nothing: never auto-committed


# Checked BEFORE any prefix match. A prefix is a blunt instrument: `.prd-os/`
# is mostly machine-written ledgers, but it also holds authored issue specs, and
# every resolve drops a `.lock` beside the ledger it is writing.
NEVER_AUTO_COMMIT = (
    ".lock",                 # sp-a21cb27c: ephemeral, and sweeping it is a race
)
NEVER_AUTO_COMMIT_DIRS = (
    ".prd-os/issues/",       # issue SPECS are authored, not exhaust
    ".prd-os/findings/",     # review findings are authored
)

# Executable source, in ANY area. See the note in `classify`: the AREA_MAP rows
# `plugins/` and `q-system/.q-system/` are named for directories that happen to
# contain Python, so code was still being swept under a generic subject with no
# Linear id after ASK-498 supposedly ended that. Extension is the durable axis --
# a new code directory appears far more often than a new language does.
SOURCE_EXTENSIONS = (
    ".py", ".sh", ".bash", ".zsh", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
)


def classify(filepath):
    """(type, message) for an auto-committable file, else a SKIP_* reason string.

    Returns a STRING rather than None for both skip cases so the caller can tell
    "deliberately ignored" (q-system/output, gitignored) from "nobody classified
    this" (an instance's source tree). The second one is the whole point: it is
    reported to the operator instead of being swept.
    """
    if filepath.endswith(NEVER_AUTO_COMMIT) or \
            filepath.startswith(NEVER_AUTO_COMMIT_DIRS):
        return SKIP_UNCLASSIFIED
    # EXECUTABLE SOURCE IS NEVER SWEPT, whatever area it lands in (2026-08-13).
    #
    # ASK-498 removed the generic fallback and this file's own comment says source
    # trees are "deliberately absent: code is what an agent commits deliberately".
    # Two AREA_MAP rows still contradicted that, because they are named for
    # DIRECTORIES that happen to contain code: `plugins/` (the kipi-core plugin,
    # which is a Python package) and `q-system/.q-system/` (which holds scripts/).
    #
    # Measured 2026-08-13 on this instance, in one session: `test_length_axis.py`
    # was committed as "feat: update plugins" and `voice-dna-loader.py` as "chore:
    # update system infrastructure", both while the agent was still working on them
    # and before it could write a real message with a Linear id. That is the same
    # race and the same generic-subject outcome ASK-498 was opened to end; the fix
    # was scoped by directory when the real axis is WHAT THE FILE IS.
    #
    # Extension, not directory, because a new code directory is added far more often
    # than a new language is.
    if filepath.endswith(SOURCE_EXTENSIONS):
        return SKIP_UNCLASSIFIED
    for prefix, commit_type, msg in AREA_MAP:
        if filepath.startswith(prefix):
            if commit_type is None:
                return SKIP_DECLARED
            return (commit_type, msg)
    if "/" in filepath:
        tail = filepath.split("/", 1)[1]
        for prefix, commit_type, msg in INSTANCE_AREAS:
            if tail.startswith(prefix):
                if commit_type is None:
                    return SKIP_DECLARED
                return (commit_type, msg)
    return SKIP_UNCLASSIFIED


# Commit types that are the SYSTEM's own exhaust rather than the founder's
# writing. "chore" is session memory and system infrastructure; "content" and
# "feat" are canonical, my-project, marketing and plugins, all founder-authored.
SYSTEM_STATE_TYPES = frozenset(("chore",))


def system_state_paths(paths):
    """Subset of paths safe for the FLEET SYNC to commit unattended.

    why (ASK-605): kipi-update.sh carried its own three-entry
    SYSTEM_OWNED_PATHS list meaning exactly what classify() already means, and
    the two disagreed. `q-system/memory/open-loops.json` is written by a
    background heartbeat, is `chore` here, was absent there -- and on
    2026-08-10 it alone left 4 of 7 instances permanently unsyncable. One
    concept, one list, and this is the list.

    Deliberately NARROWER than classify(). The Stop hook may commit content in
    an active session where the founder is present; a fleet-wide sweep across
    every instance at once is a different blast radius, and half-finished
    canonical edits are not the updater's to take.
    """
    return [p for p in paths
            if isinstance(classify(p), tuple)
            and classify(p)[0] in SYSTEM_STATE_TYPES]


def group_files(files):
    """(groups, unclassified). Only classified files are ever committed."""
    groups = defaultdict(list)
    unclassified = []
    for f in sorted(files):
        result = classify(f)
        if result == SKIP_UNCLASSIFIED:
            unclassified.append(f)
            continue
        if result == SKIP_DECLARED:
            continue
        groups[result].append(f)
    return groups, unclassified


def report_skipped(unclassified):
    """Say out loud what was left uncommitted, and why.

    TRANSCRIPT ONLY. This hook does NOT alert. Founder-directed 2026-08-10 after
    reading #general: 51 of 100 messages in one 4.5-hour window were this
    notification, and the four security reverts and one dead job posted into the
    same window were unreadable underneath them.

    An earlier round (ASK-603) tried to fix that with a throttle -- speak on a
    CHANGED file set, otherwise stay quiet for 12h. It did not work, and the
    reason is structural rather than a tuning miss: during active work the file
    set changes on nearly every turn, so the digest changes on nearly every turn,
    so the throttle passes. The condition being reported (files are uncommitted
    right now) is TRUE almost continuously while someone is working, and a
    continuously-true condition is not an event. No throttle value fixes that;
    only not alerting does.

    The information is not lost. It prints below, which is where the operator or
    the next session reads it. Anything here that genuinely needs a human is
    caught by the commit gates, not by a Stop-hook ping.
    """
    if not unclassified:
        return
    print(f"auto-commit: {len(unclassified)} file(s) NOT committed "
          f"(unclassified path, commit these yourself with a real message + issue id):")
    for f in unclassified[:20]:
        print(f"  - {f}")
    if len(unclassified) > 20:
        print(f"  - ... and {len(unclassified) - 20} more")


def staged_linecounts(files):
    """{path: (adds, dels) | None} for the STAGED diff, plus the totals.

    `None` means git reported no line counts for that path (a binary file).
    A path absent from the mapping means the diff could not be attributed, and
    the caller degrades to a bare path rather than guessing.

    THE SCAR (2026-08-16, commit 80b82f84). An unattended Stop-hook commit read
    `chore: update system infrastructure` over the body line
    `- q-system/.q-system/capability-manifest.json`. That message was not
    missing the path -- the path was right there. What it could not say is that
    the change was FIVE DELETED LINES and nothing else, so a silent revert of a
    real capability-manifest entry looked byte-for-byte like an ordinary
    update. It cost a second session a manual diff to find. Direction and
    magnitude are the half a path cannot carry, so they are read from git here
    rather than described by the hook.

    Read AFTER staging and scoped to the same pathspec the commit uses, so the
    counts describe exactly what this commit will contain -- not the worktree,
    which a concurrent session may have moved on.
    """
    per_path = {}
    adds_total = dels_total = 0
    r = run(["git", "diff", "--cached", "--numstat", "-z", "--"] + files)
    if r.returncode != 0:
        return per_path, 0, 0
    # `-z` and not the plain form: git QUOTES a path containing a space, a
    # newline or a non-ASCII byte in the default output, which would not match
    # the pathspec strings the caller holds. Verified against git directly:
    # a non-rename record is `adds\tdels\tpath\0`.
    for record in r.stdout.split("\0"):
        if not record:
            continue
        parts = record.split("\t")
        if len(parts) != 3:
            # A RENAME emits `adds\tdels\0old\0new\0`, which arrives here as a
            # short record trailed by bare paths. Annotate nothing rather than
            # attribute one file's counts to another file's name.
            continue
        raw_adds, raw_dels, path = parts
        if raw_adds == "-" or raw_dels == "-":
            per_path[path] = None  # binary; git reports no line counts
            continue
        try:
            adds, dels = int(raw_adds), int(raw_dels)
        except ValueError:
            continue
        per_path[path] = (adds, dels)
        adds_total += adds
        dels_total += dels
    return per_path, adds_total, dels_total


def describe_change(path, per_path):
    """One body line for one file: the path, and what happened to it."""
    if path not in per_path:
        return f"- {path}"
    counts = per_path[path]
    if counts is None:
        return f"- {path} (binary)"
    adds, dels = counts
    line = f"- {path} (+{adds}/-{dels})"
    if dels and not adds:
        # The shape that hid commit 80b82f84. A pure deletion is the one change
        # an unattended commit can make that nobody asked for, so it is called
        # out in words -- greppable in `git log`, not inferable from a number a
        # reader has to notice is zero.
        line += "  <-- DELETIONS ONLY"
    return line


def commit_group(commit_type, message, files):
    """Stage files and create a commit."""
    # Stage
    run(["git", "add", "--"] + files)

    # Build commit message
    per_path, adds_total, dels_total = staged_linecounts(files)
    # The stat rides in the SUBJECT, not only the body. The 80b82f84 review
    # happened in `git log --oneline`, where a body is invisible; a subject that
    # says "update system infrastructure" for a five-line deletion is not merely
    # uninformative, it is wrong in the one direction that matters.
    header = (f"{commit_type}: {message} "
              f"({len(files)} file(s), +{adds_total}/-{dels_total})")
    body_lines = [describe_change(f, per_path) for f in files[:20]]
    if len(files) > 20:
        body_lines.append(f"- ... and {len(files) - 20} more files")

    # The linear-first commit-msg gate refuses any commit with no issue id.
    # This hook fires unattended on Stop and has no way to know which issue the
    # session belonged to, so it declares itself as a bypass rather than being
    # silently blocked -- which would kill the safety net that makes work
    # survive a context loss or a parallel-session branch switch.
    # Consequence on purpose: every auto-commit shows up in the bypass ledger,
    # so "how much work never reached Linear" is a number, not a guess.
    body_lines.append("")
    body_lines.append("[no-issue: auto-commit safety net, unattended Stop hook]")

    full_msg = header + "\n\n" + "\n".join(body_lines)

    # PATHSPEC, not a bare commit (2026-08-07, adversarial review finding-1).
    # `git commit -m` with no pathspec commits the ENTIRE INDEX, so anything an agent
    # had staged and not yet committed was swept in anyway -- while report_skipped
    # printed that it had NOT been committed. A false report is worse than the silence
    # it replaced: it tells the next session the file is still theirs to commit.
    # Reproduced before the fix: the hook printed "NOT committed
    # q-consult/pipeline/repo_links.py" and the commit contained that exact file.
    # kipi-update.sh already fixed this same defect once (its PR #98 note says so);
    # it came back through a different door.
    r = run(["git", "commit", "-m", full_msg, "--"] + files)
    if r.returncode == 0:
        print(f"  committed: {header} ({len(files)} files)")
    else:
        # Could be nothing to commit (already staged), not fatal
        print(f"  skipped: {header} - {r.stderr.strip()[:80]}")


# One instance apply runs minutes, never hours; a marker older than this is a
# crashed run whatever its pid says (pids get recycled).
RUN_MARKER_MAX_AGE_S = int(os.environ.get("KIPI_UPDATE_RUN_MARKER_MAX_AGE_S", "7200"))


def fleet_update_in_progress():
    """The fleet updater's run marker, or None when no live run owns this checkout.

    kipi-update.sh writes <git-common-dir>/kipi-update.run ("<pid> <start>") for
    the duration of one instance apply. This hook fires at every turn end of
    every session sitting in the checkout, so on 2026-09-06 it committed the
    updater's half-delivered rules, settings and plugins under its own generic
    messages while the sync was still running, and its pre-commit held
    index.lock for the whole verify (sp-9306036e). A live marker means the
    updater owns the index right now: commit nothing. A marker whose pid is
    dead is a crashed run's leftover: remove it and proceed, so a crash cannot
    silence this safety net forever. The common dir, not the worktree git dir,
    so a linked worktree of the same checkout reads the same marker.
    """
    r = run(["git", "rev-parse", "--git-common-dir"])
    if r.returncode != 0:
        return None
    # `git rev-parse --git-common-dir` answers RELATIVE to the cwd it ran in,
    # and run() executes in PROJ_DIR (CLAUDE_PROJECT_DIR), not in this
    # process's cwd. Resolving against os.getcwd() pointed at the wrong repo
    # whenever the two differed, and a missing marker there reads as "no run
    # in progress": the guard failed open (PR #314 round 2).
    common = r.stdout.strip()
    if not os.path.isabs(common):
        common = os.path.abspath(os.path.join(PROJ_DIR, common))
    marker = os.path.join(common, "kipi-update.run")
    if not os.path.exists(marker):
        return None
    # Two facts have to agree before the marker counts as live: the pid is
    # alive AND the start stamp is younger than RUN_MARKER_MAX_AGE_S. Pid
    # liveness alone is not enough: a marker that survived SIGKILL or a reboot
    # can point at a recycled pid that is some unrelated process, and this
    # hook would then commit nothing on that checkout forever (PR #314
    # review, round 1). A fleet apply of one instance runs minutes, never
    # hours, so an old stamp is a crashed run whatever the pid says.
    try:
        with open(marker, encoding="utf-8") as fh:
            fields = fh.read().split()
        pid = int(fields[0])
        started = time.strptime(fields[1], "%Y-%m-%dT%H:%M:%SZ")
        age_s = time.time() - calendar.timegm(started)
        if age_s > RUN_MARKER_MAX_AGE_S:
            raise ProcessLookupError("marker older than the run bound")
        os.kill(pid, 0)
    except (ValueError, IndexError, ProcessLookupError, FileNotFoundError, OverflowError):
        try:
            os.remove(marker)
        except OSError:
            pass
        return None
    except PermissionError:
        # Alive, owned by another user: still a live writer.
        return f"pid {pid}"
    return f"pid {pid}"


def another_commit_in_flight():
    """A reason string if git's own locks say someone is mid-commit, else None.

    THE THIRD WRITER (sp-4bff1b91, sp-d0ce1966, sp-e06433b8, measured 2026-09-06).
    `fleet_update_in_progress` above coordinates with the ONE writer that agreed to
    leave a marker. This hook is the writer nobody can negotiate with: it fires at
    every turn end in every session on the checkout, and it took no lock at all. Two
    sessions can hold a ref window perfectly and still lose a commit to it.

    Measured that night in one session: three of five git operations died on
    `Unable to create '.git/index.lock'`, and EVERY ONE EXITED 0. A commit that
    reports success while landing nothing is worse than one that refuses.

    WE READ THE LOCKS, WE DO NOT REMOVE THEM. Deleting a lock that a live 8-minute
    pre-commit still owns corrupts that commit's index. kipi-update.sh still sweeps
    HEAD.lock/index.lock/AUTO_MERGE.lock with an unconditional force-delete at the
    top of its instance loop, no pid, mtime or age test at all (~L1915, sp-50119dec;
    an earlier draft of this docstring cited L1714, which is unrelated env-var code).
    Read that citation narrowly: the SAME file is also the one that already solved
    this properly, at ~L1313-1400, where every index write it makes waits for the
    lock to clear, bounded at 600s, with bounded retry and a loud error
    (sp-523c1a25). A Stop hook cannot spend 600s at turn end, so it takes the other
    half of that answer: refuse now, and the next turn end picks the work up.

    NO AGE BOUND ON PURPOSE, unlike the run marker. A commit here holds index.lock
    for the length of its pre-commit, measured at 447-497 seconds here and
    independently at 445s in kipi-update.sh's own note from the same night. Review
    round 2 called that figure false, having measured ~12ms and no lock at all
    during a pre-commit. RE-MEASURED 2026-09-07 over three command shapes against
    a 5s pre-commit hook, and the figure stands: `git commit -m x -- <path>`,
    which is exactly what commit_group runs, holds index.lock (plus a next-index
    lock) for the WHOLE hook; `git commit -a` does too; only `git add` followed by
    a bare `git commit` holds nothing, and that is the one shape this hook never
    uses. Measure the pathspec form, or the number will look invented again. So a
    bound low enough to be useful against a crashed lock would fire constantly
    against healthy ones. A truly orphaned lock is rare, visible, and a human's
    call: "no process holds it AND every live hook's cwd is a worktree" is the test
    that settled it by hand, and it needs `lsof`, which a Stop hook must not spend.

    AND THAT BOUND COSTS LESS THAN THE FIRST DRAFT OF THIS DOCSTRING CHARGED IT.
    Measured 2026-09-07: git itself exits 128 on a held index.lock, and commit_group
    turns ANY non-zero into a `skipped:` line while this hook exits 0. So an orphaned
    lock ALREADY stopped this hook from committing, silently, before this guard
    existed. It replaces a failure found after a 450s pre-commit with a refusal
    that costs nothing. An earlier draft went further and said the guard adds NO
    new silent-outage mode; review round 2 proved that false, and it is true now
    only because of the fix it forced -- the refusal prints on stdout, because the
    fleet wiring discards stderr. See the comment in main(). The genuinely new
    behaviour is the opposite one, and it is frequent rather than rare: a peer
    session's `git status` holds index.lock for a fraction of a second, so some turn
    ends now skip a commit they would have won. Work stays on disk either way.

    --git-dir, NOT --git-common-dir, AND THE TWO GUARDS HERE DISAGREE ON PURPOSE.
    fleet_update_in_progress above reads the COMMON dir because a run marker is a
    claim on the whole checkout. A lock is not: index.lock and HEAD.lock are
    per-worktree. Measured 2026-09-07 -- holding <main>/.git/index.lock does not
    block a `git add` run from a linked worktree, and holding that worktree's own
    lock does (rc=128). So this spelling names exactly the lock that can stop THIS
    checkout. Harmonizing the two would silence the safety net in every linked
    worktree for the eight minutes the main checkout spends inside a pre-commit,
    over a lock none of them would ever contend. Pinned by
    test_a_worktree_does_not_refuse_on_the_main_checkouts_lock, the only test in the
    file that can tell the two spellings apart.
    """
    r = run(["git", "rev-parse", "--git-dir"])
    if r.returncode != 0:
        return None
    git_dir = r.stdout.strip()
    if not os.path.isabs(git_dir):
        git_dir = os.path.abspath(os.path.join(PROJ_DIR, git_dir))
    for name in ("index.lock", "HEAD.lock"):
        path = os.path.join(git_dir, name)
        if os.path.exists(path):
            try:
                age = int(time.time() - os.path.getmtime(path))
                return f"{name} held {age}s"
            except OSError:
                return name
    return None


def main():
    # Check we're in a git repo
    r = run(["git", "rev-parse", "--is-inside-work-tree"])
    if r.returncode != 0:
        return

    # STDOUT, NOT STDERR, AND THAT IS THE WHOLE POINT (review round 2, major).
    # settings-template.json wires this hook as `... auto-commit.py 2>/dev/null
    # || true` at line 395, the single wiring of it, and that is the copy the fleet
    # updater installs on every instance. So stderr is DISCARDED on 22+ checkouts.
    # (An earlier draft of this comment said "lines 380 and 406". Those came from
    # a checkout with local edits to that file and point at unrelated hooks. A
    # scar comment with a wrong pointer reads as coverage, which is the exact
    # defect this PR was reviewed for; re-derive line numbers from the tree you
    # are actually shipping.)
    # The behaviour these guards replaced reported a lock collision on STDOUT,
    # as commit_group's `skipped:` line naming the file and git's own error, and
    # that line survived the redirect. Returning early with a stderr-only
    # message made the safety net go quiet with literally zero output: an
    # orphaned index.lock (no age bound, by design) would switch this hook off
    # on that checkout forever and print nothing anywhere. The message is the
    # only thing that tells a human to go look, so it has to reach the channel
    # that survives. Pinned by
    # test_a_refusal_reaches_the_channel_the_fleet_wiring_keeps.
    live_run = fleet_update_in_progress()
    if live_run is not None:
        print(f"auto-commit: fleet updater run in progress ({live_run}); "
              "committing nothing")
        return

    held = another_commit_in_flight()
    if held is not None:
        print(f"auto-commit: another commit is in flight ({held}); "
              "committing nothing. The next turn end picks this work up.")
        return

    files = get_changed_files()
    if not files:
        print("auto-commit: no changes")
        return

    groups, unclassified = group_files(files)
    if not groups:
        print("auto-commit: no committable changes")
        report_skipped(unclassified)
        return

    print(f"auto-commit: {len(files)} files in {len(groups)} groups")
    for (commit_type, message), group_files_list in groups.items():
        commit_group(commit_type, message, group_files_list)

    report_skipped(unclassified)
    print("auto-commit: done")


if __name__ == "__main__":
    # `--system-state`: read paths on stdin, print the subset the FLEET SYNC may
    # commit unattended. This is the shared-classifier chokepoint for ASK-605 --
    # kipi-update.sh shells this instead of keeping a second list that drifts.
    # Pure and side-effect free: it touches no git state and commits nothing.
    if "--system-state" in sys.argv:
        for path in system_state_paths(
                [ln.strip() for ln in sys.stdin if ln.strip()]):
            print(path)
        sys.exit(0)
    try:
        main()
    except Exception as e:
        # Never block session exit
        print(f"auto-commit error: {e}", file=sys.stderr)
        sys.exit(0)
