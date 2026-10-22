#!/usr/bin/env python3
"""commit-msg gate: every commit names the Linear issue it belongs to.

Pairs with .claude/rules/linear-first.md. Wired as a lefthook `commit-msg`
command; git passes the path to the pending commit message as argv[1].

Exit 0 = allow, exit 1 = refuse the commit (git aborts).

Why a commit-msg gate rather than a session check: git is the one substrate
every kipi instance shares, and Linear already mints a stable id per issue.
A message is inspectable after the fact; "I opened Linear at some point during
the session" is not.

The escape hatch is deliberate but NOT free. `[no-issue: <reason>]` allows the
commit and appends it to a bypass ledger, so work landing outside Linear is
countable instead of invisible. A bypass hatch nobody can measure is just a
hole; the ledger is what turns it into a number the founder can look at.
"""
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

def team_keys() -> list:
    """The team keys that count as a Linear reference, from ONE place.

    That place is `KIPI_LINEAR_TEAM`, already the fleet's single convention for
    "which Linear team is this instance" -- alert-to-linear.py,
    spillover-promote.py, linear-triage-health.py and linear-route.py all read
    it with the same "ASK" default. Deriving the gate's prefix scope from it
    means the keys are never retyped here: an instance on another workspace is
    configured, not stranded, and a comma-separated value covers a repo that
    legitimately cites more than one team.
    """
    raw = os.environ.get("KIPI_LINEAR_TEAM", "ASK")
    keys = [k.strip().upper() for k in raw.split(",") if k.strip()]
    return keys or ["ASK"]


def issue_re(keys: list) -> "re.Pattern":
    """Match a declared team key + dash + number, and nothing else.

    Uppercase-only on purpose: lowercase "ask-61" in prose is not a reference.

    Scoped to declared keys because the old pattern was `[A-Z][A-Z0-9]{1,9}-\\d+`,
    which accepts ANY uppercase token followed by a dash and a number. Measured
    on this repo's history 2026-10-22: 16 commits cleared the gate citing no real
    issue, HEAD among them (`RULE-2026` out of `RULE-2026-10-20-A`), plus
    `UTF-8`, `SHA-256`, `DEC-30`, `PRD-2`, `PHASE-0`, `CRITICAL-1`. A denylist of
    those prefixes would have been the same bug pointed the other way: the next
    noise prefix passes silently. The live workspace has exactly one team, key
    ASK (teams query, 2026-10-22), so an undeclared prefix is noise by
    definition (ASK-2810).
    """
    alternation = "|".join(re.escape(k) for k in keys)
    return re.compile(r"\b(?:" + alternation + r")-\d+\b")


ISSUE_RE = issue_re(team_keys())

# [no-issue: reason] with a non-empty reason. An empty reason is not an escape.
BYPASS_RE = re.compile(r"\[no-issue:\s*(?P<reason>[^\]]*?)\s*\]", re.IGNORECASE)

# Messages git generates or that are mid-rebase machinery. Gating these would
# break merge, revert, and autosquash for no gain: they inherit their parent's
# provenance rather than representing new work.
SKIP_PREFIXES = ("merge ", "revert ", "fixup!", "squash!", "amend!")

DEFAULT_LEDGER = "q-system/output/linear-bypass.jsonl"


def repo_root() -> Path:
    """Resolve the repo root, falling back to cwd outside a git dir."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0 and out.stdout.strip():
            return Path(out.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return Path.cwd()


def strip_comments(text: str) -> str:
    """Drop git's own '#' comment lines and the scissors section."""
    lines = []
    for line in text.splitlines():
        if line.startswith("#"):
            continue
        if line.startswith("------------------------ >8"):
            break
        lines.append(line)
    return "\n".join(lines)


def ledger_path() -> Path:
    override = os.environ.get("LINEAR_BYPASS_LEDGER")
    if override:
        return Path(override)
    return repo_root() / DEFAULT_LEDGER


def record_bypass(reason: str, subject: str) -> None:
    """Append the bypass so it can be counted. Never block a commit on I/O."""
    entry = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "reason": reason,
        "subject": subject[:200],
    }
    try:
        path = ledger_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except OSError as exc:
        # A ledger that cannot be written is a real problem, but refusing the
        # commit over it would strand work. Say so loudly and let it through.
        print(f"linear-first: WARNING could not write bypass ledger: {exc}",
              file=sys.stderr)


def refuse(subject: str) -> int:
    keys = team_keys()
    print(
        "\nBLOCK: this commit names no Linear issue.\n"
        "\n"
        f"  subject: {subject or '(empty)'}\n"
        f"  team keys accepted: {', '.join(keys)}\n"
        "\n"
        "A token like RULE-2026-10-20-A, UTF-8 or PHASE-0 is NOT an issue id.\n"
        "On another Linear workspace, declare its key:\n"
        "  export KIPI_LINEAR_TEAM=ASK,<YOUR-KEY>\n"
        "\n"
        "Every commit records the work it belongs to. Pick one:\n"
        "\n"
        "  1. Add the issue id anywhere in the message:\n"
        "       fix(gate): restamp classifier (ASK-61)\n"
        "\n"
        "  2. No issue yet? Create one, then reference it.\n"
        "\n"
        "  3. Genuinely not issue-worthy (typo, formatting):\n"
        "       chore: fix typo [no-issue: docs typo]\n"
        "     This is logged to the bypass ledger, not waved through.\n",
        file=sys.stderr,
    )
    return 1


def main(argv: list) -> int:
    if len(argv) < 2:
        return 0

    msg_file = Path(argv[1])
    try:
        raw = msg_file.read_text(encoding="utf-8")
    except OSError:
        # No message file to inspect: not this gate's business to fail the commit.
        return 0

    body = strip_comments(raw).strip()
    if not body:
        # An empty message aborts the commit in git anyway.
        return 0

    subject = body.splitlines()[0].strip()

    if subject.lower().startswith(SKIP_PREFIXES):
        return 0

    if ISSUE_RE.search(body):
        return 0

    bypass = BYPASS_RE.search(body)
    if bypass:
        reason = bypass.group("reason").strip()
        if reason:
            record_bypass(reason, subject)
            print(f"linear-first: bypass recorded ({reason})")
            return 0
        print("linear-first: [no-issue:] needs a reason.", file=sys.stderr)
        return refuse(subject)

    return refuse(subject)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
