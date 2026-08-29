#!/usr/bin/env python3
"""Mutation sweep: find declared tests that RUN, PASS, and cannot fail.

The class this exists for (17 instances measured in one session, 2026-08-29):
a check that executes, returns green, and is structurally blind to the thing it
was built to catch. Two of those 17 were MUTATION HARNESSES that lied -- one
reported perfect survival because a module-level ImportError killed every case,
one because it ran no tests at all. So this harness proves its own work rather
than asserting it (see SELF-GUARDS below).

The population is q-system/.q-system/capability-manifest.json's expected_tests:
the fleet's own declaration of which tests are supposed to exist and run.

## The two-stage probe

Stage 1 -- ABSENT (attribution proof, and the positive control).
  Move a candidate subject file out of the tree, run the test, move it back.
  A test that still passes with its subject GONE does not depend on that file.
  This is what makes stage 2 trustworthy: it is a control that must go RED, and
  it is runner-agnostic (an import error and a `python3 missing.py` both fail),
  so it works for the 95 bash tests as well as the 87 python ones.

Stage 2 -- DISARM (the finding).
  Only for pairs ABSENT confirmed. Neuter every failure-signalling site in the
  subject at once: nonzero `sys.exit` -> `sys.exit(0)`, `return False` ->
  `return True`, bash `exit 1` -> `exit 0`. The subject can no longer report
  failure. If the test STILL passes, the test cannot observe this subject's
  verdict. That is the founder's class stated as an executable experiment.

A single "total disarm" mutant per (test, subject) rather than N per-site
mutants is deliberate: 182 tests x N x runtime is a sweep nobody runs twice.
Localisation is a follow-up pass on the survivors, which are few.

## SELF-GUARDS (a survival report from a harness that ran nothing is the worst
## possible output here, so each of these is checked, not assumed)

1. APPLIED, by bytes.  sha256(before) != sha256(after) and the mutated file is
   re-read from disk. "sed exited 0" is not proof a mutant applied.
2. SYNTACTICALLY VALID.  `ast.parse` / `bash -n` on the mutant. A syntax error
   is killed by any test that merely imports the file -- a trivial kill that
   would inflate the score for free.
3. EXECUTED.  Every recorded verdict carries the child's real exit code and
   wall duration. A run that timed out has returncode None and is classified
   `mutant-timeout`, never KILLED and never SURVIVED.
4. BASELINE GREEN.  A test that is already red is EXCLUDED. You cannot measure
   whether a mutation turns a test red when it is red to begin with.
5. CONTROL RESTORED.  After every mutant the file is restored from a byte copy
   and the test is re-run; it must be green again. A red control means the
   harness corrupted the tree, and that test's results are discarded rather
   than reported.
6. FRESH BYTECODE.  Each run gets its own PYTHONPYCACHEPREFIX. `exit 1` ->
   `exit 0` is the same file SIZE and the restore lands in the same second, so
   CPython happily serves the MUTANT'S .pyc for the restored source. This has
   burned this harness's ancestor; the empty cache dir is the fix.
7. NEVER `git checkout`.  Restore is a cp from a backup taken in this process.
   A `git checkout --` restore once destroyed a whole uncommitted fix.
8. SERIAL BY CONSTRUCTION.  No --jobs. Mutation is a write to the shared tree;
   two workers mutating one checkout is a corruption waiting for a race. Cost
   is bounded by mutant COUNT (--limit / --only / the resume cache), not by
   parallelism.

## Runner fidelity

The test invocation is not reimplemented here. `run_contained` is imported from
a COPY of capability-gate.py, so the sweep runs each test exactly the way the
gate does -- same argv, same cwd, same QROOT, same process-group containment.
The copy matters: capability-gate.py is itself a subject in the population, and
a harness that imported the live file would be running mutated code as its own
runner.

Posture: ON-DEMAND and ADVISORY. Never a blocking hook. It rewrites files in the
working tree while it runs, so it refuses a dirty tree unless forced.
"""

import argparse
import ast
import datetime
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SCHEMA_VERSION = 1
DEFAULT_TIMEOUT_S = 60
# The mutant runs the same test as the baseline. A mutant that pushes it far
# past its own measured baseline is a hang, not a verdict, so the budget is
# derived per test rather than fixed.
MUTANT_TIMEOUT_FLOOR_S = 20
MUTANT_TIMEOUT_FACTOR = 3.0


