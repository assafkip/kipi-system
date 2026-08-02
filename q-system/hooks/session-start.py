#!/usr/bin/env python3
"""
Session Start Hook for Q Instance.

Runs on SessionStart (once per session, with daily sentinel to avoid repeats).
Loads critical context that would otherwise be forgotten:
1. Last session handoff (what was in progress)
2. Yesterday's unconfirmed action cards (what was drafted but not confirmed)
3. Open follow-up loops and their escalation state

Uses a sentinel file to ensure it only runs once per day.
Output goes to stdout and appears in the conversation as context.

Exit code 0 always (never blocks, only injects context).
"""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path


def get_project_dir():
    """Find the project directory from environment or fallback."""
    return os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())


def get_qroot(project_dir):
    """Auto-detect q-system root. Subtree instances have q-system/q-system/."""
    nested = Path(project_dir) / "q-system" / "q-system" / "canonical"
    if nested.exists():
        return Path(project_dir) / "q-system" / "q-system"
    return Path(project_dir) / "q-system"


def get_sentinel_path():
    """Daily sentinel file path."""
    today = datetime.now().strftime("%Y-%m-%d")
    return Path(f"/tmp/q-session-{today}")


def already_ran_today():
    """Check if session-start already ran today."""
    sentinel = get_sentinel_path()
    return sentinel.exists()


def mark_ran():
    """Create sentinel file for today."""
    sentinel = get_sentinel_path()
    sentinel.write_text(datetime.now().isoformat())


def load_handoff(project_dir):
    """Read last-handoff.md for prior session context."""
    qroot = get_qroot(project_dir)
    handoff_path = qroot / "memory" / "last-handoff.md"
    if not handoff_path.exists():
        return None
    content = handoff_path.read_text().strip()
    if "no prior handoff" in content.lower():
        return None
    return content


def load_yesterday_cards(project_dir):
    """Read yesterday's morning log for unconfirmed action cards."""
    qroot = get_qroot(project_dir)
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    log_path = qroot / "output" / f"morning-log-{yesterday}.json"
    if not log_path.exists():
        return None, yesterday

    try:
        with open(log_path) as f:
            log = json.load(f)
    except (json.JSONDecodeError, IOError):
        return None, yesterday

    cards = log.get("action_cards", [])
    unconfirmed = [c for c in cards if c.get("card_delivered") and not c.get("founder_confirmed")]
    if not unconfirmed:
        return None, yesterday

    return unconfirmed, yesterday


def load_open_loops(project_dir):
    """Read open-loops.json for loop state summary."""
    qroot = get_qroot(project_dir)
    loops_path = qroot / "output" / "open-loops.json"
    if not loops_path.exists():
        return None
    try:
        with open(loops_path) as f:
            data = json.load(f)
        loops = [l for l in data.get("loops", []) if l.get("status") == "open"]
        if not loops:
            return None
        counts = {0: 0, 1: 0, 2: 0, 3: 0}
        force_close = []
        for l in loops:
            level = l.get("escalation_level", 0)
            counts[level] = counts.get(level, 0) + 1
            if level >= 3:
                force_close.append(l["target"])
        summary = f"{len(loops)} open (L0:{counts[0]} L1:{counts[1]} L2:{counts[2]} L3:{counts[3]})"
        return summary, force_close
    except (json.JSONDecodeError, IOError):
        return None


def load_today_log(project_dir):
    """Check if today's morning routine already ran."""
    qroot = get_qroot(project_dir)
    today = datetime.now().strftime("%Y-%m-%d")
    log_path = qroot / "output" / f"morning-log-{today}.json"
    if not log_path.exists():
        return None
    try:
        with open(log_path) as f:
            log = json.load(f)
        steps = log.get("steps", {})
        if steps:
            done = sum(1 for v in steps.values() if v.get("status") == "done")
            return f"Morning routine partially complete: {done} steps done"
    except (json.JSONDecodeError, IOError):
        pass
    return None


