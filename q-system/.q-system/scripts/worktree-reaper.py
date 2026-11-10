#!/usr/bin/env python3
"""Remove finished agent worktrees, and alarm when the disk is low (ASK-2882).

THE SCAR, 2026-10-22 about 14:20 PT. The Data volume reached 0 bytes free. Every
shell, agent and launchd write failed with ENOSPC. ~/projects/_wt held 14 GB:
about 35 consulting worktrees at ~390 MB each, most for PRs merged days before.
Agents create worktrees and nothing ever removed them.

WHAT "FINISHED" MEANS. A worktree is removed only when ALL of these hold:
  - it sits under one of the configured roots (worktree-reaper.json), and is a
    linked worktree (`.git` is a file), never a primary checkout;
  - `git status --porcelain` is empty: no modified and no untracked files;
  - it is not locked (`git worktree lock`), and for a review tree no live
    pr-review-agent.sh run holds its `<tree>.lock`;
  - no process has its working directory inside it (an agent still in it);
  - git has not touched it for `min_idle_hours`;
  - its HEAD is already on origin's default branch, OR a GitHub PR for its
    branch or HEAD is merged or closed and no PR for it is open. A review tree
    (review-trees/<owner>_<repo>__pr-<N>) is matched by the N in its name.
Anything else is kept, and the log says why. A PR lookup that FAILED keeps the
tree as "PR lookup failed" and is counted in the summary line, never read as
"no PR found" (ASK-4390).

NEVER rm. Removal is `git worktree remove` WITHOUT --force, so git itself
refuses a tree that is not clean, and no ref is ever deleted. A branch tree's
commits stay on its branch. A review tree is DETACHED and has no branch, so it
goes only when its HEAD is on a remote-tracking ref (review_worktree puts the
reviewed head on refs/remotes/pr/<N>); otherwise it is kept as "detached HEAD
is on no remote ref". Either way a removed worktree loses no commit. A review
tree is also CLAIMED through pr-review-agent.sh's own lock protocol before it is
removed (see _claim_review_tree). If the open-process census cannot be taken
(lsof fails), nothing is removed that run.

Dry run by default. `--apply` removes. The daily job (com.kipi.worktree-reaper)
runs with --apply. After the pass, free space under `alarm_below_gb` files one
deduplicated alert through alert-to-linear.py.
"""
from __future__ import annotations

import argparse
import fcntl
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG = os.path.join(HERE, "..", "worktree-reaper.json")
ALERT = os.path.join(HERE, "alert-to-linear.py")
DEFAULTS = {"roots": [], "min_idle_hours": 6, "alarm_below_gb": 10,
            "refuse_worktree_below_gb": 5}
LOOKUP_FAILED = "PR lookup failed"
# pr-review-agent.sh review_tree_path: <state>/review-trees/<artifact_key>__pr-<N>.
REVIEW_TREE = re.compile(r"^(?P<key>.+)__pr-(?P<n>[0-9]+)$")
# acquire_wt_lock's mutex: ONE per review-trees directory, never unlinked.
REVIEW_MUTEX = ".tree-lock.mutex"
REVIEW_MUTEX_WAIT_S = 5      # acquire_wt_lock's own deadline for the same flock
EMPTY_LOCK_GRACE_S = 5       # an empty .lock is a claim mid-create only this long
LOCK_HELD = "a review run holds its lock"


def load_config(path: str | None = None) -> dict:
    path = path or os.environ.get("KIPI_WORKTREE_REAPER_CONFIG") or DEFAULT_CONFIG
    cfg = dict(DEFAULTS)
    try:
        with open(path, encoding="utf-8") as fh:
            cfg.update({k: v for k, v in json.load(fh).items() if not k.startswith("_")})
    except (OSError, ValueError) as exc:
        print(f"worktree-reaper: config {path} unreadable ({exc}); using defaults",
              file=sys.stderr)
    return cfg


def free_gb(path: str = "/") -> float:
    return shutil.disk_usage(path).free / 2**30


def _git(cwd: str, *args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True,
                          timeout=timeout)


def candidates(roots: list[str]) -> list[str]:
    """Linked worktrees under the roots. A primary checkout has a .git DIRECTORY."""
    found = set()
    for root in roots:
        for p in glob.glob(os.path.expanduser(root)):
            if os.path.isfile(os.path.join(p, ".git")):
                found.add(os.path.realpath(p))
    return sorted(found)


