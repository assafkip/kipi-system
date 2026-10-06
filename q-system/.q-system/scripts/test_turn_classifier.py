#!/usr/bin/env python3
"""Tests for turn_classifier.py and the three UserPromptSubmit injectors that use it.

ASK-2511. Fixtures are generic paraphrases of real turns from one long session,
kept to their SHAPE (length, envelope, verbs, pasted body). No names, paths or
clients: this repo is public.

Every hook test runs a COPY of the hook in a temp dir, with HOME and the project
dir pointed at temp, so nothing here reads or writes a live corpus or ledger.
Run: python3 -m pytest q-system/.q-system/scripts/test_turn_classifier.py -q
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import turn_classifier as tc  # noqa: E402

NOTIFICATION = (
    "<task-notification>\n<task-id>a0000000000000001</task-id>\n"
    "<status>completed</status>\n"
    "<summary>Agent \"Draft five posts\" finished</summary>\n"
    "<result>Drafted the reply and the post, fixed the failing test, wired the hook, "
    "and wrote the email. Commit pushed; the gate is green.</result>\n"
    "</task-notification>"
)
SYSTEM_NOTIFICATION = (
    "<system-reminder>\n[SYSTEM NOTIFICATION - NOT USER INPUT]\n"
    "This is an automated background-task event, NOT a message from the user.\n"
    "</system-reminder>\n" + NOTIFICATION
)
PASTED_POST = (
    "here is my version, use this one\n\n"
    "Most teams think the dashboard is the product.\n\n"
    "It is not. The product is the decision someone makes after reading it."
)

SHOULD_SKIP = [
    NOTIFICATION,
    SYSTEM_NOTIFICATION,
    "<task-notification>\n<task-id>b1</task-id>\n<summary>Background command "
    "\"Locate draft files\" completed (exit code 0)</summary>\n</task-notification>",
    "ok",
    "go",
    "yes",
    "done?",
    "how much longer",
    "what now?",
    "still going?",
    "is this done/",
    "whats working now?>",
    "go to round 3",
    "Has it been longer than 25 minutes",
    "Why is this taking so long?",
    "what is making it run for 13 minutes?",
    "explain whats going on simply",
]

SHOULD_INJECT = [
    "write the post",
    "draft a reply",
    "rewrite this so it sounds like me",
    "can you draft an email to the client about the delay",
    "reply to this comment for me",
    "Make it into a LinkedIn post about the audit",
    "draft three tweets from this idea",
    "write a short newsletter intro about the launch",
    PASTED_POST,
    "<pasted_content id=\"x1\">\nsome long text the founder pasted\n</pasted_content>\nfix this",
    "1. not actionable\n2. too technical\n3. makes no sense",
    "did you show me examples of posts?",
]

# Neither class: each injector keeps its own trigger. Listed so a future widening
# of "status" that swallows real design questions turns this red.
SHOULD_FALL_THROUGH = [
    "Would this mechanism be different and separate from the voice loop?",
    "I need you to identify why this is taking so long exactly. This is taking way too long.",
    "you can turn off the number check",
]


class TestClassifier(unittest.TestCase):
    def test_fixture_counts_meet_the_spec(self):
        self.assertGreaterEqual(len(SHOULD_SKIP), 10)
        self.assertGreaterEqual(len(SHOULD_INJECT), 10)

    def test_skips(self):
        for p in SHOULD_SKIP:
            with self.subTest(p=p[:40]):
                self.assertFalse(tc.should_inject(p), tc.classify(p))

    def test_injects(self):
        for p in SHOULD_INJECT:
            with self.subTest(p=p[:40]):
                self.assertEqual(tc.classify(p), "writing")
                self.assertTrue(tc.should_inject(p))

    def test_falls_through_to_each_hooks_own_trigger(self):
        for p in SHOULD_FALL_THROUGH:
            with self.subTest(p=p[:40]):
                self.assertEqual(tc.classify(p), "other")

    def test_a_notification_full_of_writing_verbs_is_still_a_notification(self):
        # The exact defect: agent prose says draft/post/reply/email.
        self.assertTrue(tc.has_writing_verb(NOTIFICATION))
        self.assertEqual(tc.classify(NOTIFICATION), "notification")

    def test_typed_text_before_a_quoted_notification_is_not_silenced(self):
        p = "write a reply based on this:\n" + NOTIFICATION
        self.assertEqual(tc.classify(p), "writing")

    def test_cap_marks_the_cut_and_respects_the_share(self):
        big = ("line of context\n" * 2000)
        out = tc.cap(big, "knowledge-inject")
        self.assertLessEqual(len(out.encode()), tc.SHARES["knowledge-inject"])
        self.assertIn("cut at 4000 bytes", out)
        self.assertEqual(tc.cap("small", "knowledge-inject"), "small")

    def test_the_largest_real_lesson_fits_the_lessons_share(self):
        lessons = HERE.parent.parent / "lessons"
        if not lessons.is_dir():
            self.skipTest("no lessons corpus in this checkout")
        biggest = max(len(p.read_bytes()) for p in lessons.glob("*.md"))
        self.assertLess(biggest + 600, tc.SHARES["lessons-inject"])

    def test_turn_cap_is_the_sum_of_shares(self):
        self.assertEqual(tc.TURN_BYTE_CAP, sum(tc.SHARES.values()))


def _sandbox(scripts):
    """Copy the named scripts plus the classifier into a temp scripts dir."""
    root = Path(tempfile.mkdtemp(prefix="ask2511-"))
    sdir = root / "q-system" / ".q-system" / "scripts"
    sdir.mkdir(parents=True)
    for name in list(scripts) + ["turn_classifier.py"]:
        shutil.copy(HERE / name, sdir / name)
    (root / ".claude").mkdir()
    return root, sdir


def _run(script, prompt, root, extra_env=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_", "KIPI_"))}
    env.update({"HOME": str(root / "home"), "CLAUDE_PROJECT_DIR": str(root),
                "KIPI_VOICE_DIR": str(root / "no-voice-corpus"), "TMPDIR": str(root / "tmp")})
    (root / "home").mkdir(exist_ok=True)
    (root / "tmp").mkdir(exist_ok=True)
    env.update(extra_env or {})
    payload = json.dumps({"prompt": prompt, "session_id": "s-" + str(abs(hash(prompt))), "cwd": str(root)})
    r = subprocess.run([sys.executable, str(script)], input=payload, capture_output=True,
                       text=True, env=env, cwd=str(root), timeout=60)
    assert r.returncode == 0, r.stderr
    return r.stdout


class TestVoiceLoader(unittest.TestCase):
    def setUp(self):
        self.root, self.sdir = _sandbox(["voice-dna-loader.py"])
        refs = self.root / "plugins" / "kipi-core" / "skills" / "founder-voice" / "references"
        refs.mkdir(parents=True)
        (refs / "voice-dna.md").write_text("VOICE-MARKER-7731\n" + ("a real voice rule line\n" * 120))
        self.hook = self.sdir / "voice-dna-loader.py"

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_a_writing_request_still_gets_the_voice_payload(self):
        out = _run(self.hook, "can you draft a reply to this comment", self.root)
        ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Writing request detected", ctx)
        self.assertIn("VOICE-MARKER-7731", ctx)

    def test_a_pasted_post_gets_the_voice_payload(self):
        out = _run(self.hook, PASTED_POST + "\n\nedit this", self.root)
        self.assertIn("VOICE-MARKER-7731", out)

    def test_a_notification_gets_nothing(self):
        self.assertEqual(_run(self.hook, NOTIFICATION, self.root), "")
        self.assertEqual(_run(self.hook, SYSTEM_NOTIFICATION, self.root), "")

    def test_status_questions_get_nothing(self):
        for p in ("how much longer", "ok", "go", "is this done?"):
            with self.subTest(p=p):
                self.assertEqual(_run(self.hook, p, self.root), "")

    def test_negative_control_the_same_words_without_the_envelope_fire(self):
        # Proves the empty result above comes from the gate, not from a broken
        # sandbox: the notification's own body, typed by a person, does inject.
        body = NOTIFICATION.split("<result>")[1].split("</result>")[0]
        self.assertIn("VOICE-MARKER-7731", _run(self.hook, body, self.root))

    def test_a_missing_classifier_fails_open_not_silent(self):
        (self.sdir / "turn_classifier.py").unlink()
        self.assertIn("VOICE-MARKER-7731", _run(self.hook, "write the post", self.root))


class TestLessonsInject(unittest.TestCase):
    def setUp(self):
        self.root, self.sdir = _sandbox(["lessons-inject.py"])
        les = self.root / "q-system" / "lessons"
        les.mkdir(parents=True)
        for i in range(4):
            (les / f"lesson-{i}.md").write_text(
                f"---\nid: lesson-{i}\ntitle: fix the failing hook test {i}\n---\n\n"
                + ("hook test fix gate commit detail line\n" * 60))
        self.hook = self.sdir / "lessons-inject.py"

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_a_notification_gets_nothing(self):
        self.assertEqual(_run(self.hook, NOTIFICATION, self.root), "")

    def test_an_engineering_prompt_still_fires_and_stays_under_its_share(self):
        out = _run(self.hook, "fix the failing hook test before you commit the gate change", self.root)
        ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("[lessons-inject]", ctx)
        self.assertLessEqual(len(ctx.encode()), tc.SHARES["lessons-inject"])


class TestKnowledgeInject(unittest.TestCase):
    STUB = (
        "def supply(root, prompt, session_id, **kw):\n"
        "    open(str(root) + '/supply-called', 'a').write('x')\n"
        "    return {'x': 1}\n"
        "def render(bundle):\n"
        "    return '[knowledge-supply] COVERAGE FULL\\n' + ('fact line\\n' * 3000)\n"
    )

    def setUp(self):
        self.root, self.sdir = _sandbox(["knowledge-inject.py"])
        (self.sdir / "knowledge_supply.py").write_text(self.STUB)
        self.hook = self.sdir / "knowledge-inject.py"

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_a_notification_gets_nothing_and_never_reaches_supply(self):
        self.assertEqual(_run(self.hook, NOTIFICATION, self.root), "")
        self.assertFalse((self.root / "supply-called").exists())

    def test_a_real_prompt_is_capped_to_its_share(self):
        out = _run(self.hook, "what did we promise the client about the audit scope last week", self.root)
        ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertTrue(ctx.startswith("[knowledge-supply]"))
        self.assertLessEqual(len(ctx.encode()), tc.SHARES["knowledge-inject"])
        self.assertIn("ASK-2511", ctx)


if __name__ == "__main__":
    unittest.main()
