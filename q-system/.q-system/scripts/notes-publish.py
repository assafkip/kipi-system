#!/usr/bin/env python3
"""notes-publish: copy session notes and RCAs onto a notes-only `kipi/notes` branch.

ASK-2190 (plan: q-system/output/plans/notes-publish-2026-09-28.md). Cloud
sessions see only GitHub. The Stop hook `q-system/hooks/auto-commit.py` commits
notes on whatever branch is checked out and never pushes, so an instance's
`main` handoff went months stale while the fresh one sat on a feature branch,
and RCAs (under the ignored `q-system/output/**`) never reached git at all.

What it does, with git PLUMBING only (temp GIT_INDEX_FILE, hash-object -w,
update-index --cacheinfo, write-tree, commit-tree, push <sha>:refs/heads/kipi/notes):
  - it never checks out, and never touches HEAD, the index, the working tree,
    the checked-out branch or main; it never pushes code;
  - only allowlisted notes paths (`is_notes_path`) are ever added to the tree,
    mirroring chief/instance.py STATE_FILES / HANDOFF / CASE_FILES / ACTIVE_CASE
    plus `output/rca/*.md`;
  - an origin that is PUBLIC gets nothing, and so does one whose visibility
    cannot be proven (fail closed): unauthenticated GET https://github.com/<o>/<r>,
    200 public, 404 private, anything else unknown;
  - in the skeleton (instance-registry.json at the root, the same self-detection
    as instance-automation-guard) the repo is public, so its RCAs go to the
    consulting checkout's `kipi/notes` under `kipi-system/output/rca/` and its
    own handoff is published nowhere (founder choice b, 2026-09-28);
  - per path, BY LINEAGE, never by clocks (codex rounds 2-3, #464): a local file
    replaces the kipi/notes entry only when this checkout has SEEN that entry
    (its git history of the path, or its own record in the git dir of what it
    published or overlaid), or the path is absent there. Otherwise the entry is
    kept: `kept-newer-remote` when the branch's lineage (.kipi-notes-lineage.json,
    the versions each copy superseded) already holds the local copy,
    `kept-conflict` when both sides changed independently. A notes path deleted
    locally is removed from the branch only while the branch still holds a copy
    this checkout saw (instance mode only), and LINEAGE keeps a tombstone
    (`.deleted`) so a stale checkout still holding that exact copy never writes it
    back, and its overlay removes it; an empty collection still reaches deletion
    (codex round 4);
  - a legacy subtree instance's q-system/q-system/ is collected too, the root
    session-start.py reads the handoff from;
  - no change -> no commit; a rejected push (race) is refetched, rebuilt and
    retried once, then logged and dropped. Commits end `[skip ci]`.

`--overlay` is the READ side (codex major on #464: the branch had no consumer, so
a cloud session still loaded the stale default-branch handoff). It runs in every
session: fetch kipi/notes and write each allowlisted notes file whose branch copy
supersedes the local one, meaning the local content is already in the branch's
lineage (so nothing local is lost), or the local file is absent and this checkout
never saw that copy before deleting it. Round 3 made the Mac run it too: a checkout
that only publishes never learns another machine's copy and would keep-conflict
forever. It never writes a code path, never stages or commits, never writes through
a symlink; a local session prints only when it overlaid something.
Called from q-system/hooks/session-start.py before the handoff is loaded.

Called non-fatally at the end of auto-commit.py's main(). Always exits 0; every
outcome is one `notes-publish:` line on STDOUT (the fleet wiring discards the
hook's stderr). Test seam: KIPI_NOTES_VISIBILITY=public|private|unknown replaces
the network check. stdlib only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

BRANCH = "kipi/notes"
REF = "refs/heads/" + BRANCH
CONSULTING = "ASK_AI_consultant"
SKELETON_PREFIX = "kipi-system/output/rca/"
NET_TIMEOUT = 30          # per network git call; the hook caps the whole run
OVERLAY_TIMEOUT = 3       # per network git call on the SessionStart path (hook cap 5s)
HTTP_TIMEOUT = 5

# Mirrors chief/instance.py: HANDOFF, STATE_FILES, ACTIVE_CASE, CASE_FILES.
HANDOFF = "memory/last-handoff.md"
STATE_FILES = ("dashboard.md", "memory/investigation-state.md")
ACTIVE_CASE = ".active-case"
CASE_FILES = ("memory/last-handoff.md", "memory/investigation-state.md")

_NOTES_RE = re.compile(
    r"^(?:(?:q-system/)?q-[^/]+/(?:memory/last-handoff\.md|dashboard\.md|memory/investigation-state\.md"
    r"|\.active-case|investigations/case-[^/]+/memory/(?:last-handoff|investigation-state)\.md"
    r"|output/rca/[^/]+\.md)"
    r"|kipi-system/output/rca/[^/]+\.md)$")

_GH_RE = re.compile(
    r"^(?:https?://(?:[^@/]+@)?github\.com/|git@github\.com:|ssh://git@github\.com/)"
    r"([^/]+)/([^/]+?)(?:\.git)?/?$")


def is_notes_path(path: str) -> bool:
    """The single allowlist. Nothing outside it is ever added to kipi/notes."""
    if any(part in ("", ".", "..") for part in path.split("/")):
        return False
    return bool(_NOTES_RE.match(path))


def parse_github(url: str):
    m = _GH_RE.match(url.strip())
    return (m.group(1), m.group(2)) if m else None


def visibility_of(url: str, opener=urllib.request.urlopen) -> str:
    """'public' | 'private' | 'unknown'. Unknown means publish nothing."""
    gh = parse_github(url)
    if gh is None:
        return "unknown"
    req = urllib.request.Request(f"https://github.com/{gh[0]}/{gh[1]}", method="GET")
    try:
        with opener(req, timeout=HTTP_TIMEOUT) as resp:
            status = getattr(resp, "status", None)
    except urllib.error.HTTPError as e:
        status = e.code
    except Exception:
        return "unknown"
    return {200: "public", 404: "private"}.get(status, "unknown")


def _default_visibility(url: str) -> str:
    forced = os.environ.get("KIPI_NOTES_VISIBILITY", "").strip()
    if forced in ("public", "private", "unknown"):
        return forced
    return visibility_of(url)


def _plain_file(p: Path) -> bool:
    return p.is_file() and not p.is_symlink()


def collect_instance(root: Path) -> dict:
    """tree path -> source file, for every q-* dir (q-system included)."""
    out = {}
    nested = root / "q-system" / "q-system"   # legacy subtree layout, as session-start reads it
    for q in sorted(root.glob("q-*")) + ([nested] if nested.is_dir() else []):
        if not q.is_dir() or q.is_symlink():
            continue
        cands = [q / HANDOFF, q / ACTIVE_CASE] + [q / r for r in STATE_FILES]
        cands += [c / r for c in sorted((q / "investigations").glob("case-*")) for r in CASE_FILES]
        cands += sorted((q / "output" / "rca").glob("*.md"))
        for p in cands:
            if _plain_file(p):
                out[p.relative_to(root).as_posix()] = p
    return out


def collect_skeleton_rcas(root: Path) -> dict:
    out = {}
    for p in sorted((root / "q-system" / "output" / "rca").glob("*.md")):
        if _plain_file(p):
            out[SKELETON_PREFIX + p.name] = p
    return out


def is_skeleton(root: Path) -> bool:
    return (root / "instance-registry.json").exists()


def consulting_checkout(root: Path):
    try:
        reg = json.loads((root / "instance-registry.json").read_text())
    except (OSError, ValueError) as e:
        return None, f"could not read instance-registry.json ({e})"
    for inst in reg.get("instances", []) if isinstance(reg, dict) else []:
        if isinstance(inst, dict) and inst.get("name") == CONSULTING:
            path = Path(os.path.expanduser(str(inst.get("path", ""))))
            if (path / ".git").exists():
                return path, None
            return None, f"consulting checkout not found at {path}"
    return None, f"no {CONSULTING} entry in instance-registry.json"


class _Git:
    def __init__(self, repo: Path, index: str | None = None):
        env = {k: v for k, v in os.environ.items()
               if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")}
        env["GIT_TERMINAL_PROMPT"] = "0"
        if index:
            env["GIT_INDEX_FILE"] = index
        self.repo, self.env = repo, env

    def __call__(self, *args, timeout=NET_TIMEOUT):
        return subprocess.run(["git", *args], cwd=self.repo, env=self.env,
                              capture_output=True, text=True, timeout=timeout)


def _last(stderr: str) -> str:
    lines = [ln for ln in stderr.strip().splitlines() if ln.strip()]
    return lines[-1] if lines else "no error text"


LINEAGE = ".kipi-notes-lineage.json"   # on kipi/notes only; never a notes path, never overlaid
DELETED = ".deleted"                    # LINEAGE key: path -> versions a checkout deleted (round 4)
LINEAGE_CAP = 200                       # versions kept per path, newest last
SEEN_FILE = "kipi-notes-seen.json"      # under this checkout's git dir, never committed


def _parse_json(text: str) -> dict:
    try:
        val = json.loads(text)
    except ValueError:
        return {}
    return val if isinstance(val, dict) else {}


def _cap(shas) -> list:
    out = []
    for sha in shas:
        if sha in out:
            out.remove(sha)
        out.append(sha)
    return out[-LINEAGE_CAP:]


def _lineage(g: _Git, commit) -> dict:
    """path -> every blob kipi/notes' copy of that path has superseded or holds."""
    if not commit:
        return {}
    r = g("show", f"{commit}:{LINEAGE}", timeout=10)
    return _parse_json(r.stdout) if r.returncode == 0 else {}


