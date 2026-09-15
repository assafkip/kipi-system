#!/usr/bin/env python3
"""Paired test for capability-gate.py (prd-silent-absence-capability-gate).

Every section builds a THROWAWAY sandbox repo in a tempdir and runs the real
gate against it via subprocess — never against the live repo (fable-discipline
test isolation). Sections map to the PRD's binding contracts and are
selectable: --only schema|overlay|quarantine|wiring|runner|mode|negative-proof.

The negative-proof section is the F-matrix (finding-7): F1 undeclared-caught,
F3 skeleton-only skip + undeclared-fails-in-instance, F2 unwired-caught,
vanished-artifact-caught. A gate that cannot be seen to FAIL is a rubber stamp.
"""
import argparse
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

GATE = pathlib.Path(__file__).resolve().parent / "capability-gate.py"
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import capability_manifest  # noqa: E402


def write_manifest(root, m):
    """Write the sandbox repo's manifest in the layout the gate actually reads.

    The manifest is a fragment DIRECTORY, one JSON per declaration, because the
    single 182-entry array it replaced was the merge conflict in 37 of 41
    conflicting PRs. Every fixture below still hands over a whole manifest dict
    -- the explode is the only thing that moved, so a section that used to
    assert on a manifest shape still asserts on exactly that shape.
    """
    capability_manifest.explode(root, m)


def duplicate_fragment(root, section, dest_name="a-copy.json"):
    """Copy one declaration to a second filename in the same section.

    The array layout let a duplicate be written by appending the same entry
    twice. A fragment is named after the declaration it carries, so an explode
    can no longer produce one -- the only way a duplicate reaches the assembled
    view now is a hand-copied fragment, which is the shape this reproduces. The
    duplicate rules in validate_manifest have to keep firing on it, and the
    name/declaration mismatch has to be loud on top, or one entry could silently
    overwrite another.
    """
    sdir = capability_manifest.fragment_dir(root) / section
    src = sorted(f for f in sdir.iterdir() if f.suffix == ".json")[0]
    (sdir / dest_name).write_text(src.read_text())


failures = []


def check(name, cond):
    if cond:
        print(f"PASS: {name}")
    else:
        failures.append(name)
        print(f"FAIL: {name}")


def make_repo(tmp, skeleton=True, manifest=None):
    root = pathlib.Path(tmp)
    (root / "q-system/.q-system/scripts/test").mkdir(parents=True)
    if skeleton:
        (root / "instance-registry.json").write_text('{"instances": []}')
    m = manifest if manifest is not None else base_manifest()
    write_manifest(root, m)
    return root


def base_manifest(**over):
    m = {"schema_version": 1, "expected_tests": [], "required_data": [],
         "skeleton_only": [], "declared_inert": [], "uncovered_known": []}
    m.update(over)
    return m


def add_test(root, rel, body="import sys; sys.exit(0)"):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    if rel.endswith(".sh"):
        p.write_text("#!/bin/bash\n" + body + "\n")
    else:
        p.write_text(body + "\n")
    return rel


def entry(rel, **kw):
    e = {"path": rel, "runner": "bash" if rel.endswith(".sh") else "python3"}
    e.update(kw)
    return e


def run_gate(root, *args):
    r = subprocess.run([sys.executable, str(GATE), "--repo-root", str(root), *args],
                       capture_output=True, text=True, timeout=120)
    return r.returncode, r.stdout + r.stderr


