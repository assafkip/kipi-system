#!/usr/bin/env python3
"""founder_notify.deliver(): "delivered" must say where the text actually is.

Review finding (PR #746, ASK-4479 S2): chief's dm_length turns a message over 20 rows
or 2000 chars into a first line plus an app Chat link, while deliver() reported a
plain delivery. The full text IS saved to the app Chat, so the delivery is honest,
but the result has to say so. These tests pin that.

No live path: the chief package here is a throwaway one written into a temp dir that
mirrors chief's phone_text shaping (fits / dm_length / save_long) and a post_to that
sends through a recording transport. Nothing is sent anywhere.
"""
import importlib.util
import json
import os
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "scripts", "founder_notify.py")

_FAKE_PHONE_TEXT = '''
APP_LINK = "https://app.example.invalid"
DM_MAX_CHARS = 2000
DM_MAX_LINES = 20
SAVE_OK = {ok}
def fits(answer):
    t = (answer or "").strip()
    return len(t) <= DM_MAX_CHARS and t.count("\\n") < DM_MAX_LINES
def save_long(text):
    return "row1" if SAVE_OK else None
def dm_length(answer, saver=None):
    text = (answer or "").strip()
    if fits(text):
        return text
    first = next((l.strip() for l in text.splitlines() if l.strip()), "")
    saved = (saver or save_long)(text)
    if saved:
        return first + "\\nFull answer is in the app Chat: " + APP_LINK + "/chat?m=" + saved
    return text[:DM_MAX_CHARS - 60] + "\\n(cut: the full text could not be saved to the app)"
'''

_FAKE_TELEGRAM_OUT = '''
import os
from . import phone_text
def post_to(chat, text, label, saver=None):
    shown = label + ": " + text.strip()
    line = phone_text.dm_length(shown, saver=saver)
    if os.environ.get("FAKE_HOLD"):
        return {"delivered": True, "held": True, "reason": "kept for retry: down"}
    return {"delivered": True, "refused": False, "chat": chat, "sent": line}
'''


def _load():
    spec = importlib.util.spec_from_file_location("founder_notify_t", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fake_chief(root, save_ok=True):
    pkg = os.path.join(root, "chief")
    os.makedirs(pkg)
    open(os.path.join(pkg, "__init__.py"), "w").close()
    with open(os.path.join(pkg, "phone_text.py"), "w") as f:
        f.write(_FAKE_PHONE_TEXT.format(ok=save_ok))
    with open(os.path.join(pkg, "telegram_out.py"), "w") as f:
        f.write(_FAKE_TELEGRAM_OUT)


class TestDeliverSaysWhereTheTextIs(unittest.TestCase):
    def setUp(self):
        self.mod = _load()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # pytest sets PYTEST_CURRENT_TEST, which makes deliver() refuse by design.
        p = mock.patch.object(self.mod, "_under_test", return_value=False)
        p.start()
        self.addCleanup(p.stop)

    def _deliver(self, message, save_ok=True, hold=False):
        _fake_chief(self.tmp.name, save_ok)
        env = {"KIPI_CHIEF_ROOT": self.tmp.name}
        if hold:
            env["FAKE_HOLD"] = "1"
        with mock.patch.dict(os.environ, env):
            os.environ.pop("KIPI_FOUNDER_NOTIFY_CMD", None)
            return self.mod.deliver(message, timeout=30)

    def test_short_message_is_plain_delivery(self):
        res = self._deliver("short note")
        self.assertTrue(res["delivered"])
        self.assertNotIn("collapsed", res)
        self.assertNotIn("held", res)

    def test_forty_line_message_reports_collapsed_with_the_link(self):
        body = "\n".join(f"row {i}" for i in range(40))
        res = self._deliver(body)
        self.assertTrue(res["delivered"])
        self.assertTrue(res.get("collapsed"), res)
        self.assertTrue(res["saved"])
        self.assertTrue(res["link"].endswith("/chat"), res)

    def test_collapsed_with_failed_save_says_saved_false(self):
        body = "\n".join(f"row {i}" for i in range(40))
        res = self._deliver(body, save_ok=False)
        self.assertTrue(res.get("collapsed"))
        self.assertFalse(res["saved"])

    def test_held_key_is_carried(self):
        res = self._deliver("short note", hold=True)
        self.assertTrue(res["delivered"])
        self.assertTrue(res.get("held"), res)

    def test_runner_seam_passes_the_flags_through(self):
        out = json.dumps({"delivered": True, "collapsed": True, "saved": True, "link": "L/chat"})
        res = self.mod.deliver("x", runner=lambda a, c, t: (0, out))
        self.assertTrue(res["collapsed"])
        self.assertEqual(res["link"], "L/chat")

    def test_the_fake_length_rule_matches_chiefs_when_chief_is_present(self):
        chief = os.path.join(os.path.expanduser("~"), "projects", "chief")
        real = os.path.join(chief, "chief", "phone_text.py")
        if not os.path.exists(real):
            self.skipTest("no chief checkout on this machine")
        spec = importlib.util.spec_from_file_location("real_phone_text", real)
        rm = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(rm)
        ns = {}
        exec(_FAKE_PHONE_TEXT.format(ok=True), ns)
        for text in ("a", "\n".join("x" * 5 for _ in range(19)), "\n".join("x" for _ in range(20)),
                     "y" * 2000, "y" * 2001):
            self.assertEqual(rm.fits(text), ns["fits"](text), repr(text[:20]))


if __name__ == "__main__":
    unittest.main()