# ---------------------------------------------------------------- runner load

def load_runner(root):
    """Import run_contained from a COPY of capability-gate.py.

    Not a reimplementation: a harness whose runner drifts from the real one
    measures a test nobody runs (the extracted-function fidelity gap). Not the
    live file either: capability-gate.py is in the population, so a sweep that
    imported it directly would end up executing its own mutant as the runner.
    """
    src = root / "q-system/.q-system/scripts/capability-gate.py"
    if not src.is_file():
        raise SystemExit(f"mutation-sweep: capability-gate.py not found at {src}")
    tmpdir = tempfile.mkdtemp(prefix="msweep-runner-")
    copy = Path(tmpdir) / "capability_gate_copy.py"
    shutil.copy2(src, copy)
    spec = importlib.util.spec_from_file_location("capability_gate_copy", copy)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not hasattr(mod, "run_contained"):
        raise SystemExit("mutation-sweep: capability-gate.py has no run_contained; "
                         "the runner contract moved and this harness is stale.")
    return mod


# ------------------------------------------------------------ test population

def load_population(root, manifest_path=None):
    path = manifest_path or (root / "q-system/.q-system/capability-manifest.json")
    data = json.loads(Path(path).read_text())
    out = []
    for entry in data.get("expected_tests", []):
        p = entry.get("path", "")
        if entry.get("quarantine"):
            continue
        if not (root / p).is_file():
            continue
        out.append({
            "path": p,
            "runner": entry.get("runner", "python3"),
            "timeout_s": entry.get("timeout_s", DEFAULT_TIMEOUT_S),
        })
    return out


# ------------------------------------------------------- subject attribution

# A test artifact is never a subject: mutating one test to see whether another
# notices measures nothing about the code under test.
_TEST_NAME = re.compile(r"^(test[_-]|conftest\.py$)")
_PATHLIKE = re.compile(r"[A-Za-z0-9_./-]+\.(?:py|sh)")


def _is_test_file(p: Path):
    return bool(_TEST_NAME.match(p.name))


def candidate_subjects(root, test_rel, max_subjects):
    """Candidate source files this test might exercise, best guess first.

    Purely a CANDIDATE list. Attribution is not settled here -- the ABSENT
    control settles it by execution, which is the whole point: a static guess
    that named the wrong file would otherwise manufacture false survivors.
    """
    test_path = root / test_rel
    try:
        text = test_path.read_text(errors="ignore")
    except OSError:
        return []
    scored = {}

    def add(p: Path, score):
        try:
            rel = p.resolve().relative_to(root.resolve())
        except (ValueError, OSError):
            return
        if not p.is_file() or _is_test_file(p):
            return
        key = str(rel)
        scored[key] = max(scored.get(key, 0), score)

    # 1. Naming convention: test-foo.sh / test_foo.py -> foo.{py,sh}
    stem = test_path.name
    for pre in ("test_", "test-"):
        if stem.startswith(pre):
            stem = stem[len(pre):]
            break
    base = re.sub(r"\.(py|sh)$", "", stem)
    # test-foo-rule-wired.sh and test-foo-lint.py both point at foo's family;
    # peel trailing qualifiers so the convention still lands on the engine.
    bases = {base}
    parts = base.split("-")
    for i in range(len(parts) - 1, 0, -1):
        bases.add("-".join(parts[:i]))
    search_dirs = [test_path.parent, test_path.parent.parent,
                   root / "q-system/.q-system/scripts", root / "q-system/.q-system"]
    for b in bases:
        if not b:
            continue
        exact = (b == base)
        for d in search_dirs:
            for ext in (".py", ".sh"):
                add(d / (b + ext), 100 if exact else 60)
                add(d / (b.replace("-", "_") + ext), 98 if exact else 58)

    # 2. Paths the test names in its own text. A test that runs
    #    `python3 q-system/.q-system/scripts/foo.py` says so literally.
    for m in _PATHLIKE.finditer(text):
        cand = m.group(0).lstrip("./")
        if "/" in cand:
            add(root / cand, 80)
        else:
            # A bare `foo.py` in the test text. Dropping these once made every
            # test that names its subject without a path read as having no
            # candidate subject at all -- unmeasured, and silently so.
            for d in search_dirs:
                add(d / cand, 70)

    # 3. Python imports resolvable next to the test or in the scripts root.
    for m in re.finditer(r"^\s*(?:from|import)\s+([A-Za-z_][A-Za-z0-9_]*)",
                         text, re.MULTILINE):
        name = m.group(1)
        for d in search_dirs:
            add(d / (name + ".py"), 90)

    ranked = sorted(scored.items(), key=lambda kv: (-kv[1], kv[0]))
    return ranked[:max_subjects]


