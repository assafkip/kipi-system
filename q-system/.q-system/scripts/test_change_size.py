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
    assert v["selected_tests"] == [T_WIDGET] and not v["untested_by_name"]


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
    assert v["selected_tests"] == [] and v["untested_by_name"] == [LIB]


def test_a_comment_that_talks_about_a_script_is_not_a_caller(cs):
    case_comment_is_not_a_caller(cs)


def test_the_walk_stops_one_step_out(cs):
    code = dict(CODE, **{"x/outer.sh": "bash widget.sh"})
    declared = dict(DECLARED, **{"t/test-outer.sh": "bash outer.sh"})
    assert cs.plan([(LIB, 3)], declared, code)["selected_tests"] == [T_WIDGET]


def test_an_executable_nothing_names_is_said_out_loud_not_run_as_the_suite(cs):
    v = cs.plan([("tools/orphan.py", 2)], DECLARED, CODE)
    assert not v["full_suite"] and v["tier"] == "M" and v["untested_by_name"] == ["tools/orphan.py"]


def test_a_repo_that_declares_no_tests_gets_no_untested_floor(cs):
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


def test_a_changed_fixture_runs_the_test_that_owns_its_directory(cs):
    case_fixture_reaches_its_owner(cs)


def case_enumerated_input_reaches_its_scanner(cs):
    # Same review, major 2: a test that globs its inputs never names them.
    declared = dict(DECLARED, **{"t/test-install-jobs-coverage.py": 'for p in root.rglob("com.kipi.*.plist"): check(p)'})
    v = cs.plan([(PLIST, 2)], declared, CODE)
    assert v["selected_tests"] == ["t/test-install-jobs-coverage.py"] and not v["full_suite"]


def test_a_changed_input_runs_the_test_whose_pattern_enumerates_it(cs):
    case_enumerated_input_reaches_its_scanner(cs)


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


def case_scanners_do_not_trip_the_width_cap(cs):
    # A fixed floor is not evidence that THIS diff is suite-wide.
    declared = dict(DECLARED, **{f"t/test-scan-{i}.py": "d.iterdir()" for i in range(cs.MAX_SELECTED + 5)})
    v = cs.plan([(SCRIPT, 1)], declared, CODE)
    assert not v["full_suite"] and len(v["selected_tests"]) > cs.MAX_SELECTED


def test_the_always_run_floor_does_not_force_a_full_suite(cs):
    case_scanners_do_not_trip_the_width_cap(cs)


def case_a_naming_pattern_is_ownership(cs):
    # A pattern with a NAME in it means that test owns the file, so the file is
    # not reported as unowned. A type-only pattern selects but does not own.
    declared = dict(DECLARED, **{"t/test-install.py": 'root.rglob("com.kipi.*.plist")'})
    assert cs.plan([(PLIST, 2)], declared, CODE)["untested_by_name"] == []


def test_a_pattern_that_names_something_is_ownership(cs):
    case_a_naming_pattern_is_ownership(cs)


def case_unowned_data_is_reported_not_swept(cs):
    # Rounds 1-3 were one class. The full suite = the DECLARED tests, so a file
    # none of them can see is not covered by running all of them.
    for path in (PLIST, FIXTURE, "config/routes.json"):
        v = cs.plan([(path, 1)], DECLARED, CODE)
        assert not v["full_suite"] and v["untested_by_name"] == [path] and v["tier"] == "M", path
    # Prose is not an input to anything.
    v = cs.plan([("docs/notes.md", 40)], DECLARED, CODE)
    assert not v["full_suite"] and v["untested_by_name"] == []


def test_a_file_no_declared_test_owns_is_named_not_swept(cs):
    case_unowned_data_is_reported_not_swept(cs)


def case_a_bare_wildcard_owns_nothing(cs):  # noqa: D401 -- ownership, not selection
    # codex, PR #377 round 3: a test that globs `*` in its own tmp dir claimed every
    # changed file, so the unowned-data fallback and UNTESTED BY NAME both went dead.
    declared = dict(DECLARED, **{"t/test-tmp.py": 'for p in tmp.glob("*"): p.unlink()',
                                 "t/test-json.py": 'for p in d.rglob("*.json"): load(p)'})
    v = cs.plan([("config/routes.json", 1)], declared, CODE)
    assert v["untested_by_name"] == ["config/routes.json"] and not v["full_suite"]
    v = cs.plan([("tools/orphan.py", 2)], declared, CODE)
    assert v["untested_by_name"] == ["tools/orphan.py"] and not v["full_suite"]
    # ...and the scanners still RUN: selecting a test is not the same as owning.
    assert "t/test-tmp.py" in v["selected_tests"]


def test_a_type_only_pattern_runs_its_test_but_owns_nothing(cs):
    case_a_bare_wildcard_owns_nothing(cs)
    for p, want in (("*", False), ("*.*", False), ("*.json", False), ("**/*.py", False),
                    ("com.kipi.*.plist", True), ("prd-*.md", True), ("*.verdict.json", True)):
        assert cs.names_something(p) is want, p


def test_patterns_are_read_from_the_tests_own_text(cs):
    text = """for p in d.glob("*.verdict.json"): pass
find "$ROOT" -name 'com.kipi.*.plist'
git ls-files 'plugins/*/hooks/hooks.json'"""
    assert cs.enumeration_patterns(text) == ["*.verdict.json", "com.kipi.*.plist", "plugins/*/hooks/hooks.json"]
    assert cs.pattern_matches("com.kipi.*.plist", PLIST)
    assert cs.pattern_matches("plugins/*/hooks/hooks.json", "plugins/prd-os/hooks/hooks.json")
    assert not cs.pattern_matches("com.kipi.*.plist", "q-system/x/com.cole.widget.plist")
    assert cs.owning_dirs(FIXTURE) == ["widget-cases"]          # not `fixtures`, not `test`


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
    ("an enumerating test owns what it globs", "                   if any(pattern_matches(p, path) for p in pats if names_something(p))}", "                   if False}", case_a_naming_pattern_is_ownership),
    ("every scanner always runs", "    always = {t for t, text in declared.items() if scans_the_tree(text)}", "    always = set()", case_every_scanner_always_runs),
    ("the floor is outside the width cap", "    pulled = selected - always", "    pulled = selected", case_scanners_do_not_trip_the_width_cap),
    ("a type-only pattern owns nothing", "for p in pats if names_something(p))}", "for p in pats)}", case_a_bare_wildcard_owns_nothing),
    ("unowned data is reported", "if not direct and not path.endswith(DOC_SUFFIXES):", "if False:", case_unowned_data_is_reported_not_swept),
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
