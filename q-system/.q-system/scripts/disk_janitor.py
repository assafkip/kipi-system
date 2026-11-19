#!/usr/bin/env python3
"""disk_janitor.py: delete regenerable junk on the Mac mini, on a schedule.

Pairs with the launchd job com.kipi.disk-janitor (daily 04:30, --apply). Runs
under /usr/bin/python3 (3.9), so no 3.10+ syntax here.

Founder-directed 2026-09-11, after the internal disk hit 1.3 GB free of 228 GB.
Measured that day: 8,776 leaked python mkdtemp dirs in the per-user temp folder
(16.7 GB, one burst on 2026-09-10), 173 PR review checkouts under
~/.config/kipi/review-trees (5.5 GB), agent worktrees under */.claude/worktrees
(4.1 GB), updater caches and installer leftovers. None of it was founder work,
and nothing swept it. "Create a process that ensures the junk gets auto cleaned
so I don't have to do this myself all the time."

Why a Python allowlist and not a shell script of recursive deletes: the
destructive-op hook exists because an agent once "fixed" a credential mismatch
by deleting a production volume (2026-05-17). A janitor with no gates is that
shape on a timer. Every rail below is there so an unattended run cannot become
that incident:

  ALLOWLIST   only the RULES below run; every target must sit directly under the
              rule's parent, which must resolve under $HOME, the per-user temp
              base or the Claude temp root (/private/tmp/claude-<uid>). Anything
              else is refused and logged, never deleted.
  AGE GATE    per rule, measured on the NEWEST mtime inside the tree, so a tree
              still being written to is young even if its top dir is old.
  GIT GATE    a checkout with a dirty `git status` is skipped; a checkout whose
              git call errors, or writes to stderr (a subdir it could not read), is
              skipped; so is a target it cannot read at all. Unknown is never clean.
  LIVE GATE   a target that holds the cwd OR any open file of a live process is
              skipped (one system-wide lsof census per run); rules can also
              require a zero-open-files check of their own.
  SYMLINKS    never followed; a symlinked entry is skipped.
  DRY DEFAULT --dry prints the plan and deletes nothing; only --apply deletes.
  LOG         one JSON line per action in ~/.config/kipi/disk-janitor.log.
  ALERT       free space still under FLOOR_GB after --apply, or any delete error,
              goes to slack-notify.sh (Sana's Linear triage, founder-notifications.md).
              Once per run, on state, never per item. Under HARD_FLOOR_GB it pages
              once per episode (state in disk-janitor-floor.json; re-armed when
              free space is back over HARD_REARM_GB).
  ONE WRITER  --apply and --floor-check hold an flock on disk-janitor.lock; a
              second run exits 0 and logs that it waited for nobody.

ASK-4228 (2026-11-09): the Data volume hit 100% (189 MiB free), a PR review died
on ENOSPC writing its transcript, and --dry said it could free 0.00 GB: every
target it was allowed to touch was too young for its age gate. The space sat in
classes that are safe at ANY age, so these rules carry their own gate instead
of an age gate:
  updater-caches          age 0; live gate only. The app downloads again.
  review-trees-finished   age 0; gh says the PR is MERGED or CLOSED (any other
                          answer, or no answer, is a skip), no live review lock,
                          plus the git and live gates.
  claude-mcp-logs         .jsonl files over 1 day under claude-cli-nodejs/*/mcp-logs-*.
  claude-session-scratch  /private/tmp/claude-<uid>/<project>/<session>/scratchpad
                          whose session has ended: not in ~/.claude/sessions under a
                          live pid, uuid in no process command line and no open
                          file, newest write over 6h. REPORT-ONLY until
                          "session_scratch_apply": true in disk-janitor.json.
  FLOOR TRIGGER           --floor-check (launchd com.kipi.disk-janitor-floor, every
                          5 min) runs --apply when free space is under FLOOR_GB, at
                          most once per FLOOR_COOLDOWN_S unless under HARD_FLOOR_GB.

ASK-4229 (2026-11-09): a killed proof script left a 5.4 GB tmp-mkdtemp dir that the
1-day gate protected while the disk sat at 190 MiB free. Rule tmp-mkdtemp now
carries floor_min_age_days = 2h, used only when trigger == "floor" (the same idle
rule as ~/.local/bin/disk-clean-tmp). The 04:30 --apply keeps 1 day; the live,
symlink and newest-mtime gates are unchanged.

Test env overrides (all optional): JANITOR_HOME, JANITOR_TMPBASE, JANITOR_NOW
(epoch seconds), JANITOR_LOG, JANITOR_LIVE (JSON list of paths; replaces the
lsof census), JANITOR_NO_OPENFILES=1 (skip the per-rule lsof +D check),
JANITOR_NO_NOTIFY=1, JANITOR_REPO (where slack-notify.sh lives),
JANITOR_CLAUDETMP (the Claude temp root), JANITOR_GH (the gh binary),
JANITOR_FREE_GB (the free-space reading), JANITOR_PROCS (JSON list of {start, exe},
or null for an unreadable process table), JANITOR_APPS (where installed apps live). Tests: test_disk_janitor_reclaim.py. JANITOR_NO_UV=1 skips `uv cache prune` (tests set it).
"""
import argparse
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from typing import Dict, List, Optional

DAY = 86400.0
FLOOR_GB = 20.0
# ASK-4228: 2 GB is where reviews started dying on ENOSPC (189 MiB free on
# 2026-11-09). Re-arm at 5 GB so free space hovering at the line pages once, not
# on every 5-minute check.
HARD_FLOOR_GB = 2.0
HARD_REARM_GB = 5.0
FLOOR_COOLDOWN_S = 3600.0
UUID_RE = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
# pr-review-agent.sh names a tree artifact_key(<owner>/<repo>, n): '/' -> '_'.
# A GitHub owner cannot contain '_', so the first '_' splits owner from repo.
REVIEW_TREE_RE = re.compile(r"^([A-Za-z0-9-]+)_([A-Za-z0-9._-]+)__pr-([0-9]+)$")


class Rule(object):
    """One class of junk. `parents` are glob patterns with {HOME} / {TMP} /
    {CLAUDETMP} tokens. `gate(ctx, path)` returns None to pass or a
    (count-tag, reason) pair to skip. `apply_switch` names a config key that must
    be JSON true before the rule deletes; while it is not, the rule reports."""

    def __init__(self, name, parents, kind="dir", match=r".*", min_age_days=7,
                 git_gate=False, open_files_gate=False, recursive=False, note="",
                 parent_match=None, gate=None, apply_switch=None, floor_min_age_days=None, wt_child=None, unlock=False,
                 shared_probe=None, ignored_dirty=False):
        self.name = name
        self.parents = parents
        self.kind = kind                    # "dir" or "file"
        self.match = re.compile(match)
        self.min_age_days = float(min_age_days)
        # ASK-4229: the age a target must reach when the FLOOR trigger runs. None
        # means the same as min_age_days. A killed run's orphan is fresh exactly
        # when the disk is dying, so a 1-day gate kept it for 24 h.
        self.floor_min_age_days = None if floor_min_age_days is None else float(floor_min_age_days)
        self.git_gate = git_gate
        self.open_files_gate = open_files_gate
        self.recursive = recursive          # file rules: walk the parent
        self.note = note
        self.parent_match = re.compile(parent_match) if parent_match else None
        self.gate = gate
        self.apply_switch = apply_switch
        # ASK-4234: name of a linked worktree INSIDE the target (verify.sh's tmp.X/wt).
        # Its registration lives in the main repo's .git/worktrees, so the repo to
        # prune is read from that child, not from the target itself.
        self.wt_child = wt_child
        # ASK-4234: chmod u+rwx the target's dirs before rmtree. Only for scratch with no git
        # gate: rounds 3 and 4 of PR 841 both showed that unlocking a git-gated tree lets a
        # gate that could not read it say clean. Same class twice, so the feature is scoped out.
        self.unlock = unlock
        # ASK-3976: shared_probe(ctx, path) True means the target's blocks are shared
        # with another file (an APFS clone), so its du bytes are not what a delete frees.
        self.shared_probe = shared_probe
        # PR 849 review, finding 3: `--untracked-files=normal` hides ignored files, so a
        # clean worktree holding a local .env or output/ read as clean and was deleted.
        # True for the worktree rules: any ignored path except Python byte-code caches
        # (IGNORED_REGENERABLE) is a keep.
        self.ignored_dirty = ignored_dirty


