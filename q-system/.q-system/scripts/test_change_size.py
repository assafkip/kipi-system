"""change-size.py picks the tests a diff earns, and the gate obeys it (ASK-1749).

Two halves. The classifier is a pure function, so most cases hand it a diff as
data. The gate half runs the SHIPPED capability-gate.py functions against a
throwaway git repo under tmp_path: no network, no live data path, and the only
"tests" it executes are two one-line scripts that drop a marker file.

Every decision point has a mutant at the bottom. Each mutant is the shipped
source with one guard rewritten, and each must make a named case fail. A guard
whose removal nothing notices is decoration.
"""
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
CS_SRC = (HERE / "change-size.py").read_text()
GATE_SRC = (HERE / "capability-gate.py").read_text()


def load(src: str, name: str, tmp: Path):
    f = tmp / f"{name}.py"
    f.write_text(src)
    spec = importlib.util.spec_from_file_location(name, f)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def cs(tmp_path):
    return load(CS_SRC, "cs_under_test", tmp_path)


SCRIPT = "q-system/.q-system/scripts/widget.sh"
LIB = "q-system/.q-system/scripts/widget-lib.sh"
T_WIDGET = "q-system/.q-system/scripts/test/test-widget.sh"
T_OTHER = "q-system/.q-system/scripts/test/test-other.sh"
DECLARED = {T_WIDGET: 'bash "$HERE/../widget.sh" --selftest', T_OTHER: "echo unrelated"}
CODE = {SCRIPT: '. "$DIR/widget-lib.sh"\nrun', LIB: "helper() { :; }"}


# ------------------------------------------------------------ the classifier
def case_one_line(cs):
    v = cs.plan([(SCRIPT, 1)], DECLARED, CODE)
    assert (v["tier"], v["full_suite"], v["selected_tests"]) == ("S", False, [T_WIDGET])


def test_a_one_line_change_runs_the_one_test_that_names_it(cs):
    case_one_line(cs)


def case_escalator_beats_line_count(cs):
    # THE NEGATIVE SELF-TEST the issue asks for: one changed line, and still the
    # full suite, because the line is in the machinery that decides what runs.
    for path in ("q-system/.q-system/scripts/capability-gate.py",
                 "q-system/.q-system/scripts/change-size.py",
                 ".github/workflows/validate.yml", "lefthook.yml",
                 "plugins/kipi-core/voiceloop/requirements-authorship.txt",
                 "plugins/prd-os/tests/conftest.py", "pyproject.toml",
                 "pytest.ini", "tox.ini", "setup.cfg",
                 "q-system/.q-system/capability/declared_inert/x.json"):
        v = cs.plan([(path, 1)], DECLARED, CODE)
        assert v["full_suite"] and v["tier"] == "L", path


def test_an_escalator_is_never_reported_small(cs):
    case_escalator_beats_line_count(cs)


def test_a_newly_declared_test_runs_on_the_pr_that_declares_it(cs):
    frag = "q-system/.q-system/capability/expected_tests/q-system__x.json"
    v = cs.plan([(frag, 4)], DECLARED, CODE, fragments={frag: T_OTHER})
    assert not v["full_suite"] and v["selected_tests"] == [T_OTHER]


def diff(path, *added):
    return f"+++ b/{path}\n" + "\n".join("+" + a for a in added) + "\n"


def case_import_scoping(cs):
    local = {"widget", "pipeline"}
    assert cs.third_party_imports(diff("app/x.py", "import torch"), local) == ["torch"]
    assert cs.third_party_imports(diff("app/x.py", "from transformers.models import Foo"), local) == ["transformers"]
    # A test file importing pytest is not a new dependency of the product.
    assert cs.third_party_imports(diff("app/test_x.py", "import pytest"), local) == []
    assert cs.third_party_imports(diff("app/tests/helper.py", "import pytest"), local) == []
    # Prose is not an import statement. Both of these were called dependencies
    # by the first cut, on real commits of main.
    assert cs.third_party_imports(diff("app/x.py", "    from that point on the run is dead"), local) == []
    assert cs.third_party_imports(diff("app/x.py", "    import THIS file into the fixture"), local) == []
    assert cs.third_party_imports(diff("app/x.py", "import json, os", "from pipeline import run"), local) == []
    # Every module on the line is read, not just the first.
    assert cs.third_party_imports(diff("app/x.py", "import json, torch as t"), local) == ["torch"]