def held_dirs() -> list[str] | None:
    """Working directories of every process. None when the census fails."""
    try:
        out = subprocess.run(["lsof", "-a", "-d", "cwd", "-Fn"], capture_output=True,
                             text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode not in (0, 1) or not out.stdout:
        return None
    return [os.path.realpath(line[1:]) for line in out.stdout.splitlines()
            if line.startswith("n/")]


def _in_use(wt: str, held: list[str]) -> bool:
    return any(h == wt or h.startswith(wt + os.sep) for h in held)


def _idle_hours(gitdir: str, now: float) -> float:
    stamps = []
    for name in ("index", "HEAD", os.path.join("logs", "HEAD")):
        try:
            stamps.append(os.path.getmtime(os.path.join(gitdir, name)))
        except OSError:
            pass
    return (now - max(stamps)) / 3600 if stamps else float("inf")


def _locked(gitdir: str) -> bool:
    return os.path.exists(os.path.join(gitdir, "locked"))


def _is_review_tree(wt: str) -> bool:
    return os.path.basename(os.path.dirname(wt)) == "review-trees"


def _lock_holder(lock: str) -> tuple[bool, str]:
    """(live?, text) for a review tree's `<tree>.lock`.

    acquire_wt_lock writes the run's PID there. release_wt_lock deletes it on a
    clean exit, but a killed run leaves it: 114 named a dead PID on 2026-11-10.
    So only a live holder counts, decided the way that script's proven_dead()
    decides it. An unreadable lock counts as live. An EMPTY one is a claim
    mid-create, live for EMPTY_LOCK_GRACE_S only: acquire_wt_lock reclaims an
    empty lock after 0.2 s, and one that stayed live forever pinned a merged
    tree under a false reason (PR #731 round 1, finding 2)."""
    try:
        with open(lock, encoding="ascii", errors="replace") as fh:
            text = fh.read().strip()
        age = time.time() - os.path.getmtime(lock)
    except FileNotFoundError:
        return False, ""
    except OSError:
        return True, ""
    if text == "":
        return age < EMPTY_LOCK_GRACE_S, text
    try:
        pid = int(text)
    except ValueError:
        return False, text
    if pid <= 0:
        return False, text
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, OverflowError):
        return False, text
    except PermissionError:
        return True, text
    return True, text


def _review_lock_held(wt: str) -> bool:
    """Cheap pre-filter at verdict time. The claim below is the real check."""
    return _is_review_tree(wt) and _lock_holder(wt + ".lock")[0]