# ------------------------------------------------------------------- mutation

# Every rule turns a FAILURE signal into a SUCCESS signal and nothing else. The
# mutant does not change what the code computes; it changes only whether the
# code is able to report that something is wrong. That keeps a survivor's
# meaning unambiguous: the test cannot see this subject's verdict.
# Trailing whitespace is [ \t]*, never \s*. `\s` matches the newline, so a
# `\s*$` rule silently ATE the line ending and welded two statements into one
# -- a mutant that is a syntax error, killed by anything that loads the file,
# scoring a free kill for every test in the population. The syntax guard caught
# it on the first self-test run; the anchors are narrow now so it cannot recur.
_EOL = r"([ \t]*\r?\n?)$"
PY_RULES = [
    (re.compile(r"(\bsys\.exit\s*\(\s*)(?!0\s*\))[^)]*(\))"), r"\g<1>0\g<2>"),
    (re.compile(r"(\braise\s+SystemExit\s*\(\s*)(?!0\s*\))[^)]*(\))"), r"\g<1>0\g<2>"),
    (re.compile(r"^([ \t]*)return[ \t]+False" + _EOL), r"\g<1>return True\g<2>"),
    (re.compile(r"^([ \t]*)return[ \t]+[1-9][0-9]*" + _EOL), r"\g<1>return 0\g<2>"),
]
SH_RULES = [
    (re.compile(r"^([ \t]*)exit[ \t]+[1-9][0-9]*" + _EOL), r"\g<1>exit 0\g<2>"),
    (re.compile(r"^([ \t]*)return[ \t]+[1-9][0-9]*" + _EOL), r"\g<1>return 0\g<2>"),
]


def make_disarm(text, suffix):
    """Return (mutated_text, n_sites). n_sites==0 means this file has no
    failure-signalling site to neuter -- reported as such, never as a pass."""
    rules = PY_RULES if suffix == ".py" else SH_RULES
    out, n = [], 0
    for line in text.splitlines(keepends=True):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            out.append(line)
            continue
        new = line
        for pat, repl in rules:
            new2 = pat.sub(repl, new)
            if new2 != new:
                n += 1
                new = new2
        out.append(new)
    return "".join(out), n


def syntax_ok(root, path: Path, text, suffix):
    """A syntactically broken mutant is killed by anything that loads the file.
    Counting that as a kill would inflate every score for free."""
    if suffix == ".py":
        try:
            ast.parse(text)
            return True
        except SyntaxError:
            return False
    with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as fh:
        fh.write(text)
        tmp = fh.name
    try:
        r = subprocess.run(["bash", "-n", tmp], capture_output=True, timeout=30)
        return r.returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False
    finally:
        os.unlink(tmp)


# --------------------------------------------------------------- test running

class Sweep:
    def __init__(self, root, runner, verbose=False):
        self.root = root
        self.runner = runner
        self.verbose = verbose

    def run_test(self, entry, timeout=None):
        """Exactly the gate's invocation, plus a private bytecode cache.

        PYTHONPYCACHEPREFIX is the one deliberate deviation. `exit 1` ->
        `exit 0` leaves the file the same SIZE, and the restore lands inside
        the same mtime second, so CPython's (size, mtime) validity check passes
        and it serves the MUTANT'S cached bytecode for restored source. A fresh
        empty cache dir per run makes every run compile what is actually on
        disk. Semantics are otherwise untouched.
        """
        full = self.root / entry["path"]
        cmd = (["python3", str(full)] if entry["runner"] == "python3"
               else ["bash", str(full)])
        cache = tempfile.mkdtemp(prefix="msweep-pyc-")
        env = dict(os.environ,
                   QROOT=str(self.root / "q-system"),
                   PYTHONPYCACHEPREFIX=cache)
        t0 = time.time()
        try:
            r = self.runner.run_contained(cmd, self.root, env,
                                          timeout or entry["timeout_s"])
        finally:
            shutil.rmtree(cache, ignore_errors=True)
        return {
            "rc": None if r.timed_out else r.returncode,
            "timed_out": bool(r.timed_out),
            "duration_s": round(time.time() - t0, 2),
            "out_bytes": len(r.stdout) + len(r.stderr),
            "tail": "\n".join((r.stdout + r.stderr).splitlines()[-8:]),
        }

    # -- self-guard 1 & 5: byte-exact swap and byte-exact restore -------------

    def _backup(self, target: Path):
        fd, bpath = tempfile.mkstemp(prefix="msweep-bak-")
        os.close(fd)
        shutil.copy2(target, bpath)
        return bpath

    def _restore(self, target: Path, bpath, orig_sha):
        """cp from our own backup. NEVER `git checkout --`: that restore form
        once wiped a whole uncommitted fix out of a working tree."""
        shutil.copy2(bpath, target)
        os.unlink(bpath)
        if sha(target.read_bytes()) != orig_sha:
            raise SystemExit(f"mutation-sweep: FAILED TO RESTORE {target}. "
                             "Stopping rather than reporting results from a "
                             "corrupted tree.")