def test_only_a_real_import_in_app_code_is_a_new_dependency(cs):
    case_import_scoping(cs)


def test_a_new_third_party_import_forces_the_full_suite(cs):
    v = cs.plan([(SCRIPT, 1)], DECLARED, CODE, diff("app/x.py", "import torch"), set())
    assert v["full_suite"] and "torch" in v["reasons"][0]


def case_hop(cs):
    # The lib is named by no test. The script that sources it is. One hop.
    v = cs.plan([(LIB, 3)], DECLARED, CODE)
    assert v["selected_tests"] == [T_WIDGET]


def test_a_sourced_lib_reaches_the_tests_of_the_script_that_sources_it(cs):
    case_hop(cs)


def case_callers_tests_run_even_when_the_file_has_its_own(cs):
    # codex, PR #377 round 2: a lib with its OWN unit test, and a caller whose test
    # breaks when the lib changes. Both run.
    declared = dict(DECLARED, **{"t/test-lib.sh": "source widget-lib.sh"})
    v = cs.plan([(LIB, 3)], declared, CODE)
    assert v["selected_tests"] == sorted(["t/test-lib.sh", T_WIDGET])


def test_a_lib_with_its_own_test_still_runs_its_callers_tests(cs):
    case_callers_tests_run_even_when_the_file_has_its_own(cs)


def case_comment_is_not_a_caller(cs):
    code = {SCRIPT: "# scar: widget-lib.sh once ate the ledger\nrun", LIB: "helper() { :; }"}
    v = cs.plan([(LIB, 3)], DECLARED, code)
    assert v["selected_tests"] == [] and not v["full_suite"]


def test_a_comment_that_talks_about_a_script_is_not_a_caller(cs):
    case_comment_is_not_a_caller(cs)


def test_the_walk_stops_one_step_out(cs):
    code = dict(CODE, **{"x/outer.sh": "bash widget.sh"})
    declared = dict(DECLARED, **{"t/test-outer.sh": "bash outer.sh"})
    assert cs.plan([(LIB, 3)], declared, code)["selected_tests"] == [T_WIDGET]


def test_an_executable_nothing_names_runs_nothing_rather_than_everything(cs):
    # "The full suite" means the DECLARED tests. None of them can see this file,
    # so running all 236 exercises it exactly as much as running none.
    v = cs.plan([("tools/orphan.py", 2)], DECLARED, CODE)
    assert not v["full_suite"] and v["tier"] == "S" and v["selected_tests"] == []


def test_a_two_line_change_in_a_repo_that_declares_no_tests_is_small(cs):
    # ASK-1749 acceptance row 1, from the corpus the issue names: a 2-line
    # read-site registration is S.
    assert cs.plan([("app/read_sites.py", 2)], {}, {})["tier"] == "S"


FIXTURE = "q-system/.q-system/scripts/test/fixtures/widget-cases/absent.json"
PLIST = "q-system/.q-system/launchd/com.kipi.widget.plist"


def case_fixture_reaches_its_owner(cs):
    # codex, PR #377 round 1, major 1: a PR that breaks only a tracked fixture ran
    # ZERO tests, because everything under fixtures/ was skipped before matching.
    declared = dict(DECLARED, **{T_WIDGET: 'FX="$HERE/fixtures/widget-cases"; bash widget.sh < "$FX/x"'})
    v = cs.plan([(FIXTURE, 3)], declared, CODE)
    assert v["selected_tests"] == [T_WIDGET] and not v["full_suite"]
    assert cs.owning_dirs(FIXTURE) == ["widget-cases"]          # not `fixtures`, not `test`


def test_a_changed_fixture_runs_the_test_that_owns_its_directory(cs):
    case_fixture_reaches_its_owner(cs)