def sec_schema():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp, manifest={"schema_version": 99})
        rc, out = run_gate(root, "--check-only")
        check("schema: wrong version RED", rc == 1 and "schema_version" in out)
    for bad in (True, 1.0, "1"):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp, manifest=base_manifest(schema_version=bad))
            rc, out = run_gate(root, "--check-only")
            check(f"schema: non-int version {bad!r} RED", rc == 1 and "schema_version" in out)
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp, manifest=base_manifest(
            skeleton_only=["q-system/a.py"]))
        duplicate_fragment(root, "skeleton_only")
        rc, out = run_gate(root, "--check-only")
        check("schema: duplicate in skeleton_only RED", rc == 1 and "duplicate path in skeleton_only" in out)
    with tempfile.TemporaryDirectory() as tmp:
        # An unknown top-level KEY is now an unknown section DIRECTORY: the
        # assembler builds the dict from the known sections, so that is the only
        # shape an undeclared bucket can take. The property is unchanged -- a
        # bucket nothing reads must be RED, never silently ignored.
        root = make_repo(tmp)
        (capability_manifest.fragment_dir(root) / "bogus_key").mkdir()
        rc, out = run_gate(root, "--check-only")
        check("schema: unknown section dir RED",
              rc == 1 and "unknown fragment section" in out)
    with tempfile.TemporaryDirectory() as tmp:
        # and a stray file in the fragment root, which is the other way to write
        # a declaration nothing will ever assemble
        root = make_repo(tmp)
        (capability_manifest.fragment_dir(root) / "loose.json").write_text("{}")
        rc, out = run_gate(root, "--check-only")
        check("schema: stray file in fragment root RED",
              rc == 1 and "stray file in fragment root" in out)
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        rel = add_test(root, "q-system/.q-system/scripts/test_a.py")
        write_manifest(root, base_manifest(expected_tests=[entry(rel)]))
        duplicate_fragment(root, "expected_tests")
        rc, out = run_gate(root, "--check-only")
        check("schema: duplicate path RED", rc == 1 and "duplicate" in out)
        check("schema: fragment name mismatch RED",
              rc == 1 and "does not match its declaration" in out)
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        write_manifest(root, base_manifest())
        sdir = capability_manifest.fragment_dir(root) / "expected_tests"
        sdir.mkdir(parents=True, exist_ok=True)
        (sdir / "broken.json").write_text("{nope")
        rc, out = run_gate(root, "--check-only")
        check("schema: malformed JSON RED", rc == 1 and "malformed" in out)
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        rel = add_test(root, "q-system/.q-system/scripts/test_a.py")
        m = base_manifest(expected_tests=[entry(rel, timeout_s=9999)])
        write_manifest(root, m)
        rc, out = run_gate(root, "--check-only")
        check("schema: timeout out of bounds RED", rc == 1 and "out of bounds" in out)
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        shutil.rmtree(capability_manifest.fragment_dir(root))
        rc, out = run_gate(root, "--check-only")
        check("schema: missing manifest RED", rc == 1 and "manifest missing" in out)
    with tempfile.TemporaryDirectory() as tmp:
        # SINGLE WRITER. A rebase of one of the 37 branches that predate the
        # split can resurrect the monolith. Picking a winner would silently drop
        # one source's declarations -- the same loss class the split exists to
        # end -- so two sources is RED, and it names both.
        root = make_repo(tmp)
        (root / capability_manifest.LEGACY_MANIFEST).write_text(
            json.dumps(base_manifest()))
        rc, out = run_gate(root, "--check-only")
        check("schema: legacy monolith beside the fragment dir RED",
              rc == 1 and "TWO manifest sources" in out)
    with tempfile.TemporaryDirectory() as tmp:
        # and the monolith ALONE, which is a checkout that never got the split
        root = make_repo(tmp)
        shutil.rmtree(capability_manifest.fragment_dir(root))
        (root / capability_manifest.LEGACY_MANIFEST).write_text(
            json.dumps(base_manifest()))
        rc, out = run_gate(root, "--check-only")
        check("schema: legacy monolith alone RED (not silently honoured)",
              rc == 1 and "predates the fragment migration" in out)
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp, manifest=base_manifest(
            required_data=[{"path": "q-system/x.json", "scope": "skeletn"}]))
        rc, out = run_gate(root, "--check-only")
        check("schema: required_data scope typo RED", rc == 1 and "scope must be" in out)
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp, manifest=base_manifest(
            expected_tests=[{"path": "/etc/passwd", "runner": "bash"}]))
        rc, out = run_gate(root, "--check-only")
        check("schema: absolute path RED", rc == 1 and "unsafe" in out)
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp, manifest=base_manifest(
            expected_tests=[{"path": "q-system/../../x/test_a.py", "runner": "python3"}]))
        rc, out = run_gate(root, "--check-only")
        check("schema: dotdot escape RED", rc == 1 and "unsafe" in out)


