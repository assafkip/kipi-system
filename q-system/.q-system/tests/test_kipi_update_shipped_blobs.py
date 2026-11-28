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


def test_pruned_side_branch_is_a_documented_superset(tmp_path):
    """Codex P1 on PR #908, decided: the map may hold a blob the old rev-list pruned.

    rev-list's default history simplification drops a side branch a merge discarded
    (`merge -s ours`); one unfiltered log pass cannot simplify per path, so it keeps
    that blob. Direction pinned here: the old answer is always a SUBSET of the map, so
    a file the old loop called shipped is never reported ahead of the skeleton.
    """
    repo = make_repo(tmp_path)
    git(repo, "switch", "-q", "-c", "side")
    (repo / "q-system/lessons/a.md").write_text("a side\n")
    git(repo, "commit", "-qam", "side edit")
    git(repo, "switch", "-q", "main")
    (repo / "q-system/lessons/c.md").write_text("c v2\n")
    git(repo, "commit", "-qam", "main edit")
    git(repo, "merge", "-q", "-s", "ours", "side", "-m", "discard side")
    rel = "q-system/lessons/a.md"
    old = oracle(repo, "HEAD", rel)
    new = map_for(sb.build_map(str(repo), "HEAD"), rel)
    assert old <= new
    assert len(new - old) == 1


def test_cache_is_set_in_parent_shell_and_cleaned(tmp_path):
    """Codex P2 on PR #908: the cache path must survive in the parent, not die in $(...)."""
    repo = make_repo(tmp_path)
    (repo / "kipi-update-shipped-blobs.py").write_bytes(
        (ROOT / "kipi-update-shipped-blobs.py").read_bytes())
    src = (ROOT / "kipi-update.sh").read_text().splitlines()
    start = next(i for i, ln in enumerate(src) if ln.startswith("fleet_ship_ref()"))
    end = next(i for i, ln in enumerate(src) if ln.startswith("# INSTALL THE VENDORED HOOKS"))
    funcs = tmp_path / "funcs.sh"
    funcs.write_text("\n".join(src[start:end]) + "\n")
    tmpdir = tmp_path / "tmp"
    tmpdir.mkdir()
    script = (
        f'SCRIPT_DIR="{repo}"; SKELETON_BRANCH=main; PROVENANCE_OK=1; TMPDIR="{tmpdir}"\n'
        f'. "{funcs}"\n'
        'F=q-system/lessons/c.md\n'
        'fleet_authored_blob $F $F || echo SHIPPED_MISS\n'
        '[ -n "$SHIPPED_BLOB_MAP" ] && [ -s "$SHIPPED_BLOB_MAP" ] || echo PARENT_LOST\n'
        'echo changed > "$SCRIPT_DIR/$F"\n'
        'fleet_authored_blob $F $F && echo FALSE_HIT\n'
    )
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, cwd=repo)
    assert "SHIPPED_MISS" not in out.stdout, out.stdout + out.stderr
    assert "PARENT_LOST" not in out.stdout, out.stdout + out.stderr
    assert "FALSE_HIT" not in out.stdout, out.stdout + out.stderr
    assert len(list(tmpdir.iterdir())) == 1  # one map, named by mktemp, from the parent
    # Round 2 of PR #908: an unrunnable helper must say so, not read as "instance ahead".
    broken = tmp_path / "nohelper"
    broken.mkdir()
    git(broken, "init", "-q")
    (broken / "f.md").write_text("x\n")
    script2 = (
        f'SCRIPT_DIR="{broken}"; SKELETON_BRANCH=main; PROVENANCE_OK=1; TMPDIR="{tmpdir}"\n'
        f'. "{funcs}"\n'
        'fleet_authored_blob f.md "$SCRIPT_DIR/f.md" || echo RC_NONZERO\n'
        'fleet_authored_blob f.md "$SCRIPT_DIR/f.md" || echo RC_NONZERO_AGAIN\n'
        'fleet_authored_blob f.md "$SCRIPT_DIR/f.md" || echo RC_NONZERO_AGAIN\n'
    )
    out2 = subprocess.run(["bash", "-c", script2], capture_output=True, text=True, cwd=repo)
    assert "RC_NONZERO" in out2.stdout
    assert out2.stdout.count("RC_NONZERO_AGAIN") == 2  # a cached failure still answers "not shipped"
    # ASK-5855: a failed build warns ONCE per ref, not once per lookup.
    assert out2.stderr.count("WARN: shipped-blob map unavailable") == 1, out2.stderr
    # PR #911 review: the failure itself is not cached, so a fault that clears is
    # retried in the SAME run: fail once, fix the toolchain mid-run, look up again.
    helper = ROOT / "kipi-update-shipped-blobs.py"
    script3 = (
        script2.split("fleet_authored_blob")[0]
        + 'fleet_authored_blob f.md "$SCRIPT_DIR/f.md" || echo FIRST_FAILED\n'
        + f'cp "{helper}" "$SCRIPT_DIR/" && git -C "$SCRIPT_DIR" add f.md\n'
        + 'git -C "$SCRIPT_DIR" -c user.email=t@t -c user.name=t commit -qm f\n'
        + 'fleet_authored_blob f.md "$SCRIPT_DIR/f.md" && echo RETRY_OK\n'
    )
    out3 = subprocess.run(["bash", "-c", script3], capture_output=True, text=True, cwd=repo)
    assert "FIRST_FAILED" in out3.stdout, out3.stdout + out3.stderr
    assert "RETRY_OK" in out3.stdout, out3.stdout + out3.stderr
    # The EXIT cleanup is the consumer of that variable: it must remove it.
    cleanup = "\n".join(src).split("cleanup_updater_temps() {")[1].split("\n}\n")[0]
    assert 'rm -f -- "$SHIPPED_BLOB_MAP"' in cleanup