def finished_pr_gate(ctx, path):
    """review-trees-finished: pass only when GitHub says the PR is MERGED or
    CLOSED. pr-review-agent.sh reaps its own repo's finished trees at the start of
    a run, so a repo that stops getting reviews keeps its trees forever: 3.9 GB of
    them on 2026-11-09. A wrong keep costs disk; a wrong delete costs a live review
    its tree, so every unknown is a keep."""
    m = REVIEW_TREE_RE.match(os.path.basename(path))
    if not m:
        return ("skip-pr-unknown", "name is not <owner>_<repo>__pr-<n>")
    # The review holds <tree>.lock (a PID) while it reads the tree; the census
    # misses a review that is between tool calls.
    try:
        with open(path + ".lock") as fh:
            holder = fh.read().strip()
    except OSError:
        holder = ""
    if holder.isdigit() and _pid_alive(int(holder)):
        return ("skip-lock-held", "review lock held by live pid %s" % holder)
    slug = "%s/%s" % (m.group(1), m.group(2))
    state = ctx.pr_state(slug, m.group(3))
    if state in ("MERGED", "CLOSED"):
        return None
    return ("skip-pr-open" if state == "OPEN" else "skip-pr-unknown",
            "%s#%s state %r" % (slug, m.group(3), state or "lookup failed"))


def _unlock_tree(path, top=True):
    """A review run left .claims dirs at mode 000 (2026-11-18): du and rmtree both
    hit Permission denied, which counted as an error and raised the alert. Only
    called on a target every other gate already passed for deletion."""
    # the target itself too: a mode-000 target errored on every run (review PR 841, finding 4)
    # top=False for git-gated rules: git_state() read a mode-000 checkout as not-a-repo
    # and passed, so unlocking AFTER the gate must never be what lets dirty work be deleted
    # (review round 3, major).
    if top:
        try:
            os.chmod(path, 0o700)
        except OSError:
            pass
    for root, dirs, _files in os.walk(path, followlinks=False):
        for d in dirs:
            full = os.path.join(root, d)
            if not os.path.islink(full):
                try:
                    os.chmod(full, 0o700)
                except OSError:
                    pass


def staged_snapshot_gate(ctx, path):
    """tmp-verify-staged: pass only for a verify.sh staged snapshot, i.e. a mktemp
    dir whose wt/ is a linked worktree of a repo that still exists. verify.sh
    removes it in an EXIT trap, which a killed or timed-out commit never runs:
    six of them, 466 MB each, sat on the disk on 2026-11-18 under the 7-day
    gate of tmp-mktemp-shell, while the next commit needed 5 GiB free."""
    wt = os.path.join(path, "wt")
    repo = parent_repo_of_worktree(wt)
    if not repo:
        return ("skip-not-snapshot", "no linked worktree at wt/")
    if not os.path.exists(os.path.join(repo, ".git")):
        return ("skip-repo-missing", "main repo %s is gone; prune cannot run" % repo)
    if ctx.is_live(os.path.realpath(wt)):
        return ("skip-live", "a live process holds the snapshot worktree")
    # PR 849 review, finding 5: any tmp.X/wt linked worktree used to pass, and agent
    # jobs park worktrees under tmp.X too. verify.sh always adds wt with --detach and
    # never edits a tracked file, so a branch checkout or a dirty one is not its.
    # Ignored files are not checked here: a leaked snapshot measured 2026-11-18 holds
    # __pycache__ and test .lock files from the pytest run it was killed in.
    if _git_out(wt, "symbolic-ref", "-q", "HEAD") != ("", 1):
        return ("skip-not-snapshot", "wt/ is on a branch or git could not read it")
    if git_state(wt) != "clean":
        return ("skip-not-snapshot", "wt/ has uncommitted or untracked work, or git could not read it")
    # The marker: --staged writes $TMP/index, the select path verify-select-plugin.
    # --changed writes neither, but checks out an existing commit, so its HEAD is on
    # some ref. A detached commit that is on no ref and has no marker could be the
    # only copy of someone's commits: keep it.
    if not any(os.path.lexists(os.path.join(path, m)) for m in SNAPSHOT_MARKERS):
        out = _git_out(wt, "for-each-ref", "--contains", "HEAD", "--count=1", "--format=%(refname)")
        if out[1] != 0 or not out[0].strip():
            return ("skip-not-snapshot", "no verify.sh marker and HEAD is on no ref")
    return None


SNAPSHOT_MARKERS = ("index", "verify-select-plugin")


def mktemp_shell_gate(ctx, path):
    """tmp-mktemp-shell: pass a plain mktemp dir, keep any git checkout in it that git
    cannot vouch for. ASK-5443: this rule had no git gate, so the parked worktrees
    tmp-verify-staged keeps (skip-not-snapshot) fell through to it at day 7 and were
    rmtree'd with their uncommitted work. Checked: the target itself and each
    top-level child (wt/ is the shape agents use) whose .git lexists."""
    candidates = [path]
    try:
        names = sorted(os.listdir(path))
    except OSError:
        return ("skip-unreadable", "target is not readable; cannot look for a checkout")
    candidates += [os.path.join(path, n) for n in names
                   if not os.path.islink(os.path.join(path, n)) and os.path.isdir(os.path.join(path, n))]
    for c in candidates:
        if not os.path.lexists(os.path.join(c, ".git")):
            continue
        # ignored=True: an agent's .env or build output is work too; only byte-code
        # caches are exempt (git_state's IGNORED_REGENERABLE).
        state = git_state(c, ignored=True)
        if state != "clean":
            return ("skip-git-" + state, "%s is a git checkout git reports %s" % (c, state))
        # A clean detached HEAD on no ref may be the only copy of a commit; the
        # worktree's reflog goes with the delete (same rail as staged_snapshot_gate).
        head = _git_out(c, "symbolic-ref", "-q", "HEAD")
        if head[1] == 0:
            # On a branch. In a linked worktree (.git is a file) the branch lives in the
            # main repo, so the delete loses nothing. A standalone clone (.git is a dir)
            # holds its branches itself: keep it unless every local branch is pushed.
            if os.path.isdir(os.path.join(c, ".git")):
                ahead = _git_out(c, "for-each-ref", "refs/heads", "--format=%(refname:short) %(upstream:short) %(upstream:track)")
                if ahead[1] != 0:
                    return ("skip-git-error", "%s: git could not list branches" % c)
                # Ref names cannot hold a space, so split is exact. No upstream leaves
                # one field. git 2.54 prints track as "[ahead 1]", "[ahead 1, behind 2]"
                # or "[gone]" (probed 2026-11-18). Read the track field only: matching
                # the whole line kept a synced branch named "ahead-x" (PR 853 review).
                for line in ahead[0].splitlines():
                    parts = line.split(None, 2)
                    track = parts[2] if len(parts) > 2 else ""
                    if len(parts) < 2 or "ahead" in track or track == "[gone]":
                        return ("skip-unpushed", "%s: standalone clone with an unpushed branch (%s)" % (c, line.strip()))
            continue
        if head != ("", 1):
            return ("skip-git-error", "%s: git could not read HEAD" % c)
        out = _git_out(c, "for-each-ref", "--contains", "HEAD", "--count=1", "--format=%(refname)")
        if out[1] != 0 or not out[0].strip():
            return ("skip-unreachable", "%s HEAD is detached on no ref" % c)
    return None