def sec_replay():
    """--add-from: the rebase tool for the branches that predate the split.

    It is additive by contract, so the negative case matters more than the happy
    one: a branch that REMOVED a declaration must be reported, not silently
    replayed as a deletion. Removing someone else's declaration during a rebase
    is exactly the silent loss the split exists to prevent.
    """
    import subprocess as sp

    def add_from(root, base, head):
        b = root / "base.json"; h = root / "head.json"
        b.write_text(json.dumps(base)); h.write_text(json.dumps(head))
        r = sp.run([sys.executable,
                    str(pathlib.Path(__file__).resolve().parent / "capability_manifest.py"),
                    "--root", str(root), "--add-from", str(b), str(h)],
                   capture_output=True, text=True, timeout=60)
        return r.returncode, r.stdout + r.stderr

    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        rel = add_test(root, "q-system/.q-system/scripts/test_new.py")
        base = base_manifest()
        head = base_manifest(expected_tests=[entry(rel)])
        rc, out = add_from(root, base, head)
        check("replay: an added declaration becomes a fragment",
              rc == 0 and "added fragment" in out)
        rc2, out2 = run_gate(root, "--check-only")
        check("replay: the replayed repo is GREEN (declaration and file agree)",
              rc2 == 0)

    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        rel = add_test(root, "q-system/.q-system/scripts/test_new.py")
        base = base_manifest(expected_tests=[entry(rel)])
        head = base_manifest()
        rc, out = add_from(root, base, head)
        check("replay: a REMOVED declaration is refused, never silently dropped",
              rc == 1 and "REMOVED" in out)

    # EDIT, the case that was refused as a removal until sp-6b25c567. Byte-keyed
    # diffing put the old serialization in `base - head` and the new one in
    # `head - base`, so changing one field of a declaration looked like deleting
    # someone else's and adding your own. PR #207 is exactly this shape.
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        rel = add_test(root, "q-system/.q-system/scripts/test_new.py")
        old = entry(rel)
        new = dict(old, runner="bash")
        base = base_manifest(expected_tests=[old])
        head = base_manifest(expected_tests=[new])
        # main still holds the base version, so the edit is a safe fast-forward.
        sdir = root / capability_manifest.FRAGMENT_DIR / "expected_tests"
        sdir.mkdir(parents=True, exist_ok=True)
        (sdir / capability_manifest.fragment_name("expected_tests", old)).write_text(
            json.dumps(old, indent=1, sort_keys=True) + "\n")
        rc, out = add_from(root, base, head)
        check("replay: an EDITED declaration replays, not refused as a removal",
              rc == 0 and "REMOVED" not in out)
        landed = json.loads(
            (sdir / capability_manifest.fragment_name("expected_tests", new)).read_text())
        check("replay: the edit actually landed on disk",
              landed.get("runner") == "bash")

    # The same edit, but main changed that declaration too. Taking the branch's
    # version would drop main's, which is the deletion class this tool refuses.
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        rel = add_test(root, "q-system/.q-system/scripts/test_new.py")
        old = entry(rel)
        theirs = dict(old, runner="sh")
        ours = dict(old, runner="bash")
        base = base_manifest(expected_tests=[old])
        head = base_manifest(expected_tests=[ours])
        sdir = root / capability_manifest.FRAGMENT_DIR / "expected_tests"
        sdir.mkdir(parents=True, exist_ok=True)
        frag = sdir / capability_manifest.fragment_name("expected_tests", old)
        frag.write_text(json.dumps(theirs, indent=1, sort_keys=True) + "\n")
        rc, out = add_from(root, base, head)
        check("replay: an edit that collides with main is refused",
              rc == 1 and "EDITED" in out)
        check("replay: main's version survives the refusal",
              json.loads(frag.read_text()).get("runner") == "sh")

    # The edit whose fragment is GONE. Main removed that declaration on purpose;
    # replaying the branch's edit would write it back and resurrect a gate main
    # retired. Codex major, PR #285 round 1: _read_fragment returns None for both
    # "missing" and "unreadable", and the old check only refused a non-None value
    # that differed, so a deletion read as a safe edit and the tool reported
    # success. Same loss class as a silent removal, pointing the other way.
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        rel = add_test(root, "q-system/.q-system/scripts/test_new.py")
        old = entry(rel)
        base = base_manifest(expected_tests=[old])
        head = base_manifest(expected_tests=[dict(old, runner="bash")])
        sdir = root / capability_manifest.FRAGMENT_DIR / "expected_tests"
        rc, out = add_from(root, base, head)
        check("replay: an edit whose fragment main REMOVED is refused",
              rc == 1 and "EDITED" in out and "removed" in out)
        check("replay: the removed declaration is not resurrected",
              not (sdir / capability_manifest.fragment_name(
                  "expected_tests", old)).exists())

    # The edit whose fragment is unreadable. This cannot tell a concurrent edit
    # from a removal, so it must refuse rather than pick one.
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        rel = add_test(root, "q-system/.q-system/scripts/test_new.py")
        old = entry(rel)
        base = base_manifest(expected_tests=[old])
        head = base_manifest(expected_tests=[dict(old, runner="bash")])
        sdir = root / capability_manifest.FRAGMENT_DIR / "expected_tests"
        sdir.mkdir(parents=True, exist_ok=True)
        frag = sdir / capability_manifest.fragment_name("expected_tests", old)
        frag.write_text("{ this is not json")
        rc, out = add_from(root, base, head)
        check("replay: an unreadable fragment is refused, never overwritten",
              rc == 1 and "unreadable" in out)
        check("replay: the unreadable fragment is left alone",
              frag.read_text() == "{ this is not json")


def sec_overlay():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        rel = add_test(root, "q-system/.q-system/scripts/test_extra.py")
        (root / "capability-manifest.local.json").write_text(
            json.dumps({"expected_tests": [entry(rel)]}))
        rc, out = run_gate(root)
        check("overlay: ADD of new test accepted + run", rc == 0 and "ran=1" in out)
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        rel = add_test(root, "q-system/.q-system/scripts/test_a.py")
        m = base_manifest(expected_tests=[entry(rel)])
        write_manifest(root, m)
        (root / "capability-manifest.local.json").write_text(
            json.dumps({"expected_tests": [entry(rel)]}))
        rc, out = run_gate(root, "--check-only")
        check("overlay: collision with canonical RED", rc == 1 and "collides" in out)
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        (root / "capability-manifest.local.json").write_text(
            json.dumps({"skeleton_only": ["x"]}))
        rc, out = run_gate(root, "--check-only")
        check("overlay: reclassification key RED", rc == 1 and "may only ADD" in out)
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        (root / "capability-manifest.local.json").write_text(
            json.dumps({"expected_tests": [{"path": "/tmp/evil.py", "runner": "python3"}]}))
        rc, out = run_gate(root, "--check-only")
        check("overlay: unsafe path RED", rc == 1 and "unsafe" in out)
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        rel = add_test(root, "q-system/.q-system/scripts/test_extra.py")
        (root / "capability-manifest.local.json").write_text(
            json.dumps({"expected_tests": [{"path": rel, "runner": "cobol"}]}))
        rc, out = run_gate(root, "--check-only")
        check("overlay: invalid runner RED", rc == 1 and "runner" in out)
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp, manifest=base_manifest(
            required_data=[{"path": "q-system/canonical/x.json", "scope": ["nobody"]}]))
        (root / "q-system/canonical").mkdir(parents=True)
        (root / "capability-manifest.local.json").write_text(json.dumps(
            {"required_data": [{"path": "q-system/canonical/x.json", "scope": ["nobody-else"]}]}))
        rc, out = run_gate(root, "--check-only")
        check("overlay: required_data collision with canonical RED",
              rc == 1 and "collides with canonical required_data" in out)


