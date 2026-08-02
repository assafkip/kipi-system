#!/usr/bin/env python3
"""
Self-contained test for fable-discipline-lint.py. Exit 0 = all pass, 1 = a case failed.

Dogfoods the fable-discipline skill: every fixture is written under a TemporaryDirectory
(isolation), never a real path. Run from this directory:
    python3 test_fable_discipline_lint.py
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# REF HATCH: point the suite at a DIFFERENT copy of the lint, so the pre-feature
# lint can be checked out from a git ref and watched to FAIL. A regression case
# added after its own fix has never been observed red, and an unobserved-red case
# is an assertion about nothing. This suite used to pass unchanged against the
# lint from a5ac9c1 -- deleting the whole outbound-channel detector left its own
# regression suite green.
#
#   git show <pre-feature-ref>:plugins/prd-os/skills/fable-discipline/scripts/\
#     fable-discipline-lint.py > /tmp/old-lint.py
#   FABLE_LINT_UNDER_TEST=/tmp/old-lint.py python3 test_fable_discipline_lint.py
LINT = (os.environ.get("FABLE_LINT_UNDER_TEST")
        or str(Path(__file__).resolve().parent / "fable-discipline-lint.py"))

# (filename, content, expected_exit)
CASES = [
    ("test_live.py",
     'import sqlite3\ndef test_x():\n    sqlite3.connect("investigations/data/investigations.db")\n',
     2),
    ("test_var_indirection.py",
     'import sqlite3\ndef test_x():\n    db_path = "investigations/data/prod.db"\n    sqlite3.connect(db_path)\n',
     2),
    ("test_isolated.py",
     'import sqlite3\ndef test_x(tmp_path):\n    sqlite3.connect(":memory:")\n    sqlite3.connect(str(tmp_path / "t.db"))\n',
     0),
    ("test_skip.py",
     '# fable-discipline-lint-skip\nimport sqlite3\ndef test_x():\n    sqlite3.connect("data/live.db")\n',
     0),
    ("test_assertion_ctx.py",
     'def test_audit(out):\n    # audit test names the live path on purpose\n    assert "data/prod.db" in out\n',
     0),
    ("test_augmented.py",
     'def test_x():\n    db_path = "/var/lib/app"\n    db_path += "/var/lib/app/prod.db"\n',
     2),
    ("test_walrus.py",
     'import sqlite3\ndef test_x():\n    if (p := "/var/lib/app/prod.db"):\n        sqlite3.connect(p)\n',
     2),
    ("test_dict_target.py",
     'def test_x(cfg):\n    cfg["db"] = "/var/lib/app/prod.db"\n',
     2),
    ("test_fstring.py",
     'import sqlite3\nfrom pathlib import Path\ndef test_x():\n    sqlite3.connect(f"{Path(\'/var/lib/app/prod.db\')}")\n',
     2),
    ("test_golden_fixture.py",
     'def test_x():\n    open("/repo/tests/golden/prod.db")\n',
     0),
    ("app.py",
     'import sqlite3\nsqlite3.connect("investigations/data/investigations.db")\n',
     0),
    # --- spillover deferral capture (code files only; the GATE is the teeth) ---
    ("deferred_uncaptured.py",
     '# TODO: archive filter is out of scope here, fix later\nVALUE = 1\n',
     2),
    ("deferred_acked.py",
     '# spillover-skip\n# out of scope: captured as sp-123 already\nVALUE = 1\n',
     0),
    ("no_deferral.py",
     'def add(a, b):\n    return a + b  # straightforward\n',
     0),
    ("deferral_in_markdown.md",
     'We left the CLI digest filter out of scope for now; fix later.\n',
     0),
]


# --- outbound-channel cases -------------------------------------------------
# These are TREE-SHAPED on purpose. The detector resolves a runner NEXT TO the
# test (../<name> or ./<name>), so a flat tempdir makes every runner
# unresolvable and the whole detector reports green on a leaking fixture. The
# first version of this suite had no channel cases at all: it passed unchanged
# against the pre-feature lint, which means deleting the detector outright left
# its own regression suite green. A self-test that cannot detect its own
# removal is decoration.

# Reaches the pager on a LIVE line -> notify-capable.
PAGER_RUNNER = (
    '#!/usr/bin/env bash\n'
    'NOTIFY="${KIPI_NOTIFY:-$SCRIPT_DIR/slack-notify.sh}"\n'
    'bash "$NOTIFY" "a human needs to look at this"\n'  # notify-kind-skip: fixture text, not a call
)
# Names the notifier only in PROSE -> not notify-capable, must not be flagged.
QUIET_RUNNER = (
    '#!/usr/bin/env bash\n'
    '# historical note: this used to call slack-notify.sh, it no longer does\n'
    'echo ok\n'
)

# Real suites anchor themselves with BASH_SOURCE; the fixtures must too, or
# the detector cannot place the executed path in this checkout and (correctly)
# stays quiet, which would make every positive case below vacuously green.
_ANCHOR = 'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\n'
_HEAD = _ANCHOR + 'RUNNER="$SCRIPT_DIR/../pager-runner.sh"\n'

# (case name, test-file body, target: "test"|"runner", expected exit)
CHANNEL_CASES = [
    ("unstubbed invocation",
     _HEAD + 'bash "$RUNNER" --go\n', "test", 2),
    ("per-command stub on the same line",
     _HEAD + 'KIPI_NOTIFY=/usr/bin/true bash "$RUNNER" --go\n', "test", 0),
    ("stub carried across a backslash continuation",
     _HEAD + 'env FOO=1 \\\n    KIPI_NOTIFY=/usr/bin/true \\\n'
             '    bash "$RUNNER" --go\n', "test", 0),
    # THE regression for the file-wide-stub defect. One stubbed site used to
    # suppress detection for every other site in the file; the real
    # test-severity-floor.sh had 5 stubbed and 2 unstubbed and passed.
    ("PARTIAL stub: one site covered, one not",
     _HEAD + 'KIPI_NOTIFY=/usr/bin/true bash "$RUNNER" --first\n'
             'bash "$RUNNER" --second\n', "test", 2),
    ("exported stub covers the whole file",
     'export KIPI_NOTIFY=/usr/bin/true\n' + _HEAD + 'bash "$RUNNER" --go\n',
     "test", 0),
    ("writing your own notifier into a sandbox skeleton",
     _HEAD + 'printf "exit 0\\n" > "$WORK/skel/scripts/slack-notify.sh"\n'
             'bash "$RUNNER" --go\n', "test", 0),
    ("grep-only reference is not an invocation",
     _HEAD + 'grep -q needle "$RUNNER"\n', "test", 0),
    ("bash -n is a parse, not a run",
     _HEAD + 'bash -n "$RUNNER"\n', "test", 0),
    ("bash -c handing the runner to grep is not an invocation",
     _HEAD + 'OUT="$(bash -c \'grep -c x \'"\'$RUNNER\'")"\n', "test", 0),
    ("runner that only NAMES the notifier in a comment",
     'RUNNER="$SCRIPT_DIR/../quiet-runner.sh"\nbash "$RUNNER" --go\n', "test", 0),
    ("skip marker bypasses",
     '# fable-discipline-lint-skip\n' + _HEAD + 'bash "$RUNNER" --go\n',
     "test", 0),
    # Editing the RUNNER must re-check the tests that drive it. The edited file
    # alone can never show this: the leak lives in files the edit did not touch.
    # Identity is the resolved PATH. A sandbox copy of a pager-capable runner
    # cannot page anyone, and flagging it is the false positive that gets a lint
    # switched off. test-dispatch-liveness.sh runs "$ROOT/converge.sh" from a
    # mktemp dir and was wrongly blocked.
    ("sandbox copy of the runner is not the production runner",
     _ANCHOR + 'SB="$(mktemp -d)"\nRUNNER="$SB/pager-runner.sh"\n'
               'bash "$RUNNER" --go\n', "test", 0),
    # Precision first: this lint is defence in depth behind the slack-notify.sh
    # loopback refusal, so an unplaceable path stays quiet rather than crying wolf.
    ("unplaceable path is not flagged",
     'RUNNER="$MYSTERY_DIR/pager-runner.sh"\nbash "$RUNNER" --go\n', "test", 0),
    # An exemption cannot reach backwards: the early call already ran with the
    # real notifier.
    ("a LATER export does not exempt an EARLIER invocation",
     _HEAD + 'bash "$RUNNER" --early\n'
             'export KIPI_NOTIFY=/usr/bin/true\n'
             'bash "$RUNNER" --late\n', "test", 2),
    ("editing the runner sees its unstubbed test",
     _HEAD + 'bash "$RUNNER" --go\n', "runner", 2),
    ("editing the runner is clean when its test is stubbed",
     _HEAD + 'KIPI_NOTIFY=/usr/bin/true bash "$RUNNER" --go\n', "runner", 0),
]


def run_channel_case(base, name, body, target):
    """Build <base>/scripts/{pager,quiet}-runner.sh + scripts/test/test-x.sh."""
    scripts = base / "scripts"
    tdir = scripts / "test"
    tdir.mkdir(parents=True, exist_ok=True)
    (scripts / "pager-runner.sh").write_text(PAGER_RUNNER)
    (scripts / "quiet-runner.sh").write_text(QUIET_RUNNER)
    test_file = tdir / "test-channel-case.sh"
    test_file.write_text(body)
    return run(test_file if target == "test" else scripts / "pager-runner.sh")


def run(path):
    return subprocess.run([sys.executable, LINT, str(path)],
                          capture_output=True, text=True).returncode


def main():
    failures = 0
    with tempfile.TemporaryDirectory() as d:
        base = Path(d)
        for name, content, want in CASES:
            f = base / name
            f.write_text(content)
            got = run(f)
            ok = got == want
            print(f"  [{'PASS' if ok else 'FAIL'}] {name}: exit {got} (want {want})")
            if not ok:
                failures += 1

    for name, body, target, want in CHANNEL_CASES:
        # Each case gets its OWN tree; a shared one lets a previous fixture's
        # stub file satisfy the next case and every assertion goes soft.
        with tempfile.TemporaryDirectory() as d:
            got = run_channel_case(Path(d), name, body, target)
        ok = got == want
        print(f"  [{'PASS' if ok else 'FAIL'}] channel/{target}: {name}: "
              f"exit {got} (want {want})")
        if not ok:
            failures += 1

    total = len(CASES) + len(CHANNEL_CASES)
    if failures:
        print(f"fable-discipline-lint self-test: {failures} FAILED")
        sys.exit(1)
    print(f"fable-discipline-lint self-test: all {total} cases passed")
    sys.exit(0)


if __name__ == "__main__":
    main()