class _History:
    """What THIS checkout has seen of each notes path (codex round 3, #464).

    why: round 2 compared the local file's commit time with kipi/notes' commit
    time. Those clocks come from unrelated histories, so a stale session that
    committed later still overwrote the fresher handoff. Decisions are now by
    content lineage: a checkout replaces the branch copy only when it has seen
    that exact copy (in its git history, or recorded here when it published or
    overlaid it), and the branch carries LINEAGE so a reader can tell whether its
    own copy was already superseded. Timestamps decide nothing.
    """

    def __init__(self, repo: Path, tracks_deletions: bool):
        self.repo, self.g, self.tracks_deletions = repo, _Git(repo), tracks_deletions
        self._rec = None

    def _rec_path(self) -> Path:
        p = self.g("rev-parse", "--git-path", SEEN_FILE, timeout=10).stdout.strip()
        return Path(p) if os.path.isabs(p) else self.repo / p

    def _record(self) -> dict:
        if self._rec is None:
            try:
                self._rec = _parse_json(self._rec_path().read_text())
            except OSError:
                self._rec = {}
        return self._rec

    def versions(self, rel: str) -> list:
        """Every blob `rel` has held in local history, oldest first."""
        out = self.g("log", "--reverse", "-m", "--format=", "--raw", "--no-abbrev",
                     "HEAD", "--", rel, timeout=10).stdout
        shas = []
        for line in out.splitlines():
            if line.startswith(":"):
                shas += [s for s in line.split("\t", 1)[0].split()[2:4] if s.strip("0")]
        return _cap(shas)

    def seen(self, tree_path: str, rel: str) -> set:
        return set(self.versions(rel)) | set(self._record().get(tree_path, []))

    def remember(self, tree_path: str, sha: str) -> None:
        rec = self._record()
        rec[tree_path] = _cap(list(rec.get(tree_path, [])) + [sha])

    def save(self) -> None:
        if self._rec is None:
            return
        p = self._rec_path()
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(self._rec, indent=1, sort_keys=True) + "\n")
        os.replace(tmp, p)