def sec_quarantine():
    q = {"reason": "r", "spillover_id": "sp-x", "expires": "2099-01-01"}
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        rel = add_test(root, "q-system/.q-system/scripts/test_bad.py", "import sys; sys.exit(1)")
        m = base_manifest(expected_tests=[entry(rel, quarantine=q)])
        write_manifest(root, m)
        rc, out = run_gate(root)
        check("quarantine: valid future expiry skips + notes", rc == 0 and "QUARANTINED" in out)
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        rel = add_test(root, "q-system/.q-system/scripts/test_bad.py", "import sys; sys.exit(1)")
        expired = dict(q, expires="2020-01-01")
        m = base_manifest(expected_tests=[entry(rel, quarantine=expired)])
        write_manifest(root, m)
        rc, out = run_gate(root, "--check-only")
        check("quarantine: EXPIRED is RED", rc == 1 and "EXPIRED" in out)
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        rel = add_test(root, "q-system/.q-system/scripts/test_bad.py", "import sys; sys.exit(1)")
        m = base_manifest(expected_tests=[entry(rel, quarantine={"reason": "r"})])
        write_manifest(root, m)
        rc, out = run_gate(root, "--check-only")
        check("quarantine: missing fields RED", rc == 1 and "missing" in out)


def engine(root, rel):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('if __name__ == "__main__":\n    print("hi")\n')
    return rel


