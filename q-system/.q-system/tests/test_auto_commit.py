#!/usr/bin/env python3
"""The auto-commit Stop hook (ASK-498).

The property: it is a safety net for GENERATED STATE, and it must never sweep an
instance's source tree into an unattended generic commit.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

HOOK = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))), "q-system", "hooks", "auto-commit.py")


@pytest.fixture(autouse=True)
def _isolated_notify_cache(tmp_path_factory, monkeypatch):
    """No test may touch the REAL ~/.cache/kipi notify state.

    Without this, report_skipped recorded a live digest on the first run and
    then suppressed itself on the second, so the suite went red with no code
    change. A test that writes a live data path is the exact habit the
    fable-discipline lint blocks.
    """
    monkeypatch.setenv("KIPI_CACHE_HOME",
                       str(tmp_path_factory.mktemp("cache")))


def _repo(tmp_path):
    d = tmp_path / "repo"
    d.mkdir()
    run = lambda *a: subprocess.run(a, cwd=d, capture_output=True, text=True)
    run("git", "init", "-q")
    run("git", "config", "user.email", "t@t.t")
    run("git", "config", "user.name", "t")
    (d / "seed.txt").write_text("x")
    run("git", "add", "-A")
    run("git", "commit", "-q", "-m", "seed")
    return d, run


def _write(root, rel, body="content\n"):
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body)


def _fire(root):
    return subprocess.run([sys.executable, HOOK], capture_output=True, text=True,
                          cwd=root, env=dict(os.environ, CLAUDE_PROJECT_DIR=str(root)))


def _tracked(run):
    return run("git", "ls-files").stdout.split()


def test_the_hook_exists_where_settings_points():
    """Load-path proof. The Stop hook runs $CLAUDE_PROJECT_DIR/q-system/hooks/auto-commit.py."""
    assert os.path.isfile(HOOK), HOOK


def test_source_code_is_never_swept_into_a_generic_commit(tmp_path):
    """THE case. Three real sweeps (d96e621, 7a252f4, f0a3183) took feature work
    onto main under 'chore: update project files', twice racing the agent writing it."""
    root, run = _repo(tmp_path)
    _write(root, "q-consult/pipeline/repo_links.py", "# real work\n")
    _write(root, "q-consult/tests/test_thing.py", "# a test\n")
    out = _fire(root)
    tracked = _tracked(run)
    assert "q-consult/pipeline/repo_links.py" not in tracked
    assert "q-consult/tests/test_thing.py" not in tracked
    assert "update project files" not in run("git", "log", "--oneline").stdout


def test_unclassified_files_are_reported_not_silently_left(tmp_path):
    """Silence would recreate the defect in reverse: work uncommitted, nobody told."""
    root, _run = _repo(tmp_path)
    _write(root, "q-consult/pipeline/repo_links.py")
    out = _fire(root)
    assert "NOT committed" in out.stdout
    assert "q-consult/pipeline/repo_links.py" in out.stdout


def test_the_generated_state_safety_net_still_works(tmp_path):
    """Negative control. Without this, deleting the whole hook would pass every
    test above -- proving only that nothing is committed, which is not the goal."""
    root, run = _repo(tmp_path)
    _write(root, "memory/MEMORY.md", "- note\n")
    _write(root, "q-system/canonical/decisions.md", "RULE-1\n")
    _fire(root)
    tracked = _tracked(run)
    assert "memory/MEMORY.md" in tracked
    assert "q-system/canonical/decisions.md" in tracked


def test_a_mixed_tree_commits_state_and_leaves_source(tmp_path):
    """The real-world shape: an agent mid-edit while session memory also changed."""
    root, run = _repo(tmp_path)
    _write(root, "memory/MEMORY.md", "- note\n")
    _write(root, "q-consult/pipeline/repo_links.py", "# real work\n")
    _fire(root)
    tracked = _tracked(run)
    assert "memory/MEMORY.md" in tracked
    assert "q-consult/pipeline/repo_links.py" not in tracked


def _hook_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("auto_commit", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_declared_skips_are_not_reported_as_unclassified():
    """q-system/output is gitignored on purpose; nagging about it is noise.

    Driven through `group_files` directly, not the CLI: `get_changed_files` already
    filters q-system/output before classify ever sees it, so the end-to-end route
    could never reach this branch. Mutation-caught -- routing declared skips into
    the unclassified list left the CLI test green because the path never arrived.
    """
    mod = _hook_module()
    groups, unclassified = mod.group_files({
        "q-system/output/report.json",
        "memory/MEMORY.md",
        "q-consult/pipeline/x.py",
    })
    assert unclassified == ["q-consult/pipeline/x.py"], \
        "a declared skip must not be reported as unclassified"
    assert list(groups.values()) == [["memory/MEMORY.md"]]


def test_classify_answers_the_three_cases():
    mod = _hook_module()
    assert mod.classify("memory/MEMORY.md") == ("chore", "update auto-memory")
    assert mod.classify("q-system/output/x.json") == mod.SKIP_DECLARED
    assert mod.classify("q-consult/pipeline/x.py") == mod.SKIP_UNCLASSIFIED


def test_every_auto_commit_still_declares_its_bypass(tmp_path):
    """The hook cannot know the issue, so it must keep declaring the hatch and
    stay countable in the bypass ledger."""
    root, run = _repo(tmp_path)
    _write(root, "memory/MEMORY.md", "- note\n")
    _fire(root)
    body = run("git", "log", "-1", "--format=%B").stdout
    assert "[no-issue:" in body


def test_the_hook_never_raises_into_session_exit(tmp_path):
    """It is a Stop hook. A crash here must not cost the session."""
    out = subprocess.run([sys.executable, HOOK], capture_output=True, text=True,
                         cwd=str(tmp_path),
                         env=dict(os.environ, CLAUDE_PROJECT_DIR="/nonexistent/nope"))
    assert out.returncode == 0


# --- adversarial review findings (2026-08-07) -------------------------------------

def test_a_pre_staged_unclassified_file_is_not_swept_in(tmp_path):
    """finding-1, CRITICAL. `git commit -m` with no pathspec commits the WHOLE INDEX.

    An agent that ran `git add` and had not yet committed had its file swept into the
    auto-commit anyway -- while the report printed that the file was NOT committed. A
    false report is worse than the silence it replaced: it tells the next session the
    file is still theirs. This is also the exact race the original incidents describe.
    """
    root, run = _repo(tmp_path)
    _write(root, "q-consult/pipeline/repo_links.py", "# real work\n")
    _write(root, "memory/MEMORY.md", "- note\n")
    run("git", "add", "q-consult/pipeline/repo_links.py")   # staged, not committed
    out = _fire(root)
    # `git ls-files` reads the INDEX, and this test staged the file itself, so it is
    # listed either way. The question is what landed in the COMMIT.
    committed = run("git", "show", "--name-only", "--format=", "HEAD").stdout.split()
    assert "q-consult/pipeline/repo_links.py" not in committed, \
        "a pre-staged source file was swept into the auto-commit"
    assert "memory/MEMORY.md" in committed
    assert "NOT committed" in out.stdout
    # The report must not be able to lie: what it says was skipped really was skipped.
    for line in out.stdout.splitlines():
        if line.strip().startswith("- "):
            assert line.strip()[2:] not in committed, f"report lied about {line!r}"


def test_instance_content_directories_are_committed(tmp_path):
    """finding-2, CRITICAL. AREA_MAP only described the SKELETON (q-system/...).

    An instance keeps its real content one segment over. Measured on the consulting
    instance before the fix: 1047 of 2099 tracked files unclassified, including
    my-project (the system of record), canonical and marketing. Dropping the fallback
    without this disabled the net for exactly what it exists to protect.
    """
    root, run = _repo(tmp_path)
    for rel in ("q-consult/canonical/decisions.md",
                "q-consult/my-project/clients.json",
                "q-consult/marketing/content-themes.md",
                "q-consult/memory/last-handoff.md"):
        _write(root, rel)
    _fire(root)
    tracked = _tracked(run)
    for rel in ("q-consult/canonical/decisions.md",
                "q-consult/my-project/clients.json",
                "q-consult/marketing/content-themes.md",
                "q-consult/memory/last-handoff.md"):
        assert rel in tracked, f"{rel} is instance generated state and was not committed"


def test_instance_source_and_output_are_still_not_committed(tmp_path):
    """The negative half of finding-2. Widening coverage must not swallow code.

    Without this, INSTANCE_AREAS could be broadened to `("", ...)` and the test above
    would pass while the original defect returned.
    """
    root, run = _repo(tmp_path)
    _write(root, "q-consult/pipeline/cycle.py", "# code\n")
    _write(root, "q-consult/email-watch/ledger.py", "# code\n")
    _write(root, "q-consult/output/report.json", "{}\n")
    out = _fire(root)
    tracked = _tracked(run)
    assert "q-consult/pipeline/cycle.py" not in tracked
    assert "q-consult/email-watch/ledger.py" not in tracked
    assert "q-consult/output/report.json" not in tracked
    assert "q-consult/output/report.json" not in out.stdout, \
        "generated churn is a declared skip, not a nag"


def test_classify_covers_skeleton_and_instance_alike():
    mod = _hook_module()
    assert mod.classify("q-system/canonical/x.md") == ("content", "update canonical files")
    assert mod.classify("q-consult/canonical/x.md") == ("content", "update canonical files")
    assert mod.classify("q-thaena/my-project/x.json") == ("content", "update project state")
    assert mod.classify("q-consult/output/x.json") == mod.SKIP_DECLARED
    assert mod.classify("q-consult/pipeline/x.py") == mod.SKIP_UNCLASSIFIED


def test_the_hook_never_alerts_at_all(tmp_path, monkeypatch):
    """THE INVARIANT, founder-directed 2026-08-10: this hook alerts nobody.

    It used to shell out to slack-notify.sh, throttled by a digest of the file
    set (ASK-603). The throttle could not work: during active work the file set
    changes nearly every turn, so the digest changes nearly every turn, so it
    spoke nearly every turn. 51 of 100 #general messages in one 4.5-hour window
    were this hook, burying four security reverts and a dead job.

    A subprocess spawn of ANY kind from report_skipped is the regression, which
    is why this asserts on subprocess.run rather than on the word "slack" -- the
    fleet alert path was renamed once already and a string check would have
    missed it."""
    mod = _hook_module()
    calls = []
    monkeypatch.setattr(mod.os.path, "isfile", lambda p: True)
    monkeypatch.setattr(mod.subprocess, "run",
                        lambda *a, **k: calls.append(a[0]) or None)
    mod.report_skipped(["q-consult/pipeline/x.py"])
    assert not calls, f"report_skipped spawned a process: {calls}"


def test_the_skipped_files_are_still_named_on_the_transcript(tmp_path, capsys):
    """Not alerting is not the same as staying silent. Removing the ping must
    not also remove the record -- that would recreate the original defect in
    reverse, work sitting uncommitted with nobody told anywhere."""
    mod = _hook_module()
    mod.report_skipped(["q-consult/pipeline/x.py"])
    out = capsys.readouterr().out
    assert "q-consult/pipeline/x.py" in out
    assert "NOT committed" in out


def test_report_skipped_never_raises_into_session_exit(tmp_path):
    mod = _hook_module()
    mod.PROJ_DIR = str(tmp_path)
    mod.report_skipped(["a/b.py"])        # must not raise
    mod.report_skipped([])                # nor on the empty case



# The module handle the classifier suites below use. It lived under the
# ASK-603 throttle heading until that throttle was deleted (2026-08-10); the
# tests that used it did not go away with it, so the loader moved here rather
# than out.
import importlib.util  # noqa: E402
import json  # noqa: E402

_spec = importlib.util.spec_from_file_location("auto_commit", HOOK)
auto_commit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(auto_commit)


class TestTheFleetSyncSharesThisClassifier:
    """ASK-605. kipi-update.sh carried its own 3-entry SYSTEM_OWNED_PATHS list
    meaning exactly what classify() means: "system exhaust, safe to commit
    unattended". They disagreed, and the disagreement had teeth --
    q-system/memory/open-loops.json is written by a background heartbeat, is
    `chore` here, was absent there, and blocked 4 of 7 instances from ever
    syncing. One concept must have one list.
    """

    def test_the_file_that_blocked_four_instances_is_system_state(self):
        assert auto_commit.system_state_paths(
            ["q-system/memory/open-loops.json"]) == \
            ["q-system/memory/open-loops.json"]

    def test_the_integrity_baseline_is_system_state(self):
        assert auto_commit.system_state_paths(
            ["q-system/.q-system/claude-integrity-baseline.json"])

    def test_founder_content_is_never_system_state(self):
        """NARROWER than classify() on purpose. An unattended fleet-wide sweep
        of a half-finished canonical edit is a second writer to his branch."""
        for p in ["q-system/canonical/decisions.md",
                  "q-system/my-project/current-state.md",
                  "q-system/marketing/brand-voice.md",
                  "plugins/kipi-core/skills/founder-voice/SKILL.md"]:
            assert auto_commit.system_state_paths([p]) == [], p

    def test_work_product_is_never_system_state(self):
        """The 162 files the old sweeper took from Alice."""
        for p in ["q-investigate/investigations/case-001/evidence/capture.pdf",
                  "q-investigate/.../generators/fill_sheet.py",
                  "output/opportunities/opps-2026-08-01.md",
                  "q-pure/output/drafts/2026-08-10-sushma.md",
                  "projects/2026_QEP_Agent_Automation/progress.md"]:
            assert auto_commit.system_state_paths([p]) == [], p

    def test_it_filters_a_mixed_list_rather_than_all_or_nothing(self):
        mixed = ["q-system/memory/open-loops.json",
                 "q-investigate/evidence/capture.pdf",
                 "q-system/canonical/decisions.md"]
        assert auto_commit.system_state_paths(mixed) == \
            ["q-system/memory/open-loops.json"]

    def test_the_cli_mode_reads_stdin_and_prints_only_system_state(self):
        """kipi-update.sh shells this; the contract is the stdout list."""
        import subprocess as sp
        r = sp.run([sys.executable, HOOK, "--system-state"], text=True,
                   capture_output=True,
                   input="q-system/memory/open-loops.json\n"
                         "q-investigate/evidence/capture.pdf\n")
        assert r.returncode == 0
        assert r.stdout.split() == ["q-system/memory/open-loops.json"]


class TestDeclaredSkipMustActuallyBeIgnored:
    """ASK-605 cause 2. AREA_MAP carries q-system/output/ as
    `(None, None)  # skip - gitignored`. The .gitignore only ignores that
    directory BY EXTENSION (*.html, *.json, *.log) -- never *.md. So
    q-system/output/*.md is not committed, not ignored, and not even REPORTED
    (SKIP_DECLARED is silent). It blocks the fleet sync invisibly. cole-gtm sat
    stuck on exactly two such files.
    """

    def test_the_prd_os_ledger_is_system_state(self):
        """.prd-os/spillover.jsonl is an append-only ledger the system writes.
        It was unclassified, so it blocked cole-gtm's sync with no way out."""
        assert auto_commit.system_state_paths([".prd-os/spillover.jsonl"]) == \
            [".prd-os/spillover.jsonl"]

    def test_every_declared_skip_prefix_is_actually_gitignored(self):
        """The claim in the comment must be true, or the path blocks silently.

        Reads the real .gitignore rather than trusting the comment. This is the
        check that would have caught cole-gtm before a human did.
        """
        root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))))
        for prefix, commit_type, _ in auto_commit.AREA_MAP:
            if commit_type is not None:
                continue
            # Ask git, do not pattern-match the .gitignore by hand. The first
            # version of this test did the latter, and it PASSED against the
            # exact repo whose cole-gtm blockers proved it false.
            for ext in (".md", ".txt", ".yaml", ""):
                probe = f"{prefix}probe-does-not-exist{ext}"
                r = subprocess.run(["git", "check-ignore", "-q", probe],
                                   cwd=root, capture_output=True)
                assert r.returncode == 0, (
                    f"{probe} is NOT gitignored, yet {prefix} is declared "
                    f"skip-because-gitignored in AREA_MAP. Such a file is "
                    f"never committed, never ignored and never reported -- it "
                    f"blocks the fleet sync invisibly, which is what left "
                    f"cole-gtm stuck on two .md files.")


class TestTheNeverList:
    """sp-a21cb27c, caught before it shipped. Classifying `.prd-os/` as chore
    (ASK-605, to unblock cole-gtm's dirty spillover.jsonl) also made the
    ephemeral `.jsonl.lock` and the AUTHORED issue specs auto-committable. A
    prefix is a blunt instrument; these are the exceptions, checked first.
    """

    def test_the_ledger_is_still_taken(self):
        assert auto_commit.system_state_paths([".prd-os/spillover.jsonl"])

    def test_a_lock_file_is_never_taken(self):
        assert auto_commit.system_state_paths([".prd-os/spillover.jsonl.lock"]) == []
        assert auto_commit.classify(".prd-os/spillover.jsonl.lock") == \
            auto_commit.SKIP_UNCLASSIFIED

    def test_authored_prd_os_content_is_never_taken(self):
        for p in (".prd-os/issues/ath-durable-recovery.md",
                  ".prd-os/findings/some-review.json"):
            assert auto_commit.system_state_paths([p]) == [], p

    def test_a_lock_anywhere_is_never_taken(self):
        """Not a .prd-os special case: a lock is a race wherever it lives."""
        assert auto_commit.system_state_paths(
            ["q-system/memory/open-loops.json.lock"]) == []


class TestExecutableSourceIsNeverSwept:
    """ASK-498 removed the generic fallback but scoped the fix by DIRECTORY, and two
    AREA_MAP rows are named for directories that hold Python: `plugins/` (kipi-core is
    a package) and `q-system/.q-system/` (holds scripts/).

    Measured 2026-08-13 in one session on this fleet: `test_length_axis.py` was
    committed as "feat: update plugins" and `voice-dna-loader.py` as "chore: update
    system infrastructure", both while an agent was still editing them and before it
    could write a message carrying a Linear id.
    """

    SWEPT_ON_2026_08_13 = (
        "plugins/kipi-core/voiceloop/tests/test_length_axis.py",
        "q-system/.q-system/scripts/voice-dna-loader.py",
    )

    def test_the_two_files_actually_swept_are_now_reported(self):
        for p in self.SWEPT_ON_2026_08_13:
            assert auto_commit.classify(p) == auto_commit.SKIP_UNCLASSIFIED, p
            assert auto_commit.system_state_paths([p]) == [], p

    def test_source_is_refused_in_every_area(self):
        for p in ("plugins/kipi-core/voiceloop/selector.py",
                  "q-system/hooks/auto-commit.py",
                  "q-system/.q-system/agent-pipeline/runner.py",
                  "q-system/canonical/helper.py",
                  "scripts/voice_ref.py",
                  "sites/build.mjs",
                  "q-system/marketing/gen.sh"):
            assert auto_commit.classify(p) == auto_commit.SKIP_UNCLASSIFIED, p

    def test_the_generated_state_safety_net_still_commits(self):
        """Removing the sweep must not disable the net it was built for."""
        for p in ("q-system/canonical/voice-sources.md",
                  "q-system/memory/last-handoff.md",
                  "q-system/marketing/brand-voice.md",
                  ".prd-os/spillover.jsonl"):
            assert not isinstance(auto_commit.classify(p), str), p

    def test_a_plugin_manifest_is_not_source(self):
        """plugin.json must still be taken: the version-bump gate refuses a plugin
        commit until it is bumped, so refusing it here would deadlock that gate."""
        r = auto_commit.classify("plugins/kipi-core/.claude-plugin/plugin.json")
        assert not isinstance(r, str), r


# --- the commit message must say what changed, not just where (2026-08-16) ----
#
# THE INCIDENT. Commit 80b82f84 on kipi-system read:
#
#     chore: update system infrastructure
#     - q-system/.q-system/capability-manifest.json
#
# and silently reverted five lines of a real capability-manifest entry. The
# path was ALREADY in the message; naming files was never the gap. Direction and
# magnitude were, so a deletion was indistinguishable from an update and a
# second session had to diff the commit by hand to find it. These cases pin the
# half that was missing, and `test_an_addition_is_not_labelled_a_deletion` is
# the discrimination control -- without it, a hook that stamped
# "DELETIONS ONLY" on every commit would pass the reproducer.


def _last_msg(run):
    return run("git", "log", "-1", "--format=%B").stdout


def _seed_tracked(root, run, rel, body):
    """A file that EXISTS AT HEAD, so the next write is a real diff and not an
    add. The incident was an edit to a long-tracked file; an untracked file
    would only ever produce insertions and could not reproduce it."""
    _write(root, rel, body)
    run("git", "add", "--", rel)
    run("git", "commit", "-q", "-m", "seed " + rel)


MANIFEST = "q-system/.q-system/capability-manifest.json"


def test_a_pure_deletion_is_named_as_a_deletion(tmp_path):
    """The 80b82f84 reproducer: five lines removed, nothing added."""
    root, run = _repo(tmp_path)
    _seed_tracked(root, run, MANIFEST,
                  "".join(f"line-{n}\n" for n in range(8)))
    (root / MANIFEST).write_text("".join(f"line-{n}\n" for n in range(3)))
    _fire(root)
    msg = _last_msg(run)
    assert MANIFEST in msg, f"the changed path left the message entirely\n{msg}"
    assert "+0/-5" in msg, (
        "the message did not carry the line counts, so a 5-line revert still "
        f"reads exactly like an ordinary update\n{msg}")
    assert "DELETIONS ONLY" in msg, (
        f"a pure deletion was not called out in words\n{msg}")


def test_an_addition_is_not_labelled_a_deletion(tmp_path):
    """DISCRIMINATION CONTROL. A hook that always stamped the deletion marker
    would pass the reproducer above and be worthless. This is the case that
    must stay quiet."""
    root, run = _repo(tmp_path)
    _seed_tracked(root, run, MANIFEST, "line-0\n")
    (root / MANIFEST).write_text("".join(f"line-{n}\n" for n in range(6)))
    _fire(root)
    msg = _last_msg(run)
    assert "+5/-0" in msg, f"insertions were not counted\n{msg}"
    assert "DELETIONS ONLY" not in msg, (
        f"a pure ADDITION was labelled a deletion\n{msg}")


def test_a_mixed_edit_reports_both_directions(tmp_path):
    root, run = _repo(tmp_path)
    _seed_tracked(root, run, MANIFEST, "a\nb\nc\n")
    (root / MANIFEST).write_text("a\nCHANGED\nc\n")
    _fire(root)
    msg = _last_msg(run)
    assert "+1/-1" in msg, f"a mixed edit lost its counts\n{msg}"
    assert "DELETIONS ONLY" not in msg, (
        f"an edit that also added lines was labelled a pure deletion\n{msg}")


def test_the_subject_line_carries_the_stat(tmp_path):
    """`git log --oneline` shows the SUBJECT and nothing else. That is where the
    80b82f84 review actually happened, so the body alone does not close it."""
    root, run = _repo(tmp_path)
    _seed_tracked(root, run, MANIFEST, "".join(f"l{n}\n" for n in range(6)))
    (root / MANIFEST).write_text("l0\n")
    _fire(root)
    subject = run("git", "log", "-1", "--format=%s").stdout.strip()
    assert "+0/-5" in subject, (
        f"the one-line log still hides the direction of the change\n{subject}")


def test_a_binary_file_degrades_instead_of_crashing(tmp_path):
    """git reports `-` for binary line counts. The hook must still commit."""
    root, run = _repo(tmp_path)
    rel = "q-system/.q-system/blob.bin"
    _write(root, rel, "seed\n")
    run("git", "add", "--", rel)
    run("git", "commit", "-q", "-m", "seed blob")
    (root / rel).write_bytes(b"\x00\x01\x02binary\xff")
    _fire(root)
    msg = _last_msg(run)
    assert rel in msg, f"the binary file was dropped from the message\n{msg}"
    assert "binary" in msg, f"the binary file was not marked as such\n{msg}"


# --- the third writer (2026-09-06) -------------------------------------------------
# fleet_update_in_progress coordinates with the one writer that leaves a marker. This
# hook was the writer nobody could negotiate with: it fires at every turn end in every
# session on a shared checkout and took no lock at all. Measured in one session that
# night, three of five git operations died on "Unable to create .git/index.lock" and
# every one of them EXITED 0.

def test_it_refuses_while_another_commit_holds_index_lock(tmp_path):
    """sp-4bff1b91. A commit in flight owns index.lock for its whole pre-commit,
    measured at 447-497s on the consulting checkout. Firing into that either dies at
    exit 0 or lands a commit nobody asked for."""
    root, run = _repo(tmp_path)
    _write(root, "memory/MEMORY.md", "- note\n")
    lock = os.path.join(root, ".git", "index.lock")
    with open(lock, "w", encoding="utf-8") as fh:
        fh.write("")
    try:
        out = _fire(root)
    finally:
        os.remove(lock)
    assert "another commit is in flight" in (out.stdout + out.stderr), \
        "the hook fired into a held index.lock instead of refusing"
    log = run("git", "log", "--oneline").stdout
    assert "chore" not in log, "it committed while another writer held the lock"


def test_it_refuses_on_head_lock_too(tmp_path):
    """HEAD.lock is a SEPARATE door, and this docstring named the wrong reason
    for it. It said the ref lock killed the prd-os ledger sweep mid pre-commit
    (sp-d0ce1966). Review round 2 measured that a commit on an attached branch
    produces index.lock and `refs/heads/<branch>.lock` and NEVER HEAD.lock, and
    an independent watch agrees: only index.lock appears through a slow
    pre-commit. The check still earns its place -- HEAD.lock has real producers
    (checkout, reset, merge, alongside the AUTO_MERGE / ORIG_HEAD / packed-refs
    family) and dropping it reddens this test. What it does NOT cover is
    `refs/heads/<branch>.lock`, which a commit really does take; that window is
    sub-second and index.lock spans it, so it is deliberately not checked."""
    root, run = _repo(tmp_path)
    _write(root, "memory/MEMORY.md", "- note\n")
    lock = os.path.join(root, ".git", "HEAD.lock")
    with open(lock, "w", encoding="utf-8") as fh:
        fh.write("")
    try:
        out = _fire(root)
    finally:
        os.remove(lock)
    assert "another commit is in flight" in (out.stdout + out.stderr)


def test_it_does_not_delete_the_lock_it_refuses_on(tmp_path):
    """THE CONTROL THAT MATTERS MOST. kipi-update.sh:1714 force-deletes these locks
    with no pid, mtime or age test (sp-50119dec). Removing a lock that a live
    8-minute pre-commit still owns corrupts that commit's index. Refusing is the
    whole fix; deleting would be a worse bug wearing the same commit message."""
    root, _ = _repo(tmp_path)
    _write(root, "memory/MEMORY.md", "- note\n")
    lock = os.path.join(root, ".git", "index.lock")
    with open(lock, "w", encoding="utf-8") as fh:
        fh.write("sentinel")
    try:
        _fire(root)
        assert os.path.exists(lock), "the hook DELETED a lock it does not own"
        with open(lock, encoding="utf-8") as fh:
            assert fh.read() == "sentinel", "the hook rewrote a lock it does not own"
    finally:
        if os.path.exists(lock):
            os.remove(lock)


def test_it_still_commits_when_no_lock_is_held(tmp_path):
    """The negative control. A guard that refuses always is not a guard, it is an
    outage: the safety net exists so work survives a context loss."""
    root, run = _repo(tmp_path)
    _write(root, "memory/MEMORY.md", "- note\n")
    _fire(root)
    log = run("git", "log", "--oneline").stdout
    assert "chore" in log, "the hook refused with no lock held, so it never commits"


def _worktree(tmp_path):
    """A linked worktree of a fresh repo, plus its main checkout.

    Returns (main_root, wt_root, main_git_dir, wt_git_dir).
    """
    main, run = _repo(tmp_path)
    wt = tmp_path / "wt"
    run("git", "branch", "-q", "side")
    run("git", "worktree", "add", "-q", str(wt), "side")
    main_git = main / ".git"
    wt_git = main_git / "worktrees" / "wt"
    assert wt_git.is_dir(), f"the worktree fixture never linked: {wt_git}"
    return main, wt, main_git, wt_git


def test_a_worktree_does_not_refuse_on_the_main_checkouts_lock(tmp_path):
    """THE MUTANT THIS EXISTS FOR: --git-common-dir in place of --git-dir.

    It survives every other test in this file, because a plain repo's git dir IS
    its common dir, so the two spellings are indistinguishable there. They are not
    indistinguishable on this checkout, which carries a dozen linked worktrees.

    MEASURED 2026-09-07, not reasoned: index.lock and HEAD.lock are PER-WORKTREE.
    Holding `<main>/.git/index.lock` does not block a `git add` run from a linked
    worktree (rc=0), and holding `<main>/.git/worktrees/<n>/index.lock` does not
    block one run from the main checkout (rc=0). Only the worktree's own lock
    stops it (rc=128, "Unable to create ... index.lock"). So `--git-dir`, which
    answers the per-worktree dir, names exactly the lock that can stop THIS
    checkout, and `--git-common-dir` names one that cannot.

    The cost of getting it wrong is quiet and fleet-wide: a commit in the main
    checkout holds index.lock for its whole pre-commit (445-497s measured), so a
    common-dir read would silence the safety net in every linked worktree for
    eight minutes at a time, for a lock none of them was ever going to contend.
    Note that fleet_update_in_progress deliberately reads the OPPOSITE dir, and
    is right to: a run marker is a claim on the whole checkout, a lock is not.
    """
    _main, wt, main_git, _wt_git = _worktree(tmp_path)
    _write(wt, "memory/MEMORY.md", "- note\n")
    lock = main_git / "index.lock"
    lock.write_text("held by the main checkout")
    try:
        _fire(wt)
    finally:
        lock.unlink()
    log = subprocess.run(["git", "log", "--oneline"], cwd=wt,
                         capture_output=True, text=True).stdout
    assert "chore" in log, (
        "the worktree refused on a lock in the MAIN checkout's git dir, which "
        "cannot block it. The guard is reading --git-common-dir, not --git-dir.")


def test_a_worktree_still_refuses_on_its_own_lock(tmp_path):
    """The other direction, so the test above cannot be satisfied by never
    refusing at all. The per-worktree lock is the one that stops this checkout."""
    _main, wt, _main_git, wt_git = _worktree(tmp_path)
    _write(wt, "memory/MEMORY.md", "- note\n")
    lock = wt_git / "index.lock"
    lock.write_text("held by this worktree")
    try:
        out = _fire(wt)
    finally:
        lock.unlink()
    assert "another commit is in flight" in (out.stdout + out.stderr), \
        "a worktree fired into its OWN held index.lock instead of refusing"
    log = subprocess.run(["git", "log", "--oneline"], cwd=wt,
                         capture_output=True, text=True).stdout
    assert "chore" not in log, "it committed while holding its own lock"


def test_the_lock_dir_resolves_against_PROJ_DIR_not_the_process_cwd(tmp_path):
    """PR #321 review, minor. The SAME defect PR #314 round 2 fixed one guard up.

    `git rev-parse --git-dir` answers RELATIVE to the cwd it ran in, and run()
    executes in PROJ_DIR (CLAUDE_PROJECT_DIR), which is not this process's cwd.
    Resolving the answer against os.getcwd() points at a path that does not exist
    whenever the two differ, no lock is ever found, and the guard FAILS OPEN into
    the exact pre-guard behaviour it was built to remove.

    fleet_update_in_progress carries that scar in its own comment and IS pinned,
    but in a DIFFERENT FILE this suite does not run:
    q-system/hooks/test/test_auto_commit_run_marker.py::
    test_live_marker_is_seen_when_cwd_is_not_the_project_dir. An earlier draft of
    this docstring said it had no test either; that was wrong, and missing that
    second file is also how a channel change here shipped past a green run of
    this suite and reddened CI. Every other test in THIS file fires with
    cwd == PROJ_DIR, so
    `os.path.abspath(git_dir)` in place of `os.path.abspath(join(PROJ_DIR, ...))`
    passed all 43 of them. This is the one that can tell them apart.
    """
    root, run = _repo(tmp_path)
    _write(root, "memory/MEMORY.md", "- note\n")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    assert not (elsewhere / ".git").exists(), "the fixture must not be a repo"
    lock = root / ".git" / "index.lock"
    lock.write_text("held")
    try:
        out = subprocess.run(
            [sys.executable, HOOK], capture_output=True, text=True,
            cwd=str(elsewhere),
            env=dict(os.environ, CLAUDE_PROJECT_DIR=str(root)))
    finally:
        lock.unlink()
    assert "another commit is in flight" in (out.stdout + out.stderr), (
        "with cwd outside PROJ_DIR the guard did not see PROJ_DIR's held lock. "
        "The git-dir answer is being resolved against the process cwd.")
    assert "chore" not in run("git", "log", "--oneline").stdout, \
        "it committed while a lock was held in PROJ_DIR's git dir"



def test_a_refusal_reaches_the_channel_the_fleet_wiring_keeps(tmp_path):
    """REVIEW ROUND 2, MAJOR. The refusal was on stderr, which is thrown away.

    settings-template.json wires this hook as `... auto-commit.py 2>/dev/null ||
    true` (line 395), and that is the copy the fleet updater installs on
    every instance. The behaviour the lock guard replaced reported a collision on
    STDOUT via commit_group's `skipped:` line, which survived that redirect. A
    stderr-only refusal does not: an orphaned index.lock, which has no age bound
    by design, would switch the safety net off on that checkout forever and print
    nothing anywhere a human looks.

    So this asserts the CHANNEL, not the wording. It fires the hook exactly the
    way the fleet does, with stderr discarded, and fails if the reason vanishes.
    """
    root, _run = _repo(tmp_path)
    _write(root, "memory/MEMORY.md", "- note\n")
    lock = root / ".git" / "index.lock"
    lock.write_text("held")
    try:
        out = subprocess.run(
            [sys.executable, HOOK], capture_output=True, text=True, cwd=str(root),
            env=dict(os.environ, CLAUDE_PROJECT_DIR=str(root)))
    finally:
        lock.unlink()
    assert "another commit is in flight" in out.stdout, (
        "the refusal did not reach STDOUT, so `2>/dev/null` in the shipped hook "
        "wiring discards it and the safety net goes off in total silence.\n"
        f"stdout={out.stdout!r}\nstderr={out.stderr!r}")


def test_the_fleet_update_refusal_reaches_stdout_too(tmp_path):
    """The sibling guard, hardened in the same breath. It had the identical
    stderr-only shape and the identical consequence, and fixing one of two
    guards that fail the same way is how this class comes back."""
    root, _run = _repo(tmp_path)
    _write(root, "memory/MEMORY.md", "- note\n")
    marker = root / ".git" / "kipi-update.run"
    marker.write_text(f"{os.getpid()} {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}")
    try:
        out = subprocess.run(
            [sys.executable, HOOK], capture_output=True, text=True, cwd=str(root),
            env=dict(os.environ, CLAUDE_PROJECT_DIR=str(root)))
    finally:
        marker.unlink()
    assert "fleet updater run in progress" in out.stdout, (
        "the fleet-updater refusal did not reach STDOUT.\n"
        f"stdout={out.stdout!r}\nstderr={out.stderr!r}")
