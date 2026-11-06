#!/usr/bin/env python3
"""Tests for rca-lint.py's recurrence check (ASK-2541).

Driven the way the plugin's hooks.json drives it: a PostToolUse JSON payload on
stdin to the script as a subprocess. Importing the module would skip the hook
entry point, and a guard tested away from its caller's shape proves nothing
about the caller.

Every fixture lives under pytest's tmp_path. No test reads a real RCA corpus.

Why this exists: an RCA's root cause matched an earlier RCA's action items
(a gate, a scanner, one fresh agent per task) and the new RCA only half-said
which earlier action had failed. A recurrence nobody names gets fixed a third
time the same way.
"""
import json
import subprocess
import sys
from pathlib import Path

LINT = Path(__file__).with_name("rca-lint.py")

# Dates sit after the lint's grandfather cutoff, so the check is live for them.
OLD_DATE = "2030-01-01"
NEW_DATE = "2030-02-01"


def rca(title, date, surface, structural, actions, extra=""):
    acts = "\n".join(f"- [ ] {a} Owner: ops. Type: code" for a in actions)
    return f"""# RCA: {title}

**Date:** {date}
**Trigger:** a failing run

## What happened

Something broke in production.

## Surface symptom

A log line showed the failure.

## Surface root cause

{surface}

## Structural root cause

### Root cause #1: the structural cause
type: process

{structural}

## Verification

Ran the reproducer and got a green result.

## Contributing factors

- none worth naming

## Fixes shipped

- Surface fix: pending
{extra}
## Action items

{acts}

## Lessons

- keep it short
"""


# The earlier RCA: its action items name a throttle wrapper, a nightly sweeper
# and a quota ledger.
OLD = rca(
    "widget exporter burned the quota",
    OLD_DATE,
    "The widget exporter called the remote renderer with no throttle.",
    "Nothing bounded renderer calls per job.",
    [
        "Build `quota_throttle` wrapper with a per-job renderer budget and a quota ledger row per call.",
        "Ship a nightly sweeper that lists every renderer call site not routed through `quota_throttle`.",
        "Unrelated chore: rotate the backup bucket keys.",
    ],
)

# The new RCA: its root cause is the same throttle, sweeper and ledger failing.
NEW_SURFACE = (
    "The exporter bypassed `quota_throttle` through an early return, so no quota ledger row was written."
)
NEW_STRUCTURAL = (
    "The nightly sweeper counted a renderer call site as routed through `quota_throttle` by reading "
    "source. The per-job renderer budget never saw the call, and the quota ledger stayed empty."
)

# Fillers give the matcher a corpus to judge rarity against: words every RCA
# shares are not evidence of a recurrence.
FILLERS = [
    rca("css cache served stale styles", "2029-11-01",
        "The stylesheet hash was not part of the cache key.",
        "Cache keys were assembled by hand in three places.",
        ["Derive the stylesheet cache key from one helper.", "Add a stale-style browser test."]),
    rca("timezone parse shifted invoices", "2029-11-02",
        "Invoice dates were parsed as local time.",
        "No contract said which timezone the invoice feed used.",
        ["Parse invoice dates as UTC at the feed boundary.", "Add a DST-boundary invoice test."]),
    rca("disk filled during image import", "2029-11-03",
        "The image importer kept temp files after each batch.",
        "Temp cleanup ran only on success.",
        ["Clean importer temp files in a finally block.", "Alert when free disk drops under ten percent."]),
]

RECURRENCE_OK = """
## Recurrence

Earlier RCA: rca-widget-quota-2030-01-01.md. Its actions failed as follows.

- Action `quota_throttle` wrapper with a per-job renderer budget: marked built, but the exporter returns before the wrapper, so it never ran on the real path.
- Action nightly sweeper of renderer call sites: shipped, but it read source instead of watching one real call, so it reported the bypass as routed.
"""


def setup_corpus(tmp_path, new_text, new_name=f"rca-widget-again-{NEW_DATE}.md"):
    d = tmp_path / "q-system" / "output" / "rca"
    d.mkdir(parents=True)
    (d / f"rca-widget-quota-{OLD_DATE}.md").write_text(OLD)
    for i, f in enumerate(FILLERS):
        (d / f"rca-filler-{i}-2029-11-0{i + 1}.md").write_text(f)
    target = d / new_name
    target.write_text(new_text)
    return target


def run_hook(path):
    payload = {"tool_name": "Write", "tool_input": {"file_path": str(path)}}
    p = subprocess.run([sys.executable, str(LINT)], input=json.dumps(payload),
                       capture_output=True, text=True, timeout=60)
    return p.returncode, p.stderr


def new_rca(date=NEW_DATE, extra="", surface=NEW_SURFACE, structural=NEW_STRUCTURAL):
    return rca("widget exporter burned the quota again", date, surface, structural,
               ["Move the throttle above the early return.", "Add a runtime test."], extra=extra)


def test_recurring_rca_without_recurrence_section_is_blocked(tmp_path):
    target = setup_corpus(tmp_path, new_rca())
    code, err = run_hook(target)
    assert code == 2, err
    assert "recurrence" in err.lower()
    assert f"rca-widget-quota-{OLD_DATE}.md" in err
    assert "quota_throttle" in err  # the matched action is named
    assert "rotate the backup bucket" not in err  # an unmatched action is not


