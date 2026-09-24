#!/usr/bin/env python3
"""Validator for the monthly voice-refresh schedule (issue voice-refresh-schedule).

Runnable directly (`python3 automation/test_voice_refresh_schedule.py`): asserts
the plist is valid and monthly, the nudge routes ONLY through slack-notify.sh
(no osascript), and the template is installable by the ONE shipped installer.

2026-09-07: this file used to carry `test_installer_registers_health`, which
asserted that `automation/install-voice-refresh.sh` contained the literal string
"registration skipped". That message was a lie in both directions. The installer
tested for `q-system/.q-system/scripts/launchd-health-register.sh`, a file that
was never added in any of this repo's 3140 commits on any ref, so the else branch
ran on every install and every install announced the watchdog absent. The watchdog
is present at `q-system/.q-system/scripts/launchd-health-check.py` and needs no
registration at all: `discover_problems()` globs `~/Library/LaunchAgents` per
watched prefix, which is how com.kipi.voice-refresh was already covered (measured:
70 labels enumerated, the target among them, with nothing registered anywhere).

So the suite was pinning the defect. Inverting it is part of the fix, and the
installer it asserted about is gone: install-plist.sh is the single writer.
"""
import os
import plistlib
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
PLIST = os.path.join(HERE, "com.kipi.voice-refresh.plist")
NUDGE = os.path.join(HERE, "voice-refresh-nudge.sh")
INSTALLER = os.path.join(REPO, "q-system", ".q-system", "scripts", "install-plist.sh")


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


def test_template_renders_through_the_single_installer():
    """The template must be reachable AND renderable by the one shipped installer.

    --render-only, not a real install: this runs in CI and on the founder's laptop,
    and a test that loads a job is a test that touches a live data path.
    """
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "rendered.plist")
        r = subprocess.run(["bash", INSTALLER, "com.kipi.voice-refresh",
                            "--render-only", out],
                           capture_output=True, text=True, timeout=120)
        assert r.returncode == 0, "installer could not render the template: " + r.stderr
        body = open(out).read()
        assert "__" not in body.replace("__pycache__", ""), "placeholder left in rendered plist"
        plistlib.loads(body.encode())


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
