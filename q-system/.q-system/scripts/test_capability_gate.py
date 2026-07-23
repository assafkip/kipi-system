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
import subprocess
import sys
import tempfile

GATE = pathlib.Path(__file__).resolve().parent / "capability-gate.py"
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
    (root / "q-system/.q-system/capability-manifest.json").write_text(json.dumps(m))
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
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp, manifest=base_manifest(bogus_key=[]))
        rc, out = run_gate(root, "--check-only")
        check("schema: unknown key RED", rc == 1 and "unknown top-level" in out)
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        rel = add_test(root, "q-system/.q-system/scripts/test_a.py")
        root_m = base_manifest(expected_tests=[entry(rel), entry(rel)])
        (root / "q-system/.q-system/capability-manifest.json").write_text(json.dumps(root_m))
        rc, out = run_gate(root, "--check-only")
        check("schema: duplicate path RED", rc == 1 and "duplicate" in out)
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        (root / "q-system/.q-system/capability-manifest.json").write_text("{nope")
        rc, out = run_gate(root, "--check-only")
        check("schema: malformed JSON RED", rc == 1 and "malformed" in out)
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        rel = add_test(root, "q-system/.q-system/scripts/test_a.py")
        m = base_manifest(expected_tests=[entry(rel, timeout_s=9999)])
        (root / "q-system/.q-system/capability-manifest.json").write_text(json.dumps(m))
        rc, out = run_gate(root, "--check-only")
        check("schema: timeout out of bounds RED", rc == 1 and "out of bounds" in out)
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        (root / "q-system/.q-system/capability-manifest.json").unlink()
        rc, out = run_gate(root, "--check-only")
        check("schema: missing manifest RED", rc == 1 and "manifest missing" in out)


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
        (root / "q-system/.q-system/capability-manifest.json").write_text(json.dumps(m))
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


def sec_quarantine():
    q = {"reason": "r", "spillover_id": "sp-x", "expires": "2099-01-01"}
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        rel = add_test(root, "q-system/.q-system/scripts/test_bad.py", "import sys; sys.exit(1)")
        m = base_manifest(expected_tests=[entry(rel, quarantine=q)])
        (root / "q-system/.q-system/capability-manifest.json").write_text(json.dumps(m))
        rc, out = run_gate(root)
        check("quarantine: valid future expiry skips + notes", rc == 0 and "QUARANTINED" in out)
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        rel = add_test(root, "q-system/.q-system/scripts/test_bad.py", "import sys; sys.exit(1)")
        expired = dict(q, expires="2020-01-01")
        m = base_manifest(expected_tests=[entry(rel, quarantine=expired)])
        (root / "q-system/.q-system/capability-manifest.json").write_text(json.dumps(m))
        rc, out = run_gate(root, "--check-only")
        check("quarantine: EXPIRED is RED", rc == 1 and "EXPIRED" in out)
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        rel = add_test(root, "q-system/.q-system/scripts/test_bad.py", "import sys; sys.exit(1)")
        m = base_manifest(expected_tests=[entry(rel, quarantine={"reason": "r"})])
        (root / "q-system/.q-system/capability-manifest.json").write_text(json.dumps(m))
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
        (root / "q-system/.q-system/capability-manifest.json").write_text(json.dumps(m))
        rc, out = run_gate(root, "--check-only")
        check("wiring: declared_inert passes with note", rc == 0 and "DECLARED-INERT" in out)
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        engine(root, "q-system/.q-system/scripts/hooked-engine.py")
        (root / ".claude").mkdir()
        (root / ".claude/settings.json").write_text('{"hooks": "hooked-engine.py"}')
        rc, out = run_gate(root, "--check-only")
        check("wiring: settings.json reference is wired", rc == 0)
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        engine(root, "q-system/.q-system/scripts/chain-a.py")
        (root / "q-system/.q-system/scripts/chain-a.py").write_text(
            'import subprocess\nsubprocess.run(["python3", "chain-b.py"])\n')
        engine(root, "q-system/.q-system/scripts/chain-b.py")
        (root / ".claude").mkdir()
        (root / ".claude/settings.json").write_text('{"hooks": "chain-a.py"}')
        rc, out = run_gate(root, "--check-only")
        check("wiring: closure wires hook->A->B chain", rc == 0)
        # negative control: unwired C referencing D must NOT wire D
        engine(root, "q-system/.q-system/scripts/orphan-c.py")
        (root / "q-system/.q-system/scripts/orphan-c.py").write_text(
            'import subprocess\nsubprocess.run(["python3", "orphan-d.py"])\n')
        engine(root, "q-system/.q-system/scripts/orphan-d.py")
        rc, out = run_gate(root, "--check-only")
        check("wiring: unwired peer cannot wire its sibling",
              rc == 1 and "orphan-c.py" in out and "orphan-d.py" in out)