def test_recurrence_section_naming_file_and_each_action_passes(tmp_path):
    target = setup_corpus(tmp_path, new_rca(extra=RECURRENCE_OK))
    code, err = run_hook(target)
    assert code == 0, err


def test_recurrence_section_missing_one_action_is_blocked(tmp_path):
    partial = "\n".join(RECURRENCE_OK.splitlines()[:-1]) + "\n"  # drops the sweeper line
    target = setup_corpus(tmp_path, new_rca(extra=partial))
    code, err = run_hook(target)
    assert code == 2, err
    assert "sweeper" in err


def test_one_line_cannot_answer_two_actions(tmp_path):
    # One vague line that brushes both actions' vocabulary is not a per-action
    # answer. Each line answers at most one action.
    lumped = (f"\n## Recurrence\n\nEarlier RCA: rca-widget-quota-{OLD_DATE}.md.\n\n"
              "- The `quota_throttle` wrapper, per-job renderer budget and nightly sweeper "
              "of call sites all failed somehow.\n")
    target = setup_corpus(tmp_path, new_rca(extra=lumped))
    code, err = run_hook(target)
    assert code == 2, err
    assert "recurrence-action-unanswered" in err


def test_recurrence_section_without_earlier_file_name_is_blocked(tmp_path):
    unnamed = RECURRENCE_OK.replace(f"rca-widget-quota-{OLD_DATE}.md", "the earlier one")
    target = setup_corpus(tmp_path, new_rca(extra=unnamed))
    code, err = run_hook(target)
    assert code == 2, err
    assert f"rca-widget-quota-{OLD_DATE}.md" in err


def test_unrelated_rca_is_not_flagged(tmp_path):
    # Negative control: a clean RCA that shares no root cause must pass, or a
    # red above could mean the matcher flags everything.
    target = setup_corpus(tmp_path, new_rca(
        surface="The PDF footer font was missing from the print container.",
        structural="Fonts were installed by a manual step nobody scripted."))
    code, err = run_hook(target)
    assert code == 0, err


def test_grandfathered_rca_is_not_checked(tmp_path):
    target = setup_corpus(tmp_path, new_rca(date="2020-01-01"),
                          new_name="rca-widget-again-2020-01-01.md")
    code, err = run_hook(target)
    assert code == 0, err


def test_only_earlier_rcas_count(tmp_path):
    # The matching RCA is dated AFTER the new one, so it cannot be a recurrence.
    target = setup_corpus(tmp_path, new_rca(date="2029-12-01"),
                          new_name="rca-widget-again-2029-12-01.md")
    code, err = run_hook(target)
    assert code == 0, err


def test_four_shared_terms_never_match_however_large_the_dir(tmp_path):
    # PR 527 review: a pair-unique term weighs ln(n+2), so in a big directory
    # a few shared identifiers summed past the score and blocked an unrelated
    # RCA. Exactly 4 shared terms per action, 20 unrelated siblings: no match.
    target = setup_corpus(tmp_path, new_rca(
        surface="A renderer budget mismatch inside the quota_throttle wrapper.",
        structural="The nightly sweeper started late."))
    for i in range(20):
        w = f"zeta{i}word"
        (target.parent / f"rca-bulk-{i}-2029-10-01.md").write_text(rca(
            f"bulk {w}", "2029-10-01", f"The {w} failed.", f"No owner for {w}.",
            [f"Fix the {w} first.", f"Test the {w} again."]))
    code, err = run_hook(target)
    assert code == 0, err


def test_heading_with_suffix_still_counts(tmp_path):
    suffixed = RECURRENCE_OK.replace("## Recurrence", "## Recurrence (ASK-1)")
    target = setup_corpus(tmp_path, new_rca(extra=suffixed))
    code, err = run_hook(target)
    assert code == 0, err


def test_undated_rca_is_still_checked(tmp_path):
    undated = new_rca().replace(f"**Date:** {NEW_DATE}\n", "")
    target = setup_corpus(tmp_path, undated, new_name="rca-widget-again.md")
    code, err = run_hook(target)
    assert code == 2, err
    assert "recurrence-unnamed" in err


def test_same_day_follow_up_is_checked(tmp_path):
    import os
    target = setup_corpus(tmp_path, new_rca(date=OLD_DATE),
                          new_name=f"rca-widget-again-{OLD_DATE}.md")
    old = target.parent / f"rca-widget-quota-{OLD_DATE}.md"
    os.utime(old, (1_000_000_000, 1_000_000_000))  # written before the follow-up
    code, err = run_hook(target)
    assert code == 2, err
    assert "recurrence-unnamed" in err


def test_recurrence_skip_only_skips_recurrence(tmp_path):
    marker = "\n<!-- rca-recurrence-skip -->\n"
    target = setup_corpus(tmp_path, new_rca() + marker)
    code, err = run_hook(target)
    assert code == 0, err
    # The other checks still run under the recurrence-only marker.
    broken = new_rca().replace("## Verification", "## Notes") + marker
    target.write_text(broken)
    code, err = run_hook(target)
    assert code == 2, err
    assert "Verification" in err and "[recurrence-" not in err


def test_skip_marker_still_bypasses(tmp_path):
    target = setup_corpus(tmp_path, new_rca() + "\n<!-- rca-lint-skip -->\n")
    code, err = run_hook(target)
    assert code == 0, err
