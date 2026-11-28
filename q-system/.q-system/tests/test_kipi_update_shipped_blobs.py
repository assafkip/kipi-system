"""ASK-5851: the one-pass shipped-blob map must equal the old per-file rev-list answer.

The oracle below IS the old fleet_authored_blob loop (rev-list per path, rev-parse per
commit). The map is built from a fixture repo made here, never a live path: 3 lesson
files across 2 commits, one rewritten, one deleted.
"""
import importlib.util
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location(
    "shipped_blobs", ROOT / "kipi-update-shipped-blobs.py")
sb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sb)


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", *args],
        check=True, capture_output=True, text=True).stdout


def make_repo(tmp_path):
    repo = tmp_path / "skel"
    (repo / "q-system/lessons").mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    lessons = repo / "q-system/lessons"
    (lessons / "a.md").write_text("a v1\n")
    (lessons / "b.md").write_text("b v1\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "one")
    (lessons / "a.md").write_text("a v2\n")
    (lessons / "c.md").write_text("c v1\n")
    (lessons / "b.md").unlink()
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "two")
    return repo


def oracle(repo, ref, rel):
    """The old loop: every blob rev-parse finds at a commit that touched rel."""
    blobs = set()
    for commit in git(repo, "rev-list", ref, "--", rel).split():
        res = subprocess.run(["git", "-C", str(repo), "rev-parse", f"{commit}:{rel}"],
                             capture_output=True, text=True)
        if res.returncode == 0:
            blobs.add(res.stdout.strip())
    return blobs


def map_for(lines, rel):
    return {ln.split("\t")[1] for ln in lines if ln.split("\t")[0] == rel}


def assert_map_matches_oracle(repo, build):
    lines = build(str(repo), "HEAD")
    rels = ["q-system/lessons/a.md", "q-system/lessons/b.md", "q-system/lessons/c.md"]
    for rel in rels:
        assert map_for(lines, rel) == oracle(repo, "HEAD", rel), rel


def test_map_matches_per_file_rev_list(tmp_path):
    repo = make_repo(tmp_path)
    assert_map_matches_oracle(repo, sb.build_map)
    lines = sb.build_map(str(repo), "HEAD")
    # a has two shipped versions, b keeps its only one after deletion, c has one.
    assert len(map_for(lines, "q-system/lessons/a.md")) == 2
    assert len(map_for(lines, "q-system/lessons/b.md")) == 1
    assert len(map_for(lines, "q-system/lessons/c.md")) == 1


def test_mutant_latest_blob_only_is_caught(tmp_path):
    """Negative self-test: a map holding only the newest blob per path must FAIL the check."""
    repo = make_repo(tmp_path)

    def mutant(repo_path, ref):
        latest = {}
        for line in sb.build_map(repo_path, ref):
            path, blob = line.split("\t")
            latest[path] = blob
        return [f"{p}\t{b}" for p, b in latest.items()]

    try:
        assert_map_matches_oracle(repo, mutant)
    except AssertionError:
        return
    raise AssertionError("mutant survived: the oracle comparison cannot fail")


def test_real_history_lessons_match_oracle():
    """Every lesson file in this repo, against the old loop, on a read-only ref."""
    lines = sb.build_map(str(ROOT), "HEAD")
    rels = git(ROOT, "ls-files", "q-system/lessons").split()
    assert len(rels) > 50
    for rel in rels:
        assert map_for(lines, rel) == oracle(ROOT, "HEAD", rel), rel
