#!/usr/bin/env python3
"""auto-commit.py never commits a .claude/ deletion, and its commits pass the issue gate.

THE SCAR (ASK-4386, measured 2026-11-10). rule_gate's baseline defect (ASK-4283)
deleted tracked rule files in two unattended worker trees. Each agent left the
deletions UNSTAGED on purpose. The Stop hook staged and committed them anyway:
`70163e63 chore: update rules` on sana/ask-4309 (13 files, -613) and
`f31929ab chore: update rules` on 4 Points sana/case-051-session (-533). A whole
case session then ran without q-investigation.md and evidence-capture-protocol.md.
Those commits carried `[no-issue: auto-commit safety net ...]`, so the linear-first
commit-msg gate waved them through on a branch cut for a named issue.

Pinned here, in throwaway repos with the REAL gate installed as commit-msg:
  * a deletion or line loss of a tracked .claude/ path is held, staged or not;
  * the hook's other work still commits (the safety net is not switched off);
  * a pure .claude/ addition still commits, and a deliberate agent commit of a
    .claude/ deletion still lands (negative self-test: .claude/ is not frozen);
  * on a branch named for an issue, the hook's commit names that issue, and the
    gate refuses a [no-issue:] bypass there.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "..", "auto-commit.py")
GATE = os.path.join(HERE, "..", "..", ".q-system", "scripts", "linear-issue-ref-check.py")


def git(repo, *args, env=None):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True,
                          check=False, env=env)


class Scratch(unittest.TestCase):
    branch = "main"

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="auto-commit-claude-del-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = os.path.join(self.tmp, "repo")
        self.ledger = os.path.join(self.tmp, "bypass.jsonl")
        os.makedirs(self.repo)
        git(self.repo, "init", "-q", "-b", self.branch)
        for k, v in (("user.email", "t@t.t"), ("user.name", "test"),
                     ("commit.gpgsign", "false")):
            git(self.repo, "config", k, v)
        # The real gate, not a copy of its logic. A local hooksPath so no global
        # hook manager decides what this fixture measures.
        hooks = os.path.join(self.tmp, "hooks")
        os.makedirs(hooks)
        with open(os.path.join(hooks, "commit-msg"), "w") as fh:
            fh.write(f'#!/bin/sh\nexec "{sys.executable}" "{GATE}" "$1"\n')
        os.chmod(os.path.join(hooks, "commit-msg"), 0o755)
        git(self.repo, "config", "core.hooksPath", hooks)
        self.env = {k: v for k, v in os.environ.items() if k != "CLAUDE_CODE_REMOTE"}
        self.env.update(CLAUDE_PROJECT_DIR=self.repo, KIPI_LINEAR_TEAM="ASK",
                        LINEAR_BYPASS_LEDGER=self.ledger, KIPI_NOTIFY="/usr/bin/true")
        self.write(".claude/rules/keep.md", "rule one\nrule two\nrule three\n")
        self.write(".claude/rules/other.md", "a\nb\nc\n")
        self.write("q-system/memory/notes.md", "base\n")
        git(self.repo, "add", "-A")
        r = git(self.repo, "commit", "-q", "-m", "base (ASK-1)", env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.base = self.head()

    def write(self, rel, text):
        path = os.path.join(self.repo, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(text)

    def head(self):
        return git(self.repo, "rev-parse", "HEAD").stdout.strip()

    def at_head(self, rel):
        return git(self.repo, "show", f"HEAD:{rel}").stdout

    def run_hook(self):
        r = subprocess.run([sys.executable, HOOK], cwd=self.repo, env=self.env,
                           capture_output=True, text=True, check=False)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def new_messages(self):
        return git(self.repo, "log", "--format=%B%x00", f"{self.base}..HEAD").stdout


class ClaudeDeletionsAreHeld(Scratch):
    def test_unstaged_rule_deletion_is_never_committed(self):
        os.remove(os.path.join(self.repo, ".claude/rules/keep.md"))
        self.write("q-system/memory/notes.md", "base\nmore\n")
        out = self.run_hook().stdout
        self.assertEqual(self.at_head(".claude/rules/keep.md"),
                         "rule one\nrule two\nrule three\n",
                         "the hook committed a .claude/ deletion:\n" + out)
        # The deletion is never STAGED by the hook. It is also no longer LEFT on
        # disk: round 2's major was that holding the commit left the rule file
        # missing, so StopHookRestoresWhatHoldsNoWork owns where it goes now. What
        # must never appear here is a staged deletion the next commit would take.
        staged = git(self.repo, "diff", "--cached", "--name-status", "--", ".claude").stdout
        self.assertNotIn("D\t.claude/rules/keep.md", staged, "the deletion was staged")
        # Control: the safety net still commits the rest.
        self.assertEqual(self.at_head("q-system/memory/notes.md"), "base\nmore\n", out)

    def test_staged_rule_deletion_is_never_committed(self):
        # The agent staged the deletion itself. The hook still does not commit it,
        # and (round 2's major) does not leave the file gone either: a path absent
        # from disk holds no work, so it comes back from HEAD and is unstaged.
        git(self.repo, "rm", "-q", ".claude/rules/keep.md")
        self.run_hook()
        self.assertIn("rule one", self.at_head(".claude/rules/keep.md"))
        staged = git(self.repo, "diff", "--cached", "--name-status", "--", ".claude").stdout
        self.assertNotIn("D\t.claude/rules/keep.md", staged,
                         "a staged .claude/ deletion survived into the index")

    def test_rule_line_loss_is_held(self):
        # rule_gate's section revert shape: the file stays, lines go.
        self.write(".claude/rules/other.md", "a\n")
        self.run_hook()
        self.assertEqual(self.at_head(".claude/rules/other.md"), "a\nb\nc\n")

    def test_negative_self_test_claude_is_not_frozen(self):
        # A pure addition under .claude/ still auto-commits.
        self.write(".claude/rules/new.md", "fresh\n")
        self.write(".claude/rules/other.md", "a\nb\nc\nd\n")
        self.run_hook()
        self.assertEqual(self.at_head(".claude/rules/new.md"), "fresh\n")
        self.assertEqual(self.at_head(".claude/rules/other.md"), "a\nb\nc\nd\n")
        # A deliberate agent commit of a .claude/ deletion (the step after
        # apply-claude-changes.sh writes the tree) still lands through the gate.
        git(self.repo, "rm", "-q", ".claude/rules/keep.md")
        r = git(self.repo, "commit", "-q", "-m", "remove keep rule (ASK-7)", env=self.env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("keep.md", git(self.repo, "ls-files").stdout)


class RenamesNeverHalfCommit(Scratch):
    """PR #738 round 1 (major): the delete half was held, the add half landed, and
    HEAD carried both names, which kipi update then fans out."""

    def assert_one_name_at_head(self, out):
        names = git(self.repo, "ls-tree", "-r", "--name-only", "HEAD").stdout.split()
        self.assertIn(".claude/rules/keep.md", names, out)
        self.assertNotIn(".claude/rules/renamed.md", names,
                         "the rename's add half committed beside its held delete:\n" + out)

    def test_unstaged_rename_commits_neither_half(self):
        os.rename(os.path.join(self.repo, ".claude/rules/keep.md"),
                  os.path.join(self.repo, ".claude/rules/renamed.md"))
        self.assert_one_name_at_head(self.run_hook().stdout)

    def test_staged_rename_commits_neither_half(self):
        git(self.repo, "mv", ".claude/rules/keep.md", ".claude/rules/renamed.md")
        self.assert_one_name_at_head(self.run_hook().stdout)


class SystemStateRestoresHeldLosses(Scratch):
    """PR #738 round 1 (blocking major): a held loss dropped from --system-state
    stayed dirty inside the updater's own guard scope, so kipi update abandoned
    that instance on every run. HEAD is the truth there: put it back."""

    def setUp(self):
        super().setUp()
        self.held_dir = os.path.join(self.tmp, "held-claude")
        self.env["KIPI_AUTOCOMMIT_HELD_DIR"] = self.held_dir

    def system_state(self):
        # The updater's exact feed: `git status --porcelain -uall | cut -c4-`.
        st = git(self.repo, "status", "--porcelain", "-uall").stdout
        feed = "".join(ln[3:] + "\n" for ln in st.splitlines())
        r = subprocess.run([sys.executable, HOOK, "--system-state"], cwd=self.repo,
                           env=self.env, input=feed, capture_output=True, text=True,
                           check=False)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.split("\n"), r.stderr

    def assert_guard_clean(self, err):
        # kipi-update.sh's dirty-tree guard, the same two reads it makes.
        for args in (("diff", "--cached", "--quiet", "--", ".claude/"),
                     ("diff", "--quiet", "--", ".claude/")):
            r = git(self.repo, *args)
            self.assertEqual(r.returncode, 0, "the updater guard still refuses: "
                             + git(self.repo, "status", "--short").stdout + err)

    def test_held_deletion_is_restored_so_the_instance_still_syncs(self):
        os.remove(os.path.join(self.repo, ".claude/rules/keep.md"))
        self.write("q-system/memory/notes.md", "base\nmore\n")
        out, err = self.system_state()
        self.assertNotIn(".claude/rules/keep.md", out, "the updater was told to commit a deletion")
        self.assertIn("q-system/memory/notes.md", out, "control: system state still flows")
        self.assert_guard_clean(err)
        with open(os.path.join(self.repo, ".claude/rules/keep.md")) as fh:
            self.assertEqual(fh.read(), "rule one\nrule two\nrule three\n")

    def test_staged_deletion_is_restored(self):
        git(self.repo, "rm", "-q", ".claude/rules/keep.md")
        out, err = self.system_state()
        self.assertNotIn(".claude/rules/keep.md", out)
        self.assert_guard_clean(err)

    def test_line_loss_is_restored_and_the_working_copy_is_kept(self):
        self.write(".claude/rules/other.md", "a\n")
        out, err = self.system_state()
        self.assert_guard_clean(err)
        kept = []
        for root, _, files in os.walk(self.held_dir):
            for f in files:
                if f == "other.md":
                    with open(os.path.join(root, f)) as fh:
                        kept.append(fh.read())
        self.assertEqual(kept, ["a\n"], "the overwritten working copy was not kept")
        with open(os.path.join(self.held_dir, "restored.jsonl")) as fh:
            self.assertIn(".claude/rules/other.md", fh.read())

    def test_staged_rename_restores_the_old_name_and_commits_neither(self):
        git(self.repo, "mv", ".claude/rules/keep.md", ".claude/rules/renamed.md")
        out, err = self.system_state()
        self.assertFalse([p for p in out if "renamed.md" in p or "keep.md" in p], out)
        self.assert_guard_clean(err)
        self.assertTrue(os.path.exists(os.path.join(self.repo, ".claude/rules/renamed.md")),
                        "the new name was deleted from disk")

    def test_negative_self_test_nothing_held_writes_nothing(self):
        # A pure .claude/ addition is still system state, and no loss means the
        # classifier stays read-only: no restore, no state directory.
        self.write(".claude/rules/new.md", "fresh\n")
        out, _ = self.system_state()
        self.assertIn(".claude/rules/new.md", out)
        self.assertFalse(os.path.exists(self.held_dir), "a restore ran with nothing held")


class StopHookRestoresWhatHoldsNoWork(Scratch):
    """PR #738 round 2 (major): the Stop hook held the commit and left the deleted
    rule file MISSING from the worktree, so the next session there ran without that
    rule and no named consumer put it back.

    The discriminator is not the caller, it is whether the working copy holds
    anything. A path absent from disk holds no work, so HEAD can be restored over
    it losing nothing. A path still on disk with lines dropped holds someone's
    content, and a live session is in that tree to read the printed line.
    """

    def test_deleted_rule_file_is_back_on_disk_after_the_stop_hook(self):
        os.remove(os.path.join(self.repo, ".claude/rules/keep.md"))
        self.write("q-system/memory/notes.md", "base\nmore\n")
        out = self.run_hook().stdout
        path = os.path.join(self.repo, ".claude/rules/keep.md")
        self.assertTrue(os.path.exists(path),
                        "the next session in this tree still runs without the rule:\n" + out)
        with open(path) as fh:
            self.assertEqual(fh.read(), "rule one\nrule two\nrule three\n")
        # Still never COMMITTED as a deletion, and the rest still commits.
        self.assertIn("rule one", self.at_head(".claude/rules/keep.md"))
        self.assertEqual(self.at_head("q-system/memory/notes.md"), "base\nmore\n", out)

    def test_a_shrink_is_left_alone_so_a_live_session_keeps_its_edit(self):
        # The negative self-test for the restore: content on disk is never reverted
        # while a session is live in the tree.
        self.write(".claude/rules/other.md", "a\n")
        self.run_hook()
        with open(os.path.join(self.repo, ".claude/rules/other.md")) as fh:
            self.assertEqual(fh.read(), "a\n", "the Stop hook reverted a live edit")
        self.assertEqual(self.at_head(".claude/rules/other.md"), "a\nb\nc\n")

    def test_staged_deletion_is_restored_and_unstaged(self):
        git(self.repo, "rm", "-q", ".claude/rules/keep.md")
        self.run_hook()
        self.assertTrue(os.path.exists(os.path.join(self.repo, ".claude/rules/keep.md")))
        self.assertIn("rule one", self.at_head(".claude/rules/keep.md"))


class RestoreNamesItsConsumer(Scratch):
    """PR #738 round 2 (major): the restore reverted content in a live instance
    checkout with its only notice discarded by `kipi-update.sh 2>/dev/null` and its
    ledger read by nothing. A restore that can cost content files one ticket for
    Sana through slack-notify.sh, which is the fleet's named consumer.
    """

    def setUp(self):
        super().setUp()
        self.held_dir = os.path.join(self.tmp, "held-claude")
        self.alerts = os.path.join(self.tmp, "alerts.txt")
        notify = os.path.join(self.tmp, "notify.sh")
        with open(notify, "w") as fh:
            fh.write(f'#!/bin/sh\nprintf "%s\\n" "$1" >> "{self.alerts}"\n')
        os.chmod(notify, 0o755)
        self.env["KIPI_AUTOCOMMIT_HELD_DIR"] = self.held_dir
        self.env["KIPI_AUTOCOMMIT_NOTIFY"] = notify

    def system_state(self):
        st = git(self.repo, "status", "--porcelain", "-uall").stdout
        feed = "".join(ln[3:] + "\n" for ln in st.splitlines())
        r = subprocess.run([sys.executable, HOOK, "--system-state"], cwd=self.repo,
                           env=self.env, input=feed, capture_output=True, text=True,
                           check=False)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.split("\n"), r.stderr

    def filed(self):
        if not os.path.exists(self.alerts):
            return []
        with open(self.alerts) as fh:
            return [ln for ln in fh.read().splitlines() if ln.strip()]

    def test_a_shrink_restore_files_exactly_one_ticket_for_sana(self):
        self.write(".claude/rules/other.md", "a\n")
        self.system_state()
        msgs = self.filed()
        self.assertEqual(len(msgs), 1, "the restore reached no named consumer: " + repr(msgs))
        self.assertIn("ASK-4386", msgs[0])
        self.assertIn("1 .claude/ path", msgs[0],
                      "the alert does not say how many paths: " + msgs[0])

    def test_the_alert_shape_is_stable_so_it_cannot_flood(self):
        # The 2026-08-10 flood that moved this sink off Slack was 51 auto-commit
        # messages naming a file set that changed every turn. alert-to-linear.py
        # dedupes by SHAPE, so the path list must not be in the message.
        self.write(".claude/rules/other.md", "a\n")
        self.write(".claude/rules/keep.md", "rule one\n")
        self.system_state()
        msgs = self.filed()
        self.assertEqual(len(msgs), 1, "one ticket per restore EVENT, not per path")
        self.assertNotIn("other.md", msgs[0], "the path list is in the alert: " + msgs[0])
        self.assertNotIn("keep.md", msgs[0], "the path list is in the alert: " + msgs[0])

    def test_a_deletion_only_restore_files_nothing(self):
        # Restoring a path that is absent from disk cannot cost content, so it is
        # not an event worth a ticket. Keeps the queue honest.
        os.remove(os.path.join(self.repo, ".claude/rules/keep.md"))
        self.system_state()
        self.assertEqual(self.filed(), [], "a lossless restore filed a ticket")


class IssueBranchCommitsNameTheIssue(Scratch):
    branch = "sana/ask-4309"

    def test_hook_commit_on_an_issue_branch_names_the_issue(self):
        self.write("q-system/memory/notes.md", "base\nmore\n")
        out = self.run_hook().stdout
        msgs = [m.strip() for m in self.new_messages().split("\0") if m.strip()]
        self.assertTrue(msgs, "control: the hook made no commit at all:\n" + out)
        for m in msgs:
            self.assertIn("ASK-4309", m, "a hook commit on sana/ask-4309 skipped the gate")
            self.assertNotIn("[no-issue:", m)

    def test_gate_refuses_a_bypass_on_an_issue_branch(self):
        self.write("q-system/memory/notes.md", "x\n")
        git(self.repo, "add", "-A")
        r = git(self.repo, "commit", "-q", "-m",
                "chore: update rules\n\n[no-issue: auto-commit safety net]", env=self.env)
        self.assertNotEqual(r.returncode, 0, "the gate let a bypass through on sana/ask-4309")
        self.assertEqual(self.head(), self.base)


class FleetToolBypassIsNeverRefused(Scratch):
    """PR #738 round 2 (minor): the new refusal was written against every emitter
    of `[no-issue:]`, not against the one that can name a branch issue.

    Measured in this repo on 2026-11-14: nine call sites emit the bypass. Exactly
    one (`auto-commit.py:635`) runs inside an agent's issue worktree. The other
    eight run in a main checkout and have no issue to name, and the gate's own
    docstring is explicit that the hatch is deliberate and made COUNTABLE by the
    ledger rather than closed. `kipi-update.sh:3189` already prints "this instance
    will very likely be refused below" when its system-state commit fails, so
    refusing those eight abandons that instance on every sync. That is round 1's
    blocking major re-created through a different file.
    """

    branch = "sana/ask-4309"

    def commit_with(self, reason):
        self.write("q-system/memory/notes.md", f"x {reason}\n")
        git(self.repo, "add", "-A")
        return git(self.repo, "commit", "-q", "-m",
                   f"chore: work\n\n[no-issue: {reason}]", env=self.env)

    def test_fleet_tool_bypasses_still_commit_on_an_issue_branch(self):
        for reason in ("fleet updater system-state commit",
                       "fleet updater skeleton sync",
                       "fleet updater instance-local untrack",
                       "fleet updater never-commit untrack",
                       "fleet updater exhaust, no issue in this instance",
                       "fleet migration, sp-8d55455a tracks it",
                       "automated daily lesson persist"):
            r = self.commit_with(reason)
            self.assertEqual(r.returncode, 0,
                             f"the gate abandoned an instance over {reason!r}: "
                             + r.stdout + r.stderr)

    def test_the_bypass_stays_countable_for_a_fleet_tool(self):
        self.commit_with("fleet updater skeleton sync")
        with open(self.ledger) as fh:
            self.assertIn("fleet updater skeleton sync", fh.read(),
                          "an allowed bypass stopped being countable")

    def test_the_auto_commit_bypass_is_still_refused_there(self):
        # The one emitter that CAN ask the gate for the branch issue stays refused,
        # so the hook cannot go back to dodging the gate (70163e63's shape).
        before = self.head()
        r = self.commit_with("auto-commit safety net, unattended Stop hook")
        self.assertNotEqual(r.returncode, 0, "the hook's own bypass was waved through")
        self.assertEqual(self.head(), before)


class BypassStillWorksOffIssueBranches(Scratch):
    branch = "sana/case-051-session"

    def test_bypass_allowed_when_the_branch_names_no_issue(self):
        self.write("q-system/memory/notes.md", "x\n")
        git(self.repo, "add", "-A")
        r = git(self.repo, "commit", "-q", "-m", "chore: notes\n\n[no-issue: typo]",
                env=self.env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