def test_an_enumerated_input_reaches_its_test_through_the_scanner_floor(cs):
    # Same review, major 2: a test that globs its inputs never names them. The
    # answer is not a glob parser -- a test that enumerates also WALKS, so the
    # always-run floor has it. Round 1's 40-line parser chose nothing this does not.
    declared = dict(DECLARED, **{"t/test-install-jobs-coverage.py": 'for p in root.rglob("com.kipi.*.plist"): check(p)'})
    v = cs.plan([(PLIST, 2)], declared, CODE)
    assert v["selected_tests"] == ["t/test-install-jobs-coverage.py"] and not v["full_suite"]


SCANNER = "t/test-scans.py"
SCAN_FORMS = ("for p in d.iterdir(): check(p)", "for root,_,fs in os.walk(d): pass",
              "for n in os.listdir(d): pass", 'for f in "$DIR"/*.sh; do bash "$f"; done',
              "git ls-files | while read f; do :; done", 'find "$ROOT" -type f')


def case_every_scanner_always_runs(cs):
    # THE CLASS, KILLED BY CONSTRUCTION (codex, PR #377 rounds 1-4). Four rounds
    # each named another spelling the pattern parser did not know. A test that
    # walks the tree reads files nobody named, so it runs on every diff, whatever
    # the spelling and whatever changed.
    for form in SCAN_FORMS:
        declared = dict(DECLARED, **{SCANNER: form})
        v = cs.plan([(SCRIPT, 1)], declared, CODE)
        assert SCANNER in v["selected_tests"], form
    # A test that walks nothing is not dragged in.
    declared = dict(DECLARED, **{SCANNER: "assert compute(2) == 4"})
    assert SCANNER not in cs.plan([(SCRIPT, 1)], declared, CODE)["selected_tests"]


def test_a_test_that_walks_the_tree_runs_on_every_diff(cs):
    case_every_scanner_always_runs(cs)


PLIST_SCANNER = "t/test-install-plist.sh"
SCANNER_TEXT = 'for p in "$ROOT"/launchd/*.plist; do check "$p"; done'


def case_a_declared_scanner_leaves_the_floor(cs):
    # ASK-1918. A scanner runs on EVERY diff because nobody wrote down what it
    # covers. Measured 2026-09-19: the 73-artifact selected path cost 699s of the
    # full suite's 822s (runs 35488448685 / 35486006414), so 31% of the artifacts
    # carry 85% of the cost and no SELECTOR can get under that floor.
    #
    # Rounds 1-4 of PR #377 tried to INFER coverage by parsing globs out of the
    # test's own source. Each round named another spelling the parser did not
    # know; round 4 gave up and made every scanner always-run. The declaration
    # below is the same question asked of a human instead of a regex, so there is
    # no fifth spelling.
    declared = dict(DECLARED, **{PLIST_SCANNER: SCANNER_TEXT})
    covers = {PLIST_SCANNER: ["**/*.plist"]}
    # A python-only diff: the scanner cannot be affected, so it does not run.
    v = cs.plan([(SCRIPT, 1)], declared, CODE, covers=covers)
    assert PLIST_SCANNER not in v["selected_tests"], v["selected_tests"]
    # A plist diff: it runs.
    v = cs.plan([(PLIST, 1)], declared, CODE, covers=covers)
    assert PLIST_SCANNER in v["selected_tests"], v["selected_tests"]


def test_a_scanner_that_declares_its_coverage_runs_only_when_it_matches(cs):
    case_a_declared_scanner_leaves_the_floor(cs)


def case_an_undeclared_scanner_keeps_the_floor(cs):
    # THE NEGATIVE SELF-TEST. Zero declarations must reproduce today's behaviour
    # exactly, so this lands one fragment at a time with no flag day.
    declared = dict(DECLARED, **{PLIST_SCANNER: SCANNER_TEXT})
    for covers in ({}, {PLIST_SCANNER: []}, None):
        v = cs.plan([(SCRIPT, 1)], declared, CODE, covers=covers)
        assert PLIST_SCANNER in v["selected_tests"], covers