# ASK-5855: the batch helpers that replaced instance_ahead_scan's per-file git calls.
# Each oracle below IS the old per-file call; each test carries one mutant that the
# comparison must catch, so a comparison that cannot fail is caught here first.

def make_instance(tmp_path):
    """An instance repo (index) plus files on disk outside the skeleton, as in a dry model."""
    inst = tmp_path / "inst"
    (inst / "q-system/sub").mkdir(parents=True)
    git(inst, "init", "-q", "-b", "main")
    for rel, body in {"q-system/a.md": "a v1\n", "q-system/sub/b.md": "b local\n",
                      "q-system/sp ace.md": "s\n"}.items():
        (inst / rel).write_text(body)
    git(inst, "add", "-A")
    git(inst, "commit", "-q", "-m", "inst")
    (inst / "q-system/untracked.md").write_text("u\n")
    return inst


CANDIDATES = ["q-system/a.md", "q-system/sub/b.md", "q-system/sp ace.md",
              "q-system/untracked.md", "q-system/never.md"]


def old_is_tracked(root, shown):
    return subprocess.run(["git", "-C", str(root), "ls-files", "--error-unmatch", "--", shown],
                          capture_output=True).returncode == 0


def assert_tracked_matches(inst, tracked_fn):
    tracked = tracked_fn(str(inst))
    for shown in CANDIDATES:
        assert (shown in tracked) == old_is_tracked(inst, shown), shown


def test_tracked_paths_match_per_file_ls_files(tmp_path):
    inst = make_instance(tmp_path)
    assert_tracked_matches(inst, sb.tracked_paths)


def test_mutant_tracked_from_disk_is_caught(tmp_path):
    """Mutant: reading the worktree instead of the index calls an untracked file tracked."""
    inst = make_instance(tmp_path)

    def mutant(root):
        base = Path(root)
        return {p.relative_to(base).as_posix() for p in base.rglob("*")
                if p.is_file() and ".git" not in p.parts}

    try:
        assert_tracked_matches(inst, mutant)
    except AssertionError:
        return
    raise AssertionError("mutant survived: the ls-files comparison cannot fail")


def old_hash(repo, path):
    res = subprocess.run(["git", "-C", str(repo), "hash-object", "--", path],
                         capture_output=True, text=True)
    return res.stdout.strip() if res.returncode == 0 else ""


def hash_inputs(tmp_path):
    repo = make_repo(tmp_path)
    inst = make_instance(tmp_path)
    nl = inst / "q-system/new\nline.md"
    nl.write_text("n\n")
    # A missing path makes --stdin-paths abort the whole batch: the fallback must
    # still give every other file its per-file answer.
    paths = [str(inst / rel) for rel in CANDIDATES] + [str(nl)]
    return repo, paths


def assert_hashes_match(repo, paths, hash_fn):
    assert hash_fn(str(repo), paths) == [old_hash(repo, p) for p in paths]