def _git_out(path, *args):
    """(stdout, returncode) of `git -C path args`; -1 when git cannot run, -2 on any
    stderr (git did not see everything)."""
    try:
        r = subprocess.run(["git", "-C", path] + list(args), capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return ("", -1)
    if r.stderr.strip():
        return (r.stdout, -2)
    return (r.stdout, r.returncode)


def session_ended_gate(ctx, path):
    """claude-session-scratch: pass only when the session is provably over. An idle
    interactive session holds no file and carries no uuid in its command line
    (measured 2026-11-09 on 6 live sessions), so the registry Claude Code keeps in
    ~/.claude/sessions/<pid>.json is the signal that sees it. Anything this
    cannot read is 'unknown', and unknown keeps the folder."""
    sid = os.path.basename(os.path.dirname(path))
    live = ctx.session_liveness()
    if live is None:
        return ("skip-session-unknown", "session liveness unknown: %s" % ctx.session_err)
    ids, haystack = live
    if sid in ids:
        return ("skip-session-live", "session %s is registered to a live pid" % sid)
    if sid in haystack:
        return ("skip-session-live", "session %s is in a running process or open file" % sid)
    return None


CLONE_WINDOW_S = 10.0


def _app_bundle_id(app, cache):
    """CFBundleIdentifier of an .app, or None. Cached per run."""
    if app not in cache:
        import plistlib
        try:
            with open(os.path.join(app, "Contents", "Info.plist"), "rb") as fh:
                cache[app] = plistlib.load(fh).get("CFBundleIdentifier")
        except Exception:
            cache[app] = None
    return cache[app]


MAIN_EXE_RE = re.compile(r"^(/.+?\.app)/Contents/MacOS/[^/]+$")


def clone_live_gate(ctx, path):
    """chrome-code-sign-clone (ASK-3976). Pass only an orphan clone. Keep when:
    the process table cannot be read; this clone was born within CLONE_WINDOW_S
    of a running main process of its bundle (measured: clone LowSzi born
    11:10:54, its Chrome started 11:10:53); or some running main process of the
    bundle has no clone born near its start, because then which clone it uses
    cannot be told and every one is kept."""
    procs = ctx.processes()
    if procs is None:
        return ("skip-procs-unknown", "process table could not be read")
    parent = os.path.dirname(path)
    bundle = os.path.basename(parent)[:-len(".code_sign_clone")]
    # PR 849 review, finding 1 (major): this gate failed OPEN. A running Chrome
    # whose Info.plist could not be read, or whose bundle id differed from the
    # folder name, was not counted, `starts` came out empty and every clone was
    # deleted, the live one included. So the app is read from the clone itself,
    # and an unreadable plist, or a running process of that app that does not
    # resolve to this bundle id, keeps everything.
    try:
        apps = [n[:-len(".bundle")] for n in os.listdir(path) if n.endswith(".app.bundle")]
    except OSError:
        return ("skip-procs-unknown", "cannot list this clone to tell which app it is")
    if not apps:
        return ("skip-procs-unknown", "clone holds no <App>.app.bundle; its app cannot be told")
    needles = ["/%s/Contents/MacOS/" % a for a in apps]
    bare = set(a[:-len(".app")] for a in apps)
    starts = []
    for start, exe in procs:
        m = MAIN_EXE_RE.match(exe)
        # Helpers live under Contents/Frameworks/.../Helpers/X.app; only the
        # outermost .app is a main process.
        if m and "/Contents/" not in m.group(1):
            bid = _app_bundle_id(m.group(1), ctx.bundle_cache)
            if bid is None:
                return ("skip-procs-unknown", "cannot read the bundle id of running %s" % m.group(1))
            if bid == bundle:
                starts.append(start)
                continue
        if any(n in exe for n in needles) or exe.strip() in bare:
            return ("skip-procs-unknown", "running %r did not resolve to bundle %s" % (exe, bundle))
    if not starts:
        return None
    births = []
    try:
        siblings = os.listdir(parent)
    except OSError as e:
        # finding 6: unguarded, this aborted the whole run.
        return ("skip-procs-unknown", "cannot list the clone folder (%s)" % e)
    for name in siblings:
        try:
            births.append(os.stat(os.path.join(parent, name)).st_birthtime)
        except (OSError, AttributeError):
            return ("skip-procs-unknown", "cannot read a sibling clone's birth time")
    try:
        mine = os.stat(path).st_birthtime
    except (OSError, AttributeError):
        return ("skip-procs-unknown", "cannot read this clone's birth time")
    for st in starts:
        if abs(mine - st) <= CLONE_WINDOW_S:
            return ("skip-live-clone", "born %.0fs from a running %s start" % (mine - st, bundle))
    for st in starts:
        if not any(abs(b - st) <= CLONE_WINDOW_S for b in births):
            return ("skip-live-unmatched", "a running %s has no clone born at its start" % bundle)
    return None


F_LOG2PHYS_EXT = 65     # <sys/fcntl.h>; struct log2phys is #pragma pack(4): uint32, off_t, off_t


def _phys_offset(path):
    import fcntl as _f
    import struct
    fd = os.open(path, os.O_RDONLY)
    try:
        out = _f.fcntl(fd, F_LOG2PHYS_EXT, struct.pack("=Iqq", 0, 1 << 20, 0))
        return struct.unpack("=Iqq", out)[2]
    finally:
        os.close(fd)


def clone_shares_app_blocks(ctx, path):
    """True when the clone's biggest file sits on the same physical blocks as the
    installed app's copy, so deleting the clone frees about nothing. Measured
    2026-11-18: the 531 MB framework had one physical address in all 5 clones and
    in /Applications. An orphan owns its blocks only after an app update; then
    the paths or the extents differ and this returns False. Any doubt is False,
    which reports du bytes as before."""
    try:
        bundles = [n for n in os.listdir(path) if n.endswith(".app.bundle")]
    except OSError:
        return False
    if len(bundles) != 1:
        return False
    clone_app = os.path.join(path, bundles[0])
    src_app = os.path.join(ctx.apps_dir, bundles[0][:-len(".bundle")])
    best, best_size = None, 0
    for root, _dirs, files in os.walk(clone_app, followlinks=False):
        for n in files:
            full = os.path.join(root, n)
            try:
                st = os.lstat(full)
            except OSError:
                continue
            # nlink > 1 is the hardlinked main binary: same inode, proves nothing.
            if st.st_nlink == 1 and st.st_size > best_size and not os.path.islink(full):
                best, best_size = full, st.st_size
    if best is None:
        return False
    src = os.path.join(src_app, os.path.relpath(best, clone_app))
    try:
        if os.path.getsize(src) != best_size:
            return False
        return _phys_offset(best) == _phys_offset(src)
    except (OSError, IOError):
        return False


RULES = [
    # 1 day, not 2: the 2026-09-10 burst was still "young" at the first live dry
    # run and the disk had 6 GB left. A mkdtemp dir a process still uses shows
    # up in the open-file census; one it merely remembers the path of and
    # revisits after a day is the accepted residual.
    Rule("tmp-mkdtemp", ["{TMP}/T"], match=r"^tmp[a-z0-9_]{6,}$", min_age_days=1,
         floor_min_age_days=2.0 / 24,
         note="python tempfile.mkdtemp leak; 2026-09-10 burst: 8,776 dirs, 16.7 GB"),
    Rule("tmp-pymp", ["{TMP}/T"], match=r"^pymp-", min_age_days=1,
         note="multiprocessing temp dirs left by killed workers"),
    # ORDER MATTERS (codex review, PR 841): this must run before tmp-mktemp-shell. That rule
    # matches the same dirs at 7 days and rmtrees them without pruning the repo
    # registration behind wt/, which leaves a stale .git/worktrees entry.
    # ASK-4234. 1 h, 30 min under the floor: a commit's snapshot is touched for
    # as long as it runs, and the live census covers a quiet one.
    Rule("tmp-verify-staged", ["{TMP}/T"], match=r"^tmp\.[A-Za-z0-9]{6,}$", min_age_days=1.0 / 24,
         floor_min_age_days=0.5 / 24, gate=staged_snapshot_gate, wt_child="wt",
         note="ASK-4234: verify.sh staged snapshot leaked by a killed commit; 466 MB each"),
    # pr-review-agent.sh removes its own run./ctx. dir in an EXIT trap; what is
    # left is from a killed run. Nothing reads these after the run (read the
    # script's review_scratch_cleanup). Hand-made dirs (sana*, pr334*) do not match.
    Rule("review-scratch-runs", ["{HOME}/.config/kipi/review-scratch"], match=r"^(run|ctx)\.[A-Za-z0-9]+$",
         min_age_days=1, unlock=True, note="ASK-4234: orphaned review run and PR-context dirs"),
    # ASK-5443: gate + wt_child. The gate keeps a parked checkout git cannot vouch for;
    # wt_child prunes the .git/worktrees entry of a clean wt/ it does delete.
    Rule("tmp-mktemp-shell", ["{TMP}/T"], match=r"^tmp\.[A-Za-z0-9]{6,}$", min_age_days=7,
         gate=mktemp_shell_gate, wt_child="wt",
         note="shell mktemp -d dirs; 7 days because agent jobs park worktrees here"),
    # ASK-3976. The old rule targeted the PARENT folder with an open-files gate. The
    # parent always holds the live clone, so it skipped every day from 2026-09-29.
    # Each clone is a child now, and lsof cannot gate it: every clone's main binary
    # is a hardlink of the app's, so every clone shows one open file. Birth time
    # against running main processes is the liveness signal (clone_live_gate).
    Rule("chrome-code-sign-clone", ["{TMP}/X/*.code_sign_clone"], match=r"^code_sign_clone\.[A-Za-z0-9]+$",
         min_age_days=1.0 / 24, gate=clone_live_gate, shared_probe=clone_shares_app_blocks,
         note="ASK-3976: bundle clones leaked by killed browser launches; ~0 bytes until an app update"),
    Rule("review-trees", ["{HOME}/.config/kipi/review-trees"], min_age_days=14, git_gate=True,
         note="detached-HEAD checkouts made by the PR review agent"),
    Rule("review-trees-finished", ["{HOME}/.config/kipi/review-trees"],
         match=REVIEW_TREE_RE.pattern, min_age_days=0, git_gate=True, gate=finished_pr_gate,
         note="ASK-4228: trees of merged or closed PRs at any age"),
    Rule("review-tree-locks", ["{HOME}/.config/kipi/review-trees"], kind="file",
         match=r"\.lock$", min_age_days=14),
    # ignored_dirty: review trees are left out on purpose. pr-review-agent.sh makes
    # them and nobody works in them, and their test residue (.lock files) would make
    # review-trees-finished keep every tree forever.
    Rule("kipi-worktrees", ["{HOME}/.config/kipi/worktrees"], min_age_days=21, git_gate=True,
         ignored_dirty=True,
         note="Sana's issue worktrees; 21 days + clean, unfinished work is never touched"),
    Rule("agent-worktrees",
         ["{HOME}/projects/*/.claude/worktrees", "{HOME}/projects/*/projects/*/.claude/worktrees"],
         match=r"^agent-", min_age_days=7, git_gate=True, ignored_dirty=True,
         note="Claude Code EnterWorktree leftovers"),
    Rule("projects-wt", ["{HOME}/projects/_wt"], min_age_days=21, git_gate=True, ignored_dirty=True),
    Rule("sana-work", ["{HOME}/.cache/sana-work"], min_age_days=14, git_gate=True, ignored_dirty=True),
    Rule("codex-sessions", ["{HOME}/.codex/sessions"], kind="file", recursive=True, min_age_days=30),
    # Age 0 (ASK-4228): the 7-day gate kept 1.5 GB of downloads the founder then
    # deleted by hand at 100% disk. An app re-downloads its update; a cache an
    # updater has open is still caught by the live gate.
    Rule("updater-caches", ["{HOME}/Library/Caches"], match=r"(ShipIt$|-updater$|^@.*updater$)",
         min_age_days=0, note="Squirrel/ShipIt and electron-updater keep every downloaded app update"),
    Rule("claude-mcp-logs", ["{HOME}/Library/Caches/claude-cli-nodejs/*/mcp-logs-*"], kind="file",
         match=r"\.jsonl$", min_age_days=1,
         note="ASK-4228: Claude Code MCP debug logs; 27,634 files, 1.0 GB on 2026-11-09"),
    # REPORT-ONLY (ASK-4228): on 2026-11-09 the founder chose not to delete one
    # such folder, a consulting/Cookie session's 5.4 GB scratch, because that
    # session's work might not be finished. So this class logs what it would free
    # and deletes nothing until "session_scratch_apply": true in disk-janitor.json.
    Rule("claude-session-scratch", ["{CLAUDETMP}/*/*"], match=r"^scratchpad$", min_age_days=0.25,
         parent_match=UUID_RE, gate=session_ended_gate, apply_switch="session_scratch_apply",
         note="ASK-4228: scratch of ended Claude sessions; 7.8 GB on 2026-11-09"),
    Rule("docker-install-leftover", ["{HOME}/Library/Application Support/com.docker.install"],
         match=r"^in_progress$", min_age_days=1),
    Rule("npx-cache", ["{HOME}/.npm/_npx"], min_age_days=30),
]


# ----------------------------------------------------------------------------
# context

def _now():
    return float(os.environ.get("JANITOR_NOW") or time.time())


def _home():
    return os.path.realpath(os.environ.get("JANITOR_HOME") or os.path.expanduser("~"))


def _kipi_dir(home):
    return os.path.join(home, ".config", "kipi")


def _log_path(home):
    return os.environ.get("JANITOR_LOG") or os.path.join(_kipi_dir(home), "disk-janitor.log")


class Ctx(object):
    def __init__(self, mode, rules, trigger="run"):
        self.mode = mode                                    # "dry" | "apply"
        self.rules = rules
        self.trigger = trigger                              # "run" | "floor"
        self.now = _now()
        self.home = _home()
        self.tmp = os.path.realpath(os.environ.get("JANITOR_TMPBASE") or _darwin_tmp_base())
        self.claudetmp = os.path.realpath(os.environ.get("JANITOR_CLAUDETMP")
                                          or "/tmp/claude-%d" % os.getuid())
        self.roots = [self.home, self.tmp, self.claudetmp]
        self.log_path = _log_path(self.home)
        self.run_id = uuid.uuid4().hex[:8]
        self.config, self.config_path = load_config(self.home)
        self.live, self.live_ok = _live_census()
        # One set lookup per candidate instead of a scan of the census: the
        # MCP-log rule alone has ~43k candidates and the census ~16k paths.
        self.live_set = set(self.live)
        self.live_ancestors = set()
        for held in self.live:
            d = os.path.dirname(held)
            while d and d not in self.live_ancestors and d != os.path.dirname(d):
                self.live_ancestors.add(d)
                d = os.path.dirname(d)
        self._sessions = False  # not computed yet; None = unknown
        self.session_err = ""
        self.pr_cache = {}
        self._procs = False     # not read yet; None = unknown
        self.bundle_cache = {}
        self.apps_dir = os.environ.get("JANITOR_APPS") or "/Applications"
        self.shared_bytes = {}  # rule -> du bytes of targets whose blocks a clone source still holds
        self.counts = {}        # rule -> {action -> n}
        self.bytes = {}         # rule -> bytes that were / would be deleted
        self.report_bytes = {}  # rule -> bytes a report-only rule would free
        self.errors = 0
        self.prune_repos = set()
        self.targets = []       # (rule, path, bytes) planned or deleted

    def bump(self, rule, action, nbytes=0):
        c = self.counts.setdefault(rule, {})
        c[action] = c.get(action, 0) + 1
        if action == "delete":
            self.bytes[rule] = self.bytes.get(rule, 0) + nbytes
        if action == "report":
            self.report_bytes[rule] = self.report_bytes.get(rule, 0) + nbytes

    def is_live(self, real):
        """The census rule from before ASK-4228, as set lookups: held == real, or
        held is under real."""
        return real in self.live_set or real in self.live_ancestors

    def switch_on(self, name):
        return self.config.get(name) is True

    def session_liveness(self):
        """(live session ids, haystack of process command lines + open paths), or
        None when any source cannot be read."""
        if self._sessions is False:
            self._sessions = self._read_sessions()
        return self._sessions

    def _read_sessions(self):
        if not self.live_ok:
            self.session_err = "the lsof census failed"
            return None
        reg = os.path.join(self.home, ".claude", "sessions")
        try:
            names = sorted(os.listdir(reg))
        except OSError as e:
            self.session_err = "no session registry at %s (%s)" % (reg, e.strerror)
            return None
        ids = set()
        for name in names:
            if not name.endswith(".json"):
                continue
            stem = name[:-len(".json")]
            try:
                with open(os.path.join(reg, name)) as fh:
                    rec = json.load(fh)
                pid = int(rec["pid"])
                sid = str(rec["sessionId"])
            except (OSError, ValueError, KeyError, TypeError):
                # A record we cannot read could name any session; if its pid is
                # alive, nothing in this run can be called ended.
                if stem.isdigit() and _pid_alive(int(stem)):
                    self.session_err = "unreadable registry record %s for a live pid" % name
                    return None
                continue
            if _pid_alive(pid):
                ids.add(sid)
        try:
            r = subprocess.run(["ps", "-axww", "-o", "command="], capture_output=True,
                               text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as e:
            self.session_err = "ps failed (%s)" % e
            return None
        if r.returncode != 0 or not r.stdout.strip():
            self.session_err = "ps failed (exit %d)" % r.returncode
            return None
        return ids, r.stdout + "\n" + "\n".join(self.live)

    def processes(self):
        """[(start epoch, executable path)] for every process, or None if ps
        cannot be read. JANITOR_PROCS (JSON list of {start, exe}, or null) is the
        test seam."""
        if self._procs is False:
            self._procs = self._read_procs()
        return self._procs

    def _read_procs(self):
        raw = os.environ.get("JANITOR_PROCS")
        if raw is not None:
            data = json.loads(raw)
            return None if data is None else [(float(p["start"]), p["exe"]) for p in data]
        try:
            r = subprocess.run(["ps", "-axww", "-o", "lstart=,comm="], capture_output=True,
                               text=True, timeout=60, env=dict(os.environ, LC_ALL="C", LANG="C"))
        except (OSError, subprocess.TimeoutExpired):
            return None
        if r.returncode != 0 or not r.stdout.strip():
            return None
        return parse_ps_lstart(r.stdout)

    def pr_state(self, slug, n):
        """MERGED / CLOSED / OPEN from gh, or "" for any failure. One call per PR."""
        key = (slug, n)
        if key in self.pr_cache:
            return self.pr_cache[key]
        gh = (os.environ.get("JANITOR_GH") or shutil.which("gh")
              or shutil.which("gh", path="/opt/homebrew/bin:/usr/local/bin"))
        state = ""
        if gh:
            try:
                r = subprocess.run([gh, "pr", "view", n, "-R", slug, "--json", "state", "-q", ".state"],
                                   capture_output=True, text=True, timeout=30)
                state = r.stdout.strip() if r.returncode == 0 else ""
            except (OSError, subprocess.TimeoutExpired):
                state = ""
        self.pr_cache[key] = state
        return state

    def log(self, rule, path, action, nbytes=0, reason=""):
        rec = {"ts": _iso(time.time()), "run": self.run_id, "mode": self.mode,
               "rule": rule, "path": path, "action": action, "bytes": nbytes}
        if reason:
            rec["reason"] = reason
        _append_json(self.log_path, rec)


def parse_ps_lstart(text):
    """`ps -axww -o lstart=,comm=` under LC_ALL=C -> [(start epoch, comm)], or None
    when any line's date does not parse (then the table is unknown, never partial).
    Pinned against captured output by test_disk_janitor_reclaim.PsParser."""
    out = []
    for line in text.splitlines():
        parts = line.split(None, 5)
        if len(parts) < 6:
            continue
        try:
            start = time.mktime(time.strptime(" ".join(parts[:5]), "%a %b %d %H:%M:%S %Y"))
        except ValueError:
            return None
        out.append((start, parts[5]))
    return out


def _darwin_tmp_base():
    # $TMPDIR is /var/folders/xx/yyy/T/ ; the base (T, C, X siblings) is its parent.
    # launchd jobs have no TMPDIR, so ask confstr, which is what the shell does.
    t = os.environ.get("TMPDIR")
    if not t:
        try:
            t = os.confstr("CS_DARWIN_USER_TEMP_DIR")
        except (ValueError, AttributeError):
            t = None
    if not t:
        return "/nonexistent-tmp-base"
    return os.path.dirname(os.path.realpath(t.rstrip("/")))


def _live_census():
    """Every path any live process holds: cwd, text, mmap, open fds. One lsof
    call for the whole run. A failure here returns an empty census, which the
    age gates still bound; it does not turn the run off. It does mark the census
    not-ok, and the session-scratch class (no real age gate) then keeps all."""
    raw = os.environ.get("JANITOR_LIVE")
    if raw is not None:
        data = json.loads(raw)
        if data is None:        # test seam: a census that failed
            return [], False
        return sorted(set(os.path.realpath(p) for p in data)), True
    try:
        out = subprocess.run(["lsof", "-n", "-Fn"], capture_output=True,
                             text=True, timeout=180).stdout
    except (OSError, subprocess.TimeoutExpired):
        return [], False
    paths = set()
    for line in out.splitlines():
        if line.startswith("n/"):
            paths.add(os.path.realpath(line[1:]))
    return sorted(paths), bool(paths)


def _pid_alive(pid):
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True     # exists, owned by someone else
    except OSError:
        return True     # cannot tell -> treat as live
    return True


def load_config(home):
    """disk-janitor.json. Missing or broken means every switch is off."""
    path = os.path.join(_kipi_dir(home), "disk-janitor.json")
    try:
        with open(path) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}, path
    return (data if isinstance(data, dict) else {}), path


def _iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(t))