def test_a_scanner_with_no_declaration_still_runs_on_every_diff(cs):
    case_an_undeclared_scanner_keeps_the_floor(cs)


def case_covers_on_a_non_scanner_grants_nothing(cs):
    # `covers` may only take a test OFF the floor. It can never put one ON, or a
    # declaration would become a second way to select, which is new power a typo
    # could aim anywhere.
    declared = dict(DECLARED, **{"t/test-quiet.sh": "assert compute(2) == 4"})
    v = cs.plan([(PLIST, 1)], declared, CODE, covers={"t/test-quiet.sh": ["**/*.plist"]})
    assert "t/test-quiet.sh" not in v["selected_tests"]


def test_covers_on_a_non_scanner_grants_nothing(cs):
    case_covers_on_a_non_scanner_grants_nothing(cs)


# EVERY `**` POSITION, BOTH DIRECTIONS (ASK-1922). PR #385 found the same defect
# twice: round 1 that a LEADING `**/` missed all 39 root-level scripts, round 2
# that an INTERIOR `**/` missed depth zero the same way. Two rounds of one class
# means the fix SHAPE was wrong, so the third answer is not a third branch --
# `covers_matches` is one translator now, and this table is what holds it. A row
# per position, and a False row beside every True one, because a matcher that
# says yes to everything passes any table made only of matches.
DOUBLE_STAR_CASES = (
    # leading: at any depth, INCLUDING none (round 1, major)
    ("**/*.sh", "kipi-promote.sh", True),
    ("**/*.sh", "q-system/.q-system/scripts/x.sh", True),
    ("**/*.sh", "kipi-promote.py", False),
    ("**/*.py", "fix-voice-style.py", True),
    ("**/*.py", "a/b/c.py", True),
    # interior: the same defect one position over (round 2, minor)
    ("q-system/**/*.sh", "q-system/x.sh", True),
    ("q-system/**/*.sh", "q-system/a/b/x.sh", True),
    ("q-system/**/*.sh", "plugins/x.sh", False),
    ("q-system/**/*.sh", "q-system/x.py", False),
    # trailing: everything BELOW the directory, and nothing beside it
    ("launchd/**", "launchd/a.plist", True),
    ("launchd/**", "launchd/deep/a.plist", True),
    ("launchd/**", "other/a.plist", False),
    # doubled: still zero-or-more, not two-or-more
    ("**/**/*.py", "a.py", True),
    ("**/**/*.py", "a/b/c.py", True),
    ("**/**/*.py", "a/b/c.sh", False),
    # `*` IS ONE SEGMENT. That is what leaves `**` something to mean. fnmatch's
    # `*` crossed `/`, so the two spellings were synonyms and `**` was decoration.
    ("q-system/*/x.sh", "q-system/a/x.sh", True),
    ("q-system/*/x.sh", "q-system/a/b/x.sh", False),
    ("q-system/*/x.sh", "q-system/x.sh", False),
    # a slash-less pattern matches the BASENAME, the way `find -name` does
    ("kipi", "kipi", True),
    ("kipi", "sub/kipi", True),
    ("kipi", "kipi-promote.sh", False),
    ("*.plist", "launchd/a.plist", True),
    ("*.plist", "launchd/a.plst", False),
)


def case_double_star_matches_at_every_position(cs):
    for pat, path, want in DOUBLE_STAR_CASES:
        assert cs.covers_matches(pat, path) is want, (pat, path, want)


def test_a_double_star_glob_matches_at_every_position(cs):
    case_double_star_matches_at_every_position(cs)


def case_covers_is_read_even_when_the_changed_file_is_itself_a_test(cs):
    # claude review of PR #385, minor 2. The per-path loop `continue`d as soon as
    # the changed path was itself a declared test (it selects itself, correctly),
    # and that skip happened BEFORE `covers` was consulted -- so a scanner whose
    # declaration named another declared test's path never ran for it. Silent:
    # covers-lint could not see it either, because the glob does match a tracked
    # file. Both tests run here, the one that owns the file and the one that
    # declared it covered.
    scanner, other = PLIST_SCANNER, T_OTHER
    declared = dict(DECLARED, **{scanner: SCANNER_TEXT})
    v = cs.plan([(other, 1)], declared, CODE, covers={scanner: [other]})
    assert other in v["selected_tests"], v["selected_tests"]
    assert scanner in v["selected_tests"], v["selected_tests"]


