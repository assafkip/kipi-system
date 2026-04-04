#!/usr/bin/env python3
"""
Post-execution audit for /q-morning.
Checks: step completion, gate compliance, action cards,
state file drift, and verification queue.

Usage:
  python3 audit-morning.py <morning-log-YYYY-MM-DD.json>
"""

import json
import sys
from datetime import datetime


def audit(log_path):
    with open(log_path) as f:
        log = json.load(f)

    day_of_week = datetime.strptime(log['date'], '%Y-%m-%d').strftime('%A').lower()
    steps = log.get('steps', {})
    action_cards = log.get('action_cards', [])
    checksums = log.get('state_checksums', {})
    verifications = log.get('verification_queue', [])
    gates = log.get('gates_checked', {})

    issues = []

    # ── 1. STEP COMPLETION ──────────────────────────────────────────
    expected = {
        "0f_connection_check", "0a_checkpoint", "0b_missed_debrief",
        "0b.5_loop_escalation",
        "0c_load_canonical", "0d_load_voice", "0e_load_audhd",
        "1_calendar", "1_gmail", "1_notion_actions", "1_notion_pipeline",
        "3_linkedin_activity", "3.5_dp_pipeline",
        "3.8_dm_check", "5.8_temperature_scoring",
        "5.85_pipeline_followup",
        "5.86_loop_review",
        "5.9_lead_sourcing", "5.9b_engagement_hitlist",
        "6_decision_compliance", "7_positioning_freshness",
        "8_briefing_output", "8.5_start_here",
        "9_notion_push", "10_daily_checklists", "11_html_output",
        # Script-generated steps
        "0c_canonical_digest",
        "6_sycophancy_audit"
    }

    if day_of_week == 'monday':
        expected.add("3.7_content_intel")

    # Day-specific content sub-steps (replaces monolithic 4_signals / 4_content)
    # Mon/Wed/Fri: signals LinkedIn, X signals, X hot take, X BTS
    # Tue/Thu: TL LinkedIn, TL X
    # Mon (additional): Medium draft
    # Fri (additional): Medium draft
    if day_of_week in ('monday', 'wednesday', 'friday'):
        expected.update({
            "4_signals_linkedin",
            "4_x_signals",
            "4_x_hot_take",
            "4_x_bts",
        })
    if day_of_week in ('tuesday', 'thursday'):
        expected.update({
            "4_tl_linkedin",
            "4_tl_x",
        })
    if day_of_week == 'wednesday':
        pass  # No Wednesday-only required steps currently
    if day_of_week == 'monday':
        expected.add("4_medium_draft")

    # Legacy: accept old monolithic step names as equivalent
    # If 4_signals is logged as done, treat it as satisfying 4_signals_linkedin only
    # (the other sub-steps still need their own entries)
    legacy_content_steps = {"4_signals", "4_content"}

    # 4.1 value drops moved to required (was optional, but it's a warm pipeline nurturing step)
    expected.add("4.1_value_drops")

    optional = {
        "1_vc_pipeline", "1.5_warm_intro", "2.5_x_activity",
        "3.2_publish_reconciliation", "4.5_marketing_health",
        "0g_monthly_checks", "9.5_investor_update_check", "7.5_checkpoint_drift",
        "2_meeting_prep",
        # Script-generated (may not run every day)
        "1c_copy_diff",
        # Legacy steps without agent equivalents (Monday-only, not yet migrated)
        "5_site_metrics", "5.5_prospect_tracking"
    }

    completed = {k for k, v in steps.items() if v.get('status') == 'done'}
    failed = {k for k, v in steps.items() if v.get('status') == 'failed'}
    skipped = {k for k, v in steps.items() if v.get('status') == 'skipped'}
    partial = {k for k, v in steps.items() if v.get('status') == 'partial'}
    not_logged = expected - completed - failed - skipped - partial

    total_required = len(expected)
    total_done = len(completed & expected)

    print()
    print("=" * 60)
    print(f"  MORNING ROUTINE AUDIT - {log['date']} ({day_of_week.title()})")
    print("=" * 60)

    # Step summary
    print(f"\n  1. STEP COMPLETION")
    print(f"     Required: {total_required} | Done: {total_done} | "
          f"Failed: {len(failed)} | Partial: {len(partial)} | "
          f"Skipped: {len(skipped)} | Missing: {len(not_logged)}")

    if failed:
        print(f"\n     FAILED:")
        for s in sorted(failed):
            err = steps[s].get('error', 'unknown')
            print(f"       [FAIL] {s}: {err}")
            issues.append(f"Step {s} failed: {err}")

    if not_logged:
        print(f"\n     NEVER ATTEMPTED (silently skipped):")
        for s in sorted(not_logged):
            print(f"       [MISSING] {s}")
            issues.append(f"Step {s} silently skipped")

    if partial:
        print(f"\n     PARTIAL:")
        for s in sorted(partial):
            print(f"       [PARTIAL] {s}: {steps[s].get('result', '')}")
            issues.append(f"Step {s} only partially completed")

    required_skipped = skipped & expected
    if required_skipped:
        print(f"\n     SKIPPED (required):")
        for s in sorted(required_skipped):
            reason = steps.get(s, {}).get('error', 'no reason')
            print(f"       [SKIP] {s}: {reason}")

    # ── 2. GATE COMPLIANCE ──────────────────────────────────────────
    print(f"\n  2. GATE COMPLIANCE")
    gate_steps = {"step_8": "8_briefing_output", "step_9": "9_notion_push", "step_11": "11_html_output"}
    gates_ok = True

    for gate_name, gate_step in gate_steps.items():
        gate_data = gates.get(gate_name, {})
        if not gate_data:
            if gate_step in completed or gate_step in partial:
                print(f"     [FAIL] {gate_name}: Gate step ran but NO gate check was logged")
                issues.append(f"{gate_name} ran without gate check")
                gates_ok = False
            else:
                print(f"     [SKIP] {gate_name}: Step didn't run")
        elif gate_data.get('checked'):
            if gate_data.get('all_prior_done'):
                print(f"     [PASS] {gate_name}: All prior steps verified")
            else:
                missing = gate_data.get('missing', [])
                print(f"     [WARN] {gate_name}: Proceeded with missing steps: {', '.join(missing)}")
                issues.append(f"{gate_name} proceeded despite missing: {', '.join(missing)}")
                gates_ok = False
        else:
            print(f"     [FAIL] {gate_name}: Not checked")
            issues.append(f"{gate_name} gate not checked")
            gates_ok = False

    if not gates:
        print(f"     [FAIL] No gate checks recorded at all")
        issues.append("No gate checks recorded")
        gates_ok = False

    # ── 3. ACTION CARDS ─────────────────────────────────────────────
    print(f"\n  3. ACTION CARDS")
    if action_cards:
        delivered = [c for c in action_cards if c.get('card_delivered')]
        confirmed = [c for c in action_cards if c.get('founder_confirmed')]
        unconfirmed = [c for c in action_cards if c.get('card_delivered') and not c.get('founder_confirmed')]
        print(f"     Total: {len(action_cards)} | Delivered: {len(delivered)} | "
              f"Confirmed: {len(confirmed)} | Pending: {len(unconfirmed)}")

        if unconfirmed:
            print(f"\n     PENDING CONFIRMATION (ask founder next session):")
            for c in unconfirmed:
                print(f"       [{c['id']}] {c['type']}: {c['target']}")
    else:
        print(f"     No action cards recorded")
        if total_done > 10:
            print(f"     [WARN] {total_done} steps completed but 0 action cards. "
                  f"Were founder-facing outputs created without tracking?")
            issues.append("No action cards despite significant step completion")

    # ── 4. STATE FILE DRIFT ─────────────────────────────────────────
    print(f"\n  4. STATE FILE CHECKSUMS")
    start_checksums = checksums.get('session_start', {})
    end_checksums = checksums.get('session_end', {})
    drift = checksums.get('drift_detected', [])

    if not start_checksums:
        print(f"     [FAIL] No session-start checksums recorded")
        issues.append("State file checksums not captured at session start")
    elif not end_checksums:
        print(f"     [WARN] Session-start recorded but no session-end checksums")
        issues.append("State file checksums not captured at session end")
    else:
        changes = 0
        for key in start_checksums:
            start_val = start_checksums.get(key)
            end_val = end_checksums.get(key)
            if start_val != end_val:
                changes += 1
        print(f"     Fields tracked: {len(start_checksums)} | Changed: {changes}")

    if drift:
        print(f"     Drift detected:")
        for d in drift:
            print(f"       - {d}")

    # ── 5. VERIFICATION QUEUE ───────────────────────────────────────
    print(f"\n  5. VERIFICATION QUEUE")
    if verifications:
        verified = [v for v in verifications if v.get('verified')]
        unverified = [v for v in verifications if not v.get('verified')]
        print(f"     Total: {len(verifications)} | Verified: {len(verified)} | "
              f"Unverified: {len(unverified)}")
        if unverified:
            print(f"\n     UNVERIFIED CLAIMS (carry to next session):")
            for v in unverified:
                print(f"       - {v['claim']} (from {v.get('source_file', 'unknown')})")
                issues.append(f"Unverified: {v['claim']}")
    else:
        print(f"     No verification items")

    # ── VERDICT ─────────────────────────────────────────────────────
    pct = total_done / total_required * 100 if total_required > 0 else 0

    if not not_logged and not failed and not partial and gates_ok:
        verdict = "COMPLETE"
        icon = "OK"
    elif pct >= 80 and not failed:
        verdict = "MOSTLY COMPLETE"
        icon = "WARN"
    elif pct >= 50:
        verdict = "PARTIAL"
        icon = "WARN"
    else:
        verdict = "INCOMPLETE"
        icon = "FAIL"

    print()
    print("-" * 60)
    print(f"  VERDICT: [{icon}] {verdict} ({total_done}/{total_required} = {pct:.0f}%)")
    if issues:
        print(f"  ISSUES:  {len(issues)}")
    print("-" * 60)

    if issues:
        print(f"\n  Issue Summary:")
        for i, issue in enumerate(issues[:10], 1):
            print(f"    {i}. {issue}")
        if len(issues) > 10:
            print(f"    ... and {len(issues) - 10} more")

    if verdict != "COMPLETE":
        print(f"\n  Next steps:")
        if not_logged:
            print(f"    - {len(not_logged)} steps silently skipped. Re-run or explicitly skip.")
        if failed:
            print(f"    - {len(failed)} steps failed. Fix errors and retry.")
        unconfirmed_cards = [c for c in action_cards if c.get('card_delivered') and not c.get('founder_confirmed')]
        if unconfirmed_cards:
            print(f"    - {len(unconfirmed_cards)} action cards pending founder confirmation.")

    print()
    return verdict


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python3 audit-morning.py <morning-log-YYYY-MM-DD.json>")
        print("Example: python3 audit-morning.py q-system/output/morning-log-2026-03-13.json")
        sys.exit(1)
    verdict = audit(sys.argv[1])
    sys.exit(0 if verdict == "COMPLETE" else 1)