def sha(b):
    return hashlib.sha256(b).hexdigest()


# ------------------------------------------------------------------ the sweep

# A candidate at or above this score is named by the test ITSELF -- its own
# text contains the filename, or the test-<name> convention matches exactly.
# Below it, the candidate is this harness's guess. The distinction decides what
# a PASSING absent-control means: a bad guess, or a test that does not need its
# own subject to exist.
STRONG_ATTRIBUTION = 70


def probe_pair(sw, entry, subj_rel, baseline, score):
    """One (test, subject) pair: ABSENT control, then DISARM mutant.

    Returns a verdict dict. Every non-verdict outcome gets its own name --
    nothing falls through to 'survived', because 'survived' is the finding and
    a harness failure dressed as a finding is exactly what this class is about.
    """
    target = sw.root / subj_rel
    suffix = target.suffix
    if suffix not in (".py", ".sh"):
        return {"verdict": "skipped-not-source"}
    orig = target.read_bytes()
    orig_sha = sha(orig)
    budget = max(MUTANT_TIMEOUT_FLOOR_S,
                 int(baseline["duration_s"] * MUTANT_TIMEOUT_FACTOR) + 1)
    budget = min(budget, entry["timeout_s"] * 2)

    # ---- Stage 1: ABSENT. The positive control -- it MUST turn the test red,
    # or the test does not depend on this file and stage 2 would be measuring
    # a file nobody loads.
    bpath = sw._backup(target)
    try:
        target.unlink()
        absent = sw.run_test(entry, budget)
    finally:
        sw._restore(target, bpath, orig_sha)
    if absent["timed_out"]:
        return {"verdict": "absent-timeout", "absent": absent}
    if absent["rc"] == 0:
        if score >= STRONG_ATTRIBUTION:
            # The test names this file and still passes with the file DELETED.
            # Strictly worse than surviving a disarm: there is no version of
            # the subject this test could fail on. Found by the harness's own
            # self-test, where a probe asserting only "the gate printed
            # something" stayed green against a gate that was not there --
            # stderr from the missing-file error satisfied it.
            return {"verdict": "SURVIVED-ABSENT", "absent": absent,
                    "score": score, "orig_sha": orig_sha[:12],
                    "mutant_sha": "n/a-file-removed"}
        # Below the threshold this is just a wrong guess, not a finding.
        return {"verdict": "no-dependency", "absent": absent, "score": score}

    # ---- Stage 2: DISARM.
    text = orig.decode("utf-8", errors="replace")
    mutated, n_sites = make_disarm(text, suffix)
    if n_sites == 0:
        return {"verdict": "no-disarm-site", "absent": absent}
    if mutated == text:
        return {"verdict": "harness-error-mutant-noop", "absent": absent}
    if not syntax_ok(sw.root, target, mutated, suffix):
        return {"verdict": "harness-error-mutant-invalid", "absent": absent}

    bpath = sw._backup(target)
    try:
        target.write_text(mutated)
        # self-guard 1: re-read from DISK. "we wrote it" is not "it is there".
        after_sha = sha(target.read_bytes())
        if after_sha == orig_sha:
            return {"verdict": "harness-error-mutant-not-applied", "absent": absent}
        mut = sw.run_test(entry, budget)
    finally:
        sw._restore(target, bpath, orig_sha)

    # self-guard 5: the tree is back, so the test must be green again. A red
    # control means this run's verdict is not trustworthy.
    control = sw.run_test(entry, budget)
    if control["rc"] != 0:
        return {"verdict": "harness-error-control-red", "absent": absent,
                "mutant": mut, "control": control}

    if mut["timed_out"]:
        return {"verdict": "mutant-timeout", "absent": absent, "mutant": mut}
    res = {
        "verdict": "KILLED" if mut["rc"] != 0 else "SURVIVED",
        "sites": n_sites,
        "absent_rc": absent["rc"],
        "mutant_rc": mut["rc"],
        "orig_sha": orig_sha[:12],
        "mutant_sha": after_sha[:12],
        "mutant": mut,
    }
    return res


