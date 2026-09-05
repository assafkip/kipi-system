#!/usr/bin/env python3
"""ASK-1144: the every-position argv scan blew the hook's 5s timeout.

PR #279 major. The scan called argv_deny_reason once per token, and each call is
a command substitution -- a subshell fork -- that re-parses the remaining tokens.
Measured on one `git` stage before the fix:

    120 tokens   0.64s
    230 tokens   3.83s
    400 tokens  19.43s

settings.json wires this hook at timeout 5, and a hook that overruns its timeout
is KILLED with its verdict DISCARDED (already measured in this repo: a 0s hook
exiting 2 blocks, an 8s hook exiting 2 runs). So a long enough command line was a
bypass requiring no cleverness -- and the slow path is the BENIGN one, which is
every call the hook ever sees.

A pre-filter now skips positions that provably cannot deny. These cases exist
because that filter is a change to SECURITY behaviour, not just to speed: the
denies that could plausibly have been lost are the ones behind transparent
prefixes, so they are pinned here explicitly.
"""

import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.environ.get(
    "KIPI_HOOK_UNDER_TEST",
    os.path.join(os.path.dirname(HERE), "hooks", "destructive-op-deny.sh"))

RM = "".join(["r", "m"])
RF = "-" + "".join(["r", "f"])
DANGER = "%s %s /tmp/probe" % (RM, RF)

# The hook's wired PreToolUse timeout. Anything slower is a discarded verdict.
HOOK_TIMEOUT_S = 5.0


def decision_for(command, timeout=120):
    home = tempfile.mkdtemp(prefix="argvprobe-")
    try:
        os.makedirs(os.path.join(home, ".claude", "audit"), exist_ok=True)
        env = dict(os.environ)
        env["HOME"] = home
        env.pop("ALLOW_DESTRUCTIVE", None)
        payload = {"tool_name": "Bash", "tool_input": {"command": command},
                   "cwd": "/tmp"}
        t0 = time.time()
        proc = subprocess.run(["bash", HOOK], input=json.dumps(payload),
                              capture_output=True, text=True, timeout=timeout)
        elapsed = time.time() - t0
        if proc.returncode == 2:
            return "deny", elapsed
        out = (proc.stdout or "").strip()
        if not out:
            return "allow", elapsed
        try:
            return (json.loads(out)["hookSpecificOutput"]["permissionDecision"],
                    elapsed)
        except (ValueError, KeyError):
            return "error", elapsed
    finally:
        shutil.rmtree(home, ignore_errors=True)