def sec_wiring():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        engine(root, "q-system/.q-system/scripts/dead-engine.py")
        rc, out = run_gate(root, "--check-only")
        check("wiring: unwired engine RED", rc == 1 and "inert-engine" in out
              and "dead-engine.py" in out)
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        rel = engine(root, "q-system/.q-system/scripts/dead-engine.py")
        m = base_manifest(declared_inert=[{"path": rel, "reason": "parked",
                                           "spillover_id": "sp-x"}])
        write_manifest(root, m)
        rc, out = run_gate(root, "--check-only")
        check("wiring: declared_inert passes with note", rc == 0 and "DECLARED-INERT" in out)
    # ASK-746 neighbour: the candidate filter said `"__main__" in text`, a bare
    # substring over the whole file. conftest.py has no exec bit and no guard --
    # its only `__main__` is one line of PROSE in its docstring telling future
    # authors to guard their exits. That sentence promoted it to a candidate, and
    # since pytest loads conftest BY NAME it could never prove itself wired, so
    # main's Skeleton Validation carried `inert-engine: conftest.py` from
    # 2026-08-10 to 2026-08-14. The tempting "fix" is a fake reference on a
    # wiring surface; the real one is that this was never an engine.
    #
    # The control for these lives above: "wiring: unwired engine RED". If a
    # loosened filter ever stops seeing real dead engines, that case goes green
    # and these three cannot tell you, so they are read together.
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        c = root / "q-system/.q-system/scripts/conftest.py"
        c.parent.mkdir(parents=True, exist_ok=True)
        c.write_text('"""Prose only: guard exits under '
                     '`if __name__ == "__main__":` so it stays importable."""\n')
        rc, out = run_gate(root, "--check-only")
        check("ASK-746: conftest.py mentioning __main__ in PROSE is not inert",
              rc == 0 and "conftest.py" not in out)
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        c = root / "q-system/.q-system/scripts/conftest.py"
        c.parent.mkdir(parents=True, exist_ok=True)
        c.write_text('if __name__ == "__main__":\n    print("hi")\n')
        c.chmod(0o755)
        rc, out = run_gate(root, "--check-only")
        check("ASK-746: conftest.py is runner-loaded, inert even with a real guard"
              " + exec bit", rc == 0 and "conftest.py" not in out)
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        p = root / "q-system/.q-system/scripts/talks_about_main.py"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('"""A library. See `if __name__ == "__main__":` elsewhere."""\n'
                     "def helper():\n    return 1\n")
        rc, out = run_gate(root, "--check-only")
        check("ASK-746: a library that only TALKS about __main__ is not an engine",
              rc == 0 and "talks_about_main" not in out)

    # ASK-517: an engine wired by a PYTHON IMPORT must not read as inert.
    # The matcher was `p.name in surface`, i.e. "loops_path.py" WITH the
    # extension, while an import names the module by its stem -- so
    # q-system/.q-system/scripts/loops_path.py, imported by the wired hook
    # q-system/hooks/session-start.py, reddened origin/main and blocked every
    # merge in the repo. Three cases, because the dangerous fix is one that
    # loosens the matcher until nothing is ever inert again.
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        engine(root, "q-system/.q-system/scripts/imported_engine.py")
        hook = root / "q-system/hooks/session-start.py"
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text("import imported_engine\nimported_engine.go()\n")
        rc, out = run_gate(root, "--check-only")
        check("ASK-517: engine wired by `import <stem>` is NOT inert",
              rc == 0 and "imported_engine" not in out)
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        engine(root, "q-system/.q-system/scripts/from_imported.py")
        hook = root / "q-system/hooks/session-start.py"
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text("from from_imported import thing\n")
        rc, out = run_gate(root, "--check-only")
        check("ASK-517: `from <stem> import ...` also counts",
              rc == 0 and "from_imported" not in out)
    with tempfile.TemporaryDirectory() as tmp:
        # PRECISION half: a bare mention of the stem in prose is NOT wiring.
        # Matching a bare stem would make any script called utils.py read as
        # wired anywhere the word "utils" appears, which turns the check off
        # without anyone noticing.
        root = make_repo(tmp)
        engine(root, "q-system/.q-system/scripts/only_mentioned.py")
        hook = root / "q-system/hooks/session-start.py"
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text("# only_mentioned is a nice idea, nobody calls it\n")
        rc, out = run_gate(root, "--check-only")
        check("ASK-517: a prose mention is NOT wiring, still RED",
              rc == 1 and "only_mentioned.py" in out)

    # plugins/ is scanned but REPORT-ONLY: it must surface as a note and must
    # NOT fail the gate, because the widening could not be validated from a
    # worktree (sp-1cb1a348). Both halves are asserted -- a note-only check
    # that silently became blocking would red 27 scripts across 22 instances.
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        engine(root, "plugins/prd-os/scripts/dead-plugin-engine.py")
        rc, out = run_gate(root, "--check-only")
        check("wiring: unwired plugin engine is REPORTED",
              "dead-plugin-engine.py" in out and "report-only" in out)
        check("wiring: unwired plugin engine does NOT fail the gate", rc == 0)
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        engine(root, "plugins/prd-os/scripts/wired-plugin-engine.py")
        hooks = root / "plugins/prd-os/hooks"; hooks.mkdir(parents=True, exist_ok=True)
        (hooks / "hooks.json").write_text('{"c": "wired-plugin-engine.py"}')
        rc, out = run_gate(root, "--check-only")
        check("wiring: wired plugin engine is not reported",
              rc == 0 and "wired-plugin-engine.py" not in out)
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        engine(root, "q-system/.q-system/scripts/hooked-engine.py")
        (root / ".claude").mkdir()
        (root / ".claude/settings.json").write_text('{"hooks": "hooked-engine.py"}')
        rc, out = run_gate(root, "--check-only")
        check("wiring: settings.json reference is wired", rc == 0)
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        main_guard = 'if __name__ == "__main__":\n    pass\n'
        (root / "q-system/.q-system/scripts/chain-a.py").parent.mkdir(parents=True, exist_ok=True)
        (root / "q-system/.q-system/scripts/chain-a.py").write_text(
            'import subprocess\nsubprocess.run(["python3", "chain-b.py"])\n' + main_guard)
        engine(root, "q-system/.q-system/scripts/chain-b.py")
        (root / ".claude").mkdir()
        (root / ".claude/settings.json").write_text('{"hooks": "chain-a.py"}')
        rc, out = run_gate(root, "--check-only")
        check("wiring: closure wires hook->A->B chain", rc == 0)
        # negative control: unwired C referencing D must NOT wire D
        (root / "q-system/.q-system/scripts/orphan-c.py").write_text(
            'import subprocess\nsubprocess.run(["python3", "orphan-d.py"])\n' + main_guard)
        engine(root, "q-system/.q-system/scripts/orphan-d.py")
        rc, out = run_gate(root, "--check-only")
        check("wiring: unwired peer cannot wire its sibling",
              rc == 1 and "orphan-c.py" in out and "orphan-d.py" in out)
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        rel = engine(root, "q-system/.q-system/scripts/lonely.py")
        helper = root / "q-system/.q-system/scripts/test/helper-fixture.sh"
        helper.parent.mkdir(parents=True, exist_ok=True)
        helper.write_text("#!/bin/bash\npython3 lonely.py\n")
        rc, out = run_gate(root, "--check-only")
        check("wiring: file under test/ dir is NOT a wiring surface",
              rc == 1 and "lonely.py" in out)
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        rel = engine(root, "q-system/.q-system/scripts/wt-only.py")
        wt = root / ".claude/worktrees/copy/note.md"
        wt.parent.mkdir(parents=True)
        wt.write_text("run wt-only.py sometimes")
        rc, out = run_gate(root, "--check-only")
        check("wiring: worktree copy is NOT a wiring surface",
              rc == 1 and "wt-only.py" in out)
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp, skeleton=False)
        engine(root, "q-system/.q-system/scripts/dead-engine.py")
        rc, out = run_gate(root, "--check-only")
        check("wiring: instance mode SKIPS inert check with loud note",
              rc == 0 and "inert-engine check: skeleton-only" in out)