def _entries(g: _Git, commit) -> dict:
    """path -> blob sha on a notes commit ({} for none)."""
    if not commit:
        return {}
    out = {}
    for rec in g("ls-tree", "-r", "-z", commit).stdout.split("\0"):
        if "\t" in rec:
            meta, path = rec.split("\t", 1)
            out[path] = meta.split()[2]
    return out


def _hash_bytes(g: _Git, data: bytes) -> str:
    with tempfile.NamedTemporaryFile(delete=False) as fh:
        fh.write(data)
    try:
        return g("hash-object", "-w", "--no-filters", fh.name).stdout.strip()
    finally:
        os.unlink(fh.name)


def _stage_notes(gi: _Git, parent, files: dict, history: _History) -> dict:
    """Per path: replace the branch copy only when this checkout has seen it.

    A branch copy this checkout never saw is kept: `kept-newer-remote` when the
    branch already superseded the local copy (it is in LINEAGE), `kept-conflict`
    when both sides changed independently. A deletion propagates only when the
    branch still holds a version this checkout saw before deleting it.
    Returns {written, kept, conflict, removed, remember, error}.
    """
    entries, lineage = _entries(gi, parent), _lineage(gi, parent)
    tombs = lineage.setdefault(DELETED, {})
    res = {"written": [], "kept": [], "conflict": [], "removed": [], "deleted_remote": [],
           "remember": [], "error": None}
    for path, src in sorted(files.items()):
        if not is_notes_path(path):          # belt and braces: never code
            continue
        h = gi("hash-object", "-w", "--no-filters", str(src))
        if h.returncode != 0:
            res["error"] = f"hash-object failed for {path} ({_last(h.stderr)})"
            return res
        sha, remote = h.stdout.strip(), entries.get(path)
        res["remember"].append((path, sha))
        if remote == sha:
            continue
        rel = src.relative_to(history.repo).as_posix()
        if remote is None and sha in tombs.get(path, ()):
            # codex round 4: another checkout deleted exactly this copy; a stale
            # checkout that still holds it must not bring it back.
            res["deleted_remote"].append(path)
            continue
        if remote is not None and remote not in history.seen(path, rel):
            res["kept" if sha in lineage.get(path, ()) else "conflict"].append(path)
            continue
        u = gi("update-index", "--add", "--cacheinfo", f"100644,{sha},{path}")
        if u.returncode != 0:
            res["error"] = f"update-index failed for {path} ({_last(u.stderr)})"
            return res
        lineage[path] = _cap(list(lineage.get(path, [])) + ([remote] if remote else [])
                             + history.versions(rel) + [sha])
        tombs.pop(path, None)                # recreated with new content: live again
        res["written"].append(path)
    for path in sorted(set(entries) - set(files)):
        if not is_notes_path(path) or path.startswith(SKELETON_PREFIX) or not history.tracks_deletions:
            continue
        if os.path.lexists(history.repo / path) or entries[path] not in history.seen(path, path):
            continue
        if gi("update-index", "--force-remove", "--", path).returncode == 0:
            res["removed"].append(path)
            tombs[path] = _cap(list(lineage.pop(path, [])) + [entries[path]])
    if res["written"] or res["removed"]:
        body = json.dumps(lineage, indent=1, sort_keys=True).encode() + b"\n"
        gi("update-index", "--add", "--cacheinfo", f"100644,{_hash_bytes(gi, body)},{LINEAGE}")
    return res