def test_a_covers_glob_naming_another_declared_test_is_honoured(cs):
    case_covers_is_read_even_when_the_changed_file_is_itself_a_test(cs)


def case_a_malformed_covers_voids_the_whole_list(cs):
    import tempfile
    _read_declared_cases(cs, Path(tempfile.mkdtemp()))


def test_read_declared_drops_a_malformed_covers(cs, tmp_path):
    _read_declared_cases(cs, tmp_path)


def _read_declared_cases(cs, tmp_path):
    # THE ASYMMETRY: everything uncertain resolves upward. A declaration that is
    # not a list of non-empty strings is DROPPED, which leaves the test on the
    # always-run floor -- the expensive answer, and the safe one.
    #
    # `mixed` is the row the docstring always claimed and the code did not do
    # (claude review of PR #385, minor 3): the first cut kept the good entries
    # and dropped only the bad ones, so `["**/*.plist", None]` still took the
    # test OFF the floor on a declaration nobody could read. One bad entry now
    # voids the whole list, which is what the safe-by-default posture means.
    root = tmp_path / "r"
    frags = root / cs.EXPECTED_TESTS_DIR
    frags.mkdir(parents=True)
    (root / "t").mkdir()
    for name, covers in (("good", ["**/*.plist"]), ("str", "**/*.plist"),
                         ("empty", []), ("junk", [None, ""]),
                         ("mixed", ["**/*.plist", None]), ("absent", "OMIT")):
        rel = f"t/test-{name}.sh"
        (root / rel).write_text("echo hi\n")
        entry = {"path": rel, "runner": "bash"}
        if covers != "OMIT":
            entry["covers"] = covers
        (frags / f"{name}.json").write_text(json.dumps(entry))
    _declared, _frags, got = cs.read_declared(root)
    assert got == {"t/test-good.sh": ["**/*.plist"]}, got


def case_scanners_do_not_trip_the_width_cap(cs):
    # A fixed floor is not evidence that THIS diff is suite-wide.
    declared = dict(DECLARED, **{f"t/test-scan-{i}.py": "d.iterdir()" for i in range(cs.MAX_SELECTED + 5)})
    v = cs.plan([(SCRIPT, 1)], declared, CODE)
    assert not v["full_suite"] and len(v["selected_tests"]) > cs.MAX_SELECTED


def test_the_always_run_floor_does_not_force_a_full_suite(cs):
    case_scanners_do_not_trip_the_width_cap(cs)


def test_a_file_no_declared_test_names_is_not_swept_into_a_full_run(cs):
    # Rounds 1-3 were one class. The full suite = the DECLARED tests, so a file
    # none of them can see is not covered by running all of them. Escalating here
    # bought 17 minutes and no coverage, so it does not escalate.
    for path in (PLIST, FIXTURE, "config/routes.json", "docs/notes.md"):
        v = cs.plan([(path, 1)], DECLARED, CODE)
        assert not v["full_suite"] and v["selected_tests"] == [], path


def case_too_wide(cs):
    declared = {f"t/test-{i}.sh": "bash widget.sh" for i in range(cs.MAX_SELECTED + 2)}
    v = cs.plan([(SCRIPT, 1)], declared, CODE)
    assert v["full_suite"] and "that is the suite" in v["reasons"][-1]


def test_a_selection_wider_than_the_cap_is_a_full_run(cs):
    case_too_wide(cs)


def case_size_is_not_a_full_run(cs):
    # 304 lines that two tests name ran all 235 under the first cut, again on
    # every review round, because CI diffs the whole PR against main.
    v = cs.plan([(SCRIPT, 304)], DECLARED, CODE)
    assert v["tier"] == "L" and not v["full_suite"] and v["selected_tests"] == [T_WIDGET]