def sec_runner():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        ok_py = add_test(root, "q-system/.q-system/scripts/test_ok.py")
        ok_sh = add_test(root, "q-system/.q-system/scripts/test/test-ok.sh", "exit 0")
        m = base_manifest(expected_tests=[entry(ok_py), entry(ok_sh)])
        write_manifest(root, m)
        rc, out = run_gate(root)
        check("runner: both runners green, ran=2", rc == 0 and "ran=2" in out)
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        bad = add_test(root, "q-system/.q-system/scripts/test_bad.py",
                       'print("boom detail")\nimport sys; sys.exit(3)')
        m = base_manifest(expected_tests=[entry(bad)])
        write_manifest(root, m)
        rc, out = run_gate(root)
        check("runner: failing test RED with tail",
              rc == 1 and "test-failed rc=3" in out and "boom detail" in out)
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        slow = add_test(root, "q-system/.q-system/scripts/test_slow.py",
                        'print("hanging-on-xyz", flush=True)\nimport time; time.sleep(30)')
        m = base_manifest(expected_tests=[entry(slow, timeout_s=5)])
        write_manifest(root, m)
        rc, out = run_gate(root)
        check("runner: timeout RED with partial output tail",
              rc == 1 and "test-timeout" in out and "hanging-on-xyz" in out)
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        env_probe = ('import os, sys\nfrom pathlib import Path\n'
                     'ok = (os.environ.get("QROOT", "").endswith("q-system")\n'
                     '      and Path.cwd().resolve() == Path(__file__).resolve().parents[3])\n'
                     'sys.exit(0 if ok else 1)')
        rel = add_test(root, "q-system/.q-system/scripts/test_envprobe.py", env_probe)
        m = base_manifest(expected_tests=[entry(rel)])
        write_manifest(root, m)
        rc, out = run_gate(root)
        check("runner: cwd=repo root and QROOT set (contract pinned)", rc == 0)
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        noisy = "\n".join(f'print("line{i}")' for i in range(1, 31)) + "\nimport sys; sys.exit(1)"
        rel = add_test(root, "q-system/.q-system/scripts/test_noisy.py", noisy)
        m = base_manifest(expected_tests=[entry(rel)])
        write_manifest(root, m)
        rc, out = run_gate(root)
        check("runner: exactly last-20-line tail (line30 in, line5 out)",
              rc == 1 and "line30" in out and "line5\n" not in out and "line10\n" not in out)


def sec_mode():
    crash = 'import sys\nopen("/nonexistent-skeleton-file-xyz")\n'
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp, skeleton=False)
        rel = add_test(root, "q-system/.q-system/scripts/test_skel.py", crash)
        m = base_manifest(expected_tests=[entry(rel)], skeleton_only=[rel])
        write_manifest(root, m)
        rc, out = run_gate(root)
        check("mode: instance skips skeleton_only (crashing test passes by skip)",
              rc == 0 and "skipped-skeleton-only=1" in out and "mode=instance" in out)
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)  # valid registry present
        rc, out = run_gate(root, "--check-only")
        check("mode: valid registry detected as skeleton", rc == 0 and "mode=skeleton" in out)
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp, skeleton=False)
        rc, out = run_gate(root, "--check-only")
        check("mode: no registry detected as instance", rc == 0 and "mode=instance" in out)
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        (root / "instance-registry.json").write_text("{broken")
        rc, out = run_gate(root, "--check-only")
        check("mode: unparseable registry RED", rc == 1 and "unreadable" in out)
    with tempfile.TemporaryDirectory() as tmp:
        wt = pathlib.Path(tmp) / ".claude/worktrees/copy1"
        wt.mkdir(parents=True)
        r = subprocess.run([sys.executable, str(GATE), "--repo-root", str(wt)],
                           capture_output=True, text=True)
        check("mode: worktree refused exit 3", r.returncode == 3 and "REFUSED" in r.stderr)