@unittest.skipUnless(shutil.which("jq"), "the hook parses its payload with jq")
@unittest.skipUnless(os.path.isfile(HOOK), "no hook to drive at %s" % HOOK)
class ArgvPrefilterCase(unittest.TestCase):

    def test_a_long_benign_command_stays_well_under_the_timeout(self):
        """The bypass itself. 400 tokens took 19.43s before the pre-filter."""
        command = "git log --oneline " + " ".join(
            "--grep=w%d" % i for i in range(400))
        decision, elapsed = decision_for(command)
        self.assertEqual(decision, "allow")
        self.assertLess(elapsed, HOOK_TIMEOUT_S,
                        "the hook took %.2fs against a %.0fs timeout; an "
                        "overrunning hook is killed and its deny discarded"
                        % (elapsed, HOOK_TIMEOUT_S))

    def test_assignment_tokens_do_not_blow_the_timeout(self):
        """PR #279 major, round 2. My first timing case padded with `--grep=x`
        -- the ONE shape the pre-filter excluded -- so it measured the path I
        had just fixed and was blind to the two that were still open. 300 `k=v`
        tokens took 8.28s."""
        command = "echo " + " ".join("K%d=v%d" % (i, i) for i in range(300))
        decision, elapsed = decision_for(command)
        self.assertEqual(decision, "allow")
        self.assertLess(elapsed, HOOK_TIMEOUT_S,
                        "%.2fs against a %.0fs timeout" % (elapsed, HOOK_TIMEOUT_S))

    def test_one_long_quoted_string_does_not_blow_the_timeout(self):
        """The quote-stripped rescan had no pre-filter at all, so a single long
        QUOTED string forked per word: 3000 words took 6.99s. Fixing one of two
        identical loops is how a bypass survives being fixed."""
        command = 'echo "' + " ".join("w%d" % i for i in range(3000)) + '"'
        decision, elapsed = decision_for(command)
        self.assertEqual(decision, "allow")
        self.assertLess(elapsed, HOOK_TIMEOUT_S,
                        "%.2fs against a %.0fs timeout" % (elapsed, HOOK_TIMEOUT_S))

    def test_a_deny_inside_a_quoted_program_token_still_fires(self):
        """The rescan exists to catch a quoted program token. Adding a filter to
        it must not cost that."""
        self.assertEqual(decision_for('"%s" %s /tmp/x' % (RM, RF))[0], "deny")

    def test_prefix_padding_does_not_blow_the_timeout(self):
        """Round three of this bypass, and the reason it kept surviving.

        Each round I removed one admitted shape, then padded the timing test
        with a shape the filter DROPS -- so the suite went green while another
        class stayed open at 5-13s. This pads with the shape the filter admitted
        LONGEST: 300 `sudo` tokens took 5.91s."""
        command = "echo " + " ".join(["sudo"] * 300)
        decision, elapsed = decision_for(command)
        self.assertEqual(decision, "allow")
        self.assertLess(elapsed, HOOK_TIMEOUT_S,
                        "%.2fs against a %.0fs timeout" % (elapsed, HOOK_TIMEOUT_S))

    def test_the_admitted_token_shape_is_bounded(self):
        """THE worst case, because it cannot be filtered away.

        `git` and `rm` must be admitted -- they are the tokens that can deny --
        so a line padded with them is unbounded by construction, and three
        rounds of narrowing the filter only moved the threshold. 4000 admitted
        tokens took 21.24s before the scans were de-forked and windowed.

        PADS WITH `rm`, NOT `git` (codex minor, round six). Both are admitted,
        and this test padded with the CHEAPER of the two, so it could not go red
        for the reason it exists. Measured after the quote-strip fix and before
        the count ceiling:

            tokens     pad=rm     pad=git
             4000       4.06s       1.95s
             6000       6.96s       3.63s
             8000      10.16s       5.85s

        Against a 5s timeout, `git` padding still passed at 6000 while `rm`
        padding had already crossed. Choosing the shape the current code handles
        best measures the fix instead of the limit, which is how this bypass
        survived five rounds of green suites.

        The expectation is now DENY, and that is the change this round makes on
        purpose. This asserted allow-and-fast, and past ~5000 tokens those two
        cannot both be true: the hook is killed at 5s and its verdict discarded,
        so "fast" was only ever achieved by not finishing. A guard that runs out
        of time must refuse, not permit."""
        for tokens in (4000, 8000):
            with self.subTest(tokens=tokens):
                command = "echo " + " ".join(["rm"] * tokens)
                decision, elapsed = decision_for(command)
                self.assertEqual(decision, "deny",
                                 "a stage past the rescan ceiling must be "
                                 "refused rather than half-checked")
                self.assertLess(elapsed, HOOK_TIMEOUT_S,
                                "the refusal itself must arrive inside the "
                                "timeout: %.2fs" % elapsed)

    def test_the_ceiling_bounds_the_invocation_not_the_stage(self):
        """Round seven, and the reason round six's headline was false.

        The ceiling was reset at the top of every `;`-separated stage, so a
        command bought a fresh 500 rescans per stage and the bound was only ever
        per-stage. Codex measured 14 padded stages, 21KB, at 5.55s against the
        wired 5s timeout, where the hook is killed and its deny DISCARDED.

        No existing timing test drove more than one stage, so the suite could not
        observe the reset. Every one of them padded a SINGLE stage harder, which
        is why six rounds of green suites sat on top of an open bypass: the tests
        kept growing along the axis that was already fixed.

        Each stage here sits UNDER the per-stage ceiling on its own, so this can
        only go red on the multiplication, not on stage size."""
        stage = " ".join(["rm"] * 400)
        for stages in (14, 30):
            with self.subTest(stages=stages):
                command = " ; ".join([stage] * stages)
                decision, elapsed = decision_for(command)
                self.assertEqual(decision, "deny",
                                 "a padded multi-stage command must still reach "
                                 "a verdict")
                self.assertLess(elapsed, HOOK_TIMEOUT_S,
                                "%d stages took %.2fs against a %.0fs timeout: "
                                "the ceiling is bounding each stage rather than "
                                "the invocation"
                                % (stages, elapsed, HOOK_TIMEOUT_S))

    def test_the_rescan_ceiling_leaves_ordinary_commands_alone(self):
        """The ceiling has to sit far above real usage or it gets switched off.

        The pre-filter admits only known deniers, so what counts toward the
        ceiling is bare `rm`/`git`-shaped WORDS in one stage -- not file names,
        paths or flags, which is what a genuinely long command is made of."""
        for command in ("echo " + " ".join(["rm"] * 100),
                        "git add " + " ".join("file%d.txt" % i for i in range(400)),
                        "echo " + " ".join("path/to/file%d" % i for i in range(3000))):
            with self.subTest(command=command[:40]):
                self.assertEqual(decision_for(command)[0], "allow")

    def test_transparent_prefixes_still_deny(self):
        """What the pre-filter could plausibly have broken. Each of these has a
        head token that is NOT a recognised program, so each depends on the
        filter still letting that position through."""
        for prefix in ("sudo", "command", "nohup", "nice", "time", "env"):
            with self.subTest(prefix=prefix):
                self.assertEqual(decision_for("%s %s" % (prefix, DANGER))[0],
                                 "deny")

    def test_an_env_assignment_prefix_still_denies(self):
        """`FOO=bar rm -rf x`. The filter keeps `[!-]*=*` precisely for this."""
        self.assertEqual(decision_for("FOO=bar %s" % DANGER)[0], "deny")
        self.assertEqual(decision_for("A=1 B=2 %s" % DANGER)[0], "deny")

    def test_a_flag_shaped_assignment_does_not_hide_a_deny(self):
        """The filter now admits ONLY `rm` and `git`; flags, assignments and
        transparent prefixes were all removed across four rounds. Each removal
        rests on the same argument, so each needs the same check: a deny after
        the skipped token must still be found from the program token, which is
        always scanned."""
        self.assertEqual(decision_for("--grep=x %s" % DANGER)[0], "deny")
        self.assertEqual(
            decision_for("git log --grep=x ; %s" % DANGER)[0], "deny")

    def test_a_deny_buried_after_many_flags_is_still_found(self):
        pad = " ".join("--grep=w%d" % i for i in range(200))
        decision, elapsed = decision_for("git log %s ; %s" % (pad, DANGER))
        self.assertEqual(decision, "deny")
        self.assertLess(elapsed, HOOK_TIMEOUT_S)

    def test_remote_deletions_spelled_without_force_are_denied(self):
        """PR #279 minors. The +refspec rule closed one flagless destructive
        push and left three; all three destroy published refs."""
        for command in ("git push origin --delete branch",
                        "git push origin :branch",
                        "git push --mirror origin"):
            with self.subTest(command=command):
                self.assertEqual(decision_for(command)[0], "deny")

    def test_a_clean_preview_is_allowed_and_the_real_one_is_not(self):
        """A preview removes nothing, and denying a preview is how a gate gets
        switched off -- previewing is how you EARN the run. The coarse regex read
        `-[a-zA-Z]*[fdx]`, so `-nd` matched on the `d`."""
        clean = "git " + "cle" + "an"
        self.assertEqual(decision_for(clean + " -nd")[0], "allow")
        self.assertEqual(decision_for(clean + " --dry-run -d")[0], "allow")
        self.assertEqual(decision_for(clean + " -fd")[0], "deny",
                         "the real clean stopped being denied when the coarse "
                         "pattern was removed")

    def test_a_quoted_destructive_behind_admitted_padding_denies_in_time(self):
        """The axes CROSSED, which is why this bypass survived four rounds.

        The two existing timing tests pad with an UNADMITTED shape and quote
        nothing, or admit tokens and quote nothing. Neither builds the payload
        that is actually expensive: padding that is BOTH admitted (`git`, which
        must be admitted because git can deny) and quoted (so the substring list
        cannot reach a verdict and only the strip-scan can). Measured on the
        code this test shipped against, that took 22.85s at 2000 tokens and
        186.52s at 4000 against a wired 5s timeout, where the hook is killed and
        its deny DISCARDED -- so the answer silently became allow.

        Padding a test with a shape the current code already handles measures
        the fix instead of the limit. That is how three previous rounds passed.
        """
        quoted_rm = '"' + "r" + 'm" -rf /tmp/zzz_never_exists'
        for tokens in (2000, 4000):
            with self.subTest(tokens=tokens):
                command = " ".join(['"git"'] * tokens) + " " + quoted_rm
                started = time.time()
                decision = decision_for(command)[0]
                elapsed = time.time() - started
                self.assertEqual(decision, "deny",
                                 "a quoted destructive behind admitted padding "
                                 "must still be denied")
                self.assertLess(elapsed, 5.0,
                                "the deny arrived after %.1fs, past the wired 5s "
                                "timeout: the hook is killed there and the verdict "
                                "is discarded, which is an allow" % elapsed)

    def test_an_overlong_stage_is_refused_rather_than_half_checked(self):
        """Fail CLOSED at the ceiling. A guard that runs out of time must not
        answer allow, so a stage past the token cap is refused with a reason
        that says how to proceed."""
        command = "git " + " ".join(["status"] * 900)
        decision, elapsed = decision_for(command)
        self.assertEqual(decision, "deny",
                         "a git stage past the token ceiling must be refused, "
                         "not half-checked")
        self.assertLess(elapsed, 5.0, "%.2fs" % elapsed)

    def test_the_ceiling_leaves_ordinary_long_commands_alone(self):
        """The cap has to sit far above real usage or it gets switched off."""
        command = "git add " + " ".join("file%d.txt" % i for i in range(300))
        self.assertEqual(decision_for(command)[0], "allow")

    def test_a_preview_is_allowed_for_push_the_same_as_for_clean(self):
        """Both halves of a contradiction shipped in one change.

        `git push --force --dry-run` was denied while `git clean --dry-run` was
        allowed fifty lines away, on the opposite reasoning. The clean arm's own
        note is the correct one: previewing is how you EARN the run, and denying
        a preview is how a gate gets switched off. A dry-run push updates no ref.
        """
        for command in ("git push --force --dry-run origin main",
                        "git push --dry-run --force origin main",
                        "git clean -n -d"):
            with self.subTest(command=command):
                self.assertEqual(decision_for(command)[0], "allow",
                                 "a preview changes nothing and must not be "
                                 "denied")

        # The negative half. Without it this passes against a hook that allows
        # every push.
        for command in ("git push --force origin main",
                        "git push origin +main",
                        "git push -f origin main"):
            with self.subTest(command=command):
                self.assertEqual(decision_for(command)[0], "deny",
                                 "the real forced push must still be denied")

    def test_ordinary_commands_are_still_allowed(self):
        for command in ("ls -la", "git status", "echo hello"):
            with self.subTest(command=command):
                self.assertEqual(decision_for(command)[0], "allow")


if __name__ == "__main__":
    unittest.main(verbosity=2)
