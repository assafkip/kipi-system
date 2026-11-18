"""Parity of the voiceloop engine between the skeleton and consulting (ASK-2901).

THE DECISION THIS PINS. The skeleton's `plugins/kipi-core/voiceloop/` is the source of
truth. Evidence, measured 2026-11-18 on origin/main of each repo:
  - `kipi update` rsyncs the skeleton's plugins/kipi-core onto consulting with --delete,
    so the skeleton is the only writer that is automatic;
  - every consulting commit that touches the engine is a "Carry ... from kipi main"
    (#552, #561, #570, #590), i.e. consulting follows;
  - the public exporter (consulting/automation/export_voice_loop.py) READS consulting's
    copy, so it is downstream of the skeleton, one hop late.
So the exporter's source is a replica, and a replica that is ahead of the skeleton is
lost work at the next sync (the roll-back scar, 2026-09-06). Two things hold that line:
  - this test: the two copies, as committed on consulting's origin/main, are byte-identical,
    or it fails and names the files. It does NOT see consulting commits that are not
    pushed or an uncommitted working tree; the updater refusal covers those;
  - kipi-update.sh: an engine file ahead of the skeleton refuses the sync with no flag
    (test-kipi-update-instance-ahead.sh, properties 5 and 6).

WHERE IT CAN RUN. It needs the consulting repo next to this one. It reads consulting's
origin/main by git object, never its working tree, because a sibling session may be
mid-edit there. In CI the sibling is absent, and ONLY then the live comparison skips,
with the reason named in the skip message. The comparison logic itself is exercised on
temp trees in every environment, including CI, so the check is never untested.
"""
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKELETON = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
ENGINE_REL = "plugins/kipi-core/voiceloop"
CONSULTING = os.environ.get(
    "KIPI_PARITY_CONSULTING_REPO", os.path.expanduser("~/projects/consulting")
)
# Not engine source: bytecode and caches differ per machine and mean nothing.
_SKIP_PARTS = ("__pycache__", ".pytest_cache")


def _keep(rel):
    return not any(part in rel.split("/") for part in _SKIP_PARTS) and not rel.endswith(".pyc")


def tree_from_dir(root):
    """{relative path: bytes} for every engine file under a directory."""
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for name in filenames:
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            if _keep(rel):
                with open(full, "rb") as fh:
                    out[rel] = fh.read()
    return out


def tree_from_git(repo, ref, subdir):
    """The same map, read from git objects so a dirty working tree cannot lie."""
    listing = subprocess.run(
        ["git", "-C", repo, "ls-tree", "-r", "-z", "--name-only", ref, "--", subdir],
        capture_output=True, check=True,
    ).stdout.decode().split("\0")
    out = {}
    for path in filter(None, listing):
        rel = path[len(subdir) + 1:]
        if _keep(rel):
            out[rel] = subprocess.run(
                ["git", "-C", repo, "show", f"{ref}:{path}"], capture_output=True, check=True
            ).stdout
    return out


def drift(left, right):
    """Sorted (path, verdict) rows where the two maps disagree. Empty means parity.

    An empty map on either side is itself drift: two empty trees are "equal" and that is
    how a wrong path would pass this test green.
    """
    rows = []
    if not left or not right:
        return [("<tree>", "one side is empty: wrong path, not parity")]
    for rel in sorted(set(left) | set(right)):
        if rel not in right:
            rows.append((rel, "missing in right"))
        elif rel not in left:
            rows.append((rel, "missing in left"))
        elif left[rel] != right[rel]:
            rows.append((rel, "differs"))
    return rows


def _consulting_ref():
    """origin/main of consulting, or None when the sibling repo is not here."""
    if not os.path.isdir(os.path.join(CONSULTING, ".git")) and not os.path.isfile(
        os.path.join(CONSULTING, ".git")
    ):
        return None
    probe = subprocess.run(
        ["git", "-C", CONSULTING, "rev-parse", "--verify", "-q", "origin/main"],
        capture_output=True,
    )
    if probe.returncode != 0:
        return None
    # Best effort: a stale origin/main reads parity for work already pushed since
    # (review of PR 836, finding 4). An offline run keeps the ref it has.
    try:
        subprocess.run(["git", "-C", CONSULTING, "fetch", "-q", "origin", "main"],
                       capture_output=True, timeout=30)
    except (subprocess.TimeoutExpired, OSError):
        pass
    return "origin/main"


