#!/usr/bin/env python3
"""Mutation sweep: find declared tests that RUN, PASS, and cannot fail.

The class this exists for (17 instances measured in one session, 2026-08-29):
a check that executes, returns green, and is structurally blind to the thing it
was built to catch. Two of those 17 were MUTATION HARNESSES that lied -- one
reported perfect survival because a module-level ImportError killed every case,
one because it ran no tests at all. So this harness proves its own work rather
than asserting it (see SELF-GUARDS below).

The population is the fleet's own declaration of which tests are supposed to
exist and run: one fragment per declaration under q-system/.q-system/capability/,
assembled through capability_manifest.load().

## The two-stage probe

Stage 1 -- TRIPWIRE (attribution proof), then ABSENT (a secondary signal).
  The TRIPWIRE is what gates stage 2: a test that does not react to its subject
  at all has no dependency worth disarming, so the pair stops there.
  ABSENT is the separate question of whether the test passes with the subject
  file GONE. It no longer short-circuits: a passing ABSENT is carried forward
  and the DISARM runs anyway, because `python3` on a missing file exits 2 and
  2 is this repo's convention for "blocked" -- so a test asserting rc == 2
  passes with the subject deleted by exit-code collision while still seeing its
  verdict perfectly. Survive both and the verdict is SURVIVED-ABSENT; killed by
  the disarm and the verdict is KILLED, with the absent pass recorded beside it.
  The earlier text described ABSENT as the stage-1 gate, which stopped being
  true when the absent control was made contradictable.

Stage 2 -- DISARM (the finding).
  Only for pairs ABSENT confirmed. Neuter every failure-signalling site in the
  subject at once and see whether the test notices. The subject can no longer
  report failure; if the test STILL passes, it cannot observe this subject's
  verdict. That is the founder's class stated as an executable experiment.

  WHAT COUNTS AS A SITE, and what deliberately does not:
    yes  `sys.exit(<literal>)` / `raise SystemExit(<literal>)` -> 0
    yes  bash `exit <n>` / `return <n>` -> 0
    yes  a JSON verdict: permissionDecision "deny" -> "allow", which is how a
         PreToolUse hook denies (at exit ZERO, so no exit rule can see it)
    NO   `sys.exit(main())` or `sys.exit(rc)`. Replacing the ARGUMENT deletes
         the call: main() never runs, the mutant does nothing, and tests
         asserting normal output go red for unrelated reasons -- scored KILLED,
         which is the false-confident direction.
    NO   `return False -> return True`. It matched every predicate, not the ones
         carrying a verdict, so a kill could be earned by unrelated logic
         breaking. Removed; the cost is captured as sp-aa0cd5da.

  The rule behind both exclusions: mutating an expression whose VALUE is the
  verdict is not the same as mutating the verdict, and a harness that cannot
  tell them apart invents coverage.

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
import atexit
import ast
import datetime
import hashlib
import importlib.util
import inspect
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SCHEMA_VERSION = 1
DEFAULT_TIMEOUT_S = 60
# 97 is not 0, 1, 2, or 127: those are the codes loose assertions already
# tolerate (`rc in (0,1,2)` is a real shape in this repo, and 127 is
# command-not-found). A control has to fail in a way nobody accidentally allows.
TRIPWIRE_RC = 97
TRIPWIRE_PY = "import sys\nsys.exit(%d)\n" % TRIPWIRE_RC
TRIPWIRE_SH = "#!/usr/bin/env bash\nexit %d\n" % TRIPWIRE_RC
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

def load_manifest_module(root):
    """Import capability_manifest.py from a COPY, same reason as the runner:
    it is itself a mutable subject, and a sweep must never assemble its
    population with its own mutant."""
    src = root / "q-system/.q-system/scripts/capability_manifest.py"
    if not src.is_file():
        raise SystemExit(
            "mutation-sweep: capability_manifest.py not found at %s. The "
            "declared population moved to a fragment directory (#263); this "
            "checkout predates it or the loader was removed." % src)
    tmpdir = tempfile.mkdtemp(prefix="msweep-manifest-")
    copy = Path(tmpdir) / "capability_manifest_copy.py"
    shutil.copy2(src, copy)
    spec = importlib.util.spec_from_file_location("capability_manifest_copy", copy)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_population(root):
    """Assemble the declared population through capability_manifest.load().

    The population is no longer one JSON array: it is one file per declaration
    under q-system/.q-system/capability/, assembled in memory (#263, which
    killed the manifest conflict class). Reading the old monolith here would
    read a DELETED file.

    load() never raises -- it returns None and appends to `errors`, because its
    other callers treat an unreadable manifest as "no data". That contract is
    exactly wrong for this tool: a sweep that quietly saw zero declared tests
    would run nothing, find nothing, and report perfect survival. That is
    instance 17 of the taxonomy this sweep exists to detect, reproduced inside
    the detector. So every not-a-population outcome is fatal here, loudly.
    """
    cm = load_manifest_module(root)
    errors = []
    data = cm.load(root, errors)
    if data is None:
        raise SystemExit("mutation-sweep: could not assemble the manifest:\n  "
                         + "\n  ".join(errors or ["load() returned None"]))
    if errors:
        raise SystemExit("mutation-sweep: manifest problems, refusing to "
                         "measure against a partial population:\n  "
                         + "\n  ".join(errors))
    declared = data.get("expected_tests") or []
    if not declared:
        raise SystemExit(
            "mutation-sweep: the declared population is EMPTY. Refusing to "
            "report survival over zero tests -- a harness that runs nothing "
            "reports perfect survival and looks identical to a healthy one.")
    # THE INSTANCE-LOCAL OVERLAY IS PART OF THE POPULATION (codex major).
    #
    # capability-gate.py reads capability-manifest.local.json as an ADD-only
    # overlay, so on an INSTANCE the gate declares more tests than the skeleton
    # manifest lists. This assembled only the canonical half, so the sweep
    # reported survival over a smaller population than the gate declares --
    # silently, and on exactly the instances this tool's placement rationale
    # says it is for. A detector that sees fewer tests than the gate is the
    # blind-spot class it exists to find.
    #
    # Validation stays with the gate: it is the thing that REFUSES a bad
    # overlay, and a second copy of those rules here would be the drift this
    # file keeps warning about. The sweep only needs to know what would run.
    overlay = root / "capability-manifest.local.json"
    if overlay.is_file():
        try:
            extra = json.loads(overlay.read_text()).get("expected_tests", [])
        except (ValueError, OSError) as exc:
            raise SystemExit(
                "mutation-sweep: capability-manifest.local.json is unreadable "
                "(%s). The gate declares tests from it, so sweeping without it "
                "would report over a smaller population than the gate does. "
                "Refusing rather than reporting a partial result." % exc)
        known = {e.get("path") for e in declared}
        declared = list(declared) + [e for e in extra
                                     if e.get("path") not in known]

    out = []
    for entry in declared:
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
    if not out:
        raise SystemExit(
            "mutation-sweep: %d test(s) declared but NONE present on disk. "
            "Refusing to report survival over an empty population."
            % len(declared))
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
# Anchors are line-based but must tolerate the ways these statements really
# appear, or the sweep UNDER-disarms and every miss biases a verdict toward
# KILLED -- a detector reporting "fine" for the reason it exists to catch.
# Measured on repo-preflight.sh: 4 `exit 1` lines, 2 found, because a case arm
# writes `exit 1 ;;`. Trailing comments and `|| exit 1` were missed the same way.
#
# Trailing whitespace is [ \t]*, never \s*: `\s` matches the newline, so a
# `\s*$` rule silently ATE the line ending and welded two statements into one.
_LEAD = r"^([ \t]*(?:(?:\|\||&&|then|else|do)[ \t]+)?)"
_PY_TAIL = r"([ \t]*(?:\#.*)?\r?\n?)$"
_SH_TAIL = r"([ \t]*;{0,2}[ \t]*(?:\#.*)?\r?\n?)$"
# `return False -> return True` IS GONE (PR #272 major).
#
# It matched every predicate in the file, not the ones carrying a verdict. A test
# could then go red because some helper's internal logic broke, and the sweep
# booked that as "this test guards the subject's ability to report failure" --
# a KILL earned by an unrelated change.
#
# A false KILLED is the dangerous direction for this tool specifically. SURVIVED
# says "look at this test"; KILLED says "this one is fine, move on". Over-claiming
# coverage retires exactly the tests someone should have checked, and it does it
# quietly.
#
# So the rule is removed rather than narrowed. Narrowing means guessing which
# `return False` is a verdict from its name or position, and a guess here
# produces the same confident-wrong-answer it would be trying to prevent. The
# exit-code rules below still cover the real verdict paths, which is where
# process-level failure signalling actually lives.
#
# WHAT THIS COSTS, stated rather than hidden: a Python gate whose deny IS
# `return False` becomes unmeasurable by this harness and will report
# no-disarm-site instead of a verdict. That is a real loss of coverage and it is
# captured, not accepted silently -- the replacement is a verdict-POSITION-aware
# rule (the returns of a function whose value reaches sys.exit or a caller's
# failure branch), which needs call-graph awareness this regex layer does not
# have.
PY_RULES = [
    (re.compile(r"^([ \t]*)return[ \t]+[1-9][0-9]*" + _PY_TAIL), r"\g<1>return 0\g<2>"),
]
SH_RULES = [
    (re.compile(_LEAD + r"exit[ \t]+[1-9][0-9]*" + _SH_TAIL), r"\g<1>exit 0\g<2>"),
    (re.compile(_LEAD + r"return[ \t]+[1-9][0-9]*" + _SH_TAIL), r"\g<1>return 0\g<2>"),
]

# THE VERDICT IS NOT ALWAYS AN EXIT CODE (ASK-1147).
#
# A PreToolUse hook denies by printing `permissionDecision: "deny"` and exiting
# ZERO. Every rule above rewrites a failure EXIT, so on those files make_disarm
# found no site, returned `no-disarm-site`, and the subject was booked
# UNMEASURED. That bucket is not a discard pile -- it is where the deny-side
# security gates live, which is to say the subjects whose tests most need to be
# proven capable of going red.
#
# Measured before this rule: destructive-op-deny.sh and merge-bypass-gate.py
# both deny at exit 0, and both were unmeasurable for that reason alone.
#
# The disarm is the semantic one: flip the verdict the process actually emits.
# Applied to BOTH suffixes, because the same JSON is built by a python dict
# (`"permissionDecision": "deny"`) and by a shell jq template
# (`permissionDecision: "deny"`), and a rule that only knew one spelling would
# leave half the population unmeasured while reporting the other half fine.
VERDICT_RULES = [
    (re.compile(r'(permissionDecision"?[ \t]*:[ \t]*")deny(")'), r"\g<1>allow\g<2>"),
]


# Call heads whose argument is the process's verdict. Rewritten by balanced
# paren scan, NOT by regex: `[^)]*(\))` stopped at the FIRST `)`, so the very
# common `sys.exit(main())` became `sys.exit(0))` -- a syntax error, which any
# test that imports the module kills for free. The ast guard caught it on a real
# file; a harness without that guard would have booked 48 sites as a clean kill.
_EXIT_HEADS = (re.compile(r"\bsys\.exit\s*\("),
               re.compile(r"\braise\s+SystemExit\s*\("))


def _disarm_exit_calls(line):
    """Replace each `sys.exit(<anything>)` / `raise SystemExit(<anything>)` on
    this line with a zero-argument form. Returns (line, n_replacements)."""
    n = 0
    for head in _EXIT_HEADS:
        pos = 0
        while True:
            m = head.search(line, pos)
            if not m:
                break
            depth, i = 1, m.end()
            while i < len(line) and depth:
                if line[i] == "(":
                    depth += 1
                elif line[i] == ")":
                    depth -= 1
                i += 1
            if depth:
                # The call spans more than this physical line. Leave it alone
                # rather than emit something unbalanced.
                pos = m.end()
                continue
            arg = line[m.end():i - 1].strip()
            if arg == "0":
                pos = i
                continue
            # ONLY A LITERAL EXIT CODE IS A VERDICT (PR #272 major).
            #
            # `sys.exit(main())` rewritten to `sys.exit(0)` does not disarm a
            # verdict -- it DELETES THE CALL. main() never runs, the mutant does
            # nothing at all, and every test asserting normal output goes red for
            # a reason that has nothing to do with failure signalling. Those
            # tests were then scored KILLED, which is the false-confident
            # direction: KILLED means "this one is fine, move on".
            #
            # Same shape as the `return False` rule removed earlier in this PR.
            # Mutating an expression whose VALUE is the verdict is not the same
            # as mutating the verdict, and a harness that cannot tell them apart
            # invents coverage.
            if not arg.isdigit():
                pos = i
                continue
            line = line[:m.end()] + "0" + line[i - 1:]
            n += 1
            pos = m.end() + 1
    return line, n


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
        if suffix == ".py":
            new, k = _disarm_exit_calls(new)
            n += k
        for pat, repl in list(rules) + VERDICT_RULES:
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
        # THE RUNNER TABLE HAS TO MATCH THE GATE'S (PR #272 major).
        #
        # ASK-1145 added `pytest` as a third runner in capability-gate.py and
        # flipped 13 declarations to it, because those modules define test
        # functions and `python3 <file>` executes none of them. This dispatch
        # still knew only two values, so every pytest-declared entry fell to the
        # `else` and was run through BASH -- which fails immediately, so the
        # sweep booked all 13 as EXCLUDED-baseline-red and measured nothing.
        #
        # Two components each correct on their own and wrong together: the gate
        # learned a runner the sweep never heard about. An unknown runner is now
        # a hard failure rather than a silent fall-through to bash, so the next
        # one cannot be absorbed the same way.
        runner = entry["runner"]
        if runner == "pytest":
            cmd = ["python3", "-m", "pytest", str(full), "-q",
                   "-p", "no:cacheprovider"]
        elif runner == "python3":
            cmd = ["python3", str(full)]
        elif runner == "bash":
            cmd = ["bash", str(full)]
        else:
            raise SystemExit(
                "mutation-sweep: unknown runner %r for %s. Add it here and in "
                "capability-gate.py together, or the sweep silently measures "
                "nothing for every test that declares it." % (runner, entry["path"]))
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
        # (backup, original sha, what we last wrote). The third is filled in by
        # _note_wrote once a mutant is on disk, so the emergency path can tell
        # OUR content from a stranger's without re-deriving anything.
        _PENDING[target] = [bpath, sha(target.read_bytes()), None]
        return bpath

    def _restore(self, target: Path, bpath, orig_sha, mutant_sha=None):
        """cp from our own backup. NEVER `git checkout --`: that restore form
        once wiped a whole uncommitted fix out of a working tree.

        REFUSES TO OVERWRITE SOMEBODY ELSE'S EDIT (PR #272 blocker). This copied
        the backup over the target unconditionally. If a human saved that file
        while the sweep held it mutated, their work was replaced by the
        pre-mutation content -- and the sha check below then PASSED, because the
        result matched orig_sha exactly as intended. Silent data loss reported as
        a successful restoration, by a tool whose subject is checks that pass for
        the wrong reason.

        The sweep lock (added this PR) keeps a second SWEEP out. It cannot keep a
        person out, and a person is who loses work here.

        So the content on disk is read FIRST. It should be our mutant. If it is
        already the original, another path restored it and there is nothing to
        do. Anything else is a third party's edit: the backup is preserved beside
        the file, their content is left alone, and the run stops.
        """
        try:
            current = sha(target.read_bytes())
        except OSError:
            current = None
        if mutant_sha is None:
            entry = _PENDING.get(target)
            if entry is not None and entry[2] is not None:
                mutant_sha = entry[2]

        # An UNKNOWN mutant_sha (None) must refuse, not permit. It means "we do
        # not know what we wrote", and treating that as permission to overwrite
        # is the same fail-open my own first cut had -- caught by this file's
        # own test rather than by review.
        #
        # The absent control passes None legitimately, and it is covered without
        # a special case: that path DELETES the file, so `current` is None and
        # the guard is skipped. A file that exists with content we cannot
        # account for is exactly what should stop the run.
        if current is not None and current != orig_sha and current != mutant_sha:
            keep = str(bpath) + ".unrestored"
            try:
                shutil.copy2(bpath, keep)
            except OSError:
                keep = str(bpath)
            _PENDING.pop(target, None)
            raise SystemExit(
                f"mutation-sweep: {target} changed while the sweep held it "
                f"mutated -- it is neither our mutant nor the original, so "
                f"somebody else wrote it.\n"
                f"  NOT overwriting their content. The pre-mutation copy is at "
                f"{keep}.\n"
                f"  Reconcile by hand, then re-run.")

        shutil.copy2(bpath, target)
        _PENDING.pop(target, None)
        os.unlink(bpath)
        if sha(target.read_bytes()) != orig_sha:
            raise SystemExit(f"mutation-sweep: FAILED TO RESTORE {target}. "
                             "Stopping rather than reporting results from a "
                             "corrupted tree.")


def sha(b):
    return hashlib.sha256(b).hexdigest()


# A mutated file must never outlive this process. `finally` does NOT run on
# SIGTERM, and the first long run of this sweep was killed mid-flight -- the
# tree came back clean by luck, between two mutations, not by design.
_PENDING = {}


def _note_wrote(target, content_sha):
    """Record what we just put on disk, for the emergency path."""
    entry = _PENDING.get(target)
    if entry is not None:
        entry[2] = content_sha


def _restore_all(*_a):
    """Emergency restore on SIGTERM / atexit.

    CARRIES THE SAME CONCURRENT-EDIT RULE as _restore (PR #272 blocker). This
    used to copy the backup over every pending target unconditionally, so the
    guard added to the normal path was bypassed by the one path that runs when
    things are going WRONG -- and a kill mid-run permanently overwrote whatever
    a person had saved. The emergency path is where destroying work is least
    forgivable, not most.

    Restores when the file is OUR mutant (the whole point: a mutant must never
    outlive this process) or is missing. Leaves anything else alone and says so
    on stderr, because a signal handler cannot ask and must not guess.
    """
    for target, entry in list(_PENDING.items()):
        bpath, orig_sha, wrote_sha = entry
        try:
            current = sha(Path(target).read_bytes())
        except OSError:
            current = None          # gone: restoring it is correct
        if current is not None and current != orig_sha and current != wrote_sha:
            try:
                sys.stderr.write(
                    "mutation-sweep: NOT restoring %s -- it holds content that "
                    "is neither our mutant nor the original, so somebody else "
                    "wrote it. The pre-mutation copy is at %s\n" % (target, bpath))
            except Exception:
                pass
            continue
        try:
            shutil.copy2(bpath, target)
        except OSError:
            pass
    _PENDING.clear()


def _install_restore_handlers():
    import atexit
    import signal as _sig
    atexit.register(_restore_all)
    for s in (_sig.SIGTERM, _sig.SIGINT, _sig.SIGHUP):
        prev = _sig.getsignal(s)

        def handler(signum, frame, _prev=prev):
            _restore_all()
            sys.exit(128 + signum)
        try:
            _sig.signal(s, handler)
        except (ValueError, OSError):
            pass


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

    # ---- Stage 1: TRIPWIRE. The dependency control.
    #
    # The file STAYS, but its whole body becomes an immediate abort with a
    # distinctive code. Any test that imports it, runs it, or shells it now
    # fails loudly. A test that stays green does not exercise this file, so
    # stage 2 would be measuring code nobody loads.
    #
    # This replaced a DELETE-the-file control, which was wrong in a way worth
    # recording: deleting a subject makes `python3 subject.py` exit 2 and print
    # to stderr, and a loose test ("rc in (0,1,2)", "some output appeared")
    # passes on that. Deletion and a bad attribution guess were therefore
    # indistinguishable -- measured on this repo, a test that merely QUOTED
    # `converge.sh` inside PRD fixture text was scored a finding. Tripwire
    # keeps the file present, so only real non-use looks like non-use.
    tripwire = TRIPWIRE_PY if suffix == ".py" else TRIPWIRE_SH
    bpath = sw._backup(target)
    try:
        target.write_text(tripwire)
        _note_wrote(target, sha(tripwire.encode("utf-8")))
        trip = sw.run_test(entry, budget)
    finally:
        sw._restore(target, bpath, orig_sha,
                    sha(tripwire.encode("utf-8")))
    if trip["timed_out"]:
        return {"verdict": "tripwire-timeout", "tripwire": trip, "score": score}
    if trip["rc"] == 0:
        # The test is green while the subject cannot run at all: it does not
        # exercise this file. A guess, not a finding.
        return {"verdict": "no-dependency", "tripwire": trip, "score": score}

    # ---- Stage 1b: ABSENT. Secondary, and only for CONFIRMED pairs. A test
    # that also passes with the file GONE is strictly worse than one that only
    # survives a disarm: no version of the subject could turn it red.
    bpath = sw._backup(target)
    try:
        target.unlink()
        absent = sw.run_test(entry, budget)
    finally:
        # The absent control DELETES the file, so there is no mutant content to
        # recognise. A file that reappeared with a stranger's bytes is exactly
        # what the guard should refuse, and passing None gets that.
        sw._restore(target, bpath, orig_sha, None)
    if not absent["timed_out"] and absent["rc"] == 0:
        # THE SCORE DECIDES WHAT A PASSING ABSENT-CONTROL MEANS (PR #272 minor).
        #
        # This read `if True:`, and STRONG_ATTRIBUTION was defined and never
        # referenced anywhere in the file. So the distinction the comment above
        # the constant describes -- "named by the test ITSELF" versus "this
        # harness's guess" -- did not exist in the code, and every weakly-paired
        # candidate was booked as a real finding about the test.
        #
        # That is the same shape the sweep hunts: a predicate whose false branch
        # is unreachable reports one answer by construction. Here it inflated
        # SURVIVED-ABSENT, which is the loudest verdict the tool emits, with
        # pairings the tool itself had only guessed at.
        if score >= STRONG_ATTRIBUTION:
            # THE DISARM GETS TO CONTRADICT THIS (codex minor, PR #272).
            #
            # This used to RETURN here, so the loudest verdict the tool emits
            # was decided by the absent control alone and nothing could argue
            # with it. The absent control deletes the file, and `python3` on a
            # missing file exits 2 -- which is this repo's own convention for
            # "blocked" (skill-hook-pairing.md). So a test asserting `rc == 2`
            # against a gate PASSES with the gate deleted, purely by exit-code
            # collision, and was reported as blind to a subject it actually
            # observes: disarming that gate's `sys.exit(2)` turns the same test
            # red.
            #
            # A test that survives BOTH is genuinely blind, and that is the
            # claim worth printing. So the absent result is carried forward and
            # the disarm stage runs: if the disarm KILLS, the test sees its
            # subject and the honest verdict is KILLED, with the absent pass
            # recorded beside it as the weaker signal it is.
            #
            # Codex found no producer in this repo today and dropped the
            # severity for it. The shape is reachable given the exit-2
            # convention, and a verdict that cannot be contradicted is the
            # tool's own failure mode, so it is fixed rather than noted.
            absent_pass = {"absent": absent, "score": score}
        else:
            # Below the bar the PAIRING is the suspect, not the test. A test
            # that passes without a file it was never really about is the
            # expected result, and reporting it as a blind test would train the
            # reader to ignore the verdict that matters.
            return {"verdict": "UNMEASURED-weak-attribution", "score": score,
                    "tripwire_rc": trip["rc"], "orig_sha": orig_sha[:12]}

    # ---- Stage 2: DISARM.
    absent_pass = locals().get("absent_pass")
    text = orig.decode("utf-8", errors="replace")
    mutated, n_sites = make_disarm(text, suffix)
    if n_sites == 0:
        return {"verdict": "no-disarm-site", "tripwire_rc": trip["rc"]}
    if mutated == text:
        return {"verdict": "harness-error-mutant-noop"}
    if not syntax_ok(sw.root, target, mutated, suffix):
        return {"verdict": "harness-error-mutant-invalid"}

    bpath = sw._backup(target)
    try:
        target.write_text(mutated)
        _note_wrote(target, sha(mutated.encode("utf-8")))
        # self-guard 1: re-read from DISK. "we wrote it" is not "it is there".
        after_sha = sha(target.read_bytes())
        if after_sha == orig_sha:
            return {"verdict": "harness-error-mutant-not-applied"}
        mut = sw.run_test(entry, budget)
    finally:
        # after_sha may be unbound if write_text raised before it was computed;
        # None then means "we do not know what we wrote", and the guard treats
        # an unknown as a refusal rather than as permission.
        sw._restore(target, bpath, orig_sha, locals().get("after_sha"))

    # self-guard 5: the tree is back, so the test must be green again. A red
    # control means this run's verdict is not trustworthy.
    control = sw.run_test(entry, budget)
    if control["rc"] != 0:
        return {"verdict": "harness-error-control-red",
                "mutant": mut, "control": control}

    if mut["timed_out"]:
        return {"verdict": "mutant-timeout", "mutant": mut}
    verdict = "KILLED" if mut["rc"] != 0 else "SURVIVED"
    if absent_pass is not None and verdict == "SURVIVED":
        # Survived the disarm AND passed with the file gone: no version of the
        # subject could turn this test red. That is the claim SURVIVED-ABSENT
        # was always meant to make.
        verdict = "SURVIVED-ABSENT"
    res = {
        "verdict": verdict,
        "sites": n_sites,
        "tripwire_rc": trip["rc"],
        "mutant_rc": mut["rc"],
        "orig_sha": orig_sha[:12],
        "mutant_sha": after_sha[:12],
        "mutant": mut,
    }
    if absent_pass is not None:
        # Recorded whichever way the disarm went. When the disarm KILLED, this
        # is the exit-code collision described above, and seeing both numbers is
        # how the next reader recognises it instead of rediscovering it.
        res["absent"] = absent_pass["absent"]
        res["absent_passed"] = True
    return res


def sweep(root, args):
    runner = load_runner(root)
    sw = Sweep(root, runner, args.verbose)
    pop = load_population(root)
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
            # THE CACHE KEY IS THE CONTENT, NOT THE PATH (PR #272 major).
            #
            # --resume matched on test path alone, so editing a test and
            # resuming replayed the OLD verdict under the NEW file's name. An
            # unattended report then described a version of the code that no
            # longer exists, with no marker saying so -- and a resumed run is
            # exactly the run nobody is watching.
            #
            # Both halves matter and both are hashed: a verdict is a claim about
            # a TEST and the SUBJECT it was measured against, so a changed
            # subject invalidates it just as a changed test does.
            #
            # A cached row from before this change carries no test_sha, and is
            # therefore treated as a MISS and re-run. Silently trusting it would
            # be the same defect wearing a compatibility argument.
            fingerprint = test_fingerprint(root, tp, resume.get(tp),
                                           entry.get("runner"),
                                           entry.get("timeout_s"))
            cached = resume.get(tp)
            if cached is not None and cached.get("test_sha") == fingerprint:
                results.append(cached)
                print(f"[{i}/{len(pop)}] cached {tp}", flush=True)
                continue
            if cached is not None:
                why = ("no fingerprint on the cached row"
                       if cached.get("test_sha") is None else "content changed")
                print(f"[{i}/{len(pop)}] re-running ({why}) {tp}", flush=True)
            base = sw.run_test(entry)
            rec = {"test": tp, "runner": entry["runner"], "baseline": base,
                   "test_sha": fingerprint,
                   "pairs": [], "ts": datetime.datetime.now().isoformat(timespec="seconds")}
            if base["timed_out"] or base["rc"] != 0:
                # self-guard 4: you cannot measure whether a mutation turns a
                # red test red.
                rec["status"] = "EXCLUDED-baseline-red"
                print(f"[{i}/{len(pop)}] EXCLUDED (baseline rc={base['rc']}) {tp}",
                      flush=True)
            else:
                # EVERY CANDIDATE SUBJECT, NOT THE FIRST CONFIRMED ONE
                # (codex major, PR #272).
                #
                # This used to `break` on the first confirmed subject, on the
                # reasoning that one confirmation settles the TEST. It does --
                # but the loudest line this tool prints is a per-SUBJECT claim,
                # "subjects no declared test guards the failure path of", and
                # that number is computed from these same pairs. A test that
                # guards two subjects was credited against one, so the other
                # read unguarded.
                #
                # The tool then contradicted itself on the same data: `--subject`
                # walks every declared test that names or imports the file and
                # reported it GUARDED, while the rollup reported it unguarded. A
                # checker whose loudest number is a known over-count teaches the
                # operator to stop reading it, and the cost lands on whoever
                # opens a test that already guards the file to write assertions
                # it does not need.
                #
                # Cost of the fix is bounded by --max-subjects (default 4), and
                # this is an on-demand tool, not a per-commit gate. Paying up to
                # 4 probes per test to stop printing a wrong headline is the
                # right trade.
                subs = candidate_subjects(root, tp, args.max_subjects)
                for s, score in subs:
                    v = probe_pair(sw, entry, s, base, score)
                    v["subject"] = s
                    rec["pairs"].append(v)
                rec["status"] = summarize(rec)
                print(f"[{i}/{len(pop)}] {rec['status']:<28} {tp}", flush=True)
            results.append(rec)
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
    finally:
        fh.close()

    # Name the filter so the report can say what its numbers cover.
    _filters = []
    if args.only:
        _filters.append("--only %s" % args.only)
    if args.limit:
        _filters.append("--limit %s" % args.limit)
    _partial = ", ".join(_filters) or None
    # WRITE THE SCOPE DOWN, because the next reader is a different entry point
    # (codex major, PR #272). --report-only re-derives from results.jsonl and
    # cannot otherwise know whether the run behind it was filtered, so it
    # reprinted the repo-wide claim over a bounded ledger. Teaching report() to
    # refuse that claim was not enough while only one caller knew the scope.
    (outdir / "scope.json").write_text(json.dumps(
        {"schema_version": SCHEMA_VERSION,
         "partial": _partial,
         "ts": datetime.datetime.now().isoformat(timespec="seconds")}, indent=2))
    report(results, outdir, partial=_partial)
    return results


def test_fingerprint(root, test_path, cached, runner=None, timeout_s=None):
    """Hash the test plus every subject a cached verdict was measured against.

    Returns None only when the test file itself cannot be read, and None never
    equals a stored fingerprint, so an unreadable test is a cache MISS rather
    than a silent hit.
    """
    paths = [test_path]
    for pair in (cached or {}).get("pairs", []) or []:
        subject = pair.get("subject")
        if subject and subject not in paths:
            paths.append(subject)
    h = hashlib.sha256()
    # THE ENGINE IS PART OF THE FINGERPRINT (PR #272 major). A verdict is a
    # claim about a test, a subject, AND the mutation semantics that produced
    # it. Adding VERDICT_RULES changed what "disarmed" means, so every cached
    # row from before it describes a different experiment -- and keying only on
    # test+subject would replay those verdicts unchanged under the new rules.
    # Hashing the rule tables means changing an operator invalidates the cache
    # by construction, with nobody having to remember to clear it.
    # THE DECLARED RUNNER IS PART OF THE EXPERIMENT (PR #272 major). Flipping a
    # test from python3 to pytest is exactly what ASK-1145 did to 13 files, and
    # it CHANGES WHICH ASSERTIONS EXECUTE -- python3 on a pytest module runs
    # none of them. Keying on file content alone reused the old verdict and never
    # ran the newly enabled ones, which is the zero-execution defect surviving
    # its own fix.
    # THE DECLARED EXECUTION LIMITS ARE PART OF THE EXPERIMENT TOO (PR #272).
    # runner was round one of this; timeout_s is the same shape. A verdict
    # produced under a 60s cap says nothing about the same test under 600s --
    # a mutant that "survived" may simply have been killed. Any manifest field
    # that changes HOW the test runs belongs here.
    h.update((runner or "").encode("utf-8"))
    h.update(b"\0")
    h.update(str(timeout_s if timeout_s is not None else "").encode("utf-8"))
    h.update(b"\0")
    # THE ENGINE IS MORE THAN ITS TABLES (PR #272 major). Hashing PY_RULES,
    # SH_RULES and VERDICT_RULES covered the DATA and left the CODE out, so
    # editing make_disarm, _disarm_exit_calls or code_only changed what
    # "disarmed" means while every cached verdict stayed valid. The tables are
    # the obvious half; the paren scanner and the comment stripper are just as
    # load-bearing and were invisible.
    #
    # THE WHOLE MODULE, because hand-listing the engine's functions is itself
    # the stale-hand-list defect (PR #272, three rounds).
    #
    # Round 1 hashed the rule TABLES. Round 2 added make_disarm,
    # _disarm_exit_calls and syntax_ok. Round 3 found candidate_subjects and
    # probe_pair still missing -- the functions deciding WHICH subject a test is
    # paired with and how the pair is probed, which are as much "the experiment"
    # as the mutation itself. Each round I enumerated, and each round the list
    # was short by exactly the parts I had not thought about.
    #
    # A list that needs a human to stay complete will be incomplete. Hashing the
    # module ENDS the class instead of shortening it once more.
    #
    # ACCEPTED COST, stated rather than discovered later: a comment or a change
    # to the report formatter now invalidates the cache and the sweep re-runs.
    # That is the SAFE direction. Under-invalidation costs a confident verdict
    # about semantics that no longer exist; over-invalidation costs CPU on a
    # tool that is already slow and whose resumed runs are the exception.
    try:
        h.update(Path(__file__).read_bytes())
    except OSError:
        # Unreadable module: a MISS, never a false hit. An engine that cannot be
        # hashed must not read as unchanged.
        return None
    h.update(b"\0")
    for rules in (PY_RULES, SH_RULES, VERDICT_RULES):
        for pat, repl in rules:
            h.update(pat.pattern.encode("utf-8"))
            h.update(b"\0")
            h.update(str(repl).encode("utf-8"))
            h.update(b"\0")
    try:
        for rel in paths:
            h.update(rel.encode("utf-8"))
            h.update(b"\0")
            h.update((root / rel).read_bytes())
            h.update(b"\0")
    except OSError:
        return None
    return h.hexdigest()[:16]


def latest_per_test(lines):
    """One row per test, the most recent. Ledger order is chronological.

    PR #272 major. results.jsonl is APPEND-ONLY and --report-only read every
    line, so a second sweep of the same population reported each test twice: the
    population count doubled, and a SURVIVED from an old run kept being reported
    long after the test was fixed, because its superseding KILLED row sat beside
    it rather than replacing it. A report that cannot age out a fixed finding
    trains the reader to ignore it.

    Malformed lines are SKIPPED and COUNTED, never silently dropped: a ledger
    this cannot parse is a broken writer, and a reader that hides that reports a
    smaller, cleaner population than actually exists -- which is the failure mode
    this whole tool is about.
    """
    latest, bad = {}, 0
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            bad += 1
            continue
        key = row.get("test")
        if key is None:
            bad += 1
            continue
        latest[key] = row          # later line wins
    if bad:
        print(f"WARNING: {bad} unreadable ledger row(s) skipped; the population "
              f"below is smaller than the file", file=sys.stderr)
    return list(latest.values())


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
              "mutant-timeout", "tripwire-timeout"):
        if v in vs:
            return v
    if "no-disarm-site" in vs:
        return "UNMEASURED-no-disarm-site"
    if "UNMEASURED-weak-attribution" in vs:
        return "UNMEASURED-weak-attribution"
    if not vs:
        return "UNMEASURED-no-candidate-subject"
    return "UNMEASURED-no-dependency"



CONFIRMED = ("KILLED", "SURVIVED", "SURVIVED-ABSENT")


def subject_rollup(results):
    """Per-SUBJECT view: does ANY declared test observe this file's ability to
    report failure?

    The per-test number alone overstates the defect count, and the reason is
    worth stating. test-capability-gate-reap.sh SURVIVES a disarm of
    capability-gate.py -- correctly: it imports run_contained and tests process
    reaping, so the gate's exit codes are outside its remit. That is a narrow
    unit test doing its job, not a blind gate.

    The question that actually decides whether something is broken is asked of
    the SUBJECT, not the test: this file can no longer report failure -- did
    anything notice? A subject whose every confirmed test survived has a
    failure path no declared test observes. That is the row to fix.
    """
    by_subject = {}
    for r in results:
        for pair in r.get("pairs", []):
            if pair["verdict"] not in CONFIRMED:
                continue
            s = by_subject.setdefault(pair["subject"], {"killed": [], "survived": []})
            key = "killed" if pair["verdict"] == "KILLED" else "survived"
            s[key].append(r["test"])
    unguarded = {s: v for s, v in by_subject.items() if not v["killed"]}
    return by_subject, unguarded


def report(results, outdir, partial=None):
    """`partial` describes the filter when the population was narrowed, e.g.
    "--limit 5". It is None for a full run, and the per-subject headline reads
    differently in each case because only one of them supports the claim."""
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
                  f"(disarmed {p['sites']} site(s); tripwire rc={p['tripwire_rc']})")
    by_subject, unguarded = subject_rollup(results)
    print(f"\n--- per-subject rollup ---")
    print(f"subjects with at least one confirmed test: {len(by_subject)}")
    if partial:
        # A BOUNDED RUN CANNOT MAKE AN UNBOUNDED CLAIM (codex major, PR #272).
        #
        # "no declared test guards this" is a statement about EVERY declared
        # test. Under --only or --limit most of them never ran, so a subject
        # guarded by a test outside the filter was reported as guarded by
        # nothing -- and `--report-only` over the full ledger then said the
        # opposite. Same defect as the first-confirmed-subject break, one layer
        # up: a claim computed from a population narrower than the claim.
        #
        # The number is still useful for the filtered set, so it is printed with
        # its scope attached rather than suppressed, and summary.json carries a
        # different key so a consumer cannot read a bounded result as a
        # repo-wide one by accident.
        print(f"subjects whose every test IN THIS FILTERED RUN survived: "
              f"{len(unguarded)}")
        print(f"  ({partial}) -- this is NOT the repo-wide claim; re-run "
              f"without the filter, or use --subject <file>")
    else:
        print(f"subjects NO declared test guards the failure path of: {len(unguarded)}")
    for s, v in sorted(unguarded.items()):
        print(f"  {s}\n      survived in: {', '.join(v['survived'])}")
        print(f"      confirm with: --subject {s}")
    summary = {"schema_version": SCHEMA_VERSION, "counts": dict(c),
               "survived": [r["test"] for r in surv],
               "survived_absent": [r["test"] for r in gone]}
    key = ("unguarded_subjects_in_filtered_population" if partial
           else "unguarded_subjects")
    summary[key] = {s: v["survived"] for s, v in unguarded.items()}
    if partial:
        summary["population"] = partial
    (outdir / "summary.json").write_text(json.dumps(summary, indent=2))
    print(f"\nledger: {outdir}/results.jsonl")



# ------------------------------------------------- zero-execution scan (static)

_MAIN_GUARD = re.compile(r"^\s*if\s+__name__\s*==\s*['\"]__main__['\"]\s*:", re.M)
_TESTDEF = re.compile(r"^\s*(?:def|async def)\s+test_\w+|^\s*class\s+Test\w+", re.M)
_PYTEST_IMPORT = re.compile(r"^\s*(?:import\s+pytest|from\s+pytest\s+import)", re.M)


def ci_pytest_targets(root):
    """Paths CI hands to pytest, so a declared test can be checked against the
    population that actually runs it.

    WHAT THIS SCAN FINDS TODAY (measured on kipi-system, not remembered):
    `zero_exec_scan` flags ZERO files. The docstring here used to say ten, one
    of them collected by `pytest plugins/prd-os/tests/` and nine executing
    nowhere. That was true when it was written and stopped being true when
    capability-gate.py grew a `pytest` runner and started refusing the shape at
    declaration time -- so the number survived the thing it described. Codex
    caught it; a stated measurement that no run reproduces is the same defect
    class this whole tool exists to find.

    COMMENT LINES ARE NOT CI STEPS. The scan used to read every line, so on this
    repo it returned four "targets", two of them fiction: `must`, out of the
    prose "pytest must exist BEFORE the gate", and
    `q-system/.q-system/tests`, out of a COMMENTED-OUT invocation in verify.yml.
    A commented-out step runs nothing, and counting it as coverage is a checker
    claiming a guard that is not there -- so a target now has to survive comment
    stripping and look like a path.
    """
    targets = []
    wf = root / ".github/workflows"
    if not wf.is_dir():
        return targets
    for f in sorted(wf.glob("*.yml")) + sorted(wf.glob("*.yaml")):
        for raw in f.read_text(errors="ignore").splitlines():
            line = raw.split("#", 1)[0]
            m = re.search(r"\bpytest\s+([^\s|;&]+)", line)
            if not m:
                continue
            tok = m.group(1).strip()
            if tok.startswith("-"):
                continue
            # A bare word is prose, not a path. Every real target names a
            # directory or a file, and both exist in the tree being scanned.
            if not (root / tok).exists():
                continue
            targets.append(tok)
    return targets


def zero_exec_scan(root):
    """Declared tests that the gate RUNS and that execute no assertions.

    The gate invokes every python3 entry as `python3 <file>`. A pytest-style
    module has no entry point, so that command imports it, defines the test
    functions, and exits 0. The gate books a pass. Nothing ran.

    This is invisible to mutation testing by construction -- a test that
    executes nothing cannot notice a mutant, so it reads as "no dependency",
    which is indistinguishable from a bad attribution guess. It needs its own
    check, and the check is static plus one confirming execution.
    """
    pop = load_population(root)
    ci = ci_pytest_targets(root)
    findings = []
    for entry in pop:
        if entry["runner"] != "python3":
            continue
        rel = entry["path"]
        text = (root / rel).read_text(errors="ignore")
        n_tests = len(_TESTDEF.findall(text))
        if not n_tests:
            continue
        if _MAIN_GUARD.search(text):
            continue  # has an entry point; it runs something
        covered = [c for c in ci if rel == c or rel.startswith(c.rstrip("/") + "/")]
        findings.append({
            "path": rel, "test_defs": n_tests,
            "uses_pytest": bool(_PYTEST_IMPORT.search(text)),
            "ci_pytest_covered_by": covered,
            "timeout_s": entry["timeout_s"],
        })
    return findings


def report_zero_exec(root, findings, sw):
    print("=== ZERO-EXECUTION SCAN ===")
    print("declared tests the gate runs as `python3 <file>` that define test "
          "functions but have no entry point.\n")
    if not findings:
        print("none.")
        return 0
    orphans = [f for f in findings if not f["ci_pytest_covered_by"]]
    for f in sorted(findings, key=lambda x: (bool(x["ci_pytest_covered_by"]), x["path"])):
        # Confirm by EXECUTION, not by reading: run it the way the gate does.
        r = sw.run_test({"path": f["path"], "runner": "python3",
                         "timeout_s": f["timeout_s"]})
        f["direct_rc"] = r["rc"]
        f["direct_out_bytes"] = r["out_bytes"]
        cov = (", ".join(f["ci_pytest_covered_by"])
               if f["ci_pytest_covered_by"] else "NOTHING")
        print(f"  {f['path']}\n      {f['test_defs']} test def(s); direct run "
              f"rc={r['rc']} out={r['out_bytes']}B; other runner: {cov}")
    print(f"\n{len(findings)} declared test file(s) execute nothing under the gate; "
          f"{len(orphans)} of those run NOWHERE else.")
    out = root / "q-system/output/mutation-sweep"
    out.mkdir(parents=True, exist_ok=True)
    (out / "zero-exec.json").write_text(json.dumps(findings, indent=2))
    return len(orphans)


def probe_subject(root, args, subj_rel):
    """Answer the question the per-test sweep cannot: does ANY declared test
    guard THIS file's ability to report failure?

    The main sweep settles each test on its first confirmed subject, so its
    per-subject rollup only covers the pairs it happened to probe. Measured on
    this repo: eight declared tests reference prd_runner.py and the sweep paired
    exactly one of them with it, which would have reported a hole that the other
    seven might well close. A claim about a SUBJECT has to be asked of every
    test that could answer it.

    Scope: tests that name the file or import its module. A test reaching the
    subject through a chain it never names is out of scope and stated as such,
    rather than silently counted as coverage.
    """
    runner = load_runner(root)
    sw = Sweep(root, runner)
    stem = pathlib.PurePath(subj_rel).name
    mod = stem[:-3] if stem.endswith(".py") else None
    candidates = []
    for entry in load_population(root):
        text = (root / entry["path"]).read_text(errors="ignore")
        if stem in text or (mod and re.search(
                r"\bimport\s+%s\b|\bfrom\s+%s\s+import\b" % (re.escape(mod), re.escape(mod)),
                text)):
            candidates.append(entry)
    print(f"subject: {subj_rel}")
    print(f"declared tests that name or import it: {len(candidates)}\n")
    killers, survivors, other = [], [], []
    for entry in candidates:
        base = sw.run_test(entry)
        if base["timed_out"] or base["rc"] != 0:
            other.append((entry["path"], "baseline-red"))
            print(f"  baseline-red      {entry['path']}")
            continue
        v = probe_pair(sw, entry, subj_rel, base, 100)
        verdict = v["verdict"]
        if verdict == "KILLED":
            killers.append(entry["path"])
        elif verdict.startswith("SURVIVED"):
            survivors.append(entry["path"])
        else:
            other.append((entry["path"], verdict))
        print(f"  {verdict:<28} {entry['path']}")
    print(f"\nGUARDED BY {len(killers)} test(s); {len(survivors)} exercise it "
          f"but cannot see its verdict.")
    if not killers:
        print("NO declared test observes this subject's failure path.")
    return 1 if not killers else 0


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
# Asserts ONLY the block exit code. This is the shape that made the absent
# control lie (codex minor, PR #272): `python3` on a DELETED file also exits 2,
# and 2 is this repo's own convention for "blocked", so the assertion passes
# against a gate that is not there. The test is NOT blind -- disarming the
# gate's `sys.exit(2)` to `sys.exit(0)` turns it red -- so the honest verdict is
# KILLED, and the absent pass is a coincidence of exit codes rather than
# evidence about the test.
SELF_TEST_EXIT2 = '''#!/usr/bin/env python3
import subprocess, sys, pathlib
g = str(pathlib.Path(__file__).parent / "fixture_gate.py")
r = subprocess.run([sys.executable, g, "bad input"], capture_output=True, text=True)
assert r.returncode == 2, f"expected rc=2, got {r.returncode}"
print("ok")
'''

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
    shutil.copy2(here / "capability_manifest.py", scripts / "capability_manifest.py")
    (scripts / "fixture_gate.py").write_text(SELF_SUBJECT)
    (scripts / "test_fixture_gate.py").write_text(SELF_TEST_SIGHTED)
    (scripts / "test_fixture_blind.py").write_text(SELF_TEST_BLIND)
    (scripts / "test_fixture_shallow.py").write_text(SELF_TEST_SHALLOW)
    (scripts / "test_fixture_unrelated.py").write_text(SELF_TEST_UNRELATED)
    (scripts / "test_fixture_exit2.py").write_text(SELF_TEST_EXIT2)
    # Fragments via the real explode(), so the fixture exercises the same
    # assembly path production uses. A fixture that hand-wrote one JSON file
    # would have kept passing through #263 while the sweep read a deleted file.
    cm = load_manifest_module(tmp)
    cm.explode(tmp, {"schema_version": 1, "expected_tests": [
        {"path": "q-system/.q-system/scripts/test_fixture_gate.py", "runner": "python3"},
        {"path": "q-system/.q-system/scripts/test_fixture_blind.py", "runner": "python3"},
        {"path": "q-system/.q-system/scripts/test_fixture_shallow.py", "runner": "python3"},
        {"path": "q-system/.q-system/scripts/test_fixture_unrelated.py", "runner": "python3"},
        {"path": "q-system/.q-system/scripts/test_fixture_exit2.py", "runner": "python3"},
    ]})

    args = argparse.Namespace(only=None, limit=None,
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
        # exit-2 collision: passes with the file GONE, but the disarm still
        # turns it red, so it is sighted. Before the absent control was made
        # contradictable this read SURVIVED-ABSENT, the loudest verdict the
        # tool emits, about a test that does its job.
        "test_fixture_exit2.py": "KILLED",
    }
    fails = []
    for k, want in expect.items():
        if got.get(k) != want:
            fails.append(f"  {k}: expected {want}, got {got.get(k)!r}")

    # The harness must also prove it EXECUTED something. A sweep that ran no
    # tests reports clean survival and looks identical to a healthy one.
    ran = sum(1 for r in results if r.get("baseline", {}).get("rc") is not None)
    if ran != 5:
        fails.append(f"  executed baselines: expected 5, got {ran}")
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
          "exit2-collision=KILLED, 5 baselines executed, "
          "mutants byte-verified)")
    return 0


# ----------------------------------------------------------------------- main

# ONE SWEEP PER REPO, ENFORCED ACROSS PROCESSES (PR #272 major).
#
# The sweep mutates TRACKED SOURCE in place and restores it from its own backup.
# Two overlapping sweeps therefore interleave on the same file: A backs up the
# original, B backs up A's MUTANT believing it is the original, and whichever
# restores last writes the wrong bytes into the working tree. The result is not a
# bad measurement, it is corrupted source -- and the restore's own sha check
# cannot see it, because each process verifies against the sha IT captured.
#
# The dirty-tree refusal does not cover this: the second sweep starts while the
# first has the tree momentarily clean between pairs, so it sees nothing wrong.
#
# `O_CREAT | O_EXCL` is the primitive, for the same reason the rest of this fleet
# uses mkdir: it is atomic on every filesystem that matters and needs no daemon.
# The lock records its pid so a human finding one can tell a live sweep from a
# corpse, and a stale lock whose pid is gone is reclaimed rather than requiring a
# manual delete -- an operator who has to clear a lock by hand eventually clears
# it while a sweep IS running.
def acquire_sweep_lock(root):
    """Return a release() callable, or exit 3 if another sweep holds the repo."""
    lock = root / "q-system/output/mutation-sweep/.sweep.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)

            def release():
                try:
                    if lock.read_text().strip() == str(os.getpid()):
                        lock.unlink()
                except OSError:
                    pass
            return release
        except FileExistsError:
            try:
                holder = int(lock.read_text().strip())
            except (OSError, ValueError):
                holder = None
            alive = False
            if holder is not None:
                try:
                    os.kill(holder, 0)
                    alive = True
                except OSError:
                    alive = False
            if alive:
                print("mutation-sweep: another sweep (pid %s) holds %s. Two sweeps "
                      "mutate the same tracked files and restore each other's "
                      "mutants into the working tree." % (holder, root),
                      file=sys.stderr)
                sys.exit(3)
            # Stale: the holder is gone. Reclaim and retry once.
            try:
                lock.unlink()
            except OSError:
                pass
    print("mutation-sweep: could not acquire the sweep lock", file=sys.stderr)
    sys.exit(3)


def dirty_tree(root):
    """TRACKED changes only (codex minor, PR #272).

    The closing proof compares this before and after the sweep. Reading
    untracked paths too made it report the tests' OWN artifacts -- scratch
    files, caches, ledgers they write while running -- as source corruption,
    and exit 3 over a tree that was restored perfectly.

    Dropping them costs nothing the proof was buying: every mutant this tool
    writes goes over a file that is already tracked, so a restoration failure
    always shows up as a tracked modification. A proof that cries wolf at its
    own test output is one people learn to ignore, which is this tool's subject.
    """
    r = subprocess.run(["git", "-C", str(root), "status", "--porcelain"],
                       capture_output=True, text=True, timeout=60)
    return [l for l in r.stdout.splitlines()
            if l.strip() and not l.startswith("??")]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--subject",
                    help="probe every declared test that names this file, to "
                         "answer whether ANYTHING guards its failure path")
    ap.add_argument("--report-only", action="store_true",
                    help="re-derive the report from results.jsonl, run nothing")
    ap.add_argument("--zero-exec-scan", action="store_true",
                    help="report declared tests that execute no assertions")
    ap.add_argument("--self-test", action="store_true",
                    help="run the harness's own negative control and exit")
    ap.add_argument("--only", help="regex; restrict the population")
    ap.add_argument("--limit", type=int, help="first N tests only")
    ap.add_argument("--max-subjects", type=int, default=4)
    ap.add_argument("--resume", action="store_true",
                    help="reuse verdicts already in results.jsonl")
    ap.add_argument("--force-dirty", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    _install_restore_handlers()
    if args.self_test:
        sys.exit(self_test())

    root = Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                               capture_output=True, text=True, timeout=60
                               ).stdout.strip() or ".").resolve()
    # Only the MUTATING path needs this. The refusal exists because a crash
    # between mutate and restore is indistinguishable from the operator's own
    # edits, and the operator's edits are what gets lost -- neither read-only
    # mode can do that, and refusing them just made the tool unusable mid-work.
    read_only = args.report_only or args.zero_exec_scan
    dirty = dirty_tree(root)
    # Held for the whole mutating run. Read-only modes mutate nothing and are
    # deliberately not serialised: refusing a report because a sweep is running
    # would make the tool unusable exactly when you want to look at it.
    if not read_only:
        _release_lock = acquire_sweep_lock(root)
        atexit.register(_release_lock)
    if dirty and not read_only and not args.force_dirty:
        print("mutation-sweep: refusing to run on a dirty tree "
              f"({len(dirty)} path(s)). Commit, stash, or pass --force-dirty.",
              file=sys.stderr)
        sys.exit(3)

    if args.subject:
        sys.exit(probe_subject(root, args, args.subject))

    if args.report_only:
        out = root / "q-system/output/mutation-sweep"
        ledger = out / "results.jsonl"
        if not ledger.is_file():
            # A traceback is a terrible error path for the commonest first-run
            # state (PR #272 minor). Say what is missing and how to make it.
            print("mutation-sweep: no ledger at %s -- nothing to report. Run a "
                  "sweep first (without --report-only)." % ledger, file=sys.stderr)
            sys.exit(2)
        rows = latest_per_test(ledger.read_text().splitlines())
        # THE SCOPE COMES FROM THE LEDGER, NOT FROM THIS INVOCATION.
        #
        # A ledger written by a --only/--limit run supports only a claim about
        # that filtered set. If scope.json is missing the ledger predates this
        # record or was written by hand, and the honest answer is that the scope
        # is unknown -- NOT that it was a full run. Defaulting to "full" is how
        # the bounded claim escaped in the first place.
        scope_file = out / "scope.json"
        if scope_file.is_file():
            try:
                partial = json.loads(scope_file.read_text()).get("partial")
            except ValueError:
                partial = "scope record unreadable"
        else:
            partial = ("scope of this ledger is unrecorded -- re-run the sweep "
                       "to establish it")
        report(rows, out, partial=partial)
        sys.exit(0)

    if args.zero_exec_scan:
        sw = Sweep(root, load_runner(root))
        sys.exit(1 if report_zero_exec(root, zero_exec_scan(root), sw) else 0)

    results = sweep(root, args)

    # Closing proof that the tree came back exactly as it started.
    #
    # COMPARE THE SET, NOT THE COUNT (PR #272 minor). This tested `len(after) !=
    # len(dirty)`, so a SWAP -- one path restored while a different one was left
    # mutated -- kept the count identical and printed "git status unchanged"
    # over a tree that had not been restored. A closing proof that can be
    # satisfied by coincidence is not a proof, which is this tool's own subject.
    after = dirty_tree(root)
    before_set, after_set = set(dirty), set(after)
    if before_set != after_set:
        appeared = sorted(after_set - before_set)
        vanished = sorted(before_set - after_set)
        print("\nmutation-sweep: TREE NOT RESTORED", file=sys.stderr)
        for path in appeared:
            print("  now dirty and was not: %s" % path, file=sys.stderr)
        for path in vanished:
            print("  was dirty and is not: %s" % path, file=sys.stderr)
        sys.exit(3)
    print("tree restored: git status unchanged")
    sys.exit(0)


if __name__ == "__main__":
    main()