def _kept_suffix(res: dict) -> str:
    out = ""
    if res["kept"]:
        out += f"; kept-newer-remote: {', '.join(res['kept'])}"
    if res["conflict"]:
        out += f"; kept-conflict (both sides changed, remote kept): {', '.join(res['conflict'])}"
    if res["deleted_remote"]:
        out += f"; not republished (deleted elsewhere): {', '.join(res['deleted_remote'])}"
    return out


def _build_and_push(g: _Git, files: dict, label: str, history: _History):
    """One attempt. Returns (done, line); done=False means retryable push rejection."""
    r = g("ls-remote", "origin", REF)
    if r.returncode != 0:
        return True, f"{label}: could not reach origin ({_last(r.stderr)}); publishing nothing"
    parent = r.stdout.split()[0] if r.stdout.strip() else None
    if not parent and not files:
        return True, f"{label}: no notes files; nothing to publish"
    if parent:
        r = g("fetch", "-q", "origin", f"+{REF}:refs/remotes/origin/{BRANCH}")
        if r.returncode != 0:
            return True, f"{label}: could not fetch {BRANCH} ({_last(r.stderr)}); publishing nothing"

    tmp = tempfile.mkdtemp(prefix="notes-publish-")
    try:
        gi = _Git(g.repo, index=os.path.join(tmp, "index"))
        r = gi("read-tree", parent) if parent else gi("read-tree", "--empty")
        if r.returncode != 0:
            return True, f"{label}: read-tree failed ({_last(r.stderr)})"
        res = _stage_notes(gi, parent, files, history)
        if res["error"]:
            return True, f"{label}: {res['error']}"
        tree = gi("write-tree").stdout.strip()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if not tree:
        return True, f"{label}: write-tree produced nothing"
    if parent and g("rev-parse", f"{parent}^{{tree}}").stdout.strip() == tree:
        _remember(history, res, published=False)
        return True, f"{label}: no change since {parent[:9]}; nothing to publish{_kept_suffix(res)}"

    env_id = {}
    if not g("config", "user.email").stdout.strip():
        env_id = {"GIT_AUTHOR_NAME": "kipi-notes", "GIT_AUTHOR_EMAIL": "kipi-notes@localhost",
                  "GIT_COMMITTER_NAME": "kipi-notes", "GIT_COMMITTER_EMAIL": "kipi-notes@localhost"}
    g.env.update(env_id)
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    args = ["commit-tree", tree, "-m", f"notes: session notes {stamp} [skip ci]"]
    if parent:
        args[2:2] = ["-p", parent]
    c = g(*args)
    if c.returncode != 0:
        return True, f"{label}: commit-tree failed ({_last(c.stderr)})"
    sha = c.stdout.strip()
    p = g("push", "-q", "origin", f"{sha}:{REF}")
    if p.returncode != 0:
        return False, _last(p.stderr)
    _remember(history, res, published=True)
    gone = f", removed {len(res['removed'])}: {', '.join(res['removed'])}" if res["removed"] else ""
    return True, (f"{label}: published {len(res['written'])} file(s){gone} to origin {BRANCH} "
                  f"({sha[:9]}){_kept_suffix(res)}")