def sec_runner():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        ok_py = add_test(root, "q-system/.q-system/scripts/test_ok.py")
        ok_sh = add_test(root, "q-system/.q-system/scripts/test/test-ok.sh", "exit 0")
        m = base_manifest(expected_tests=[entry(ok_py), entry(ok_sh)])
        (root / "q-system/.q-system/capability-manifest.json").write_text(json.dumps(m))
        rc, out = run_gate(root)
        check("runner: both runners green, ran=2", rc == 0 and "ran=2" in out)
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        bad = add_test(root, "q-system/.q-system/scripts/test_bad.py",
                       'print("boom detail")\nimport sys; sys.exit(3)')
        m = base_manifest(expected_tests=[entry(bad)])
        (root / "q-system/.q-system/capability-manifest.json").write_text(json.dumps(m))
        rc, out = run_gate(root)
        check("runner: failing test RED with tail",
              rc == 1 and "test-failed rc=3" in out and "boom detail" in out)
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        slow = add_test(root, "q-system/.q-system/scripts/test_slow.py",
                        "import time; time.sleep(30)")
        m = base_manifest(expected_tests=[entry(slow, timeout_s=5)])
        (root / "q-system/.q-system/capability-manifest.json").write_text(json.dumps(m))
        rc, out = run_gate(root)
        check("runner: timeout RED", rc == 1 and "test-timeout" in out)


def sec_mode():
    crash = 'import sys\nopen("/nonexistent-skeleton-file-xyz")\n'
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp, skeleton=False)
        rel = add_test(root, "q-system/.q-system/scripts/test_skel.py", crash)
        m = base_manifest(expected_tests=[entry(rel)], skeleton_only=[rel])
        (root / "q-system/.q-system/capability-manifest.json").write_text(json.dumps(m))
        rc, out = run_gate(root)
        check("mode: instance skips skeleton_only (crashing test passes by skip)",
              rc == 0 and "skipped-skeleton-only=1" in out and "mode=instance" in out)
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
    # F3a: declared skeleton_only is SKIPPED in an instance (no crash).
    crash = 'open("/settings-template-only-in-skeleton.json")\n'
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp, skeleton=False)
        rel = add_test(root, "q-system/.q-system/scripts/test_skelwire.py", crash)
        m = base_manifest(expected_tests=[entry(rel)], skeleton_only=[rel])
        (root / "q-system/.q-system/capability-manifest.json").write_text(json.dumps(m))
        rc, out = run_gate(root)
        check("F3a: declared skeleton-only skipped in instance", rc == 0)
    # F3b: the SAME artifact undeclared in an instance fails loud (runs+crashes).
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp, skeleton=False)
        rel = add_test(root, "q-system/.q-system/scripts/test_skelwire.py", crash)
        m = base_manifest(expected_tests=[entry(rel)])
        (root / "q-system/.q-system/capability-manifest.json").write_text(json.dumps(m))
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
        (root / "q-system/.q-system/capability-manifest.json").write_text(json.dumps(m))
        rc, out = run_gate(root, "--check-only")
        check("vanished: declared-but-missing RED", rc == 1 and "declared-but-missing" in out)
    # Required data: in-scope missing file MUST fail; out-of-scope must not.
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        m = base_manifest(required_data=[{"path": "q-system/canonical/x.json", "scope": "all"}])
        (root / "q-system/.q-system/capability-manifest.json").write_text(json.dumps(m))
        rc, out = run_gate(root, "--check-only")
        check("required_data: in-scope missing RED", rc == 1 and "required-data-missing" in out)
        m["required_data"][0]["scope"] = ["some-other-instance"]
        (root / "q-system/.q-system/capability-manifest.json").write_text(json.dumps(m))
        rc, out = run_gate(root, "--check-only")
        check("required_data: out-of-scope not demanded", rc == 0)


SECTIONS = {
    "schema": sec_schema, "overlay": sec_overlay, "quarantine": sec_quarantine,
    "wiring": sec_wiring, "runner": sec_runner, "mode": sec_mode,
    "negative-proof": sec_negative_proof,
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
