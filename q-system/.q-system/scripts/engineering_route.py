#!/usr/bin/env python3
"""Engineering signal from the morning brief -> Sana's Linear triage. Never the founder.

Founder, 2026-08-10, in slack-notify.sh's own header: *"I dont want to see any of these.
Any of the ones that need attention should go to Sana - not me."* And 2026-09-03, on the
board: *"I'm not looking for this to be a build dashboard, but a consulting dashboard."*
So `Owed today` (Linear) and `Overnight jobs` (launchd) left his brief. They did not stop
being collected; they come here.

## Why this is its OWN file and not four lines inside morning-brief.py

`test_morning_brief.py::test_no_source_file_calls_slack_notify` greps morning-brief.py,
morning-brief-deadman.py and slack_founder.py for the string "slack-notify" and fails on
a hit. That guard is correct and stays: the founder's BRIEF must never go out through the
fleet alert path, which files a Linear ticket and sends him nothing. Routing a side
channel to Sana is a different act from delivering his brief, but the guard is a source
grep and cannot tell them apart, and the fix for a blunt-but-right guard is to stop
tripping it rather than to loosen it. The first attempt put `_notify_sana` inside
morning-brief.py and the guard caught it, which is the guard working.

## Degraded only

One line per DEGRADED section, and nothing at all for a healthy one. A ticket every
morning for a clean overnight run is how an alert channel gets muted, and a muted channel
is worse than none. `founder-notifications.md`: alert on state change, once.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
NOTIFY = HERE / "slack-notify.sh"
TIMEOUT_S = 20


def messages(sources: dict, sections) -> list:
    """The lines a degraded run should file. Pure, so a test needs no subprocess."""
    out = []
    for key, title in sections:
        _rows, error = sources.get(key, ([], f"section {key} was never collected"))
        if error:
            out.append(f"morning-brief: {title} is degraded: {error}")
    return out


def send(message: str) -> None:
    """Raise when the notifier did not file. The caller records the failure.

    Codex finding (major), 2026-09-03: this swallowed the exit status and returned
    None, so `route` reported the line as ROUTED whether or not a Linear issue was
    ever created. That is the write-only-integration defect this repo has a lesson
    file about, written into the one module whose whole job is delivery. An absent
    script is still a legitimate no-op (an unconfigured machine); a script that RAN
    and failed is not.
    """
    if not NOTIFY.exists():
        # ABSENT IS NOT FILED (round 12, major). This returned None, which `route`
        # counts as a successful filing, so an unconfigured machine reported every
        # engineering line as routed to Sana while no issue existed anywhere. The
        # module's own docstring calls that the write-only-integration defect and
        # this was the last place it still lived. A no-op is still legitimate; it
        # just has to say so rather than claim a delivery.
        raise FileNotFoundError(
            f"no notifier at {NOTIFY}; nothing was filed and no issue exists")
    done = subprocess.run(["bash", str(NOTIFY), message], check=False,
                          capture_output=True, timeout=TIMEOUT_S)
    if done.returncode != 0:
        raise RuntimeError(
            f"slack-notify.sh exited {done.returncode}: "
            f"{(done.stderr or b'').decode('utf-8', 'replace').strip()[:200]}")


def route(sources: dict, sections, notify=None) -> tuple:
    """(filed, failed). Never raises: a broken notifier must not cost him his brief.

    Returns what was ACTUALLY filed and what was attempted and failed, rather than the
    old single list that reported every attempt as a success. A caller that prints
    `filed` is now telling the truth, and `failed` is the thing worth shouting about:
    it means an engineering problem was detected and then lost.
    """
    lines = messages(sources, sections)
    notify = notify or send
    filed, failed = [], []
    for line in lines:
        try:
            notify(line)
            filed.append(line)
        except Exception as exc:                            # noqa: BLE001
            failed.append((line, f"{type(exc).__name__}: {exc}"))
    return filed, failed