def _append_json(path, rec):
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)
    with open(path, "a") as fh:
        fh.write(json.dumps(rec, sort_keys=True) + "\n")


# ----------------------------------------------------------------------------
# measurement

def newest_mtime(path):
    """Newest mtime in the tree, symlinks not followed. A file: its own mtime."""
    try:
        st = os.lstat(path)
    except OSError:
        return 0.0
    newest = st.st_mtime
    if not os.path.isdir(path) or os.path.islink(path):
        return newest
    for root, dirs, files in os.walk(path, followlinks=False):
        for name in dirs + files:
            try:
                m = os.lstat(os.path.join(root, name)).st_mtime
            except OSError:
                continue
            if m > newest:
                newest = m
    return newest


def tree_bytes(path):
    """Allocated bytes. APFS clones share blocks, so this can overstate what a
    delete frees; df before/after is the number that counts."""
    try:
        st = os.lstat(path)
    except OSError:
        return 0
    if not os.path.isdir(path) or os.path.islink(path):
        return st.st_blocks * 512
    total = 0
    for root, dirs, files in os.walk(path, followlinks=False):
        for name in files:
            try:
                total += os.lstat(os.path.join(root, name)).st_blocks * 512
            except OSError:
                pass
    return total


IGNORED_REGENERABLE = re.compile(r"(^|/)(__pycache__/|\.pytest_cache/|[^/]*\.pyc$)")


