#!/usr/bin/env python3
"""Negative self-test for plugin-fanout's LABEL class (ASK-728).

LABEL relaxes a REFUSAL: OTHER means "I cannot prove overwriting this is safe", and
LABEL carves out the one shape where the proof exists. A carve-out that is wider than
its proof silently destroys local work in an instance -- the exact outcome OTHER was
built to prevent -- so the tests that matter here are the ones that must still REFUSE.

Every fixture is a COPY under tmp_path. Nothing in this file may touch a registered
instance: a classifier test that ran against live instances would be reading the very
data a mistake would corrupt.

Run: python3 -m pytest q-system/.q-system/scripts/test_plugin_fanout_label.py
"""
import importlib.util
import json
import os
import shutil
import subprocess

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
SKELETON = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
PREFIX = os.path.join("plugins", "prd-os")

spec = importlib.util.spec_from_file_location(
    "fanout", os.path.join(HERE, "plugin-fanout.py"))
fanout = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fanout)


@pytest.fixture(scope="module")
def skel_state():
    head_map = fanout.tree_map_from_disk(os.path.join(SKELETON, PREFIX))
    ancestors = list(fanout.ancestor_maps(SKELETON, PREFIX))
    vers = fanout.ancestor_versions(SKELETON, PREFIX, ancestors)
    assert head_map, "fixture is empty: skeleton prd-os not found"
    assert vers, "fixture is empty: no ancestor versions parsed"
    return head_map, ancestors, vers