def _remember(history: _History, res: dict, published: bool) -> None:
    """Record the versions the branch now holds as seen: equal ones always,
    written ones only once the push landed."""
    blocked = set(res["kept"]) | set(res["conflict"])
    for path, sha in res["remember"]:
        if path not in blocked and (published or path not in res["written"]):
            history.remember(path, sha)
    history.save()


def publish_to(target: Path, files: dict, visibility, label: str, history: _History) -> list:
    if not files and not history.tracks_deletions:
        return [f"{label}: no notes files; nothing to publish"]
    g = _Git(target)
    r = g("remote", "get-url", "origin", timeout=10)
    if r.returncode != 0 or not r.stdout.strip():
        return [f"{label}: no origin remote; publishing nothing"]
    url = r.stdout.strip()
    vis = visibility(url)
    if vis == "public":
        return [f"{label}: origin is public; publishing nothing to it"]
    if vis != "private":
        return [f"{label}: origin visibility unknown ({vis}); publishing nothing"]
    lines = []
    for attempt in (1, 2):
        done, line = _build_and_push(g, files, label, history)
        if done:
            return lines + [line]
        if attempt == 1:
            lines.append(f"{label}: push rejected ({line}); refetching and retrying once")
        else:
            lines.append(f"{label}: push failed twice ({line}); stopping")
    return lines


def run(repo: str, visibility=None) -> list:
    visibility = visibility or _default_visibility
    root = Path(repo).resolve()
    if not (root / ".git").exists():
        return ["notes-publish: not a git checkout; nothing to publish"]
    if is_skeleton(root):
        rcas = collect_skeleton_rcas(root)
        if not rcas:
            return ["notes-publish: skeleton has no RCAs; nothing to publish"]
        target, why = consulting_checkout(root)
        if target is None:
            return [f"notes-publish: skeleton RCAs not published: {why}"]
        # The skeleton's history says nothing about consulting's own paths: no deletions.
        return publish_to(target, rcas, visibility, "notes-publish (skeleton RCAs -> consulting)",
                          _History(root, tracks_deletions=False))
    return publish_to(root, collect_instance(root), visibility, "notes-publish",
                      _History(root, tracks_deletions=True))


def is_remote_session(env=None) -> bool:
    """The cloud (web) session runtime sets CLAUDE_CODE_REMOTE=true in the session env."""
    env = os.environ if env is None else env
    return env.get("CLAUDE_CODE_REMOTE", "").strip().lower() in ("1", "true", "yes")


def _unsafe_target(root: Path, rel: str) -> bool:
    """True when writing root/rel would go through a symlink anywhere on the way."""
    p = root
    for part in rel.split("/"):
        p = p / part
        if p.is_symlink():
            return True
    return False