def test_a_large_diff_earns_review_not_the_whole_suite(cs):
    case_size_is_not_a_full_run(cs)


def test_a_name_matches_whole_names_only(cs):
    assert cs.mentions("bash converge.sh", "x/converge.sh")
    assert not cs.mentions("bash test-converge.sh", "x/converge.sh")
    assert not cs.mentions("bash converge.sh.bak", "x/converge.sh")
    assert cs.mentions("then it runs converge.sh. After that", "x/converge.sh")
    assert cs.mentions("from loops_path import resolve", "scripts/loops_path.py")  # ASK-517


def test_docs_and_fixtures_are_not_app_code(cs):
    v = cs.plan([("README.md", 400), (T_WIDGET, 90)], DECLARED, CODE)
    assert v["app_lines"] == 0 and v["tier"] == "S" and v["selected_tests"] == [T_WIDGET]


# ------------------------------------------------------------------ the gate
def git(root, *args):
    subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t.invalid", *args],
                   check=True, capture_output=True)


@pytest.fixture()
def repo(tmp_path):
    root = tmp_path / "repo"
    scripts = root / "q-system/.q-system/scripts"
    (scripts / "test").mkdir(parents=True)
    frags = root / "q-system/.q-system/capability/expected_tests"
    frags.mkdir(parents=True)
    (scripts / "widget.sh").write_text("echo 1\n")
    (scripts / "capability-gate.py").write_text("# stand-in\n")
    for name, body in (("test-widget.sh", "# names widget.sh\ntouch ran-widget\n"),
                       ("test-other.sh", "touch ran-other\n")):
        (scripts / "test" / name).write_text(body)
        rel = f"q-system/.q-system/scripts/test/{name}"
        (frags / (rel.replace("/", "__") + ".json")).write_text(json.dumps({"path": rel, "runner": "bash"}))
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")
    git(root, "branch", "base")
    return root


def manifest_of(root):
    frags = sorted((root / "q-system/.q-system/capability/expected_tests").glob("*.json"))
    return {"expected_tests": [json.loads(f.read_text()) for f in frags]}


@pytest.fixture()
def gate(tmp_path):
    # The gate loads change-size.py from beside ITSELF, so the copy under test
    # gets the shipped classifier beside it.
    (tmp_path / "change-size.py").write_text(CS_SRC)
    return load(GATE_SRC, "capability_gate_under_test", tmp_path)


def case_gate_runs_only_the_selection(gate, repo):
    (repo / "q-system/.q-system/scripts/widget.sh").write_text("echo 2\n")
    git(repo, "commit", "-q", "-am", "one line")
    notes, errors = [], []
    only = gate.select_for_diff(repo, "base", notes)
    assert only == {"q-system/.q-system/scripts/test/test-widget.sh"}, notes
    gate.run_tests(repo, manifest_of(repo), "skeleton", errors, notes, only)
    assert not errors
    assert (repo / "ran-widget").exists() and not (repo / "ran-other").exists()
    assert "not-selected-for-this-diff=1" in notes[-1]


def test_the_gate_runs_the_selection_and_nothing_else(gate, repo):
    case_gate_runs_only_the_selection(gate, repo)


def test_without_a_selection_the_gate_runs_everything_as_before(gate, repo):
    notes, errors = [], []
    gate.run_tests(repo, manifest_of(repo), "skeleton", errors, notes)
    assert (repo / "ran-widget").exists() and (repo / "ran-other").exists()
    assert "not-selected" not in notes[-1]


def case_gate_falls_back_to_everything(gate, repo):
    notes = []
    assert gate.select_for_diff(repo, "no-such-ref", notes) is None
    assert "FULL suite" in notes[-1]
    (repo / "q-system/.q-system/scripts/capability-gate.py").write_text("# changed\n")
    git(repo, "commit", "-q", "-am", "touch the gate")
    assert gate.select_for_diff(repo, "base", notes) is None
    assert "FULL suite" in notes[-1] and "decides what runs" in notes[-1]