def format_output(handoff, cards, yesterday, morning_status, loops_result=None):
    """Format the session-start context message."""
    lines = []
    lines.append("SESSION START CONTEXT (auto-loaded)")
    lines.append("=" * 50)

    if loops_result:
        summary, force_close = loops_result
        lines.append("")
        lines.append(f"OPEN LOOPS: {summary}")
        if force_close:
            lines.append(f"FORCE CLOSE NEEDED: {', '.join(force_close)}")
            lines.append("These loops are 14+ days old. Must act, park, or kill today.")

    if handoff:
        lines.append("")
        lines.append("LAST SESSION HANDOFF:")
        handoff_lines = handoff.split("\n")[:20]
        lines.extend(handoff_lines)

    if cards:
        lines.append("")
        lines.append(f"UNCONFIRMED ACTION CARDS FROM {yesterday}:")
        lines.append("(These were drafted but founder hasn't confirmed they were done)")
        for c in cards:
            card_type = c.get("type", "?")
            target = c.get("target", "?")
            card_id = c.get("id", "?")
            lines.append(f"  [{card_id}] {card_type}: {target}")
        lines.append("")
        lines.append("Ask: 'Which of yesterday's actions did you actually do?'")

    if morning_status:
        lines.append("")
        lines.append(f"TODAY'S MORNING ROUTINE: {morning_status}")

    if not handoff and not cards and not morning_status and not loops_result:
        return None

    lines.append("")
    lines.append("=" * 50)
    return "\n".join(lines)


def check_claude_integrity(project_dir):
    """Run the .claude/ integrity tripwire in report mode (ASK-282).

    Returns a banner string when the tree drifted from its sanctioned baseline,
    else "". Never raises: a session must still start if the tripwire is absent
    or broken. It DOES page, because a drift nobody sees is the same as no
    tripwire at all.
    """
    import subprocess
    tw = os.path.join(project_dir, "q-system", ".q-system", "scripts",
                      "claude-integrity-tripwire.py")
    if not os.path.isfile(tw):
        return ""
    try:
        res = subprocess.run(["python3", tw, "--root", project_dir, "--check"],
                             capture_output=True, text=True, timeout=25)
    except Exception:
        return ""
    if res.returncode not in (1, 2):
        return ""
    detail = (res.stderr or "").strip()
    notifier = os.environ.get("KIPI_NOTIFY") or os.path.join(
        project_dir, "q-system", ".q-system", "scripts", "slack-notify.sh")
    try:
        subprocess.run([notifier, detail.split("\n")[0][:400]],
                       capture_output=True, timeout=20)
    except Exception:
        pass
    return ("SECURITY -- .claude/ drifted from its sanctioned baseline:\n" + detail +
            "\nIf this was you, re-baseline: python3 q-system/.q-system/scripts/"
            "claude-integrity-tripwire.py --baseline")


def main():
    project_dir = get_project_dir()

    # .claude/ integrity tripwire (ASK-282). Runs BEFORE the daily sentinel,
    # deliberately.
    #
    # SCAR (review finding, round 2): round 1 put this call after the
    # already_ran_today() gate. That gate keys on /tmp/q-session-<date>, which is
    # machine-wide and NOT repo-scoped -- so the tripwire ran at most once per
    # calendar day, and whichever repo opened a session first that day consumed
    # the sentinel for every other repo. In this repo it could have run never.
    # A security check gated behind a briefing's noise-suppression sentinel is
    # not armed; it is decorative. The briefing is what should be rate-limited,
    # not the tripwire.
    #
    # --check, NOT --enforce: a change found at session start has no attribution
    # and could be the founder's own editor between sessions. Auto-reverting an
    # unattributed change would eat his work. The PostToolUse entry (proposal,
    # PR #63) is the one that enforces, because there the actor IS the agent.
    integrity_warning = check_claude_integrity(project_dir)
    if integrity_warning:
        print(integrity_warning)

    # Only run the briefing once per day
    if already_ran_today():
        sys.exit(0)

    # Gather context
    handoff = load_handoff(project_dir)
    cards, yesterday = load_yesterday_cards(project_dir)
    morning_status = load_today_log(project_dir)
    loops_result = load_open_loops(project_dir)

    # Format and output
    output = format_output(handoff, cards, yesterday, morning_status, loops_result)

    if output:
        # Mark as ran BEFORE printing (so even if output is ignored, we don't repeat)
        mark_ran()
        print(output)
    else:
        mark_ran()

    sys.exit(0)


if __name__ == "__main__":
    main()
