#!/usr/bin/env python3
"""notes-publish.py: session notes and RCAs reach GitHub on a notes-only branch.

ASK-2190 (plan: q-system/output/plans/notes-publish-2026-09-28.md). The Stop
hook `q-system/hooks/auto-commit.py` commits notes on whatever branch is checked
out and never pushes, so a cloud session (which sees only GitHub) reads a stale
handoff. notes-publish copies ONLY notes files onto `kipi/notes` on the repo's
own origin with git plumbing and never touches HEAD, the index, the working tree
or the checked-out branch.

Every repo here is a throwaway under tmp_path with a `git init --bare` remote.
Visibility is injected (KIPI_NOTES_VISIBILITY / a checker function); nothing in
this file reaches github.com. Fixture content is generic placeholder text only:
kipi-system is a public repo.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "notes-publish.py"
HOOK = HERE.parents[2] / "hooks" / "auto-commit.py"
BRANCH = "refs/heads/kipi/notes"


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path_factory, monkeypatch):
    # auto-commit's notify cache must never be the real ~/.cache/kipi.
    monkeypatch.setenv("KIPI_CACHE_HOME", str(tmp_path_factory.mktemp("cache")))
    monkeypatch.delenv("KIPI_NOTES_VISIBILITY", raising=False)
    for k in ("GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE"):
        monkeypatch.delenv(k, raising=False)


def git(cwd, *args, check=True):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise AssertionError(f"git {args} failed: {r.stderr}")
    return r


def make_repo(tmp_path, name="inst"):
    bare = tmp_path / f"{name}-remote.git"
    git(tmp_path, "init", "-q", "--bare", str(bare))
    root = tmp_path / name
    root.mkdir()
    git(root, "init", "-q", "-b", "work")
    git(root, "config", "user.email", "t@t.t")
    git(root, "config", "user.name", "t")
    git(root, "config", "commit.gpgsign", "false")
    git(root, "remote", "add", "origin", str(bare))
    (root / ".gitignore").write_text("q-*/output/**\n")
    (root / "README.md").write_text("placeholder\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "seed")
    return root, bare


def write(root, rel, body="placeholder\n"):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)
    return p


def remote_tip(bare):
    r = git(bare, "rev-parse", "--verify", "-q", BRANCH, check=False)
    return r.stdout.strip() or None


def remote_tree(bare):
    return sorted(git(bare, "ls-tree", "-r", "--name-only", BRANCH).stdout.split())


LINEAGE = ".kipi-notes-lineage.json"


def notes_tree(bare):
    """The notes paths on kipi/notes, without the lineage manifest."""
    return [p for p in remote_tree(bare) if p != LINEAGE]


def commit_count(bare):
    return int(git(bare, "rev-list", "--count", BRANCH).stdout.strip())


def load():
    assert SCRIPT.is_file(), f"missing {SCRIPT}"
    spec = importlib.util.spec_from_file_location("notes_publish", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def publish(root, vis="private"):
    """Run the script as the hook would, visibility injected."""
    env = dict(os.environ, KIPI_NOTES_VISIBILITY=vis)
    return subprocess.run([sys.executable, str(SCRIPT), "--repo", str(root)],
                          capture_output=True, text=True, env=env, timeout=60)


def instance_notes(root):
    write(root, "q-ps/memory/last-handoff.md", "handoff v1\n")
    write(root, "q-ps/dashboard.md", "dashboard\n")
    write(root, "q-ps/memory/investigation-state.md", "state\n")
    write(root, "q-ps/.active-case", "case-001\n")
    write(root, "q-ps/investigations/case-001/memory/last-handoff.md", "case handoff\n")
    write(root, "q-ps/investigations/case-001/memory/investigation-state.md", "case state\n")
    write(root, "q-ps/output/rca/rca-sample-2026-09-28.md", "# RCA\n")


EXPECTED = sorted([
    "q-ps/memory/last-handoff.md",
    "q-ps/dashboard.md",
    "q-ps/memory/investigation-state.md",
    "q-ps/.active-case",
    "q-ps/investigations/case-001/memory/last-handoff.md",
    "q-ps/investigations/case-001/memory/investigation-state.md",
    "q-ps/output/rca/rca-sample-2026-09-28.md",
])


def snapshot(root):
    """Everything the publish must leave byte-identical."""
    files = {}
    for p in sorted(root.rglob("*")):
        if ".git" in p.relative_to(root).parts or not p.is_file():
            continue
        files[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return {
        "HEAD": (root / ".git" / "HEAD").read_bytes(),
        "head_sha": git(root, "rev-parse", "HEAD").stdout,
        "branch": git(root, "symbolic-ref", "HEAD").stdout,
        "index": (root / ".git" / "index").read_bytes(),
        "local_branches": git(root, "for-each-ref", "refs/heads").stdout,
        "status": git(root, "status", "--porcelain", "--ignored").stdout,
        "files": files,
    }


# --- the reproducer: a session end publishes the handoff ------------------

def test_session_end_publishes_the_handoff_to_kipi_notes(tmp_path):
    """RED on the old code: auto-commit never pushes, so no kipi/notes exists."""
    root, bare = make_repo(tmp_path)
    instance_notes(root)
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root), KIPI_NOTES_VISIBILITY="private")
    r = subprocess.run([sys.executable, str(HOOK)], cwd=root, env=env,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    assert remote_tip(bare), f"no kipi/notes on the remote\n{r.stdout}\n{r.stderr}"
    assert "q-ps/memory/last-handoff.md" in remote_tree(bare)
    assert git(bare, "show", f"{BRANCH}:q-ps/memory/last-handoff.md").stdout == "handoff v1\n"


def test_auto_commit_survives_a_broken_publish(tmp_path):
    """Non-fatal: an unreachable origin must not stop the hook or its commit."""
    root, _ = make_repo(tmp_path)
    git(root, "remote", "set-url", "origin", str(tmp_path / "does-not-exist.git"))
    write(root, "q-system/memory/last-handoff.md", "v1\n")
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root), KIPI_NOTES_VISIBILITY="private")
    r = subprocess.run([sys.executable, str(HOOK)], cwd=root, env=env,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0
    assert "q-system/memory/last-handoff.md" in git(root, "ls-files").stdout
    assert "auto-commit: done" in r.stdout


def test_auto_commit_calls_it_with_a_timeout():
    src = HOOK.read_text()
    assert "notes-publish.py" in src
    assert "timeout=" in src[src.index("def publish_notes"):]


# --- one commit, only notes, nothing local moved --------------------------

def test_one_commit_with_only_notes_and_the_checkout_untouched(tmp_path):
    root, bare = make_repo(tmp_path)
    instance_notes(root)
    before = snapshot(root)
    r = publish(root)
    assert r.returncode == 0, r.stderr
    assert notes_tree(bare) == EXPECTED, r.stdout
    assert LINEAGE in remote_tree(bare)
    assert commit_count(bare) == 1
    msg = git(bare, "log", "-1", "--format=%B", BRANCH).stdout
    assert "[skip ci]" in msg
    assert snapshot(root) == before


def test_second_run_without_change_makes_no_commit(tmp_path):
    root, bare = make_repo(tmp_path)
    instance_notes(root)
    publish(root)
    first = remote_tip(bare)
    r = publish(root)
    assert r.returncode == 0
    assert remote_tip(bare) == first
    assert "no change" in r.stdout
    write(root, "q-ps/memory/last-handoff.md", "handoff v2\n")
    publish(root)
    assert commit_count(bare) == 2
    assert git(bare, "show", f"{BRANCH}:q-ps/memory/last-handoff.md").stdout == "handoff v2\n"


def test_code_never_lands_in_kipi_notes(tmp_path):
    """Negative control: only the allowlisted notes paths are ever added."""
    root, bare = make_repo(tmp_path)
    instance_notes(root)
    write(root, "q-ps/pipeline/code.py", "print('x')\n")
    write(root, "q-ps/output/rca/evil.py", "print('x')\n")
    write(root, "q-ps/memory/other-notes.md", "x\n")
    write(root, "src/app.js", "x\n")
    git(root, "add", "q-ps/pipeline/code.py", "src/app.js")
    git(root, "commit", "-q", "-m", "code")
    publish(root)
    tree = notes_tree(bare)
    assert tree == EXPECTED
    assert not any(p.endswith((".py", ".js")) for p in tree)


def test_the_allowlist_itself_refuses_code_paths():
    mod = load()
    assert mod.is_notes_path("q-ps/memory/last-handoff.md")
    assert mod.is_notes_path("q-ps/output/rca/rca-x.md")
    assert mod.is_notes_path("kipi-system/output/rca/rca-x.md")
    for bad in ("q-ps/pipeline/code.py", "q-ps/output/rca/evil.py",
                "q-ps/output/rca/sub/x.md", "src/app.js", "q-ps/memory/x.md",
                "../q-ps/memory/last-handoff.md"):
        assert not mod.is_notes_path(bad), bad


# --- visibility: fail closed -----------------------------------------------

def test_public_origin_gets_nothing(tmp_path):
    root, bare = make_repo(tmp_path)
    instance_notes(root)
    r = publish(root, vis="public")
    assert remote_tip(bare) is None
    assert "public" in r.stdout


def test_unknown_visibility_pushes_nothing_and_says_why(tmp_path):
    root, bare = make_repo(tmp_path)
    instance_notes(root)
    r = publish(root, vis="unknown")
    assert remote_tip(bare) is None
    assert "visibility unknown" in r.stdout


def test_a_local_path_origin_is_unknown_without_injection(tmp_path, monkeypatch):
    """No override: a non-GitHub origin cannot be proven private, so nothing goes."""
    mod = load()
    root, bare = make_repo(tmp_path)
    instance_notes(root)
    called = []
    lines = mod.run(str(root), visibility=lambda url: called.append(url) or mod.visibility_of(url))
    assert remote_tip(bare) is None
    assert any("visibility unknown" in ln for ln in lines)


def test_github_url_parsing_and_status_mapping():
    mod = load()
    for url in ("https://github.com/o/r", "https://github.com/o/r.git",
                "git@github.com:o/r.git", "ssh://git@github.com/o/r.git",
                "https://x-access-token:abc@github.com/o/r.git"):
        assert mod.parse_github(url) == ("o", "r"), url
    assert mod.parse_github("/tmp/x.git") is None
    assert mod.parse_github("https://gitlab.com/o/r") is None

    class Resp:
        def __init__(self, status):
            self.status = status

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    import urllib.error

    def opener_for(outcome):
        def opener(req, timeout):
            assert req.full_url == "https://github.com/o/r"
            assert timeout <= 10
            if isinstance(outcome, int) and outcome >= 400:
                raise urllib.error.HTTPError(req.full_url, outcome, "x", {}, None)
            if isinstance(outcome, Exception):
                raise outcome
            return Resp(outcome)
        return opener

    url = "git@github.com:o/r.git"
    assert mod.visibility_of(url, opener=opener_for(200)) == "public"
    assert mod.visibility_of(url, opener=opener_for(404)) == "private"
    assert mod.visibility_of(url, opener=opener_for(429)) == "unknown"
    assert mod.visibility_of(url, opener=opener_for(OSError("no net"))) == "unknown"
    assert mod.visibility_of("/local/path.git", opener=opener_for(200)) == "unknown"


# --- choice b: the public skeleton routes RCAs to consulting ----------------

def test_skeleton_rcas_land_in_consulting_and_nothing_in_the_skeleton(tmp_path):
    mod = load()
    skel, skel_bare = make_repo(tmp_path, "skel")
    cons, cons_bare = make_repo(tmp_path, "cons")
    (skel / "instance-registry.json").write_text(json.dumps({
        "skeleton": {"name": "kipi-system"},
        "instances": [{"name": "ASK_AI_consultant", "path": str(cons)}],
    }))
    write(skel, "q-system/memory/last-handoff.md", "skeleton handoff\n")
    write(skel, "q-system/output/rca/rca-skel-2026-09-28.md", "# skeleton RCA\n")
    write(skel, "q-system/output/rca/notes.py", "x\n")
    cons_before = snapshot(cons)

    def vis(url):
        return "public" if url == str(skel_bare) else "private"

    lines = mod.run(str(skel), visibility=vis)
    assert remote_tip(skel_bare) is None, lines
    assert notes_tree(cons_bare) == ["kipi-system/output/rca/rca-skel-2026-09-28.md"], lines
    assert snapshot(cons) == cons_before

    # And a consulting origin that is not provably private gets nothing either.
    cons2, cons2_bare = make_repo(tmp_path, "cons2")
    (skel / "instance-registry.json").write_text(json.dumps({
        "instances": [{"name": "ASK_AI_consultant", "path": str(cons2)}]}))
    lines = mod.run(str(skel), visibility=lambda url: "unknown")
    assert remote_tip(cons2_bare) is None
    assert any("visibility unknown" in ln for ln in lines)


def test_skeleton_without_a_consulting_checkout_publishes_nothing(tmp_path):
    mod = load()
    skel, skel_bare = make_repo(tmp_path, "skel")
    (skel / "instance-registry.json").write_text(json.dumps({
        "instances": [{"name": "ASK_AI_consultant", "path": str(tmp_path / "absent")}]}))
    write(skel, "q-system/output/rca/rca-skel-2026-09-28.md", "# RCA\n")
    lines = mod.run(str(skel), visibility=lambda url: "private")
    assert remote_tip(skel_bare) is None
    assert any("consulting" in ln for ln in lines)


# --- race: a rejected push is rebuilt and retried once ---------------------

def test_a_rejected_push_is_retried_once(tmp_path):
    root, bare = make_repo(tmp_path)
    instance_notes(root)
    marker = tmp_path / "rejected-once"
    hook = bare / "hooks" / "pre-receive"
    hook.write_text(f"#!/bin/sh\nif [ ! -e '{marker}' ]; then touch '{marker}'; "
                    "echo 'simulated race' >&2; exit 1; fi\nexit 0\n")
    hook.chmod(0o755)
    r = publish(root)
    assert marker.exists()
    assert remote_tip(bare), r.stdout + r.stderr
    assert "retry" in r.stdout


def test_a_push_rejected_twice_stops_and_logs(tmp_path):
    root, bare = make_repo(tmp_path)
    instance_notes(root)
    hook = bare / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\necho 'always rejected' >&2\nexit 1\n")
    hook.chmod(0o755)
    r = publish(root)
    assert r.returncode == 0
    assert remote_tip(bare) is None
    assert "push failed" in r.stdout


# --- the consumer: a remote session overlays newer notes (codex major, #464) ---
#
# Publishing alone left kipi/notes with no reader in this repo: a cloud session
# opened on an instance repo still loaded the stale default-branch handoff.
# `--overlay` is that reader; session-start.py calls it before load_handoff().

HANDOFF_PATH = "q-ps/memory/last-handoff.md"


def overlay(root, remote=True):
    """Run the overlay as the SessionStart hook would, remote detection injected."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_CODE_REMOTE")}
    if remote:
        env["CLAUDE_CODE_REMOTE"] = "true"
    return subprocess.run([sys.executable, str(SCRIPT), "--overlay", "--repo", str(root)],
                          capture_output=True, text=True, env=env, timeout=60)