def test_hash_paths_match_per_file_hash_object(tmp_path, capsys):
    repo, paths = hash_inputs(tmp_path)
    dangling = tmp_path / "inst/q-system/dangling.md"
    dangling.symlink_to(tmp_path / "nowhere")
    paths.append(str(dangling))
    assert_hashes_match(repo, paths, sb.hash_paths)
    # PR #911 review: a missing file or dangling link must not abort the batch.
    assert "stdin-paths failed" not in capsys.readouterr().err
    present = [p for p in paths if Path(p).exists() and "\n" not in p]
    assert_hashes_match(repo, present, sb.hash_paths)  # the all-batch path too


def test_mutant_hash_without_fallback_is_caught(tmp_path):
    """Mutant: a failed batch returning "" for every file reads all of them as unshipped."""
    repo, paths = hash_inputs(tmp_path)

    def mutant(repo_path, ps):
        res = subprocess.run(["git", "-C", repo_path, "hash-object", "--stdin-paths"],
                             input="".join(p + "\n" for p in ps).encode(), capture_output=True)
        blobs = res.stdout.decode().split()
        return blobs if res.returncode == 0 and len(blobs) == len(ps) else [""] * len(ps)

    try:
        assert_hashes_match(repo, paths, mutant)
    except AssertionError:
        return
    raise AssertionError("mutant survived: the hash-object comparison cannot fail")


def filter_records(tmp_path):
    """Skeleton shipped a v1 and c v1; the instance holds a v1 (shipped), b local
    (never shipped), plus untracked and missing candidates."""
    repo = make_repo(tmp_path)
    inst = make_instance(tmp_path)
    (inst / "q-system/sub/b.md").write_text("b local\n")
    records = []
    for shown in CANDIDATES:
        rel = shown.split("/", 1)[1]
        blob_rel = "q-system/lessons/" + rel.split("/")[-1]
        records.append(["mod", shown, blob_rel, str(inst / shown), str(repo / blob_rel)])
    records.append(["del", "q-system/a.md", "q-system/lessons/a.md", str(inst / "q-system/a.md"), ""])
    mapf = tmp_path / "map"
    mapf.write_text("".join(ln + "\n" for ln in sb.build_map(str(repo), "HEAD")))
    return repo, inst, mapf, records


def old_filter(repo, inst, mapf, records):
    """The shipped per-file fallback in kipi-update.sh, run as bash on the same records."""
    src = (ROOT / "kipi-update.sh").read_text()
    start = src.index("fleet_ship_ref() {")
    end = src.index("# INSTALL THE VENDORED HOOKS")
    per_file = "instance_ahead_filter_per_file() {" + src.split(
        "instance_ahead_filter_per_file() {")[1].split("\n}\n")[0] + "\n}\n"
    script = (src[start:end] + per_file +
              f'SCRIPT_DIR="{repo}"; SKELETON_BRANCH=main; PROVENANCE_OK=1\n'
              f'SHIPPED_BLOB_MAP="{mapf}"; SHIPPED_BLOB_REF=HEAD\n'
              f'instance_ahead_filter_per_file "{inst}"\n'
              'printf "%s" "$AHEAD_KEPT"\n')
    stdin = "".join("\t".join(r) + "\n" for r in records)
    out = subprocess.run(["bash", "-c", script], input=stdin, capture_output=True,
                         text=True, check=True).stdout
    return [ln.split("\t") for ln in out.splitlines()]


def assert_filter_matches(tmp_path, filter_fn):
    repo, inst, mapf, records = filter_records(tmp_path)
    old = old_filter(repo, inst, mapf, records)
    new = filter_fn(str(repo), str(inst), str(mapf), records)
    # Trailing empty skel_file: bash read drops it, so compare the first four fields.
    assert [r[:4] for r in new] == [r[:4] for r in old]
    return old


def test_filter_ahead_matches_old_per_file_loop(tmp_path):
    old = assert_filter_matches(tmp_path, sb.filter_ahead)
    # Only b (never shipped) and the sp ace file survive; a is shipped, the rest untracked.
    assert [r[1] for r in old] == ["q-system/sub/b.md", "q-system/sp ace.md"]


def test_mutant_filter_without_tracked_check_is_caught(tmp_path):
    """Mutant: skipping the tracked check reports an untracked file as instance-ahead."""
    def mutant(repo, root, map_file, records):
        shipped = sb.load_map(map_file)
        blobs = sb.hash_paths(repo, [r[3] for r in records])
        return [r for r, b in zip(records, blobs) if not (b and f"{r[2]}\t{b}" in shipped)]

    try:
        assert_filter_matches(tmp_path, mutant)
    except AssertionError:
        return
    raise AssertionError("mutant survived: the filter comparison cannot fail")
