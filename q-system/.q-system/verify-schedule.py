#!/usr/bin/env python3
"""
Schedule JSON Verification Script.

Runs BEFORE the HTML build. If verification fails, the build is blocked.
This is the external executive function for the LLM - it doesn't trust
self-reported completion. It checks the actual output.

Called by build-schedule.py automatically.
Can also be run standalone: python3 verify-schedule.py <json-file> [day_of_week]

Exit codes:
  0 = all checks pass, safe to build HTML
  1 = verification failed, HTML build blocked

Based on research:
- "Lost in the Middle" (Stanford 2023) - LLMs forget mid-context instructions
- "Context Degradation Syndrome" - performance drops in long sessions
- Solution: external verification, not self-checking
"""

import json
import sys
from datetime import datetime


def load_schedule(path):
    with open(path) as f:
        return json.load(f)


def get_section(data, section_id):
    for s in data.get("sections", []):
        if s.get("id") == section_id:
            return s
    return None


def count_items(section):
    if not section:
        return 0
    return len(section.get("items", []))


def items_have_copy(section):
    """Check that items have actual copy-paste text, not empty copyBlocks."""
    if not section:
        return False, []
    missing = []
    for item in section.get("items", []):
        blocks = item.get("copyBlocks", [])
        has_text = any(b.get("text", "").strip() for b in blocks)
        needs_eyes = item.get("needsEyes")
        # Items with needsEyes are allowed to skip copyBlocks
        if not has_text and not needs_eyes:
            missing.append(item.get("id", "?"))
    return len(missing) == 0, missing


def verify(data, day):
    errors = []
    warnings = []

    # 1. Basic structure
    if not data.get("date"):
        errors.append("Missing 'date' field")
    if not data.get("sections"):
        errors.append("Missing 'sections' array")
        return errors, warnings  # can't check anything else

    section_ids = [s.get("id") for s in data["sections"]]

    # 2. Pipeline follow-ups (EVERY DAY)
    pf = get_section(data, "pipeline-followups")
    if not pf:
        errors.append("MISSING SECTION: 'pipeline-followups'. Step 5.85 was not completed. "
                      "Must query Notion for warm/active contacts with Last Contact > 7 days "
                      "and generate follow-up copy for at least 3.")
    else:
        count = count_items(pf)
        if count < 3:
            errors.append(f"Pipeline follow-ups has {count} items (minimum 3 required). "
                         f"Query Notion Contacts DB for warm/active contacts needing follow-up.")
        ok, missing = items_have_copy(pf)
        if not ok:
            errors.append(f"Pipeline follow-up items {missing} have no copy-paste text. "
                         f"Every follow-up needs a pre-written DM or email.")

    # 3. Quick wins (EVERY DAY)
    qw = get_section(data, "quick-wins")
    if not qw:
        warnings.append("No 'quick-wins' section. Usually there's at least 1 quick win.")
    elif count_items(qw) == 0:
        warnings.append("Quick wins section is empty.")

    # 4. Day-specific content checks
    if day in ("monday", "wednesday", "friday"):
        # Signals day: need signals LinkedIn + X signals + X hot take + X BTS
        found_signals = any("signal" in (s.get("id", "") + str(s.get("title", ""))).lower()
                          for s in data["sections"])
        found_x = any("x-post" in s.get("id", "") or "x post" in str(s.get("title", "")).lower()
                      for s in data["sections"])
        if not found_signals and not found_x:
            # Check inside existing sections for signal posts
            has_signal_item = False
            for s in data["sections"]:
                for item in s.get("items", []):
                    title = str(item.get("title", "")).lower()
                    if "signal" in title:
                        has_signal_item = True
                        break
            if not has_signal_item:
                errors.append(f"MISSING CONTENT: Monday/Wednesday/Friday requires signals post. "
                             f"No signals content found in any section.")

    if day in ("tuesday", "thursday"):
        # TL day: need thought leadership LinkedIn + X
        has_tl_item = False
        for s in data["sections"]:
            for item in s.get("items", []):
                title = str(item.get("title", "")).lower()
                platform = str(item.get("platform", "")).lower()
                if ("tl" in title or "thought leadership" in title or
                    "adhd" in title or "linkedin post" in title) and platform == "linkedin":
                    has_tl_item = True
                    break
        if not has_tl_item:
            errors.append(f"MISSING CONTENT: Tuesday/Thursday requires thought leadership LinkedIn post. "
                         f"No TL post found in any section.")

    if day == "monday":
        # Monday additional: Medium draft
        has_medium = False
        for s in data["sections"]:
            for item in s.get("items", []):
                if "medium" in str(item.get("title", "")).lower():
                    has_medium = True
                    break
        if not has_medium:
            warnings.append("Monday: No Medium draft found. Check if one is needed.")

    if day == "wednesday":
        # Wednesday: Kipi System promo post
        has_kipi = False
        for s in data["sections"]:
            for item in s.get("items", []):
                if "kipi" in str(item.get("title", "")).lower():
                    has_kipi = True
                    break
        if not has_kipi:
            warnings.append("Wednesday: No Kipi System promo post found.")

    # 5. Section ordering check
    expected_order = [
        "quick-wins", "open-loops", "pipeline-followups",
        "linkedin-engagement", "new-leads", "x-replies",
        "reddit-comments", "posts", "x-post", "x-posts",
        "medium-draft", "emails", "people", "overdue-triage",
        "compliance", "fyi", "signals-digest"
    ]
    # Check that pipeline-followups comes before new-leads if both exist
    if "pipeline-followups" in section_ids and "new-leads" in section_ids:
        pf_idx = section_ids.index("pipeline-followups")
        nl_idx = section_ids.index("new-leads")
        if pf_idx > nl_idx:
            errors.append("Section ordering: pipeline-followups must come BEFORE new-leads. "
                         "Follow-ups close deals. New leads are exciting distractions.")

    # 6. Every item should have an energy tag
    for s in data["sections"]:
        for item in s.get("items", []):
            if not item.get("energy"):
                warnings.append(f"Item {item.get('id','?')} in section {s.get('id','?')} "
                              f"has no energy tag.")

    return errors, warnings


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 verify-schedule.py <schedule-data.json> [day_of_week]")
        sys.exit(1)

    path = sys.argv[1]

    try:
        data = load_schedule(path)
    except (json.JSONDecodeError, FileNotFoundError) as e:
        print(f"VERIFY FAILED: Cannot read {path}: {e}")
        sys.exit(1)

    # Determine day of week
    if len(sys.argv) > 2:
        day = sys.argv[2].lower()
    else:
        date_str = data.get("date", "")
        if date_str:
            day = datetime.strptime(date_str, "%Y-%m-%d").strftime("%A").lower()
        else:
            day = datetime.now().strftime("%A").lower()

    errors, warnings = verify(data, day)

    # Output
    if warnings:
        for w in warnings:
            print(f"  [WARN] {w}")

    if errors:
        print()
        print("=" * 60)
        print("  VERIFICATION FAILED - HTML BUILD BLOCKED")
        print("=" * 60)
        print()
        for e in errors:
            print(f"  [FAIL] {e}")
        print()
        print(f"  {len(errors)} error(s). Fix these before building HTML.")
        print("  The LLM cannot self-authorize bypassing this check.")
        print()
        sys.exit(1)
    else:
        print(f"  VERIFIED: {day.title()} schedule passes all checks. "
              f"({len(warnings)} warning(s))")
        sys.exit(0)


if __name__ == "__main__":
    main()