class ParityLogic(unittest.TestCase):
    """The comparison must be able to fail: a check that cannot go red is decoration."""

    def _pair(self):
        a = tempfile.mkdtemp()
        b = tempfile.mkdtemp()
        for root in (a, b):
            with open(os.path.join(root, "gate.py"), "w") as fh:
                fh.write("RULE = 1\n")
            with open(os.path.join(root, "form.py"), "w") as fh:
                fh.write("FORM = 1\n")
        return a, b

    def test_identical_copies_are_parity(self):
        a, b = self._pair()
        self.assertEqual(drift(tree_from_dir(a), tree_from_dir(b)), [])

    def test_an_edited_file_is_drift(self):
        a, b = self._pair()
        with open(os.path.join(b, "gate.py"), "a") as fh:
            fh.write("LOCAL_FIX = True\n")
        self.assertEqual(drift(tree_from_dir(a), tree_from_dir(b)), [("gate.py", "differs")])

    def test_a_missing_and_an_extra_file_are_drift(self):
        a, b = self._pair()
        os.remove(os.path.join(b, "form.py"))
        with open(os.path.join(b, "extra.py"), "w") as fh:
            fh.write("X = 1\n")
        self.assertEqual(
            drift(tree_from_dir(a), tree_from_dir(b)),
            [("extra.py", "missing in left"), ("form.py", "missing in right")],
        )

    def test_bytecode_is_not_drift(self):
        a, b = self._pair()
        os.makedirs(os.path.join(b, "__pycache__"))
        with open(os.path.join(b, "__pycache__", "gate.cpython-312.pyc"), "wb") as fh:
            fh.write(b"\0")
        self.assertEqual(drift(tree_from_dir(a), tree_from_dir(b)), [])

    def test_an_empty_side_is_drift_not_parity(self):
        a, _ = self._pair()
        empty = tempfile.mkdtemp()
        self.assertTrue(drift(tree_from_dir(a), tree_from_dir(empty)))
        self.assertTrue(drift(tree_from_dir(empty), tree_from_dir(empty)))


class GitReader(unittest.TestCase):
    """tree_from_git only ran in the branch CI skips, so a broken slice stayed green
    (review of PR 836, finding 3). A temp repo exercises it everywhere."""

    def test_reads_committed_bytes_not_the_working_tree(self):
        repo = tempfile.mkdtemp()
        sub = os.path.join(repo, "plugins", "kipi-core", "voiceloop")
        os.makedirs(os.path.join(sub, "__pycache__"))
        for name, body in (("gate.py", "RULE = 1\n"), ("__pycache__/x.pyc", "z")):
            with open(os.path.join(sub, name), "w") as fh:
                fh.write(body)
        g = ["git", "-C", repo, "-c", "user.email=t@t", "-c", "user.name=t"]
        subprocess.run(g + ["init", "-q", "-b", "main"], check=True)
        subprocess.run(g + ["add", "-A", "-f"], check=True)
        subprocess.run(g + ["commit", "-qm", "c"], check=True)
        with open(os.path.join(sub, "gate.py"), "w") as fh:
            fh.write("RULE = 2  # uncommitted\n")
        got = tree_from_git(repo, "HEAD", ENGINE_REL)
        self.assertEqual(got, {"gate.py": b"RULE = 1\n"})
        self.assertEqual(drift(got, {"gate.py": b"RULE = 1\n"}), [])


class LiveParity(unittest.TestCase):
    def test_skeleton_engine_equals_consulting_origin_main(self):
        ref = _consulting_ref()
        if ref is None:
            self.skipTest(
                f"SKIPPED, NOT PASSED: no consulting repo with origin/main at {CONSULTING} "
                "(expected in CI, where only this repo is checked out). Live engine parity "
                "ran nowhere in this environment; set KIPI_PARITY_CONSULTING_REPO to run it."
            )
        mine = tree_from_dir(os.path.join(SKELETON, ENGINE_REL))
        theirs = tree_from_git(CONSULTING, ref, ENGINE_REL)
        rows = drift(mine, theirs)
        self.assertEqual(
            rows, [],
            "voiceloop engine drifted between the skeleton (left) and consulting "
            f"{ref} (right). The skeleton is the source of truth: carry the skeleton's "
            "copy into consulting, never the reverse, unless the change is first landed "
            f"in the skeleton. Rows: {rows}",
        )


if __name__ == "__main__":
    sys.exit(unittest.main())