def test_an_unreadable_diff_or_a_change_to_the_gate_runs_everything(gate, repo):
    case_gate_falls_back_to_everything(gate, repo)


# --------------------------------------------------------------- the mutants
CS_MUTANTS = [
    ("the machinery escalator", "        if why:\n            escalators.append(why)", "        if False:\n            escalators.append(why)", case_escalator_beats_line_count),
    ("imports scoped to app code", 'if line.startswith("+++") or is_test_path(current):', 'if line.startswith("+++"):', case_import_scoping),
    ("a comment is not an edge", 'if not l.lstrip().startswith("#"))', "if True)", case_comment_is_not_a_caller),
    ("the callers' tests run", "        for dep in dependents(path, live):", "        for dep in []:", None),
    ("a fixture is matched before it is skipped", "            if is_test_path(path):\n                direct |=", "            if False:\n                direct |=", case_fixture_reaches_its_owner),
    ("every scanner always runs", "    always = {t for t in scanners if t not in declared_covers}", "    always = set()", case_every_scanner_always_runs),
    ("a declaration takes a scanner off the floor", "    always = {t for t in scanners if t not in declared_covers}", "    always = set(scanners)", case_a_declared_scanner_leaves_the_floor),
    ("covers never selects a non-scanner", "                     if t in scanners and any(covers_matches(p, path) for p in pats)}", "                     if any(covers_matches(p, path) for p in pats)}", case_covers_on_a_non_scanner_grants_nothing),
    ("a malformed covers voids the whole list", " and all(isinstance(p, str) and p for p in pats)", "", case_a_malformed_covers_voids_the_whole_list),
    ("** spans zero segments", 'out.append(".*" if last else "(?:[^/]+/)*")', 'out.append(".*" if last else "[^/]+/")', case_double_star_matches_at_every_position),
    ("* stops at a separator", 'out.append("[^/]*")', 'out.append(".*")', case_double_star_matches_at_every_position),
    ("covers is read for every changed path", "    for path, _ in changed:\n        selected |= {t for t, pats in declared_covers.items()", "    for path, _ in []:\n        selected |= {t for t, pats in declared_covers.items()", case_covers_is_read_even_when_the_changed_file_is_itself_a_test),
    ("the floor is outside the width cap", "    pulled = selected - always", "    pulled = selected", case_scanners_do_not_trip_the_width_cap),
    ("the width cap", "if len(pulled) > MAX_SELECTED:", "if False:", case_too_wide),
    ("size is not a full run", "full_suite = bool(escalators)", "full_suite = bool(escalators) or app_lines > M_MAX_LINES", case_size_is_not_a_full_run),
]


def case_hop_mutant(cs):
    case_callers_tests_run_even_when_the_file_has_its_own(cs)


@pytest.mark.parametrize("label,old,new,case", CS_MUTANTS, ids=[m[0] for m in CS_MUTANTS])
def test_classifier_mutants_are_killed(label, old, new, case, tmp_path):
    assert old in CS_SRC, f"the mutant for '{label}' no longer matches the source"
    mutant = load(CS_SRC.replace(old, new, 1), "cs_mutant", tmp_path)
    with pytest.raises(AssertionError):
        (case or case_hop_mutant)(mutant)


GATE_MUTANTS = [
    ("the gate skips what was not selected", "if only is not None and path not in only:", "if False:", case_gate_runs_only_the_selection),
    ("a failed classification means everything", "        return None\n    notes.append(f\"change-size vs {base}: tier", "        return set()\n    notes.append(f\"change-size vs {base}: tier", case_gate_falls_back_to_everything),
]


@pytest.mark.parametrize("label,old,new,case", GATE_MUTANTS, ids=[m[0] for m in GATE_MUTANTS])
def test_gate_mutants_are_killed(label, old, new, case, tmp_path, repo):
    assert old in GATE_SRC, f"the mutant for '{label}' no longer matches the source"
    (tmp_path / "change-size.py").write_text(CS_SRC)
    mutant = load(GATE_SRC.replace(old, new, 1), "gate_mutant", tmp_path)
    with pytest.raises(AssertionError):
        case(mutant, repo)