def git_state(path, ignored=False):
    """'clean' | 'dirty' | 'error' | 'not-a-repo' | 'unreadable'. ignored=True counts
    any ignored path as dirty except Python byte-code caches, which only the
    interpreter writes and which every worker tree that ran a test holds."""
    # PR 841 round 4: a mode-000 target hid its .git, read as not-a-repo, passed the
    # gate and then failed rmtree on every run, paging each time.
    if not os.access(path, os.R_OK | os.X_OK):
        return "unreadable"
    # lexists, finding 2: a dangling .git symlink is not "no repo"; git then errors.
    if not os.path.lexists(os.path.join(path, ".git")):
        return "not-a-repo"
    cmd = ["git", "-C", path, "status", "--porcelain", "--untracked-files=normal"]
    if ignored:
        cmd.append("--ignored=matching")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return "error"
    # PR 841 round 4, major: with a mode-000 subdir git exits 0, prints nothing on
    # stdout and says "Permission denied" on stderr. Reading that as clean let
    # rmtree destroy every readable file of a worktree holding unsaved work. Any
    # stderr means git did not see the whole tree, so it is not "clean".
    if r.returncode != 0 or r.stderr.strip():
        return "error"
    for line in r.stdout.splitlines():
        if not line.strip():
            continue
        if line.startswith("!! ") and IGNORED_REGENERABLE.search(line[3:].strip('"')):
            continue
        return "dirty"
    return "clean"