def commit_at(root, when, msg, *paths):
    git(root, "add", "-f", *paths)
    env = dict(os.environ, GIT_AUTHOR_DATE=when, GIT_COMMITTER_DATE=when)
    r = subprocess.run(["git", "commit", "-q", "-m", msg], cwd=root, env=env,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def blob(body):
    return hashlib.sha1(b"blob %d\0" % len(body.encode()) + body.encode()).hexdigest()


def push_notes_at(tmp_path, bare, when, files, supersedes=None):
    """Put `files` on the remote kipi/notes as one commit dated `when`.

    `supersedes` {path: [bodies]} writes the lineage a real publisher leaves: the
    versions the branch copy replaced. Without it the branch copy has no lineage,
    which is what an independent edit on another machine looks like."""
    if supersedes:
        files = dict(files, **{LINEAGE: json.dumps(
            {p: [blob(b) for b in bodies] + [blob(files[p])] for p, bodies in supersedes.items()})})
    pub = tmp_path / "publisher"
    git(tmp_path, "clone", "-q", str(bare), str(pub))
    git(pub, "config", "user.email", "t@t.t")
    git(pub, "config", "user.name", "t")
    git(pub, "config", "commit.gpgsign", "false")
    git(pub, "checkout", "-q", "--orphan", "kipi/notes")
    git(pub, "rm", "-rq", "--cached", ".", check=False)
    for rel, body in files.items():
        write(pub, rel, body)
    commit_at(pub, when, "notes [skip ci]", *files)
    git(pub, "push", "-q", "origin", "HEAD:refs/heads/kipi/notes")


def cloud_clone(tmp_path, bare, when_main):
    """An instance whose default branch carries an OLD handoff, pushed, then cloned."""
    src, _ = make_repo(tmp_path, "src")
    git(src, "remote", "set-url", "origin", str(bare))
    write(src, HANDOFF_PATH, "stale handoff\n")
    commit_at(src, when_main, "old handoff", HANDOFF_PATH)
    git(src, "push", "-q", "origin", "work")
    clone = tmp_path / "cloud"
    git(tmp_path, "clone", "-q", "-b", "work", str(bare), str(clone))
    return clone


def test_remote_session_overlays_a_newer_handoff_from_kipi_notes(tmp_path):
    """RED on the old code: nothing in this repo reads kipi/notes."""
    bare = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", str(bare))
    clone = cloud_clone(tmp_path, bare, "2026-01-01T00:00:00+0000")
    push_notes_at(tmp_path, bare, "2026-09-01T00:00:00+0000",
                  {HANDOFF_PATH: "fresh handoff\n",
                   "q-ps/output/rca/rca-x-2026-09-01.md": "# RCA\n"},
                  supersedes={HANDOFF_PATH: ["stale handoff\n"]})
    index_before = (clone / ".git" / "index").read_bytes()
    head_before = git(clone, "rev-parse", "HEAD").stdout
    r = overlay(clone)
    assert r.returncode == 0, r.stderr
    assert (clone / HANDOFF_PATH).read_text() == "fresh handoff\n", r.stdout
    assert (clone / "q-ps/output/rca/rca-x-2026-09-01.md").read_text() == "# RCA\n"
    out = [ln for ln in r.stdout.splitlines() if ln.strip()]
    assert len(out) == 1 and "overlaid 2" in out[0] and HANDOFF_PATH in out[0], r.stdout
    # never stages, never commits, never moves HEAD
    assert (clone / ".git" / "index").read_bytes() == index_before
    assert git(clone, "rev-parse", "HEAD").stdout == head_before


def test_a_local_handoff_newer_than_kipi_notes_is_kept(tmp_path):
    bare = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", str(bare))
    clone = cloud_clone(tmp_path, bare, "2026-09-20T00:00:00+0000")
    push_notes_at(tmp_path, bare, "2026-09-01T00:00:00+0000", {HANDOFF_PATH: "older notes\n"})
    r = overlay(clone)
    assert r.returncode == 0, r.stderr
    assert (clone / HANDOFF_PATH).read_text() == "stale handoff\n", r.stdout
    assert "nothing newer" in r.stdout


def test_uncommitted_local_edits_are_never_overwritten(tmp_path):
    bare = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", str(bare))
    clone = cloud_clone(tmp_path, bare, "2026-01-01T00:00:00+0000")
    push_notes_at(tmp_path, bare, "2026-09-01T00:00:00+0000", {HANDOFF_PATH: "fresh\n"})
    write(clone, HANDOFF_PATH, "work in progress\n")
    overlay(clone)
    assert (clone / HANDOFF_PATH).read_text() == "work in progress\n"


def test_a_branch_copy_with_no_lineage_is_not_overlaid(tmp_path):
    """Control for round 3: a newer COMMIT DATE alone proves nothing. The branch
    copy never superseded this checkout's copy, so the local one stays."""
    bare = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", str(bare))
    clone = cloud_clone(tmp_path, bare, "2026-01-01T00:00:00+0000")
    push_notes_at(tmp_path, bare, "2026-09-01T00:00:00+0000", {HANDOFF_PATH: "fresh\n"})
    r = overlay(clone)
    assert (clone / HANDOFF_PATH).read_text() == "stale handoff\n", r.stdout


def test_a_local_session_overlays_only_what_supersedes_and_is_otherwise_silent(tmp_path):
    """Round 3: the Mac overlays too, or it could never learn a cloud edit."""
    bare = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", str(bare))
    clone = cloud_clone(tmp_path, bare, "2026-01-01T00:00:00+0000")
    push_notes_at(tmp_path, bare, "2026-09-01T00:00:00+0000", {HANDOFF_PATH: "fresh\n"})
    r = overlay(clone, remote=False)
    assert r.returncode == 0
    assert (clone / HANDOFF_PATH).read_text() == "stale handoff\n"
    assert r.stdout.strip() == ""
    git(tmp_path / "publisher", "checkout", "-q", "kipi/notes")
    write(tmp_path / "publisher", LINEAGE,
          json.dumps({HANDOFF_PATH: [blob("stale handoff\n"), blob("fresh\n")]}))
    commit_at(tmp_path / "publisher", "2026-09-02T00:00:00+0000", "lineage", LINEAGE)
    git(tmp_path / "publisher", "push", "-q", "origin", "HEAD:refs/heads/kipi/notes")
    r = overlay(clone, remote=False)
    assert (clone / HANDOFF_PATH).read_text() == "fresh\n", r.stdout
    assert "overlaid 1" in r.stdout


def test_overlay_never_writes_a_code_file_from_the_branch(tmp_path):
    """Negative control: a code path on kipi/notes is never written to the tree."""
    bare = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", str(bare))
    clone = cloud_clone(tmp_path, bare, "2026-01-01T00:00:00+0000")
    push_notes_at(tmp_path, bare, "2026-09-01T00:00:00+0000",
                  {HANDOFF_PATH: "fresh\n", "q-ps/pipeline/code.py": "print('x')\n",
                   "src/app.js": "x\n", "README.md": "overwritten\n"},
                  supersedes={HANDOFF_PATH: ["stale handoff\n"]})
    r = overlay(clone)
    assert (clone / HANDOFF_PATH).read_text() == "fresh\n", r.stdout
    assert not (clone / "q-ps/pipeline/code.py").exists()
    assert not (clone / "src/app.js").exists()
    assert (clone / "README.md").read_text() == "placeholder\n"


def test_no_kipi_notes_branch_is_a_quiet_one_liner(tmp_path):
    bare = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", str(bare))
    clone = cloud_clone(tmp_path, bare, "2026-01-01T00:00:00+0000")
    r = overlay(clone)
    assert r.returncode == 0
    assert (clone / HANDOFF_PATH).read_text() == "stale handoff\n"
    assert len(r.stdout.strip().splitlines()) == 1 and "no kipi/notes" in r.stdout


def test_session_start_runs_the_overlay_before_loading_the_handoff():
    src = (HERE.parents[2] / "hooks" / "session-start.py").read_text()
    assert "notes-publish.py" in src and "--overlay" in src
    main = src[src.index("def main"):]
    assert main.index("overlay_notes(") < main.index("load_handoff(")
    assert "timeout=" in src[src.index("def overlay_notes"):]


# --- rounds 2-3 (codex, #464): per path, by lineage; deletions propagate ----
#
# Round 2 decided by commit dates, which come from unrelated histories (round 3).
# Every decision is now by content: a publisher replaces the branch copy only when
# it has SEEN that copy (local history or its own record), and the branch's
# lineage says which versions its copy already superseded.

ACTIVE = "q-ps/.active-case"


def notes_body(bare, rel):
    r = git(bare, "show", f"{BRANCH}:{rel}", check=False)
    return r.stdout if r.returncode == 0 else None


def test_an_older_local_handoff_does_not_replace_a_newer_remote_one(tmp_path):
    """RED on b28cc6b8: every local file blindly replaced the remote entry."""
    root, bare = make_repo(tmp_path)
    write(root, HANDOFF_PATH, "old local\n")
    commit_at(root, "2026-01-01T00:00:00+0000", "old handoff", HANDOFF_PATH)
    push_notes_at(tmp_path, bare, "2026-09-01T00:00:00+0000", {HANDOFF_PATH: "newer remote\n"},
                  supersedes={HANDOFF_PATH: ["old local\n"]})
    r = publish(root)
    assert r.returncode == 0, r.stderr
    assert notes_body(bare, HANDOFF_PATH) == "newer remote\n", r.stdout
    assert "kept-newer-remote" in r.stdout and HANDOFF_PATH in r.stdout, r.stdout
    assert "published" not in r.stdout, r.stdout


def test_a_newer_local_handoff_replaces_the_remote_one(tmp_path):
    root, bare = make_repo(tmp_path)
    write(root, HANDOFF_PATH, "older remote\n")          # this checkout saw the branch copy
    commit_at(root, "2026-09-01T00:00:00+0000", "synced", HANDOFF_PATH)
    write(root, HANDOFF_PATH, "new local\n")
    commit_at(root, "2026-09-20T00:00:00+0000", "new handoff", HANDOFF_PATH)
    push_notes_at(tmp_path, bare, "2026-09-01T00:00:00+0000", {HANDOFF_PATH: "older remote\n"})
    r = publish(root)
    assert notes_body(bare, HANDOFF_PATH) == "new local\n", r.stdout
    assert "published 1 file" in r.stdout and "kept-newer-remote" not in r.stdout


def test_two_racing_publishers_the_stale_one_keeps_the_fresh_content(tmp_path):
    a, bare = make_repo(tmp_path, "a")
    write(a, HANDOFF_PATH, "stale\n")
    commit_at(a, "2026-01-01T00:00:00+0000", "stale handoff", HANDOFF_PATH)
    git(a, "push", "-q", "origin", "work")
    b = tmp_path / "b"
    git(tmp_path, "clone", "-q", "-b", "work", str(bare), str(b))
    write(a, HANDOFF_PATH, "fresh from a\n")
    commit_at(a, "2026-09-01T00:00:00+0000", "fresh handoff", HANDOFF_PATH)
    assert "published" in publish(a).stdout
    r = publish(b)                                   # b still holds the stale copy
    assert notes_body(bare, HANDOFF_PATH) == "fresh from a\n", r.stdout
    assert "kept-newer-remote" in r.stdout


def test_a_stale_session_committing_later_never_overwrites_a_fresher_handoff(tmp_path):
    """RED on 74ca51c7 (codex round 3, #464): b branched from the stale copy,
    never saw a's fresh one, and committed its own edit LATER. The commit-date
    rule let b overwrite a. By lineage b never saw a's copy: it is kept."""
    a, bare = make_repo(tmp_path, "a")
    write(a, HANDOFF_PATH, "stale\n")
    commit_at(a, "2026-01-01T00:00:00+0000", "stale handoff", HANDOFF_PATH)
    git(a, "push", "-q", "origin", "work")
    b = tmp_path / "b"
    git(tmp_path, "clone", "-q", "-b", "work", str(bare), str(b))
    git(b, "config", "user.email", "t@t.t")
    git(b, "config", "user.name", "t")
    write(a, HANDOFF_PATH, "fresh from a\n")
    commit_at(a, "2026-09-01T00:00:00+0000", "fresh handoff", HANDOFF_PATH)
    assert "published" in publish(a).stdout
    write(b, HANDOFF_PATH, "b's edit on the stale base\n")
    commit_at(b, "2026-09-30T00:00:00+0000", "later commit on a stale base", HANDOFF_PATH)
    r = publish(b)
    assert notes_body(bare, HANDOFF_PATH) == "fresh from a\n", r.stdout
    assert "kept-conflict" in r.stdout and HANDOFF_PATH in r.stdout, r.stdout


def test_two_machines_converge_through_the_overlay(tmp_path):
    """The Mac publishes, a cloud session overlays and edits, the Mac overlays
    and edits again: every hop is a fast-forward, so each one publishes."""
    mac, bare = make_repo(tmp_path, "mac")
    write(mac, HANDOFF_PATH, "v1 mac\n")
    commit_at(mac, "2026-09-01T00:00:00+0000", "v1", HANDOFF_PATH)
    git(mac, "push", "-q", "origin", "work")
    assert "published" in publish(mac).stdout
    cloud = tmp_path / "cloud"
    git(tmp_path, "clone", "-q", "-b", "work", str(bare), str(cloud))
    git(cloud, "config", "user.email", "t@t.t")
    git(cloud, "config", "user.name", "t")
    write(cloud, HANDOFF_PATH, "v2 cloud\n")
    commit_at(cloud, "2026-09-02T00:00:00+0000", "v2", HANDOFF_PATH)
    assert "published 1" in publish(cloud).stdout
    r = overlay(mac, remote=False)
    assert (mac / HANDOFF_PATH).read_text() == "v2 cloud\n", r.stdout
    commit_at(mac, "2026-09-03T00:00:00+0000", "overlaid", HANDOFF_PATH)
    write(mac, HANDOFF_PATH, "v3 mac\n")
    commit_at(mac, "2026-09-04T00:00:00+0000", "v3", HANDOFF_PATH)
    r = publish(mac)
    assert notes_body(bare, HANDOFF_PATH) == "v3 mac\n", r.stdout


def test_an_untracked_rca_edit_replaces_the_copy_this_checkout_published(tmp_path):
    """Ignored RCAs have no history: the publisher's own record is what it saw."""
    root, bare = make_repo(tmp_path)
    rca = "q-ps/output/rca/rca-y-2026-09-28.md"
    write(root, rca, "# v1\n")
    assert "published 1" in publish(root).stdout
    write(root, rca, "# v2\n")
    r = publish(root)
    assert notes_body(bare, rca) == "# v2\n", r.stdout


def _closed_case(tmp_path, deleted_at="2026-09-10T00:00:00+0000"):
    """An instance that opened a case, published it (dated 09-01), then closed it."""
    root, bare = make_repo(tmp_path)
    write(root, ACTIVE, "case-001\n")
    write(root, HANDOFF_PATH, "handoff\n")
    commit_at(root, "2026-08-01T00:00:00+0000", "open case", ACTIVE, HANDOFF_PATH)
    push_notes_at(tmp_path, bare, "2026-09-01T00:00:00+0000",
                  {ACTIVE: "case-001\n", HANDOFF_PATH: "handoff\n"})
    git(root, "rm", "-q", ACTIVE)
    env = dict(os.environ, GIT_AUTHOR_DATE=deleted_at, GIT_COMMITTER_DATE=deleted_at)
    subprocess.run(["git", "commit", "-q", "-m", "close case"], cwd=root, env=env, check=True)
    git(root, "push", "-q", "origin", "work")
    return root, bare


def test_closing_active_case_locally_removes_it_from_kipi_notes(tmp_path):
    """RED on b28cc6b8: a deleted state file stayed on kipi/notes forever."""
    root, bare = _closed_case(tmp_path)
    r = publish(root)
    assert ACTIVE not in remote_tree(bare), r.stdout
    assert HANDOFF_PATH in remote_tree(bare)
    assert "removed 1" in r.stdout and ACTIVE in r.stdout, r.stdout


def test_a_deletion_never_removes_a_branch_copy_this_checkout_never_saw(tmp_path):
    """Another machine reopened a case after this one closed case-001: the close
    is about case-001, never about a copy it did not see."""
    root, bare = _closed_case(tmp_path)
    pub = tmp_path / "publisher"
    git(pub, "checkout", "-q", "kipi/notes")
    write(pub, ACTIVE, "case-002\n")
    commit_at(pub, "2026-08-15T00:00:00+0000", "reopened elsewhere", ACTIVE)
    git(pub, "push", "-q", "origin", "HEAD:refs/heads/kipi/notes")
    r = publish(root)
    assert ACTIVE in remote_tree(bare), r.stdout


def test_a_cloud_overlay_after_the_close_does_not_resurrect_the_case(tmp_path):
    root, bare = _closed_case(tmp_path)
    publish(root)
    cloud = tmp_path / "cloud"
    git(tmp_path, "clone", "-q", "-b", "work", str(bare), str(cloud))
    r = overlay(cloud)
    assert not (cloud / ACTIVE).exists(), r.stdout


def test_overlay_never_recreates_a_path_whose_local_deletion_is_newer(tmp_path):
    """Remote still holds the case (the close was never published); the clone
    has the close in its history, so the overlay must not bring it back."""
    root, bare = _closed_case(tmp_path)              # remote .active-case dated 09-01
    cloud = tmp_path / "cloud"
    git(tmp_path, "clone", "-q", "-b", "work", str(bare), str(cloud))
    git(tmp_path / "publisher", "checkout", "-q", "kipi/notes")
    write(tmp_path / "publisher", "q-ps/dashboard.md", "never local\n")
    commit_at(tmp_path / "publisher", "2026-09-02T00:00:00+0000", "dash", "q-ps/dashboard.md")
    git(tmp_path / "publisher", "push", "-q", "origin", "HEAD:refs/heads/kipi/notes")
    r = overlay(cloud)
    assert not (cloud / ACTIVE).exists(), r.stdout
    # control: a path that never existed locally is still overlaid
    assert (cloud / "q-ps/dashboard.md").read_text() == "never local\n", r.stdout


def test_overlay_recreates_when_the_remote_copy_is_newer_than_the_deletion(tmp_path):
    root, bare = _closed_case(tmp_path)              # deleted 09-10
    pub = tmp_path / "publisher"
    git(pub, "checkout", "-q", "kipi/notes")
    write(pub, ACTIVE, "case-002\n")
    commit_at(pub, "2026-09-20T00:00:00+0000", "reopened elsewhere", ACTIVE)
    git(pub, "push", "-q", "origin", "HEAD:refs/heads/kipi/notes")
    cloud = tmp_path / "cloud"
    git(tmp_path, "clone", "-q", "-b", "work", str(bare), str(cloud))
    r = overlay(cloud)
    assert (cloud / ACTIVE).read_text() == "case-002\n", r.stdout


# --- round 4 (codex, #464): deletions reach stale checkouts; last file; nested --

def _published_then_closed(tmp_path):
    """a publishes an open case; b clones before the close; a closes and publishes."""
    a, bare = make_repo(tmp_path, "a")
    write(a, ACTIVE, "case-001\n")
    write(a, HANDOFF_PATH, "handoff\n")
    commit_at(a, "2026-09-01T00:00:00+0000", "open case", ACTIVE, HANDOFF_PATH)
    git(a, "push", "-q", "origin", "work")
    assert "published" in publish(a).stdout
    b = tmp_path / "b"
    git(tmp_path, "clone", "-q", "-b", "work", str(bare), str(b))
    git(b, "config", "user.email", "t@t.t")
    git(b, "config", "user.name", "t")
    git(a, "rm", "-q", ACTIVE)
    commit_at(a, "2026-09-02T00:00:00+0000", "close case")
    r = publish(a)
    assert ACTIVE not in remote_tree(bare), r.stdout
    return a, b, bare


def test_a_stale_checkout_never_republishes_a_case_closed_elsewhere(tmp_path):
    """RED on a85f667f: b still holds case-001, the branch no longer does, so b
    wrote it back and the closed case came back for every reader."""
    _, b, bare = _published_then_closed(tmp_path)
    r = publish(b)
    assert ACTIVE not in remote_tree(bare), r.stdout
    assert "deleted elsewhere" in r.stdout and ACTIVE in r.stdout, r.stdout


def test_the_overlay_consumes_a_deletion_made_elsewhere(tmp_path):
    """RED on a85f667f: nothing ever removed the stale local copy."""
    _, b, _ = _published_then_closed(tmp_path)
    r = overlay(b, remote=False)
    assert not (b / ACTIVE).exists(), r.stdout
    assert "deleted elsewhere" in r.stdout


def test_a_case_reopened_with_new_content_after_the_close_is_published(tmp_path):
    """Control: a tombstone covers the deleted version only, never new work."""
    _, b, bare = _published_then_closed(tmp_path)
    write(b, ACTIVE, "case-002\n")
    commit_at(b, "2026-09-03T00:00:00+0000", "reopen", ACTIVE)
    r = publish(b)
    assert notes_body(bare, ACTIVE) == "case-002\n", r.stdout
    overlay(b, remote=False)
    assert (b / ACTIVE).read_text() == "case-002\n"


def test_deleting_the_last_notes_file_still_reaches_kipi_notes(tmp_path):
    """RED on a85f667f: an empty collection returned before the deletion engine."""
    root, bare = make_repo(tmp_path)
    write(root, ACTIVE, "case-001\n")
    commit_at(root, "2026-09-01T00:00:00+0000", "open", ACTIVE)
    assert "published 1" in publish(root).stdout
    git(root, "rm", "-q", ACTIVE)
    commit_at(root, "2026-09-02T00:00:00+0000", "close")
    r = publish(root)
    assert notes_tree(bare) == [], r.stdout
    assert "removed 1" in r.stdout, r.stdout


def test_an_empty_checkout_with_no_branch_publishes_nothing(tmp_path):
    root, bare = make_repo(tmp_path)
    r = publish(root)
    assert remote_tip(bare) is None and "nothing to publish" in r.stdout, r.stdout


def test_a_legacy_nested_instance_publishes_the_handoff_session_start_reads(tmp_path):
    """RED on a85f667f (codex minor): session-start reads q-system/q-system/ in a
    subtree instance, and the publisher never collected it."""
    root, bare = make_repo(tmp_path)
    (root / "q-system" / "q-system" / "canonical").mkdir(parents=True)
    nested = "q-system/q-system/memory/last-handoff.md"
    write(root, nested, "nested handoff\n")
    r = publish(root)
    assert notes_body(bare, nested) == "nested handoff\n", r.stdout
