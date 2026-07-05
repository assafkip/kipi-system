#!/usr/bin/env python3
"""Validator for the monthly voice-refresh schedule (issue voice-refresh-schedule).

Runnable directly (`python3 automation/test_voice_refresh_schedule.py`): asserts
the plist is valid and monthly, the nudge routes ONLY through slack-notify.sh
(no osascript), and the installer registers with launchd-health. Exits non-zero
on any failure.
"""
import os
import plistlib
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PLIST = os.path.join(HERE, "com.kipi.voice-refresh.plist")
NUDGE = os.path.join(HERE, "voice-refresh-nudge.sh")
INSTALLER = os.path.join(HERE, "install-voice-refresh.sh")


def test_plist_valid_and_monthly():
    raw = open(PLIST, "rb").read().replace(b"__ROOT__", b"/tmp/repo")
    pl = plistlib.loads(raw)
    assert pl["Label"] == "com.kipi.voice-refresh", "wrong Label"
    sci = pl["StartCalendarInterval"]
    assert sci["Day"] == 1, "nudge must fire on the 1st of the month"
    assert pl["ProgramArguments"][-1].endswith("voice-refresh-nudge.sh"), "must run the nudge"


def test_nudge_slack_only_no_osascript():
    body = open(NUDGE).read()
    assert "slack-notify.sh" in body, "nudge must route through slack-notify.sh"
    # osascript must not be INVOKED; a comment documenting the ban is allowed.
    code_lines = [l for l in body.splitlines() if not l.lstrip().startswith("#")]
    assert not any("osascript" in l for l in code_lines), "osascript must not be invoked for founder pings"


def test_installer_registers_health():
    body = open(INSTALLER).read()
    assert "launchd-health" in body, "installer must register with launchd-health"
    assert "launchctl load" in body, "installer must load the launchd job"
    # honest message: no unconditional "registered" claim
    assert "registration skipped" in body, "installer must not falsely claim health registration"


def test_rendered_plist_parses_with_tricky_path():
    # Mirror the installer's render (XML-escape) so a path with #, &, < survives.
    import xml.sax.saxutils as sx
    tricky = "/tmp/re&po#dir"
    rendered = open(PLIST).read().replace("__ROOT__", sx.escape(tricky))
    pl = plistlib.loads(rendered.encode())
    assert tricky in pl["ProgramArguments"][-1], "rendered path must survive intact"


def _main():
    failures = []
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok   {name}")
            except AssertionError as e:
                failures.append(f"FAIL {name}: {e}")
    for f in failures:
        print(f)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    _main()
