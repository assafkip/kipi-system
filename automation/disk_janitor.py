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
              rule's parent, which must resolve under $HOME or the per-user temp
              base. Anything else is refused and logged, never deleted.
  AGE GATE    per rule, measured on the NEWEST mtime inside the tree, so a tree
              still being written to is young even if its top dir is old.
  GIT GATE    a checkout with a dirty `git status` is skipped; a checkout whose
              git call errors is skipped (a transient lock must not read as clean).
  LIVE GATE   a target that holds the cwd OR any open file of a live process is
              skipped (one system-wide lsof census per run); rules can also
              require a zero-open-files check of their own.
  SYMLINKS    never followed; a symlinked entry is skipped.
  DRY DEFAULT --dry prints the plan and deletes nothing; only --apply deletes.
  LOG         one JSON line per action in ~/.config/kipi/disk-janitor.log.
  ALERT       free space still under FLOOR_GB after --apply, or any delete error,
              goes to slack-notify.sh (Sana's Linear triage, founder-notifications.md).
              Once per run, on state, never per item.

Test env overrides (all optional): JANITOR_HOME, JANITOR_TMPBASE, JANITOR_NOW
(epoch seconds), JANITOR_LOG, JANITOR_LIVE (JSON list of paths; replaces the
lsof census), JANITOR_NO_OPENFILES=1 (skip the per-rule lsof +D check),
JANITOR_NO_NOTIFY=1, JANITOR_REPO (where slack-notify.sh lives).
"""
import argparse
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


class Rule(object):
    """One class of junk. `parents` are glob patterns with {HOME} / {TMP} tokens."""

    def __init__(self, name, parents, kind="dir", match=r".*", min_age_days=7,
                 git_gate=False, open_files_gate=False, recursive=False, note=""):
        self.name = name
        self.parents = parents
        self.kind = kind                    # "dir" or "file"
        self.match = re.compile(match)
        self.min_age_days = float(min_age_days)
        self.git_gate = git_gate
        self.open_files_gate = open_files_gate
        self.recursive = recursive          # file rules: walk the parent
        self.note = note


RULES = [
    # 1 day, not 2: the 2026-09-10 burst was still "young" at the first live dry
    # run and the disk had 6 GB left. A mkdtemp dir a process still uses shows
    # up in the open-file census; one it merely remembers the path of and
    # revisits after a day is the accepted residual.
    Rule("tmp-mkdtemp", ["{TMP}/T"], match=r"^tmp[a-z0-9_]{6,}$", min_age_days=1,
         note="python tempfile.mkdtemp leak; 2026-09-10 burst: 8,776 dirs, 16.7 GB"),
    Rule("tmp-pymp", ["{TMP}/T"], match=r"^pymp-", min_age_days=1,
         note="multiprocessing temp dirs left by killed workers"),
    Rule("tmp-mktemp-shell", ["{TMP}/T"], match=r"^tmp\.[A-Za-z0-9]{6,}$", min_age_days=7,
         note="shell mktemp -d dirs; 7 days because agent jobs park worktrees here"),
    Rule("chrome-code-sign-clone", ["{TMP}/X"], match=r"^com\.google\.Chrome\.code_sign_clone$",
         min_age_days=3, open_files_gate=True,
         note="Chrome clones its bundle on update; a running Chrome still maps it, hence the open-files gate"),
    Rule("review-trees", ["{HOME}/.config/kipi/review-trees"], min_age_days=14, git_gate=True,
         note="detached-HEAD checkouts made by the PR review agent"),
    Rule("review-tree-locks", ["{HOME}/.config/kipi/review-trees"], kind="file",
         match=r"\.lock$", min_age_days=14),
    Rule("kipi-worktrees", ["{HOME}/.config/kipi/worktrees"], min_age_days=21, git_gate=True,
         note="Sana's issue worktrees; 21 days + clean, unfinished work is never touched"),
    Rule("agent-worktrees",
         ["{HOME}/projects/*/.claude/worktrees", "{HOME}/projects/*/projects/*/.claude/worktrees"],
         match=r"^agent-", min_age_days=7, git_gate=True,
         note="Claude Code EnterWorktree leftovers"),
    Rule("projects-wt", ["{HOME}/projects/_wt"], min_age_days=21, git_gate=True),
    Rule("sana-work", ["{HOME}/.cache/sana-work"], min_age_days=14, git_gate=True),
    Rule("codex-sessions", ["{HOME}/.codex/sessions"], kind="file", recursive=True, min_age_days=30),
    Rule("updater-caches", ["{HOME}/Library/Caches"], match=r"(ShipIt|updater)$", min_age_days=7,
         note="Squirrel/ShipIt keep every downloaded app update"),
    Rule("docker-install-leftover", ["{HOME}/Library/Application Support/com.docker.install"],
         match=r"^in_progress$", min_age_days=1),
    Rule("npx-cache", ["{HOME}/.npm/_npx"], min_age_days=30),
]


# ----------------------------------------------------------------------------
# context

class Ctx(object):
    def __init__(self, mode, rules):
        self.mode = mode                                    # "dry" | "apply"
        self.rules = rules
        self.now = float(os.environ.get("JANITOR_NOW") or time.time())
        self.home = os.path.realpath(os.environ.get("JANITOR_HOME") or os.path.expanduser("~"))
        self.tmp = os.path.realpath(os.environ.get("JANITOR_TMPBASE") or _darwin_tmp_base())
        self.roots = [self.home, self.tmp]
        self.log_path = os.environ.get("JANITOR_LOG") or os.path.join(
            self.home, ".config", "kipi", "disk-janitor.log")
        self.run_id = uuid.uuid4().hex[:8]
        self.live = _live_census()
        self.counts = {}        # rule -> {action -> n}
        self.bytes = {}         # rule -> bytes that were / would be deleted
        self.errors = 0
        self.prune_repos = set()
        self.targets = []       # (rule, path, bytes) planned or deleted

    def bump(self, rule, action, nbytes=0):
        c = self.counts.setdefault(rule, {})
        c[action] = c.get(action, 0) + 1
        if action == "delete":
            self.bytes[rule] = self.bytes.get(rule, 0) + nbytes

    def log(self, rule, path, action, nbytes=0, reason=""):
        rec = {"ts": _iso(time.time()), "run": self.run_id, "mode": self.mode,
               "rule": rule, "path": path, "action": action, "bytes": nbytes}
        if reason:
            rec["reason"] = reason
        _append_json(self.log_path, rec)


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
    age gates still bound; it does not turn the run off."""
    raw = os.environ.get("JANITOR_LIVE")
    if raw is not None:
        return sorted(set(os.path.realpath(p) for p in json.loads(raw)))
    try:
        out = subprocess.run(["lsof", "-n", "-Fn"], capture_output=True,
                             text=True, timeout=180).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    paths = set()
    for line in out.splitlines():
        if line.startswith("n/"):
            paths.add(os.path.realpath(line[1:]))
    return sorted(paths)


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


def git_state(path):
    """'clean' | 'dirty' | 'error' | 'not-a-repo'."""
    if not os.path.exists(os.path.join(path, ".git")):
        return "not-a-repo"
    try:
        r = subprocess.run(["git", "-C", path, "status", "--porcelain", "--untracked-files=normal"],
                           capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return "error"
    if r.returncode != 0:
        return "error"
    return "dirty" if r.stdout.strip() else "clean"


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
    if age_days < rule.min_age_days:
        ctx.bump(rule.name, "skip-young")
        return "skip"
    real = os.path.realpath(path)
    for held in ctx.live:
        if held == real or held.startswith(real + os.sep):
            ctx.bump(rule.name, "skip-live")
            ctx.log(rule.name, path, "skip", reason="held by a live process")
            return "skip"
    if rule.git_gate and is_dir:
        state = git_state(path)
        if state == "dirty":
            ctx.bump(rule.name, "skip-dirty")
            ctx.log(rule.name, path, "skip", reason="dirty git checkout")
            return "skip"
        if state == "error":
            ctx.bump(rule.name, "skip-git-error")
            ctx.log(rule.name, path, "skip", reason="git status failed")
            return "skip"
    if rule.open_files_gate and has_open_files(path):
        ctx.bump(rule.name, "skip-open-files")
        ctx.log(rule.name, path, "skip", reason="open files")
        return "skip"
    nbytes = tree_bytes(path)
    repo = parent_repo_of_worktree(path) if is_dir else None
    if ctx.mode != "apply":
        ctx.bump(rule.name, "delete", nbytes)
        ctx.targets.append((rule.name, path, nbytes))
        ctx.log(rule.name, path, "would-delete", nbytes, reason="%.1fd old" % age_days)
        return "would-delete"
    errors = []

    def onerror(fn, p, exc):
        errors.append("%s: %s" % (p, exc[1]))

    if is_dir:
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
    ctx.log(rule.name, path, "delete", nbytes, reason="%.1fd old" % age_days)
    if repo:
        ctx.prune_repos.add(repo)
    return "delete"


def expand_parents(ctx, rule):
    import glob
    out = []
    for pat in rule.parents:
        pat = pat.replace("{HOME}", ctx.home).replace("{TMP}", ctx.tmp)
        for p in sorted(glob.glob(pat)):
            if os.path.isdir(p) and not os.path.islink(p):
                out.append(p)
    return out


def run_rule(ctx, rule):
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
    if ctx.mode != "apply" or not uv:
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
    try:
        return shutil.disk_usage(path).free / 1e9
    except OSError:
        return -1.0


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
    ap.add_argument("--rules", default="", help="comma-separated subset of rule names")
    ap.add_argument("--list", action="store_true", help="print the rules and exit")
    ap.add_argument("--json", action="store_true", help="print the summary as JSON")
    ap.add_argument("--floor-gb", type=float, default=FLOOR_GB)
    args = ap.parse_args(argv)

    if args.list:
        for r in RULES:
            print("%-26s %-4s age>=%-3.0fd git=%s open=%s  %s" % (
                r.name, r.kind, r.min_age_days, r.git_gate, r.open_files_gate, ", ".join(r.parents)))
        return 0

    wanted = [s.strip() for s in args.rules.split(",") if s.strip()]
    rules = [r for r in RULES if not wanted or r.name in wanted]
    unknown = set(wanted) - set(r.name for r in RULES)
    if unknown:
        print("unknown rules: %s" % ", ".join(sorted(unknown)), file=sys.stderr)
        return 2

    ctx = Ctx("apply" if args.apply else "dry", rules)
    before = free_gb(ctx.home)
    for rule in rules:
        run_rule(ctx, rule)
    if ctx.mode == "apply":
        prune_worktrees(ctx)
        uv_prune(ctx)
    after = free_gb(ctx.home)

    total_bytes = sum(ctx.bytes.values())
    n_delete = sum(c.get("delete", 0) for c in ctx.counts.values())
    summary = {"run": ctx.run_id, "mode": ctx.mode, "free_gb_before": round(before, 2),
               "free_gb_after": round(after, 2), "targets": n_delete,
               "bytes": total_bytes, "errors": ctx.errors, "rules": ctx.counts}
    _append_json(ctx.log_path, {"ts": _iso(time.time()), "summary": summary})

    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        verb = "deleted" if ctx.mode == "apply" else "would delete"
        print("disk-janitor %s run %s: %s %d targets, %.2f GB (du-measured); free %.1f -> %.1f GB" % (
            ctx.mode, ctx.run_id, verb, n_delete, total_bytes / 1e9, before, after))
        for name in sorted(ctx.counts):
            c = ctx.counts[name]
            print("  %-26s %s  %.2f GB" % (name, " ".join("%s=%d" % kv for kv in sorted(c.items())),
                                          ctx.bytes.get(name, 0) / 1e9))
        if ctx.mode != "apply":
            for rname, path, nb in sorted(ctx.targets, key=lambda t: -t[2])[:10]:
                print("  %8.2f GB  %-22s %s" % (nb / 1e9, rname, path))

    if ctx.mode == "apply":
        if ctx.errors:
            notify(ctx, "disk-janitor: %d delete errors on run %s; see ~/.config/kipi/disk-janitor.log" % (
                ctx.errors, ctx.run_id))
        elif after >= 0 and after < args.floor_gb:
            notify(ctx, "disk-janitor: internal disk still at %.1f GB free after cleanup (floor %.0f GB); "
                        "junk rules are exhausted, the rest is real data" % (after, args.floor_gb))
    return 1 if ctx.errors else 0


if __name__ == "__main__":
    sys.exit(main())
