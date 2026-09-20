"""covers-lint.py refuses a coverage declaration that selects nothing (ASK-1918).

Every case builds a throwaway git repo under tmp_path and runs the SHIPPED
script against it. No network, no live data path, and the only "tests" it
declares are one-line scripts that are never executed -- the lint reads them, it
does not run them.

The three refusals were each seen RED against the real repo before this file
existed (2026-09-19): a typo'd glob, a non-list `covers`, and a declaration on a
test change-size.py does not call a scanner.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
LINT = HERE / "covers-lint.py"
CS = HERE / "change-size.py"

SCANNER = "t/test-scan.sh"
SCANNER_BODY = 'for p in "$ROOT"/launchd/*.plist; do check "$p"; done\n'
QUIET = "t/test-quiet.sh"
QUIET_BODY = "assert_equal 4 4\n"
TRACKED_PLIST = "launchd/com.kipi.widget.plist"


def git(root, *args):
    subprocess.run(["git", "-C", str(root), "-c", "user.name=t",
                    "-c", "user.email=t@t.invalid", *args],
                   check=True, capture_output=True)


@pytest.fixture()
def repo(tmp_path):
    """A repo carrying the shipped classifier, one scanner, one non-scanner, and
    one tracked plist for a glob to match."""
    root = tmp_path / "repo"
    (root / "q-system/.q-system/scripts").mkdir(parents=True)
    (root / "q-system/.q-system/capability/expected_tests").mkdir(parents=True)
    (root / "t").mkdir()
    (root / "launchd").mkdir()
    (root / "q-system/.q-system/scripts/change-size.py").write_text(CS.read_text())
    (root / SCANNER).write_text(SCANNER_BODY)
    (root / QUIET).write_text(QUIET_BODY)
    (root / TRACKED_PLIST).write_text("<plist/>\n")
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")
    return root


def declare(root, name, entry):
    frag = root / "q-system/.q-system/capability/expected_tests" / f"{name}.json"
    frag.write_text(json.dumps(entry))
    git(root, "add", "-A")
    return frag


def run(root):
    return subprocess.run([sys.executable, str(LINT), "--repo-root", str(root)],
                          capture_output=True, text=True)


def test_a_glob_that_matches_a_tracked_file_passes(repo):
    declare(repo, "scan", {"path": SCANNER, "runner": "bash", "covers": ["**/*.plist"]})
    r = run(repo)
    assert r.returncode == 0, r.stderr
    assert "PASS" in r.stdout


def test_a_fragment_with_no_covers_passes(repo):
    declare(repo, "scan", {"path": SCANNER, "runner": "bash"})
    assert run(repo).returncode == 0


def test_a_glob_matching_no_tracked_file_is_refused(repo):
    # THE REASON THIS LINT EXISTS. `**/*.plst` takes the scanner off the
    # always-run floor and selects it for nothing, and a test that is never
    # selected is indistinguishable from a test that is never needed.
    declare(repo, "scan", {"path": SCANNER, "runner": "bash", "covers": ["**/*.plst"]})
    r = run(repo)
    assert r.returncode == 2
    assert "matches no tracked file" in r.stderr


def test_a_covers_that_is_not_a_list_is_refused(repo):
    declare(repo, "scan", {"path": SCANNER, "runner": "bash", "covers": "**/*.plist"})
    r = run(repo)
    assert r.returncode == 2
    assert "non-empty list" in r.stderr


def test_a_covers_on_a_non_scanner_is_refused_as_inert(repo):
    # change-size.py only ever honours `covers` to take a SCANNER off the floor.
    # On anything else the key does nothing, so a fragment carrying one is a
    # misunderstanding worth naming rather than silently ignoring.
    declare(repo, "quiet", {"path": QUIET, "runner": "bash", "covers": ["**/*.plist"]})
    r = run(repo)
    assert r.returncode == 2
    assert "INERT" in r.stderr


@pytest.mark.parametrize("glob", ["**.plist", "launchd/**.plist", "la**nchd/*.plist"])
def test_a_double_star_inside_a_segment_is_refused(repo, glob):
    # ASK-1922, the decidable half of "this glob cannot match what its author
    # meant". `**` is zero-or-more DIRECTORIES only when it is the whole segment;
    # written inside one it silently degrades to `*` and stops at a `/`. Two
    # rounds of PR #385 were that same silent narrowing at other positions, so
    # the one position the matcher still cannot honour gets refused at the door.
    declare(repo, "scan", {"path": SCANNER, "runner": "bash", "covers": [glob]})
    r = run(repo)
    assert r.returncode == 2, r.stdout
    assert "inside the segment" in r.stderr


def test_a_double_star_as_a_whole_segment_is_accepted(repo):
    # THE NEGATIVE SELF-TEST for the refusal above: the legal spellings still pass,
    # or the check would be an outage wearing a gate's name.
    for glob in ("**/*.plist", "launchd/**", "**/launchd/**/*.plist"):
        declare(repo, "scan", {"path": SCANNER, "runner": "bash", "covers": [glob]})
        r = run(repo)
        assert r.returncode == 0, (glob, r.stderr)


def test_a_covers_whose_path_is_missing_is_refused(repo):
    declare(repo, "gone", {"path": "t/absent.sh", "runner": "bash", "covers": ["**/*.plist"]})
    r = run(repo)
    assert r.returncode == 2
    assert "not a file" in r.stderr


def test_hook_mode_fast_exits_on_an_out_of_scope_path(repo):
    declare(repo, "scan", {"path": SCANNER, "runner": "bash", "covers": ["**/*.plst"]})
    # A broken declaration exists, but the paths given are not fragments, so the
    # hook must say nothing rather than sweep (token discipline).
    r = subprocess.run([sys.executable, str(LINT), "--repo-root", str(repo),
                        "README.md", "q-system/.q-system/scripts/change-size.py"],
                       capture_output=True, text=True)
    assert r.returncode == 0 and not r.stdout.strip()


def test_hook_mode_still_refuses_a_fragment_it_is_given(repo):
    frag = declare(repo, "scan", {"path": SCANNER, "runner": "bash", "covers": ["**/*.plst"]})
    r = subprocess.run([sys.executable, str(LINT), "--repo-root", str(repo), str(frag)],
                       capture_output=True, text=True)
    assert r.returncode == 2 and "matches no tracked file" in r.stderr