def sweep(root, args):
    runner = load_runner(root)
    sw = Sweep(root, runner, args.verbose)
    pop = load_population(root, args.manifest)
    if args.only:
        pat = re.compile(args.only)
        pop = [e for e in pop if pat.search(e["path"])]
    if args.limit:
        pop = pop[:args.limit]

    results = []
    resume = {}
    outdir = root / "q-system/output/mutation-sweep"
    outdir.mkdir(parents=True, exist_ok=True)
    store = outdir / "results.jsonl"
    if args.resume and store.is_file():
        for line in store.read_text().splitlines():
            try:
                rec = json.loads(line)
                resume[rec["test"]] = rec
            except (json.JSONDecodeError, KeyError):
                pass

    fh = store.open("a")
    try:
        for i, entry in enumerate(pop, 1):
            tp = entry["path"]
            if tp in resume:
                results.append(resume[tp])
                print(f"[{i}/{len(pop)}] cached {tp}", flush=True)
                continue
            base = sw.run_test(entry)
            rec = {"test": tp, "runner": entry["runner"], "baseline": base,
                   "pairs": [], "ts": datetime.datetime.now().isoformat(timespec="seconds")}
            if base["timed_out"] or base["rc"] != 0:
                # self-guard 4: you cannot measure whether a mutation turns a
                # red test red.
                rec["status"] = "EXCLUDED-baseline-red"
                print(f"[{i}/{len(pop)}] EXCLUDED (baseline rc={base['rc']}) {tp}",
                      flush=True)
            else:
                subs = candidate_subjects(root, tp, args.max_subjects)
                for s, score in subs:
                    v = probe_pair(sw, entry, s, base, score)
                    v["subject"] = s
                    rec["pairs"].append(v)
                    if v["verdict"] in ("KILLED", "SURVIVED", "SURVIVED-ABSENT"):
                        break  # first CONFIRMED subject settles this test
                rec["status"] = summarize(rec)
                print(f"[{i}/{len(pop)}] {rec['status']:<28} {tp}", flush=True)
            results.append(rec)
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
    finally:
        fh.close()

    report(results, outdir)
    return results


def summarize(rec):
    vs = [p["verdict"] for p in rec["pairs"]]
    if "SURVIVED-ABSENT" in vs:
        return "SURVIVED-ABSENT"
    if "SURVIVED" in vs:
        return "SURVIVED"
    if "KILLED" in vs:
        return "KILLED"
    for v in ("harness-error-control-red", "harness-error-mutant-not-applied",
              "harness-error-mutant-invalid", "harness-error-mutant-noop",
              "mutant-timeout", "absent-timeout"):
        if v in vs:
            return v
    if "no-disarm-site" in vs:
        return "UNMEASURED-no-disarm-site"
    if not vs:
        return "UNMEASURED-no-candidate-subject"
    return "UNMEASURED-no-dependency"