def _claim_review_tree(wt: str) -> tuple[str | None, str]:
    """Claim a review tree for this process by acquire_wt_lock's protocol, so a
    review cannot take it between the last check and `git worktree remove`.

    PR #731 round 1, finding 1: reading the lock outside the claim mutex left that
    window open, and a review that claimed in it lost its tree mid-run. Same steps
    as acquire_wt_lock: an flock on the directory's one mutex file (never
    unlinked), the holder read INSIDE it, and the PID written by link() so the
    file is never seen empty. The flock is dropped right after the claim, not held
    through the remove: it covers EVERY tree in the directory, and a review that
    waits on it over REVIEW_MUTEX_WAIT_S reads "ownership unknown" and stops, so
    holding it through a multi-second remove would stop unrelated reviews. The PID
    claim is what turns a late review away (acquire_wt_lock returns 2, busy).
    Returns (lock path, "") when claimed, else (None, why)."""
    lock = wt + ".lock"
    me = str(os.getpid())
    try:
        fd = os.open(os.path.join(os.path.dirname(wt), REVIEW_MUTEX),
                     os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    except OSError as exc:
        return None, f"review lock could not be taken ({exc.strerror})"
    try:
        deadline = time.monotonic() + REVIEW_MUTEX_WAIT_S
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() > deadline:
                    return None, "review lock could not be taken (mutex busy)"
                time.sleep(0.02)
        live, text = _lock_holder(lock)
        if live:
            return (lock, "") if text == me else (None, LOCK_HELD)
        tmp = f"{lock}.{me}.tmp"
        try:
            try:
                os.unlink(lock)
            except FileNotFoundError:
                pass
            with open(tmp, "w", encoding="ascii") as fh:
                fh.write(me)
            os.link(tmp, lock)
        except OSError as exc:
            return None, f"review lock could not be taken ({exc.strerror})"
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        return lock, ""
    finally:
        os.close(fd)   # drops the flock; the mutex file itself stays


def _release_review_claim(lock: str | None) -> None:
    """Give the claim back, only while it still names this process."""
    if not lock:
        return
    try:
        with open(lock, encoding="ascii", errors="replace") as fh:
            if fh.read().strip() != str(os.getpid()):
                return
        os.unlink(lock)
    except OSError:
        pass


def _on_remote_ref(wt: str, head: str) -> bool:
    """Every commit of HEAD is on some refs/remotes/* ref, so removing a DETACHED
    tree loses none (PR #731 round 1, finding 3). A failed read keeps the tree."""
    r = _git(wt, "rev-list", "-n", "1", head, "--not", "--remotes")
    return r.returncode == 0 and not r.stdout.strip()


def _slug(url: str) -> str | None:
    m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?/?$", url.strip())
    return m.group(1) if m else None


def _artifact_key(slug: str) -> str:
    """repo-slug-lib.sh artifact_key's stem: `/` -> `_`, then [^A-Za-z0-9._-] -> `_`."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", slug.replace("/", "_"))


class Repo:
    """Per-repository facts, looked up once per run, not once per worktree."""

    def __init__(self, common_dir: str):
        self.common_dir = common_dir
        self.primary = os.path.dirname(common_dir.rstrip(os.sep))
        self._default = None
        self._slug = ""
        self._prs: list[dict] | None = None
        self._looked_up = False

    def default_ref(self) -> str | None:
        if self._default is None:
            # NO FETCH. The first live dry run fetched every repo and one fetch
            # wrote a 2.2 GB pack while the disk had 2 GB free (2026-10-23).
            # A stale origin ref only keeps more trees; the PR lookup covers merges.
            r = _git(self.primary, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
            ref = r.stdout.strip() if r.returncode == 0 else ""
            if not ref:
                for guess in ("origin/main", "origin/master"):
                    if _git(self.primary, "rev-parse", "--verify", "-q", guess).returncode == 0:
                        ref = guess
                        break
            self._default = ref
        return self._default or None

    def slug(self) -> str | None:
        if self._slug == "":
            # The configured URL, not `remote get-url`: get-url applies insteadOf
            # rewrites, and the slug must name the GitHub repo either way.
            r = _git(self.primary, "config", "--get", "remote.origin.url")
            self._slug = (_slug(r.stdout) if r.returncode == 0 else None) or None
        return self._slug

    def prs(self) -> list[dict] | None:
        """Every PR of this repo, [] when it has no GitHub remote, and None when the
        lookup FAILED. ASK-4390: this used to return [] on a gh error too, so the
        GitHub outage of 2026-11-10 (TLS handshake timeout) read as "no PR found"
        for 27 trees. A failure that looks like an answer cannot be seen."""
        if not self._looked_up:
            self._looked_up = True
            slug = self.slug()
            if not slug:
                self._prs = []
                return self._prs
            why = ""
            try:
                out = subprocess.run(
                    ["gh", "pr", "list", "-R", slug, "--state", "all", "--limit", "1000",
                     "--json", "number,state,headRefName,headRefOid"],
                    capture_output=True, text=True, timeout=120)
                if out.returncode == 0:
                    prs = json.loads(out.stdout or "[]")
                    if isinstance(prs, list):
                        self._prs = prs
                    else:
                        why = "gh output is not a list"
                else:
                    lines = (out.stderr or out.stdout).strip().splitlines()
                    why = f"gh exit {out.returncode}: {lines[0] if lines else 'no output'}"
            except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
                why = f"{type(exc).__name__}: {exc}"
            if self._prs is None:
                print(f"worktree-reaper: {LOOKUP_FAILED} for {slug} ({why}); "
                      f"its unmerged trees are kept")
        return self._prs

    def review_pr(self, wt: str) -> int | None:
        """N for review-trees/<key>__pr-<N> when <key> is THIS repo's key, else None.
        Detached at the head it reviewed, such a tree matches no PR by headRefOid
        after a later push, and by branch never (ASK-4390: 8 trees, 0.43 GB)."""
        m = REVIEW_TREE.match(os.path.basename(wt)) if _is_review_tree(wt) else None
        slug = self.slug()
        if not m or not slug or m.group("key") != _artifact_key(slug):
            return None
        return int(m.group("n"))


def verdict(wt: str, repos: dict, held: list[str], cfg: dict, now: float) -> tuple[bool, str]:
    """(remove?, reason). Every keep names the check that kept it."""
    r = _git(wt, "rev-parse", "--absolute-git-dir", "--git-common-dir", "HEAD")
    if r.returncode != 0:
        return False, "git cannot read it"
    gitdir, common, head = r.stdout.splitlines()[:3]
    common = os.path.realpath(os.path.join(wt, common))
    # Idle is read BEFORE status, and status runs without optional locks:
    # a plain `git status` refreshes and rewrites the index, so measuring after
    # it read every tree as touched seconds ago (dry run 2026-10-23: 50 trees).
    idle = _idle_hours(gitdir, now)
    st = _git(wt, "--no-optional-locks", "status", "--porcelain")
    if st.returncode != 0 or st.stdout.strip():
        return False, "has uncommitted or untracked files"
    if _locked(gitdir):
        return False, "locked"
    if _review_lock_held(wt):
        return False, LOCK_HELD
    if _in_use(wt, held):
        return False, "a process is working in it"
    if idle < cfg["min_idle_hours"]:
        return False, f"touched {idle:.1f}h ago"
    repo = repos.setdefault(common, Repo(common))
    ref = repo.default_ref()
    if ref and _git(wt, "merge-base", "--is-ancestor", head, ref).returncode == 0:
        return True, f"already on {ref}"
    prs = repo.prs()
    if prs is None:
        return False, LOOKUP_FAILED
    n = repo.review_pr(wt)
    if n is not None:
        mine = [p for p in prs if p.get("number") == n]
    else:
        b = _git(wt, "symbolic-ref", "--short", "-q", "HEAD")
        branch = b.stdout.strip() if b.returncode == 0 else ""
        mine = [p for p in prs
                if p.get("headRefOid") == head or (branch and p.get("headRefName") == branch)]
    if not mine:
        return False, "not merged and no PR found"
    open_ = [p for p in mine if p.get("state") == "OPEN"]
    if open_:
        return False, f"PR #{open_[0].get('number')} is open"
    if n is not None and not _on_remote_ref(wt, head):
        return False, "detached HEAD is on no remote ref"
    p = mine[0]
    return True, f"PR #{p.get('number')} {str(p.get('state')).lower()}"


def remove(wt: str) -> tuple[bool, str]:
    r = _git(wt, "rev-parse", "--git-common-dir")
    primary = os.path.dirname(os.path.realpath(os.path.join(wt, r.stdout.strip())))
    out = _git(primary, "worktree", "remove", wt)   # no --force, ever
    return out.returncode == 0, (out.stderr or out.stdout).strip()


def alarm(cfg: dict, free: float) -> int:
    # The message is the same text every day the condition holds, so
    # alert-to-linear's fingerprint keeps ONE ticket and counts repeats. The
    # numbers that change go to this job's log, which the message points at.
    msg = (f"[disk-floor] Free disk space on this Mac is under the "
           f"{cfg['alarm_below_gb']} GB floor after the daily worktree reaper ran. "
           f"Numbers and the kept worktrees are in ~/.config/kipi/worktree-reaper.out")
    print(f"worktree-reaper: ALARM free={free:.1f}GB floor={cfg['alarm_below_gb']}GB")
    try:
        return subprocess.run([sys.executable, ALERT, msg], timeout=120).returncode
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"worktree-reaper: alarm not filed ({exc})", file=sys.stderr)
        return 1


def run(cfg: dict, apply: bool, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    held = held_dirs()
    if held is None:
        print("worktree-reaper: could not list open working directories; removing nothing")
    repos: dict = {}
    removed, kept, failed = [], [], []
    for wt in candidates(cfg["roots"]):
        if held is None:
            kept.append((wt, "process census failed"))
            continue
        try:
            ok, why = verdict(wt, repos, held, cfg, now)
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            ok, why = False, f"check failed ({exc})"
        if not ok:
            kept.append((wt, why))
        elif not apply:
            removed.append((wt, why + ", dry run"))
        else:
            # Census re-taken per tree, right before its remove (PR #556 review):
            # the one from the start of the pass cannot see an agent that resumed
            # a dormant, clean tree while earlier trees were being checked, and
            # `git worktree remove` does not refuse a tree a process is in.
            # A review tree is CLAIMED first and held through the remove, so a
            # review that claimed since the verdict keeps it, and one that comes
            # after is turned away (PR #731 round 1, finding 1).
            claim = None
            if _is_review_tree(wt):
                claim, busy = _claim_review_tree(wt)
                if claim is None:
                    kept.append((wt, busy))
                    continue
            try:
                live = held_dirs()
                if live is None or _in_use(wt, live):
                    kept.append((wt, "a process is working in it"))
                    continue
                done, err = remove(wt)
                (removed if done else failed).append((wt, why if done else err))
            finally:
                _release_review_claim(claim)
    for label, rows in (("removed", removed), ("kept", kept), ("FAILED", failed)):
        for wt, why in rows:
            print(f"{label}: {wt} ({why})")
    free = free_gb()
    lookup_failed = sum(1 for _, why in kept if why == LOOKUP_FAILED)
    print(f"worktree-reaper: removed={len(removed)} kept={len(kept)} failed={len(failed)} "
          f"pr_lookup_failed={lookup_failed} free={free:.1f}GB apply={apply}")
    alarmed = apply and free < cfg["alarm_below_gb"]
    if alarmed:
        alarm(cfg, free)
    return {"removed": [w for w, _ in removed], "kept": dict(kept),
            "failed": [w for w, _ in failed], "free_gb": free, "alarmed": alarmed,
            "pr_lookup_failed": lookup_failed}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true", help="remove (default: dry run)")
    ap.add_argument("--config", help="path to worktree-reaper.json")
    args = ap.parse_args(argv)
    result = run(load_config(args.config), args.apply)
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