def parent_repo_of_worktree(path):
    """A linked worktree's .git is a FILE: 'gitdir: <repo>/.git/worktrees/<name>'."""
    dotgit = os.path.join(path, ".git")
    if not os.path.isfile(dotgit):
        return None
    try:
        with open(dotgit) as fh:
            line = fh.read().strip()
    except OSError:
        return None
    if not line.startswith("gitdir:"):
        return None
    gitdir = line[len("gitdir:"):].strip()
    marker = os.sep + ".git" + os.sep + "worktrees" + os.sep
    idx = gitdir.find(marker)
    if idx < 0:
        return None
    return gitdir[:idx]


def has_open_files(path):
    if os.environ.get("JANITOR_NO_OPENFILES") == "1":
        return False
    try:
        r = subprocess.run(["lsof", "+D", path], capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return True   # cannot tell -> treat as live
    return bool(r.stdout.strip())


# ----------------------------------------------------------------------------
# the decision, one target at a time

def inside_roots(ctx, path):
    real = os.path.realpath(path)
    for root in ctx.roots:
        if real == root:
            return False
        if real.startswith(root + os.sep):
            return True
    return False


def consider(ctx, rule, parent, path):
    """Decide one candidate. Returns the action taken/planned."""
    name = os.path.basename(path)
    if not rule.match.search(name):
        return "nomatch"
    if os.path.islink(path):
        ctx.bump(rule.name, "skip-symlink")
        ctx.log(rule.name, path, "skip", reason="symlink")
        return "skip"
    # Allowlist: direct child of the rule's parent, and under a root. A glob
    # that resolved somewhere surprising is refused here, not deleted.
    if os.path.realpath(os.path.dirname(path)) != os.path.realpath(parent) and not rule.recursive:
        ctx.bump(rule.name, "refuse")
        ctx.log(rule.name, path, "refuse", reason="not a direct child of the rule parent")
        return "refuse"
    if not inside_roots(ctx, path) or not inside_roots(ctx, parent):
        ctx.bump(rule.name, "refuse")
        ctx.log(rule.name, path, "refuse", reason="outside HOME and the temp base")
        return "refuse"
    is_dir = os.path.isdir(path)
    if rule.kind == "dir" and not is_dir:
        return "nomatch"
    if rule.kind == "file" and is_dir:
        return "nomatch"
    age_days = (ctx.now - newest_mtime(path)) / DAY
    min_age = rule.min_age_days
    if ctx.trigger == "floor" and rule.floor_min_age_days is not None:
        min_age = rule.floor_min_age_days
    if age_days < min_age:
        ctx.bump(rule.name, "skip-young")
        return "skip"
    real = os.path.realpath(path)
    if ctx.is_live(real):
        ctx.bump(rule.name, "skip-live")
        ctx.log(rule.name, path, "skip", reason="held by a live process")
        return "skip"
    if rule.git_gate and is_dir:
        state = git_state(path, ignored=rule.ignored_dirty)
        if state == "not-a-repo":
            # PR 849 review, finding 2 (major): not-a-repo used to fall through as
            # clean, so every git-gated rule deleted any aged folder with no .git.
            # No rule here needs to remove a plain folder, so none opts out.
            ctx.bump(rule.name, "skip-not-a-repo")
            ctx.log(rule.name, path, "skip", reason="git-gated rule and no .git: not a checkout")
            return "skip"
        if state == "dirty":
            ctx.bump(rule.name, "skip-dirty")
            ctx.log(rule.name, path, "skip", reason="dirty git checkout")
            return "skip"
        if state == "error":
            ctx.bump(rule.name, "skip-git-error")
            ctx.log(rule.name, path, "skip", reason="git status failed or could not read the whole tree")
            return "skip"
        if state == "unreadable":
            # A skip, not a delete error: an error re-pages every run and the
            # janitor can never fix it (round 4, finding 2).
            ctx.bump(rule.name, "skip-unreadable")
            ctx.log(rule.name, path, "skip", reason="target is not readable; the git gate cannot see inside")
            return "skip"
    if rule.open_files_gate and has_open_files(path):
        ctx.bump(rule.name, "skip-open-files")
        ctx.log(rule.name, path, "skip", reason="open files")
        return "skip"
    if rule.gate is not None:
        verdict = rule.gate(ctx, path)
        if verdict is not None:
            ctx.bump(rule.name, verdict[0])
            ctx.log(rule.name, path, "skip", reason=verdict[1])
            return "skip"
    nbytes = tree_bytes(path)
    # The founder asked for a tracker of what can be cleaned (2026-11-18). A clone
    # that shares the app's blocks would show 1.5 GB each that no delete frees, so
    # its du bytes go to a separate "shared" bucket and count 0 toward freed.
    shared = bool(rule.shared_probe and is_dir and rule.shared_probe(ctx, path))
    if shared:
        ctx.shared_bytes[rule.name] = ctx.shared_bytes.get(rule.name, 0) + nbytes
        nbytes_du, nbytes = nbytes, 0
    repo = parent_repo_of_worktree(path) if is_dir else None
    if is_dir and rule.wt_child:
        repo = parent_repo_of_worktree(os.path.join(path, rule.wt_child))
    if rule.apply_switch and not ctx.switch_on(rule.apply_switch):
        ctx.bump(rule.name, "report", nbytes)
        # The floor job repeats hourly while under FLOOR_GB, and the same 165
        # report lines were 54 KB of an 83 KB run (2026-11-09) in a log with no
        # rotation. Its summary still carries the count and the bytes.
        if ctx.trigger != "floor":
            ctx.log(rule.name, path, "report", nbytes, reason="report-only: %s is not true in %s; %.1fh old" % (
                rule.apply_switch, ctx.config_path, age_days * 24))
        return "report"
    if ctx.mode != "apply":
        ctx.bump(rule.name, "delete", nbytes)
        ctx.targets.append((rule.name, path, nbytes))
        ctx.log(rule.name, path, "would-delete", nbytes, reason="%.1fd old%s" % (
            age_days, "; shares the app's blocks, %.2f GB du, ~0 freed" % (nbytes_du / 1e9) if shared else ""))
        return "would-delete"
    errors = []

    def onerror(fn, p, exc):
        errors.append("%s: %s" % (p, exc[1]))

    if is_dir:
        if rule.unlock:
            _unlock_tree(path)
        shutil.rmtree(path, onerror=onerror)
    else:
        try:
            os.unlink(path)
        except OSError as e:
            errors.append("%s: %s" % (path, e))
    if errors:
        ctx.errors += 1
        ctx.bump(rule.name, "error")
        ctx.log(rule.name, path, "error", nbytes, reason="; ".join(errors)[:500])
        return "error"
    ctx.bump(rule.name, "delete", nbytes)
    ctx.targets.append((rule.name, path, nbytes))
    ctx.log(rule.name, path, "delete", nbytes, reason="%.1fd old%s" % (
        age_days, "; shares the app's blocks, %.2f GB du, ~0 freed" % (nbytes_du / 1e9) if shared else ""))
    if repo:
        ctx.prune_repos.add(repo)
    return "delete"


def expand_parents(ctx, rule):
    import glob
    out = []
    for pat in rule.parents:
        pat = pat.replace("{HOME}", ctx.home).replace("{TMP}", ctx.tmp).replace(
            "{CLAUDETMP}", ctx.claudetmp)
        for p in sorted(glob.glob(pat)):
            if not os.path.isdir(p) or os.path.islink(p):
                continue
            if rule.parent_match and not rule.parent_match.search(os.path.basename(p)):
                continue
            out.append(p)
    return out


def needs_census(ctx, rule):
    """A rule whose age gate is under a day, or whose own gate reads liveness, leans
    on the lsof census to keep what a process is using. Finding 4: with lsof
    failed the census is empty, and only the session rule used to notice."""
    min_age = rule.min_age_days
    if ctx.trigger == "floor" and rule.floor_min_age_days is not None:
        min_age = rule.floor_min_age_days
    return min_age < 1.0 or rule.gate is not None


def run_rule(ctx, rule):
    if not ctx.live_ok and needs_census(ctx, rule):
        ctx.bump(rule.name, "skip-census-unknown")
        ctx.log(rule.name, "", "skip", reason="the lsof census failed and this rule needs it")
        return
    for parent in expand_parents(ctx, rule):
        if rule.recursive:
            for root, dirs, files in os.walk(parent, followlinks=False):
                for name in files:
                    consider(ctx, rule, parent, os.path.join(root, name))
            continue
        try:
            entries = sorted(os.listdir(parent))
        except OSError:
            continue
        for name in entries:
            consider(ctx, rule, parent, os.path.join(parent, name))


def prune_worktrees(ctx):
    for repo in sorted(ctx.prune_repos):
        try:
            subprocess.run(["git", "-C", repo, "worktree", "prune"], capture_output=True,
                           text=True, timeout=120)
            ctx.log("worktree-prune", repo, "prune")
        except (OSError, subprocess.TimeoutExpired) as e:
            ctx.log("worktree-prune", repo, "error", reason=str(e))


def uv_prune(ctx):
    """uv's own pruner: drops unreachable cache entries only. Lock contention
    (a running `uv run` MCP server) is a skip, never a failure."""
    # launchd's PATH has no /opt/homebrew/bin, so look there too.
    uv = shutil.which("uv") or shutil.which("uv", path="/opt/homebrew/bin:/usr/local/bin")
    if ctx.mode != "apply" or not uv or os.environ.get("JANITOR_NO_UV"):
        return
    env = dict(os.environ, UV_LOCK_TIMEOUT="10")
    try:
        r = subprocess.run([uv, "cache", "prune"], capture_output=True, text=True,
                           timeout=300, env=env)
        ctx.log("uv-prune", ctx.home, "ok" if r.returncode == 0 else "skip",
                reason=(r.stderr or r.stdout).strip()[-200:])
    except (OSError, subprocess.TimeoutExpired) as e:
        ctx.log("uv-prune", ctx.home, "skip", reason=str(e))


def free_gb(path):
    fake = os.environ.get("JANITOR_FREE_GB")
    if fake:
        return float(fake)
    try:
        return shutil.disk_usage(path).free / 1e9
    except OSError:
        return -1.0


def take_lock(home):
    """ONE WRITER. The floor job (every 5 min) and the 04:30 job can start
    together; two rmtree walks over one tree turn every second delete into an
    error and an alert. The kernel drops an flock when its holder dies, so a
    killed run never wedges the next one. Returns the open handle, or None."""
    d = _kipi_dir(home)
    try:
        if not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
        fh = open(os.path.join(d, "disk-janitor.lock"), "a")
    except OSError:
        return None
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return None
    return fh


def _floor_state_path(home):
    return os.path.join(_kipi_dir(home), "disk-janitor-floor.json")


def load_floor_state(home):
    try:
        with open(_floor_state_path(home)) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_floor_state(home, state):
    """Written only while take_lock() is held: tmp + rename, one writer."""
    path = _floor_state_path(home)
    tmp = "%s.tmp.%d" % (path, os.getpid())
    with open(tmp, "w") as fh:
        json.dump(state, fh, sort_keys=True)
    os.replace(tmp, path)


def hard_floor(ctx, free, may_page):
    """Page once per episode under HARD_FLOOR_GB; re-arm over HARD_REARM_GB.
    Returns True when this call paged."""
    state = load_floor_state(ctx.home)
    paged = state.get("hard_paged") is True
    if free < 0:
        return False
    if free >= HARD_REARM_GB:
        if paged:
            state["hard_paged"] = False
            state["rearmed_at"] = _iso(ctx.now)
            save_floor_state(ctx.home, state)
        return False
    if free < HARD_FLOOR_GB and may_page and not paged:
        notify(ctx, "disk-janitor: PAGE internal disk at %.2f GB free after cleanup, under the %.0f GB "
                    "hard floor; jobs that write to disk will fail. Junk rules are exhausted; see "
                    "~/.config/kipi/disk-janitor.log run %s for what is left" % (free, HARD_FLOOR_GB, ctx.run_id))
        state["hard_paged"] = True
        state["hard_paged_at"] = _iso(ctx.now)
        save_floor_state(ctx.home, state)
        return True
    return False


def notify(ctx, line):
    if os.environ.get("JANITOR_NO_NOTIFY") == "1":
        ctx.log("notify", "", "suppressed", reason=line)
        return
    repo = os.environ.get("JANITOR_REPO") or os.path.join(ctx.home, "projects", "kipi-system")
    script = os.path.join(repo, "q-system", ".q-system", "scripts", "slack-notify.sh")
    if not os.path.exists(script):
        ctx.log("notify", script, "missing", reason=line)
        return
    try:
        subprocess.run(["bash", script, line], capture_output=True, text=True, timeout=60)
        ctx.log("notify", script, "sent", reason=line)
    except (OSError, subprocess.TimeoutExpired) as e:
        ctx.log("notify", script, "error", reason=str(e))


# ----------------------------------------------------------------------------
# entry

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry", action="store_true", help="plan only (default)")
    g.add_argument("--apply", action="store_true", help="delete")
    g.add_argument("--floor-check", action="store_true",
                   help="run --apply only when free space is under --floor-gb (launchd, every 5 min)")
    ap.add_argument("--rules", default="", help="comma-separated subset of rule names")
    ap.add_argument("--list", action="store_true", help="print the rules and exit")
    ap.add_argument("--json", action="store_true", help="print the summary as JSON")
    ap.add_argument("--floor-gb", type=float, default=FLOOR_GB)
    args = ap.parse_args(argv)

    if args.list:
        for r in RULES:
            print("%-26s %-4s age>=%-5s git=%s open=%s  %s" % (
                r.name, r.kind, "%gd" % r.min_age_days, r.git_gate, r.open_files_gate, ", ".join(r.parents)))
        return 0

    wanted = [s.strip() for s in args.rules.split(",") if s.strip()]
    rules = [r for r in RULES if not wanted or r.name in wanted]
    unknown = set(wanted) - set(r.name for r in RULES)
    if unknown:
        print("unknown rules: %s" % ", ".join(sorted(unknown)), file=sys.stderr)
        return 2

    if args.floor_check:
        return floor_check(args, rules)
    if not args.apply:
        return run_janitor("dry", rules, args)
    lock = take_lock(_home())
    if lock is None:
        _locked(_home())
        return 0
    try:
        return run_janitor("apply", rules, args)
    finally:
        lock.close()


def _locked(home):
    _append_json(_log_path(home), {"ts": _iso(time.time()), "rule": "lock", "path": "", "action": "skip",
                                   "reason": "another disk-janitor run holds disk-janitor.lock"})
    print("disk-janitor: another run holds the lock; nothing done")


def floor_check(args, rules):
    """The floor trigger. Cheap when there is room: one statvfs and a lock, no
    census, no log line. Under the floor it runs a full --apply at most once per
    FLOOR_COOLDOWN_S; under HARD_FLOOR_GB it runs on every check."""
    home = _home()
    lock = take_lock(home)
    if lock is None:
        return 0
    try:
        free = free_gb(home)
        state = load_floor_state(home)
        if free < 0:
            return 0
        if free >= HARD_REARM_GB and state.get("hard_paged") is True:
            state["hard_paged"] = False
            state["rearmed_at"] = _iso(_now())
            save_floor_state(home, state)
        if free >= args.floor_gb:
            return 0
        last = float(state.get("last_floor_run") or 0)
        if free >= HARD_FLOOR_GB and _now() - last < FLOOR_COOLDOWN_S:
            return 0
        state["last_floor_run"] = _now()
        save_floor_state(home, state)
        return run_janitor("apply", rules, args, trigger="floor")
    finally:
        lock.close()


def run_janitor(mode, rules, args, trigger="run"):
    ctx = Ctx(mode, rules, trigger)
    before = free_gb(ctx.home)
    for rule in rules:
        run_rule(ctx, rule)
    if ctx.mode == "apply":
        prune_worktrees(ctx)
        uv_prune(ctx)
    after = free_gb(ctx.home)

    total_bytes = sum(ctx.bytes.values())
    n_delete = sum(c.get("delete", 0) for c in ctx.counts.values())
    n_report = sum(c.get("report", 0) for c in ctx.counts.values())
    summary = {"run": ctx.run_id, "mode": ctx.mode, "trigger": ctx.trigger,
               "free_gb_before": round(before, 2),
               "free_gb_after": round(after, 2), "targets": n_delete,
               "bytes": total_bytes, "errors": ctx.errors, "rules": ctx.counts,
               "report_only_targets": n_report, "report_only_bytes": ctx.report_bytes,
               "shared_bytes_not_freed": ctx.shared_bytes}
    _append_json(ctx.log_path, {"ts": _iso(time.time()), "summary": summary})

    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        verb = "deleted" if ctx.mode == "apply" else "would delete"
        print("disk-janitor %s run %s (%s): %s %d targets, %.2f GB (du-measured); free %.1f -> %.1f GB" % (
            ctx.mode, ctx.run_id, ctx.trigger, verb, n_delete, total_bytes / 1e9, before, after))
        for name in sorted(ctx.counts):
            c = ctx.counts[name]
            extra = ""
            if name in ctx.report_bytes:
                extra = "  (report-only: would free %.2f GB)" % (ctx.report_bytes[name] / 1e9)
            print("  %-26s %s  %.2f GB%s" % (name, " ".join("%s=%d" % kv for kv in sorted(c.items())),
                                            ctx.bytes.get(name, 0) / 1e9, extra))
        if ctx.shared_bytes:
            print("  shared with an app (APFS clone, not counted as freed): %.2f GB du" % (
                sum(ctx.shared_bytes.values()) / 1e9))
        if n_report:
            print("  report-only: %d targets, %.2f GB not deleted; switch is off in %s" % (
                n_report, sum(ctx.report_bytes.values()) / 1e9, ctx.config_path))
        if ctx.mode != "apply":
            for rname, path, nb in sorted(ctx.targets, key=lambda t: -t[2])[:10]:
                print("  %8.2f GB  %-22s %s" % (nb / 1e9, rname, path))

    if ctx.mode == "apply":
        paged = hard_floor(ctx, after, may_page=True)
        if ctx.errors:
            notify(ctx, "disk-janitor: %d delete errors on run %s; see ~/.config/kipi/disk-janitor.log" % (
                ctx.errors, ctx.run_id))
        elif not paged and ctx.trigger != "floor" and after >= 0 and after < args.floor_gb:
            # The floor job runs hourly while under FLOOR_GB; this line stays the
            # daily run's, or it would repeat every hour.
            notify(ctx, "disk-janitor: internal disk still at %.1f GB free after cleanup (floor %.0f GB); "
                        "junk rules are exhausted, the rest is real data" % (after, args.floor_gb))
    return 1 if ctx.errors else 0


if __name__ == "__main__":
    sys.exit(main())