def report(results, outdir):
    import collections
    c = collections.Counter(r["status"] for r in results)
    print("\n=== MUTATION SWEEP ===")
    print(f"tests in population: {len(results)}")
    for k, v in sorted(c.items(), key=lambda kv: -kv[1]):
        print(f"  {v:>4}  {k}")
    def bucket(name):
        return [r for r in results if r["status"] == name]

    gone = bucket("SURVIVED-ABSENT")
    if gone:
        print(f"\nSURVIVED-ABSENT ({len(gone)}) -- test passes with its subject "
              "FILE DELETED:")
        for r in gone:
            p = next(x for x in r["pairs"] if x["verdict"] == "SURVIVED-ABSENT")
            print(f"  {r['test']}\n      subject: {p['subject']}")
    surv = bucket("SURVIVED")
    if surv:
        print(f"\nSURVIVED ({len(surv)}) -- test passes with its subject disarmed:")
        for r in surv:
            p = next(x for x in r["pairs"] if x["verdict"] == "SURVIVED")
            print(f"  {r['test']}\n      subject: {p['subject']}  "
                  f"(disarmed {p['sites']} site(s); absent-control rc={p['absent_rc']})")
    (outdir / "summary.json").write_text(json.dumps(
        {"schema_version": SCHEMA_VERSION, "counts": dict(c),
         "survived": [{"test": r["test"],
                       "subject": next(x["subject"] for x in r["pairs"]
                                       if x["verdict"] == "SURVIVED")}
                      for r in surv],
         "survived_absent": [{"test": r["test"],
                              "subject": next(x["subject"] for x in r["pairs"]
                                              if x["verdict"] == "SURVIVED-ABSENT")}
                             for r in gone]}, indent=2))
    print(f"\nledger: {outdir}/results.jsonl")


# ------------------------------------------------------------------ self-test

SELF_SUBJECT = '''#!/usr/bin/env python3
"""Fixture gate: RED when the input contains the word bad."""
import sys


def check(text):
    if "bad" in text:
        return False
    return True


def main():
    text = sys.argv[1] if len(sys.argv) > 1 else ""
    if not check(text):
        print("GATE: RED", file=sys.stderr)
        sys.exit(2)
    print("GATE: GREEN")
    sys.exit(0)


if __name__ == "__main__":
    main()
'''

# Asserts the gate's VERDICT. Disarming the gate must turn this red.
SELF_TEST_SIGHTED = '''#!/usr/bin/env python3
import subprocess, sys, pathlib
g = str(pathlib.Path(__file__).parent / "fixture_gate.py")
r = subprocess.run([sys.executable, g, "bad input"], capture_output=True, text=True)
assert r.returncode == 2, f"expected rc=2, got {r.returncode}"
r2 = subprocess.run([sys.executable, g, "fine"], capture_output=True, text=True)
assert r2.returncode == 0
print("ok")
'''

# Runs the gate and asserts only that it PRODUCED OUTPUT. It never reads the
# verdict, and stderr from a missing-file error satisfies it just as well as a
# real run -- so it passes with the subject DELETED. The worst shape in the
# class: no version of the subject could turn this test red.
SELF_TEST_BLIND = '''#!/usr/bin/env python3
import subprocess, sys, pathlib
g = str(pathlib.Path(__file__).parent / "fixture_gate.py")
r = subprocess.run([sys.executable, g, "bad input"], capture_output=True, text=True)
assert (r.stdout + r.stderr).strip() != "", "gate produced no output"
print("ok")
'''

# Imports the subject (so deleting it DOES turn this red -- the absent control
# confirms the dependency) but calls the check and ignores its answer. Disarming
# the gate must therefore survive. This is the pair the two-stage probe exists
# to separate from the one above.
SELF_TEST_SHALLOW = '''#!/usr/bin/env python3
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import fixture_gate
fixture_gate.check("bad input")
print("ok")
'''

# References nothing: the harness must find no candidate subject at all rather
# than inventing one.
SELF_TEST_UNRELATED = '''#!/usr/bin/env python3
assert 1 + 1 == 2
print("ok")
'''