def _overlay_wanted(g: _Git, root: Path, rel: str, remote: str, lineage: dict,
                    history: _History) -> bool:
    """Does the kipi/notes copy of `rel` supersede what this checkout holds?

    Lineage, never clocks (codex round 3, #464). An absent local file is written
    unless this checkout saw that exact copy and then deleted it (a closed
    .active-case must not come back). A present one is replaced only when its
    exact content is already in the branch's lineage, so nothing local is lost:
    an uncommitted or independent local edit is never in it.
    """
    dest = root / rel
    if not dest.exists():
        return remote not in history.seen(rel, rel)
    local = g("hash-object", "--no-filters", str(dest), timeout=10).stdout.strip()
    if local == remote:
        history.remember(rel, remote)
        return False
    return bool(local) and local in lineage.get(rel, ())


def _consume_deletions(g: _Git, root: Path, entries: dict, tombs: dict) -> list:
    """Remove local copies another checkout deleted (codex round 4, #464).

    Only when the local content is EXACTLY a deleted version: an edit made after
    the deletion is new work and stays. Unstaged, like every overlay write.
    """
    removed = []
    for rel, shas in sorted(tombs.items()):
        if rel in entries or not is_notes_path(rel) or rel.startswith(SKELETON_PREFIX):
            continue
        if _unsafe_target(root, rel) or not (root / rel).is_file():
            continue
        local = g("hash-object", "--no-filters", str(root / rel), timeout=10).stdout.strip()
        if local and local in shas:
            (root / rel).unlink()
            removed.append(rel)
    return removed


def overlay(repo: str, remote=None) -> list:
    """Write kipi/notes files that supersede the local copy into the tree. Never stages.

    Runs in every session (round 3): a checkout that only ever publishes never
    learns a copy another machine wrote, and would keep-conflict forever. A
    local session prints only when it overlaid something.
    """
    quiet = not (is_remote_session() if remote is None else remote)
    root = Path(repo).resolve()
    if not (root / ".git").exists():
        return [] if quiet else ["notes-overlay: not a git checkout; nothing to overlay"]
    g = _Git(root)
    r = g("ls-remote", "origin", REF, timeout=OVERLAY_TIMEOUT)
    if r.returncode != 0:
        return [] if quiet else [f"notes-overlay: could not reach origin ({_last(r.stderr)}); nothing overlaid"]
    if not r.stdout.strip():
        return [] if quiet else [f"notes-overlay: origin has no {BRANCH}; nothing to overlay"]
    rref = f"refs/remotes/origin/{BRANCH}"
    r = g("fetch", "-q", "origin", f"+{REF}:{rref}", timeout=OVERLAY_TIMEOUT)
    if r.returncode != 0:
        return [] if quiet else [f"notes-overlay: could not fetch {BRANCH} ({_last(r.stderr)}); nothing overlaid"]
    tip = g("rev-parse", rref).stdout.strip()
    entries, lineage = _entries(g, rref), _lineage(g, rref)
    history = _History(root, tracks_deletions=True)
    written = []
    for rel, sha in sorted(entries.items()):
        # The allowlist is the only gate; kipi-system/ entries mirror ANOTHER repo's
        # RCAs (the skeleton's), so they are not this working tree's files.
        if not is_notes_path(rel) or rel.startswith(SKELETON_PREFIX) or _unsafe_target(root, rel):
            continue
        if not _overlay_wanted(g, root, rel, sha, lineage, history):
            continue
        blob = subprocess.run(["git", "cat-file", "blob", sha], cwd=root,
                              env=g.env, capture_output=True, timeout=10)
        if blob.returncode != 0:
            continue
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(blob.stdout)
        history.remember(rel, sha)
        written.append(rel)
    removed = _consume_deletions(g, root, entries, lineage.get(DELETED, {}))
    history.save()
    if not written and not removed:
        return [] if quiet else [f"notes-overlay: nothing newer on origin {BRANCH} ({tip[:9]})"]
    gone = f"; removed (deleted elsewhere): {', '.join(removed)}" if removed else ""
    return [f"notes-overlay: overlaid {len(written)} file(s) from origin {BRANCH} "
            f"({tip[:9]}), unstaged: {', '.join(written) or 'none'}{gone}"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    ap.add_argument("--overlay", action="store_true",
                    help="read side: write newer kipi/notes files into a remote session's tree")
    args = ap.parse_args(argv)
    try:
        for line in (overlay(args.repo) if args.overlay else run(args.repo)):
            print(line)
    except Exception as e:  # never fatal: the callers are Stop / SessionStart hooks
        print(f"notes-{'overlay' if args.overlay else 'publish'}: error: {type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