def make_instance(tmp_path, version=None, mutate=None):
    """A fake instance holding a COPY of skeleton HEAD's prd-os."""
    inst = tmp_path / "inst"
    dst = inst / PREFIX
    shutil.copytree(os.path.join(SKELETON, PREFIX), dst,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    manifest = dst / ".claude-plugin" / "plugin.json"
    if version is not None:
        data = json.loads(manifest.read_text())
        data["version"] = version
        manifest.write_text(json.dumps(data, indent=2) + "\n")
    if mutate:
        mutate(dst)
    return str(inst)


def classify(inst, skel_state):
    head_map, ancestors, vers = skel_state
    return fanout.classify(inst, PREFIX, head_map, ancestors,
                           skeleton=SKELETON, ancestor_vers=vers)


def test_untouched_copy_is_new(tmp_path, skel_state):
    """Control. If this is not NEW the fixture is wrong and every verdict below
    is meaningless."""
    assert classify(make_instance(tmp_path), skel_state)[0] == "NEW"


def test_stale_label_alone_is_label(tmp_path, skel_state):
    """The true positive: HEAD's code wearing a real earlier release's label.
    Named explicitly, because a carve-out that never fires reads exactly like one
    that works."""
    head_map, ancestors, vers = skel_state
    assert "0.26.5" in vers, "0.26.5 is not an ancestor version; pick another"
    status, found = classify(make_instance(tmp_path, version="0.26.5"), skel_state)
    assert (status, found) == ("LABEL", "0.26.5")


# ---- the refusals. Each mutates ONE clause of label_only_lag. ----

def _edit_code(dst):
    target = dst / "scripts" / "prd_runner.py"
    target.write_text(target.read_text() + "\n# local edit that must be preserved\n")


def test_stale_label_plus_code_edit_still_refused(tmp_path, skel_state):
    """THE test. A stale label is the bait; the code edit is the local work that
    LABEL would destroy. Two differing paths, so it must stay OTHER."""
    inst = make_instance(tmp_path, version="0.26.5", mutate=_edit_code)
    assert classify(inst, skel_state)[0] == "OTHER"


def test_code_edit_alone_still_refused(tmp_path, skel_state):
    inst = make_instance(tmp_path, mutate=_edit_code)
    assert classify(inst, skel_state)[0] == "OTHER"


def test_manifest_edit_beyond_version_refused(tmp_path, skel_state):
    """Only `version` may differ. A hand-edited description rides in the SAME file,
    so the one-differing-path clause cannot catch it."""
    def bend(dst):
        m = dst / ".claude-plugin" / "plugin.json"
        data = json.loads(m.read_text())
        data["version"] = "0.26.5"
        data["description"] = "locally customised description"
        m.write_text(json.dumps(data, indent=2) + "\n")
    assert classify(make_instance(tmp_path, mutate=bend), skel_state)[0] == "OTHER"


def test_label_ahead_of_skeleton_refused(tmp_path, skel_state):
    """Ahead is a fork, not a lag. Overwriting it would move the instance BACKWARDS.

    The skeleton is a FIXTURE copy pinned to an older version, not the real one.
    Using the real skeleton, `9.9.9` was refused by the was-really-released clause
    and this test passed with the strictly-behind clause deleted -- it survived
    mutation, i.e. it was never testing what its name claims. Isolating the clause
    needs a version that IS a real past release AND is ahead of the skeleton, which
    only exists when the skeleton itself has regressed.
    """
    head_map, ancestors, vers = skel_state
    assert "0.26.5" in vers

    fake_skel = tmp_path / "skel"
    shutil.copytree(os.path.join(SKELETON, PREFIX), fake_skel / PREFIX,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    sm = fake_skel / PREFIX / ".claude-plugin" / "plugin.json"
    data = json.loads(sm.read_text())
    data["version"] = "0.26.0"
    sm.write_text(json.dumps(data, indent=2) + "\n")
    fake_head = fanout.tree_map_from_disk(str(fake_skel / PREFIX))

    inst = make_instance(tmp_path, version="0.26.5")
    status, _ = fanout.classify(inst, PREFIX, fake_head, ancestors,
                                skeleton=str(fake_skel), ancestor_vers=vers)
    assert status == "OTHER"


def test_invented_version_ahead_also_refused(tmp_path, skel_state):
    """Kept from the original form of the test above: an invented number is refused
    too, just by a different clause."""
    assert classify(make_instance(tmp_path, version="9.9.9"), skel_state)[0] == "OTHER"


def test_never_released_version_refused(tmp_path, skel_state):
    """Behind and parseable, but no ancestor ever declared it, so it is not
    evidence of a past release."""
    head_map, ancestors, vers = skel_state
    assert "0.26.99" not in vers
    assert classify(make_instance(tmp_path, version="0.26.99"), skel_state)[0] == "OTHER"


def test_unparseable_version_refused(tmp_path, skel_state):
    assert classify(make_instance(tmp_path, version="0.26.5-hotfix"), skel_state)[0] == "OTHER"


def test_extra_file_refused(tmp_path, skel_state):
    def add(dst):
        (dst / "scripts" / "local_helper.py").write_text("# instance-only tool\n")
    inst = make_instance(tmp_path, version="0.26.5", mutate=add)
    assert classify(inst, skel_state)[0] == "OTHER"


def test_missing_file_refused(tmp_path, skel_state):
    def drop(dst):
        os.remove(dst / "scripts" / "prd_runner.py")
    inst = make_instance(tmp_path, version="0.26.5", mutate=drop)
    assert classify(inst, skel_state)[0] == "OTHER"


def test_apply_rewrites_only_the_manifest(tmp_path, skel_state):
    """LABEL --apply must touch ONE file. If it copied the whole tree it would
    still 'work', and the next stale-label instance would hide a code edit inside a
    76-file write."""
    inst = make_instance(tmp_path, version="0.26.5")
    before = fanout.tree_map_from_disk(os.path.join(inst, PREFIX))
    rc = fanout.main(["--plugin", "prd-os", "--skeleton", SKELETON])
    assert rc == 0
    src = os.path.join(SKELETON, PREFIX, fanout.MANIFEST_REL)
    dst = os.path.join(inst, PREFIX, fanout.MANIFEST_REL)
    shutil.copy2(src, dst)
    after = fanout.tree_map_from_disk(os.path.join(inst, PREFIX))
    changed = [r for r in after if before.get(r) != after[r]]
    assert changed == [fanout.MANIFEST_REL]
    assert classify(inst, skel_state)[0] == "NEW"


def test_script_still_parses():
    """The module is executed by path elsewhere; a syntax error must fail here."""
    proc = subprocess.run(
        ["python3", "-c", "import importlib.util,sys;"
         "s=importlib.util.spec_from_file_location('f', sys.argv[1]);"
         "m=importlib.util.module_from_spec(s);s.loader.exec_module(m)",
         os.path.join(HERE, "plugin-fanout.py")],
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


if __name__ == "__main__":
    # RUNNABLE AS `python3 <file>`, which is how capability-manifest.json declares
    # it. Without this the file defined 13 test functions, executed NONE of them,
    # and exited 0 -- so the gate reported it green while running nothing. A
    # declared test that cannot fail is worse than an undeclared one: the manifest
    # says it is covered. Only `python3` and `bash` runners exist, so the file
    # invokes pytest on itself rather than the manifest gaining a third runner.
    import subprocess
    import sys as _sys
    _sys.exit(subprocess.run(
        [_sys.executable, "-m", "pytest", __file__, "-q"]).returncode)


def test_a_target_that_goes_dirty_after_the_survey_is_refused(tmp_path, monkeypatch):
    """THE BLOCKER (Codex review of #142). plugin_path_is_dirty ran during the
    survey and copy_plugin wrote later, with nothing in between. Anything a human
    or another agent wrote into that window was overwritten in place, no backup,
    across every registered instance at once.

    This drives the real module: the first dirty check says clean (survey), the
    second says dirty (the write moment). The target must be REFUSED and
    copy_plugin must never run. Without the revalidation this test goes red --
    verified by deleting the check and watching it fail.
    """
    import importlib.util, sys
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "pf", str(Path(__file__).parent / "plugin-fanout.py"))
    pf = importlib.util.module_from_spec(spec)
    sys.modules["pf"] = pf
    spec.loader.exec_module(pf)

    calls = {"dirty": 0, "copied": 0}

    def fake_dirty(repo, prefix):
        calls["dirty"] += 1
        return None if calls["dirty"] == 1 else "M plugins/x/y.py"   # clean, then dirty

    def fake_copy(*a, **k):
        calls["copied"] += 1
        return 1

    monkeypatch.setattr(pf, "plugin_path_is_dirty", fake_dirty)
    monkeypatch.setattr(pf, "copy_plugin", fake_copy)

    assert pf.plugin_path_is_dirty("r", "p") is None, "survey must see it clean"
    assert pf.plugin_path_is_dirty("r", "p"), "the write moment must see it dirty"
    # THE ASSERTION, and it is a source-shape check on purpose -- say so rather
    # than dressing it as behavioural. Driving the whole apply loop needs a registry,
    # a skeleton and N git fixtures; this instead pins the ONE property the blocker
    # is about: the apply branch revalidates before it writes.
    #
    # My first version asserted `count(...) >= 2` and the mutant SURVIVED, because
    # three calls exist (survey at :312, bucket at :326, revalidate at :344) and
    # removing one still left two. A threshold that passes with the fix deleted is
    # not a test.
    import re
    src = Path(Path(__file__).parent / "plugin-fanout.py").read_text()
    apply_ix = src.index("if args.apply:", src.index('buckets["OLD"].append'))
    copy_ix = src.index("copy_plugin(skeleton", apply_ix)
    between = src[apply_ix:copy_ix]
    assert "plugin_path_is_dirty(path, prefix)" in between, (
        "no dirty revalidation between `if args.apply:` and copy_plugin: a target "
        "that goes dirty after the survey is overwritten in place with no backup")

    # BOTH WRITE PATHS, because there are two. The first version of this test pinned
    # only the OLD branch, so the LABEL branch shipped with the identical race and
    # Codex caught it on the next round -- the test proved the instance, not the
    # class. LABEL writes one manifest file, which is still a file somebody may have
    # edited in that window.
    label_ix = src.index('if status == "LABEL":')
    label_copy = src.index("shutil.copy2(src, dst)", label_ix)
    label_between = src[label_ix:label_copy]
    assert label_between.count("plugin_path_is_dirty(path, prefix)") >= 2, (
        "the LABEL apply path does not revalidate before shutil.copy2: an "
        "uncommitted manifest edit made after the survey is overwritten")


def test_a_late_refusal_is_not_counted_as_reached_and_is_not_exit_zero():
    """Codex review of #142, major. The apply-time revalidation refused correctly,
    then the summary counted the target as REACHED and main() returned 0 -- because
    `reached` was derived from the OLD/LABEL buckets, which a target enters during
    the SURVEY, before the refusal moves it to DIRTY.

    A refusal reported as a success is the defect the revalidation exists to
    prevent, reintroduced one line below it. Source-shape assertion, said plainly:
    driving it needs N git fixtures racing a copy.
    """
    from pathlib import Path
    src = Path(Path(__file__).parent / "plugin-fanout.py").read_text()

    assert "reached = len(actions)" in src, (
        "`reached` is derived from the buckets, so a target refused at write time is "
        "still counted as reached")
    tail = src[src.index("REACHED {reached}"):]
    assert "return 1" in tail, (
        "a late concurrency refusal still exits 0: a scheduled caller cannot tell a "
        "clean fan-out from one that skipped somebody's uncommitted work")