def self_test():
    """Negative self-test: the harness must distinguish a blind test from a
    sighted one on a fixture whose answer is known by construction.

    A mutation harness that reports SURVIVED for everything and one that works
    look identical from a summary line. This is the check that can tell them
    apart, and it fails loudly if the harness stops discriminating.
    """
    import collections
    tmp = Path(tempfile.mkdtemp(prefix="msweep-selftest-"))
    scripts = tmp / "q-system/.q-system/scripts"
    scripts.mkdir(parents=True)
    # The harness loads its runner from capability-gate.py at the repo root it
    # is pointed at, so the fixture repo needs the real one.
    here = Path(__file__).resolve().parent
    shutil.copy2(here / "capability-gate.py", scripts / "capability-gate.py")
    (scripts / "fixture_gate.py").write_text(SELF_SUBJECT)
    (scripts / "test_fixture_gate.py").write_text(SELF_TEST_SIGHTED)
    (scripts / "test_fixture_blind.py").write_text(SELF_TEST_BLIND)
    (scripts / "test_fixture_shallow.py").write_text(SELF_TEST_SHALLOW)
    (scripts / "test_fixture_unrelated.py").write_text(SELF_TEST_UNRELATED)
    manifest = tmp / "manifest.json"
    manifest.write_text(json.dumps({"schema_version": 1, "expected_tests": [
        {"path": "q-system/.q-system/scripts/test_fixture_gate.py", "runner": "python3"},
        {"path": "q-system/.q-system/scripts/test_fixture_blind.py", "runner": "python3"},
        {"path": "q-system/.q-system/scripts/test_fixture_shallow.py", "runner": "python3"},
        {"path": "q-system/.q-system/scripts/test_fixture_unrelated.py", "runner": "python3"},
    ]}))

    args = argparse.Namespace(manifest=manifest, only=None, limit=None,
                              max_subjects=4, resume=False, verbose=False)
    results = sweep(tmp, args)
    got = {r["test"].split("/")[-1]: r["status"] for r in results}
    expect = {
        # sighted: reads the verdict, so disarming the gate must be caught
        "test_fixture_gate.py": "KILLED",
        # blind: passes even with the subject file deleted
        "test_fixture_blind.py": "SURVIVED-ABSENT",
        # shallow: depends on the subject, ignores its verdict
        "test_fixture_shallow.py": "SURVIVED",
        # unrelated: names no subject at all
        "test_fixture_unrelated.py": "UNMEASURED-no-candidate-subject",
    }
    fails = []
    for k, want in expect.items():
        if got.get(k) != want:
            fails.append(f"  {k}: expected {want}, got {got.get(k)!r}")

    # The harness must also prove it EXECUTED something. A sweep that ran no
    # tests reports clean survival and looks identical to a healthy one.
    ran = sum(1 for r in results if r.get("baseline", {}).get("rc") is not None)
    if ran != 4:
        fails.append(f"  executed baselines: expected 4, got {ran}")
    for r in results:
        for p in r.get("pairs", []):
            if p["verdict"] in ("KILLED", "SURVIVED"):
                if p["orig_sha"] == p["mutant_sha"]:
                    fails.append(f"  {r['test']}: mutant sha == original sha "
                                 "(mutant never applied)")
    shutil.rmtree(tmp, ignore_errors=True)
    if fails:
        print("mutation-sweep --self-test: FAIL", file=sys.stderr)
        print("\n".join(fails), file=sys.stderr)
        return 1
    print("mutation-sweep --self-test: ok (sighted=KILLED, "
          "blind=SURVIVED-ABSENT, shallow=SURVIVED, unrelated=no-candidate, "
          "4 baselines executed, mutants byte-verified)")
    return 0


# ----------------------------------------------------------------------- main

def dirty_tree(root):
    r = subprocess.run(["git", "-C", str(root), "status", "--porcelain"],
                       capture_output=True, text=True, timeout=60)
    return [l for l in r.stdout.splitlines() if l.strip()]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--self-test", action="store_true",
                    help="run the harness's own negative control and exit")
    ap.add_argument("--only", help="regex; restrict the population")
    ap.add_argument("--limit", type=int, help="first N tests only")
    ap.add_argument("--max-subjects", type=int, default=4)
    ap.add_argument("--resume", action="store_true",
                    help="reuse verdicts already in results.jsonl")
    ap.add_argument("--force-dirty", action="store_true")
    ap.add_argument("--manifest")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        sys.exit(self_test())

    root = Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                               capture_output=True, text=True, timeout=60
                               ).stdout.strip() or ".").resolve()
    # This harness REWRITES FILES IN THE WORKING TREE. On a dirty tree a crash
    # between mutate and restore is indistinguishable from the operator's own
    # edits, and the operator's edits are what gets lost.
    dirty = dirty_tree(root)
    if dirty and not args.force_dirty:
        print("mutation-sweep: refusing to run on a dirty tree "
              f"({len(dirty)} path(s)). Commit, stash, or pass --force-dirty.",
              file=sys.stderr)
        sys.exit(3)

    results = sweep(root, args)

    # Closing proof that the tree came back exactly as it started.
    after = dirty_tree(root)
    if len(after) != len(dirty):
        print(f"\nmutation-sweep: TREE NOT RESTORED "
              f"({len(dirty)} dirty before, {len(after)} after)", file=sys.stderr)
        sys.exit(3)
    print("tree restored: git status unchanged")
    sys.exit(0)


if __name__ == "__main__":
    main()