def sec_negative_proof():
    # F1: an artifact that exists but is not declared MUST fail the gate.
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        add_test(root, "q-system/.q-system/scripts/test_sneaky.py")
        rc, out = run_gate(root, "--check-only")
        check("F1: present-but-undeclared RED", rc == 1 and "present-but-undeclared" in out)
    # F1b: the SAME defect one directory over. F1 above places its undeclared
    # file in `scripts/`, which discovery has always walked recursively -- so
    # the negative proof exercised the one path that already worked, and the
    # sibling directories were never asked about. `.q-system` itself was
    # scanned with `glob`, not `rglob`, so every subdirectory of it except
    # scripts/ was invisible to this direction of the diff. On main at
    # 569b0ec0 that hid ten real test files in `.q-system/tests/`: 174
    # assertions, green, executed by no runner at all. This case is the one
    # that goes red if discovery is ever narrowed back.
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        add_test(root, "q-system/.q-system/tests/test_sneaky_nested.py")
        rc, out = run_gate(root, "--check-only")
        check("F1b: present-but-undeclared in a NESTED .q-system dir RED",
              rc == 1 and "test_sneaky_nested.py" in out)
    # F3a: declared skeleton_only is SKIPPED in an instance (no crash) — and
    # the skip must be visible via the SKIP path, not an unrelated no-run
    # (codex, sag-negative-proof-matrix)
    crash = 'open("/settings-template-only-in-skeleton.json")\n'
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp, skeleton=False)
        rel = add_test(root, "q-system/.q-system/scripts/test_skelwire.py", crash)
        m = base_manifest(expected_tests=[entry(rel)], skeleton_only=[rel])
        write_manifest(root, m)
        rc, out = run_gate(root)
        check("F3a: declared skeleton-only skipped in instance",
              rc == 0 and "mode=instance" in out and "skipped-skeleton-only=1" in out)
    # F3b: the SAME artifact undeclared in an instance fails loud (runs+crashes).
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp, skeleton=False)
        rel = add_test(root, "q-system/.q-system/scripts/test_skelwire.py", crash)
        m = base_manifest(expected_tests=[entry(rel)])
        write_manifest(root, m)
        rc, out = run_gate(root)
        check("F3b: undeclared skeleton-only FAILS in instance", rc == 1 and "test-failed" in out)
    # F2: an unwired engine fails loud (also covered in sec_wiring; kept in the
    # matrix so the negative-proof check is self-contained).
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        engine(root, "q-system/.q-system/scripts/big-dead-engine.py")
        rc, out = run_gate(root, "--check-only")
        check("F2: unwired engine RED", rc == 1 and "inert-engine" in out)
    # Vanished artifact: declared but deleted MUST fail.
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        m = base_manifest(expected_tests=[entry("q-system/.q-system/scripts/test_gone.py")])
        write_manifest(root, m)
        rc, out = run_gate(root, "--check-only")
        check("vanished: declared-but-missing RED", rc == 1 and "declared-but-missing" in out)
    # Required data: in-scope missing file MUST fail; out-of-scope must not.
    # spillover-skip: "out-of-scope" here is a required_data `scope` field that
    # does not name this instance, not deferred work. Nothing to capture.
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        m = base_manifest(required_data=[{"path": "q-system/canonical/x.json", "scope": "all"}])
        write_manifest(root, m)
        rc, out = run_gate(root, "--check-only")
        check("required_data: in-scope missing RED", rc == 1 and "required-data-missing" in out)
        # scope-LIST positive match: names the sandbox's own basename, so an
        # implementation that ignores list scopes cannot pass (codex,
        # sag-negative-proof-matrix)
        m["required_data"][0]["scope"] = [pathlib.Path(tmp).resolve().name]
        write_manifest(root, m)
        rc, out = run_gate(root, "--check-only")
        check("required_data: scope-list match demanded RED",
              rc == 1 and "required-data-missing" in out)
        m["required_data"][0]["scope"] = ["some-other-instance"]
        write_manifest(root, m)
        rc, out = run_gate(root, "--check-only")
        check("required_data: out-of-scope not demanded", rc == 0)  # spillover-skip
    # Token-guard fixes are part of the pre-propagation matrix (finding-7):
    # the paired suite must be green, executed here, not assumed.
    tg_test = pathlib.Path(__file__).resolve().parent / "test_token_guard_observation.py"
    r = subprocess.run([sys.executable, str(tg_test)], capture_output=True, text=True, timeout=60)
    check("token-guard observation + stall suite green", r.returncode == 0)


def sec_skeleton_only_absent():
    # A skeleton_only path that is GENUINELY ABSENT (never created) and outside
    # the scan roots -- the fleet-RED shape codex named on PR #216. The earlier
    # tests created the file first, so no test could fail when it was missing.
    rel = "test_root_only_absent.sh"
    # ASK-972: a repo-root declaration now needs a scope_exempt prefix, so the
    # fixture carries one. That is load-bearing rather than boilerplate — it is
    # what proves the exemption waives only the SCOPE check: the skeleton case
    # below still goes RED on the file's absence.
    ex = [{"prefix": "test_", "reason": "fixture: repo-root skeleton-only artifact"}]
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp, skeleton=False)
        m = base_manifest(expected_tests=[entry(rel, runner="bash")],
                          skeleton_only=[rel], scope_exempt=ex)
        write_manifest(root, m)
        rc, out = run_gate(root)
        check("skeleton-only-absent: instance is GREEN without the file",
              rc == 0 and "declared-but-missing" not in out)
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)  # skeleton mode: the file MUST exist here
        m = base_manifest(expected_tests=[entry(rel, runner="bash")],
                          skeleton_only=[rel], scope_exempt=ex)
        write_manifest(root, m)
        rc, out = run_gate(root)
        check("skeleton-only-absent: skeleton is still RED without the file",
              rc == 1 and "declared-but-missing (outside scan root)" in out)


def sec_scan_scope():
    """ASK-972: a declaration outside SCAN_ROOTS escaped BOTH directions silently.

    The F3 direction (an artifact appearing with no declaration) only ever sees
    what `discover_tests` walks, so anything declared elsewhere sat in a scope
    nothing measured -- and nothing SAID so. These cases pin the two halves of
    the fix: an unannounced escape is refused, an announced one is counted out
    loud and still has to exist.
    """
    stray = "test-stray-probe.sh"
    # 1. THE REPRODUCER. Declaring a repo-root path is out of both scan roots.
    #    Before the fix this was accepted in silence and the gate went GREEN.
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        add_test(root, stray)
        m = base_manifest(expected_tests=[entry(stray)])
        write_manifest(root, m)
        rc, out = run_gate(root, "--check-only")
        check("scan-scope: undeclared-exemption escape is RED",
              rc == 1 and "outside the scan roots" in out)
        check("scan-scope: the refusal NAMES the scan roots",
              "q-system/.q-system/scripts" in out)

    # 2. CONTROL. The same artifact inside a scan root is still reported by the
    #    F3 direction exactly as before -- the fix must not trade one blindness
    #    for another.
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        add_test(root, "q-system/.q-system/scripts/test-stray-probe.sh")
        rc, out = run_gate(root, "--check-only")
        check("scan-scope CONTROL: in-scope undeclared still RED",
              rc == 1 and "present-but-undeclared" in out)

    # 3. An ANNOUNCED escape is accepted -- and the run says how many entries
    #    are riding it, so the boundary is legible on every run instead of
    #    being a property you have to go read the source to discover.
    exempt = [{"prefix": "test-", "reason": "repo-root automation tests"}]
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        add_test(root, stray)
        m = base_manifest(expected_tests=[entry(stray)], scope_exempt=exempt)
        write_manifest(root, m)
        rc, out = run_gate(root, "--check-only")
        check("scan-scope: declared exemption is accepted", rc == 0)
        check("scan-scope: the run REPORTS the F3-blind count",
              "1 exempt from undeclared-artifact detection" in out)

    # 4. An exemption waives the SCOPE check, never the EXISTENCE check. If it
    #    waived both, `scope_exempt` would be a delete-anything hatch.
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        m = base_manifest(expected_tests=[entry(stray)], scope_exempt=exempt)
        write_manifest(root, m)
        rc, out = run_gate(root, "--check-only")
        check("scan-scope: exempt-but-vanished is still RED",
              rc == 1 and "declared-but-missing (outside scan root)" in out)

    # 5. The instance-local overlay runs through the same validator, so it
    #    cannot be used to smuggle in an escape the canonical manifest refuses.
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp, skeleton=False)
        add_test(root, stray)
        (root / "capability-manifest.local.json").write_text(
            json.dumps({"expected_tests": [entry(stray)]}))
        rc, out = run_gate(root, "--check-only")
        check("scan-scope: overlay cannot smuggle an escape",
              rc == 1 and "outside the scan roots" in out)

    # 6. The exemption list is itself validated: a reasonless or unsafe prefix
    #    is a silent hole in the one place that is allowed to make holes.
    #    The expected message is asserted EXACTLY, and the unknown-top-level-key
    #    error is asserted ABSENT -- before scope_exempt was a known key these
    #    same cases went red on "unknown top-level keys", which is a pass for
    #    entirely the wrong reason.
    for bad, want, why in (
        (({"prefix": "test-"},), "scope_exempt entry needs prefix+reason", "reasonless"),
        (({"prefix": "/etc/", "reason": "x"},),
         "unsafe or non-relative prefix in scope_exempt", "absolute"),
        (("test-",), "scope_exempt entry needs prefix+reason", "bare string"),
    ):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp, manifest=base_manifest(scope_exempt=list(bad)))
            rc, out = run_gate(root, "--check-only")
            check(f"scan-scope: {why} scope_exempt entry RED",
                  rc == 1 and want in out and "unknown top-level keys" not in out)


SECTIONS = {
    "schema": sec_schema, "overlay": sec_overlay, "replay": sec_replay, "quarantine": sec_quarantine,
    "wiring": sec_wiring, "runner": sec_runner, "mode": sec_mode,
    "negative-proof": sec_negative_proof,
    "skeleton_only_absent": sec_skeleton_only_absent,
    "scan-scope": sec_scan_scope,
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=sorted(SECTIONS), default=None)
    args = ap.parse_args()
    for name, fn in SECTIONS.items():
        if args.only and name != args.only:
            continue
        print(f"--- {name} ---")
        fn()
    if failures:
        print(f"\n{len(failures)} FAILED: {failures}")
        sys.exit(1)
    print("\nALL PASS")


if __name__ == "__main__":
    main()
