#!/usr/bin/env python3
"""
Deterministic schedule synthesis. Replaces the 07-synthesize.md Opus agent.

Reads all bus/{date}/*.json files, applies section ordering, friction sorting,
todayFocus selection, post visual attachment, sycophancy surfacing, and investor
update triggers. Writes output/schedule-data-{date}.json.

Usage:
    python3 synthesize-schedule.py <date>

Exit codes: 0 = success, 1 = no bus directory, 2 = schema validation failed
"""

import json
import os
import re
import sys
from datetime import datetime, timedelta
from glob import glob

QROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
BUS_BASE = os.path.join(QROOT, ".q-system", "agent-pipeline", "bus")
SCHEMA_DIR = os.path.join(QROOT, ".q-system", "agent-pipeline", "schemas")
OUTPUT_DIR = os.path.join(QROOT, "output")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_bus(bus_dir, filename):
    """Load a bus JSON file. Returns None if missing."""
    path = os.path.join(bus_dir, filename)
    if not os.path.isfile(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def load_schema(name):
    """Load a JSON Schema file from schemas/."""
    path = os.path.join(SCHEMA_DIR, name)
    if not os.path.isfile(path):
        return None
    with open(path) as f:
        return json.load(f)


def validate_schedule(data, schema):
    """Basic schema validation (required fields, types). No jsonschema dependency."""
    errors = []
    for field in schema.get("required", []):
        if field not in data:
            errors.append(f"Missing required field: {field}")
    if "sections" in data and not isinstance(data["sections"], list):
        errors.append("sections must be an array")
    for i, section in enumerate(data.get("sections", [])):
        for field in ["id", "title", "accent"]:
            if field not in section:
                errors.append(f"Section {i}: missing {field}")
        for j, item in enumerate(section.get("items", [])):
            for field in ["id", "title", "energy", "time"]:
                if field not in item:
                    errors.append(f"Section {i} item {j}: missing {field}")
            if item.get("energy") not in ("quickwin", "deepfocus", "people", "admin"):
                errors.append(f"Section {i} item {j}: invalid energy '{item.get('energy')}'")
    return errors


# Friction sort key: lower = do first
FRICTION_ORDER = {
    "reply": 0,
    "DM": 1,
    "comment": 2,
    "connection_request": 3,
    "email": 4,
    "followup": 5,
    "outreach": 6,
}


def friction_key(item):
    """Sort items by friction (lowest first), then by time estimate."""
    action_type = item.get("_action_type", "outreach")
    base = FRICTION_ORDER.get(action_type, 6)
    # Parse time estimate for secondary sort
    time_str = item.get("time", "10 min")
    minutes = int(re.search(r"(\d+)", time_str).group(1)) if re.search(r"(\d+)", time_str) else 10
    return (base, minutes)


def make_item(id_, title, energy, time, platform=None, badge=None,
              context=None, links=None, copy_blocks=None, needs_eyes=None,
              extra_tags=None, days_ago=None, action_type="outreach"):
    """Build a schedule item dict."""
    item = {
        "id": id_,
        "title": title,
        "energy": energy,
        "time": time,
    }
    if platform:
        item["platform"] = platform
    if badge:
        item["badge"] = badge
    if extra_tags:
        item["extraTags"] = extra_tags
    if days_ago:
        item["daysAgo"] = days_ago
    if context:
        item["context"] = context
    if links:
        item["links"] = links
    if copy_blocks:
        item["copyBlocks"] = copy_blocks
    if needs_eyes:
        item["needsEyes"] = needs_eyes
    # Internal field for sorting, stripped before output
    item["_action_type"] = action_type
    return item


def strip_internal(items):
    """Remove internal fields before output."""
    for item in items:
        item.pop("_action_type", None)
    return items


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def build_call_banners(calendar):
    """Build callBanners from calendar.json today events."""
    if not calendar:
        return []
    banners = []
    for evt in calendar.get("today", []):
        banner = {
            "time": evt.get("time", ""),
            "info": evt.get("title", ""),
        }
        if evt.get("link"):
            banner["detail"] = f"<a href='{evt['link']}'>{evt['link']}</a>"
        banners.append(banner)
    return banners


def build_meeting_prep(meeting_prep):
    """Build meetingPrep from meeting-prep.json."""
    if not meeting_prep:
        return []
    preps = []
    for mtg in meeting_prep.get("meetings", []):
        prep = mtg.get("prep", {})
        items = []
        if prep.get("who"):
            items.append(f"<strong>Who:</strong> {prep['who']}")
        last = prep.get("last_interaction")
        if last:
            items.append(f"<strong>Last:</strong> {last.get('date', '')} - {last.get('summary', '')}")
        for pt in prep.get("talk_points", []):
            items.append(pt)
        for oi in prep.get("open_items", []):
            items.append(f"<strong>Open:</strong> {oi}")
        preps.append({
            "title": f"PREP: {mtg.get('title', '')} - {mtg.get('time', '')}",
            "items": items,
        })
    return preps


def build_today_focus(calendar, pipeline_followup, client_deliverables, loop_review, date_str):
    """Build todayFocus as heads-up bar only. Cap 3 items. Sort by time."""
    items = []

    # Calls/meetings from calendar (time-sensitive)
    if calendar:
        for evt in calendar.get("today", []):
            items.append({
                "text": f"{evt.get('time', '')} - {evt.get('title', '')}",
                "time": evt.get("time", ""),
                "energy": "people",
                "_sort_time": evt.get("time", "99:99"),
            })

    # Deadlines from client-deliverables
    if client_deliverables:
        for d in client_deliverables.get("due_today", []):
            if isinstance(d, dict):
                items.append({
                    "text": f"Due today: {d.get('deliverable', d.get('client', 'deliverable'))}",
                    "time": "today",
                    "energy": "deepfocus",
                    "_sort_time": "00:00",
                })
        for d in client_deliverables.get("overdue", []):
            if isinstance(d, dict):
                items.append({
                    "text": f"Carried forward: {d.get('deliverable', '')} ({d.get('days_overdue', '?')} days)",
                    "time": "overdue",
                    "energy": "deepfocus",
                    "_sort_time": "00:01",
                })

    # Deadlines from pipeline-followup
    if pipeline_followup:
        for fu in pipeline_followup.get("followups", []):
            days = fu.get("days_since_last_contact", 0)
            if days and days >= 14:
                items.append({
                    "text": f"{fu.get('name', 'Contact')} - no reply {days} days",
                    "time": f"{days}d",
                    "energy": "people",
                    "_sort_time": "00:02",
                })

    # Loop escalations level 3+
    if loop_review:
        for loop in loop_review.get("stale_loops", []):
            if loop.get("level", 0) >= 3:
                items.append({
                    "text": f"Loop escalation: {loop.get('action_title', 'item')}",
                    "time": f"{loop.get('days_overdue', '?')}d overdue",
                    "energy": "admin",
                    "_sort_time": "00:03",
                })

    # Sort by time of day, cap at 3
    items.sort(key=lambda x: x.get("_sort_time", "99:99"))
    items = items[:3]

    # Strip internal sort key
    for item in items:
        item.pop("_sort_time", None)

    return items if items else None


def build_quick_wins(hitlist):
    """Quick Wins from hitlist.json - items that are quickwin energy."""
    if not hitlist:
        return []
    items = []
    for action in hitlist.get("actions", []):
        if action.get("action_type") == "comment":
            energy = "quickwin"
            time = "2 min"
        elif action.get("action_type") == "DM":
            energy = "quickwin"
            time = "3 min"
        elif action.get("action_type") == "connection_request":
            energy = "quickwin"
            time = "1 min"
        else:
            continue  # Non-quick items go to other sections

        copy_blocks = []
        label = action.get("action_type", "Comment").replace("_", " ").title()
        if action.get("copy"):
            copy_blocks.append({"label": label, "text": action["copy"]})

        links = []
        if action.get("post_url"):
            links.append({"text": "Open post", "url": action["post_url"]})
        elif action.get("profile_url"):
            links.append({"text": "Open profile", "url": action["profile_url"]})

        context_parts = []
        if action.get("contact_title"):
            context_parts.append(action["contact_title"])
        if action.get("rationale"):
            context_parts.append(action["rationale"])

        item = make_item(
            id_=f"H{action.get('rank', len(items)+1)}",
            title=f"{label}: {action.get('contact_name', 'Unknown')}",
            energy=energy,
            time=time,
            platform=action.get("platform"),
            context=" - ".join(context_parts) if context_parts else None,
            links=links if links else None,
            copy_blocks=copy_blocks if copy_blocks else None,
            action_type=action.get("action_type", "comment"),
        )
        items.append(item)
    items.sort(key=friction_key)
    # Cap at 8 items, overflow goes to LinkedIn Engagement
    items = items[:8]
    return items


def build_open_loops(loop_review):
    """Open Loops from loop-review.json - level 2+."""
    if not loop_review:
        return []
    items = []
    for loop in loop_review.get("stale_loops", []):
        if loop.get("level", 0) < 2:
            continue
        badge = "KEY" if loop.get("recommendation") == "force-close" else None
        item = make_item(
            id_=f"L{len(items)+1}",
            title=loop.get("action_title", "Stale loop"),
            energy="admin",
            time="3 min",
            days_ago=f"{loop.get('days_overdue', '?')} DAYS",
            context=f"Recommendation: {loop.get('recommendation', 'review')}. {loop.get('reason', '')}",
            badge=badge,
            needs_eyes=f"Review: {loop.get('recommendation', 'action needed')} - needs your eyes",
            action_type="followup",
        )
        items.append(item)
    return items


def build_pipeline_followups(pipeline_followup):
    """Pipeline Follow-ups from pipeline-followup.json."""
    if not pipeline_followup:
        return []
    items = []
    for fu in pipeline_followup.get("followups", []):
        copy_blocks = []
        if fu.get("message"):
            label = f"{fu.get('platform', 'Message')}"
            copy_blocks.append({"label": label, "text": fu["message"]})

        context_parts = []
        if fu.get("company"):
            context_parts.append(fu["company"])
        if fu.get("role"):
            context_parts.append(fu["role"])
        if fu.get("hook"):
            context_parts.append(fu["hook"])
        days = fu.get("days_since_last_contact")

        item = make_item(
            id_=f"PF{len(items)+1}",
            title=f"Follow up: {fu.get('name', 'Unknown')}",
            energy="people",
            time="5 min",
            platform=fu.get("platform"),
            days_ago=f"{days} DAYS" if days and days >= 7 else None,
            context=" - ".join(context_parts) if context_parts else None,
            copy_blocks=copy_blocks if copy_blocks else None,
            needs_eyes="No draft available - needs your eyes" if not copy_blocks else None,
            action_type="followup",
        )
        items.append(item)
    items.sort(key=friction_key)
    return items


def build_engagement(hitlist, quick_win_ids):
    """LinkedIn Engagement from hitlist.json - comment items that overflowed Quick Wins."""
    if not hitlist:
        return []
    items = []
    for action in hitlist.get("actions", []):
        item_id = f"H{action.get('rank', len(items)+1)}"
        if item_id in quick_win_ids:
            continue  # Already in Quick Wins
        if action.get("action_type") != "comment":
            continue

        copy_blocks = []
        if action.get("copy"):
            copy_blocks.append({"label": "Comment", "text": action["copy"]})

        links = []
        if action.get("post_url"):
            links.append({"text": "Open post", "url": action["post_url"]})

        context_parts = []
        if action.get("contact_title"):
            context_parts.append(action["contact_title"])
        if action.get("rationale"):
            context_parts.append(action["rationale"])

        item = make_item(
            id_=item_id,
            title=f"Comment: {action.get('contact_name', 'Unknown')}",
            energy="quickwin",
            time="2 min",
            platform=action.get("platform"),
            context=" - ".join(context_parts) if context_parts else None,
            links=links if links else None,
            copy_blocks=copy_blocks if copy_blocks else None,
            action_type="comment",
        )
        items.append(item)
    items.sort(key=friction_key)
    return items


def build_new_leads(leads, connection_mining):
    """New Leads from leads.json + connection-mining.json."""
    items = []

    if leads:
        for lead in leads.get("qualified_leads", []):
            if lead.get("tier") not in ("A", "B"):
                continue  # Only surface Tier A and B
            links = []
            if lead.get("post_url"):
                links.append({"text": "View post", "url": lead["post_url"]})
            if lead.get("author_profile_url"):
                links.append({"text": "Profile", "url": lead["author_profile_url"]})

            extra_tags = [{"text": f"TIER {lead.get('tier', '?')}", "color": "#ef4444" if lead["tier"] == "A" else "#f59e0b"}]

            item = make_item(
                id_=f"NL{len(items)+1}",
                title=f"New lead: {lead.get('author_name', 'Unknown')} ({lead.get('platform', '')})",
                energy="people",
                time="3 min",
                platform=lead.get("platform"),
                extra_tags=extra_tags,
                context=f"{lead.get('author_title', '')} - {lead.get('pain_category', '')}",
                links=links if links else None,
                needs_eyes="Review post and draft outreach" if not lead.get("post_full_text") else None,
                action_type="outreach",
            )
            items.append(item)

    if connection_mining:
        for match in connection_mining.get("matches", []):
            if match.get("approach") == "skip":
                continue
            copy_blocks = []
            if match.get("draft_dm"):
                copy_blocks.append({"label": "DM", "text": match["draft_dm"]})

            links = []
            if match.get("profile_url"):
                links.append({"text": "Profile", "url": match["profile_url"]})

            item = make_item(
                id_=f"CM{len(items)+1}",
                title=f"Connection: {match.get('name', 'Unknown')} - {match.get('approach', 'DM')}",
                energy="quickwin" if match.get("approach") == "comment-first" else "people",
                time="3 min",
                platform="LinkedIn",
                context=f"{match.get('headline', '')} - {match.get('why_match', '')}",
                links=links if links else None,
                copy_blocks=copy_blocks if copy_blocks else None,
                action_type="DM" if match.get("approach") == "DM" else "comment",
            )
            items.append(item)

    items.sort(key=friction_key)
    return items


def build_posts(signals, founder_brand_post, post_visuals):
    """Posts from signals.json + founder-brand-post.json, with visuals attached."""
    items = []
    visual_map = {}
    if post_visuals:
        for v in post_visuals.get("visuals", []):
            visual_map[v.get("post_source", "")] = v

    # LinkedIn post from signals
    if signals and signals.get("linkedin_draft"):
        copy_blocks = [{"label": "LinkedIn Post", "text": signals["linkedin_draft"]}]
        visual = visual_map.get("linkedin_draft") or visual_map.get("signals")
        needs_eyes = None
        if not visual:
            needs_eyes = "Visual generation not available - post manually or regenerate"

        item = make_item(
            id_="POST-LI",
            title=f"LinkedIn post: {signals.get('selected_signal', {}).get('title', 'signal post')}",
            energy="deepfocus",
            time="5 min",
            platform="LinkedIn",
            context=f"Signal: {signals.get('selected_signal', {}).get('source', '')}",
            links=[{"text": "Signal source", "url": signals.get("selected_signal", {}).get("url", "")}] if signals.get("selected_signal", {}).get("url") else None,
            copy_blocks=copy_blocks,
            needs_eyes=needs_eyes,
            action_type="outreach",
        )
        # Attach visuals to item
        if visual:
            item["visuals"] = {
                "recommended": visual.get("recommended_format"),
                "heroImage": visual.get("hero_image"),
                "carousel": visual.get("carousel"),
                "socialCard": visual.get("social_card_fallback"),
            }
        items.append(item)

    # X post
    if signals and signals.get("x_draft"):
        copy_blocks = [{"label": "X Post", "text": signals["x_draft"]}]
        item = make_item(
            id_="POST-X",
            title="X post: signal reaction",
            energy="quickwin",
            time="2 min",
            platform="X",
            copy_blocks=copy_blocks,
            action_type="outreach",
        )
        items.append(item)

    # Reddit comment
    if signals and signals.get("reddit_draft") and isinstance(signals["reddit_draft"], dict):
        rd = signals["reddit_draft"]
        copy_blocks = [{"label": f"Reddit comment in {rd.get('subreddit', 'subreddit')}", "text": rd.get("comment", "")}]
        links = [{"text": "Thread", "url": rd["thread_url"]}] if rd.get("thread_url") else None
        item = make_item(
            id_="POST-RD",
            title=f"Reddit: {rd.get('subreddit', 'comment')}",
            energy="deepfocus",
            time="5 min",
            platform="Reddit",
            links=links,
            copy_blocks=copy_blocks,
            action_type="comment",
        )
        items.append(item)

    # Founder brand post (weekly)
    if founder_brand_post:
        draft = founder_brand_post.get("linkedin_draft") or founder_brand_post.get("draft", "")
        if draft:
            visual = visual_map.get("founder-brand-post") or visual_map.get("founder_brand_post")
            copy_blocks = [{"label": "LinkedIn Brand Post", "text": draft}]
            item = make_item(
                id_="POST-BRAND",
                title="Founder brand post (weekly)",
                energy="deepfocus",
                time="10 min",
                platform="LinkedIn",
                copy_blocks=copy_blocks,
                needs_eyes="Review brand post before publishing" if not visual else None,
                action_type="outreach",
            )
            if visual:
                item["visuals"] = {
                    "recommended": visual.get("recommended_format"),
                    "heroImage": visual.get("hero_image"),
                    "carousel": visual.get("carousel"),
                    "socialCard": visual.get("social_card_fallback"),
                }
            items.append(item)

    return items


def build_emails(hitlist, value_routing):
    """Emails from hitlist email actions + value-routing.json."""
    items = []

    # Value routing (value-drop emails/DMs)
    if value_routing:
        for route in value_routing.get("routes", []):
            if route.get("platform", "").lower() not in ("email", "linkedin dm", "dm"):
                continue
            copy_blocks = []
            if route.get("message"):
                copy_blocks.append({"label": f"{route.get('platform', 'Email')}", "text": route["message"]})

            context_parts = []
            if route.get("prospect_role"):
                context_parts.append(route["prospect_role"])
            if route.get("prospect_company"):
                context_parts.append(route["prospect_company"])
            if route.get("match_reason"):
                context_parts.append(f"Hook: {route['match_reason']}")

            links = []
            if route.get("signal_url"):
                links.append({"text": "Signal", "url": route["signal_url"]})

            item = make_item(
                id_=f"VR{len(items)+1}",
                title=f"Value drop: {route.get('prospect_name', 'Unknown')} - {route.get('signal_title', '')}",
                energy="deepfocus",
                time="5 min",
                platform=route.get("platform", "Email"),
                context=" - ".join(context_parts) if context_parts else None,
                links=links if links else None,
                copy_blocks=copy_blocks if copy_blocks else None,
                action_type="email",
            )
            items.append(item)

    items.sort(key=friction_key)
    return items


def build_meeting_prep_section(meeting_prep):
    """Meeting Prep as collapsible section with items."""
    if not meeting_prep:
        return []
    items = []
    for mtg in meeting_prep.get("meetings", []):
        prep = mtg.get("prep", {})
        context_parts = []
        if prep.get("who"):
            context_parts.append(prep["who"])
        last = prep.get("last_interaction")
        if last:
            context_parts.append(f"Last: {last.get('date', '')} - {last.get('summary', '')}")

        item = make_item(
            id_=f"MP{len(items)+1}",
            title=f"Prep: {mtg.get('title', '')} - {mtg.get('time', '')}",
            energy="deepfocus",
            time="10 min",
            context=" | ".join(context_parts) if context_parts else None,
            needs_eyes="Review talk points before call",
            action_type="outreach",
        )
        items.append(item)
    return items


def build_fyi(positioning, marketing_health, temperature, sycophancy_audit, compliance=None):
    """FYI section - info notes and pipeline grid."""
    info_notes = []
    pipeline = []

    if positioning:
        drift = positioning.get("drift_detected")
        if drift:
            info_notes.append(f"<strong>Positioning drift:</strong> {positioning.get('drift_summary', 'check canonical files')}")

    if marketing_health:
        stale = marketing_health.get("stale_assets", [])
        if stale:
            info_notes.append(f"<strong>Stale assets:</strong> {', '.join(str(a) if isinstance(a, str) else a.get('name', '?') for a in stale[:3])}")
        cadence = marketing_health.get("cadence_progress")
        if cadence:
            info_notes.append(f"<strong>Cadence:</strong> {cadence}")

    if temperature:
        hot = temperature.get("hot_contacts", temperature.get("hot", 0))
        warm = temperature.get("warm_contacts", temperature.get("warm", 0))
        cool = temperature.get("cool_contacts", temperature.get("cool", 0))
        if any([hot, warm, cool]):
            pipeline = [
                {"value": hot if isinstance(hot, int) else 0, "label": "Hot"},
                {"value": warm if isinstance(warm, int) else 0, "label": "Warm"},
                {"value": cool if isinstance(cool, int) else 0, "label": "Cool"},
            ]

    # Compliance violations
    if compliance:
        violations = compliance.get("auto_fail_violations", []) + compliance.get("violations", [])
        if violations:
            summaries = [v.get("message", v.get("rule", str(v))) if isinstance(v, dict) else str(v) for v in violations[:5]]
            info_notes.append(f"<strong>Compliance issues:</strong> {'; '.join(summaries)}")
        warnings = compliance.get("warnings", [])
        if warnings:
            summaries = [w.get("message", w.get("rule", str(w))) if isinstance(w, dict) else str(w) for w in warnings[:3]]
            info_notes.append(f"<strong>Compliance warnings:</strong> {'; '.join(summaries)}")

    # Sycophancy audit surfacing
    if sycophancy_audit:
        overall = sycophancy_audit.get("overall", "pass")
        harness_override = sycophancy_audit.get("harness_override")
        if harness_override:
            info_notes.append(f"<strong>Sycophancy harness override:</strong> {harness_override.get('reason', 'harness disagreed with agent')}")
        if overall == "pass":
            info_notes.append("Sycophancy audit: clean. (Residual risk always exists per Chandra et al.)")
        # "watch" is handled separately via build_sycophancy_watch_section(), not in FYI

    return info_notes, pipeline


# ---------------------------------------------------------------------------
# Sycophancy alert section (dedicated, not FYI)
# ---------------------------------------------------------------------------

def build_sycophancy_alert_section(sycophancy_audit):
    """If sycophancy overall=alert, return a dedicated section."""
    if not sycophancy_audit:
        return None
    overall = sycophancy_audit.get("overall", "pass")
    harness_override = sycophancy_audit.get("harness_override")

    # Check if harness overrode to alert
    if harness_override and harness_override.get("verdict") == "alert":
        overall = "alert"

    if overall != "alert":
        return None

    findings = []
    cb = sycophancy_audit.get("confirmation_bias", {})
    if cb.get("verdict") == "bias_detected":
        found = cb.get("contradicting_signals_found", 0)
        surfaced = cb.get("contradicting_signals_surfaced", 0)
        findings.append(f"Contradicting signals: {found} found, {surfaced} surfaced")
    ds = sycophancy_audit.get("decision_sycophancy", {})
    if ds.get("verdict") in ("watch", "alert"):
        findings.append(f"Decision sycophancy: pi={ds.get('pi', 0):.2f} (approved={ds.get('approved', 0)}, modified={ds.get('modified', 0)}, rejected={ds.get('rejected', 0)})")
    pv = sycophancy_audit.get("positioning_variance", {})
    if pv.get("verdict") in ("stale_beliefs", "spiral_risk"):
        findings.append(f"Positioning variance: {pv['verdict']}")
    if harness_override:
        findings.append(f"Harness override: {harness_override.get('reason', 'harness disagreed')}")

    info_notes = findings + [
        "The most reliable fix is a conversation with someone who will push back.",
        "This is structural, not personal. The system might be filtering."
    ]

    return {
        "id": "sycophancy-alert",
        "title": "Sycophancy Alert",
        "accent": "orange",
        "meta": "review needed",
        "collapsed": False,
        "infoNotes": info_notes,
    }


def build_sycophancy_watch_section(sycophancy_audit):
    """If sycophancy overall=watch, return an Admin-level section (not collapsed)."""
    if not sycophancy_audit:
        return None
    overall = sycophancy_audit.get("overall", "pass")
    harness_override = sycophancy_audit.get("harness_override")
    if harness_override and harness_override.get("verdict") == "watch":
        overall = "watch"
    if overall != "watch":
        return None

    checks = []
    if sycophancy_audit.get("confirmation_bias", {}).get("verdict") == "bias_detected":
        checks.append("confirmation bias")
    ds = sycophancy_audit.get("decision_sycophancy", {})
    if ds.get("verdict") in ("watch", "alert"):
        pi = ds.get("pi", 0)
        checks.append(f"decision sycophancy (pi={pi:.2f})")

    info_notes = [
        f"<strong>Sycophancy watch:</strong> {', '.join(checks) if checks else 'review needed'}",
        "Talk to someone who disagrees with a specific claim this week.",
    ]
    if harness_override:
        info_notes.append(f"Harness note: {harness_override.get('reason', 'harness flagged')}")

    return {
        "id": "sycophancy-watch",
        "title": "Sycophancy Watch",
        "accent": "yellow",
        "meta": "action suggested",
        "collapsed": False,
        "infoNotes": info_notes,
    }


# ---------------------------------------------------------------------------
# Investor update check
# ---------------------------------------------------------------------------

def check_investor_update(morning_state_path, date_str):
    """Check 5 investor update triggers. Return an item if any fire."""
    if not os.path.isfile(morning_state_path):
        return None
    try:
        with open(morning_state_path) as f:
            content = f.read()
    except OSError:
        return None

    triggers = []
    content_lower = content.lower()

    # Trigger 1: Design partner signed
    if "design partner signed" in content_lower or "dp signed" in content_lower:
        triggers.append("Design partner signed")

    # Trigger 2: Major product milestone
    if "milestone shipped" in content_lower or "major milestone" in content_lower:
        triggers.append("Product milestone shipped")

    # Trigger 3: Key hire or partnership
    if "key hire" in content_lower or "partnership" in content_lower:
        triggers.append("Key hire or partnership")

    # Trigger 4: Press or notable mention
    if "press mention" in content_lower or "notable mention" in content_lower:
        triggers.append("Press or notable mention")

    # Trigger 5: 30+ days since last investor update
    match = re.search(r"last.investor.update[:\s]+(\d{4}-\d{2}-\d{2})", content_lower)
    if match:
        try:
            last_update = datetime.strptime(match.group(1), "%Y-%m-%d")
            current = datetime.strptime(date_str, "%Y-%m-%d")
            if (current - last_update).days >= 30:
                triggers.append(f"30+ days since last investor update ({match.group(1)})")
        except ValueError:
            pass

    if not triggers:
        return None

    return make_item(
        id_="INV-UPDATE",
        title=f"Draft investor update - {triggers[0]}",
        energy="admin",
        time="30 min",
        context=f"Triggers: {', '.join(triggers)}",
        needs_eyes="Review triggers and draft update",
        action_type="email",
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print("Usage: synthesize-schedule.py <date>")
        sys.exit(1)

    date_str = sys.argv[1]
    bus_dir = os.path.join(BUS_BASE, date_str)

    if not os.path.isdir(bus_dir):
        print(f"No bus directory for {date_str}")
        sys.exit(1)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Load all bus files
    calendar = load_bus(bus_dir, "calendar.json")
    gmail = load_bus(bus_dir, "gmail.json")
    notion = load_bus(bus_dir, "crm.json")
    meeting_prep = load_bus(bus_dir, "meeting-prep.json")
    linkedin_posts = load_bus(bus_dir, "linkedin-posts.json")
    linkedin_dms = load_bus(bus_dir, "linkedin-dms.json")
    signals = load_bus(bus_dir, "signals.json")
    value_routing = load_bus(bus_dir, "value-routing.json")
    temperature = load_bus(bus_dir, "temperature.json")
    leads = load_bus(bus_dir, "leads.json")
    connection_mining = load_bus(bus_dir, "connection-mining.json")
    hitlist = load_bus(bus_dir, "hitlist.json")
    pipeline_followup = load_bus(bus_dir, "pipeline-followup.json")
    loop_review = load_bus(bus_dir, "loop-review.json")
    positioning = load_bus(bus_dir, "positioning.json")
    marketing_health = load_bus(bus_dir, "marketing-health.json")
    sycophancy_audit = load_bus(bus_dir, "sycophancy-audit.json")
    post_visuals = load_bus(bus_dir, "post-visuals.json")
    founder_brand_post = load_bus(bus_dir, "founder-brand-post.json")
    client_deliverables = load_bus(bus_dir, "client-deliverables.json")
    compliance = load_bus(bus_dir, "compliance.json")
    bootstrap = load_bus(bus_dir, "bootstrap.json")
    warm_intros = load_bus(bus_dir, "warm-intros.json")

    # Build effort summary from yesterday's session effort log
    effort = None
    try:
        yesterday = (datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
        effort_path = os.path.join(OUTPUT_DIR, f"session-effort-{yesterday}.log")
        if os.path.isfile(effort_path):
            with open(effort_path) as f:
                lines = f.read().strip().split(chr(10))
                # Take last non-empty line as effort summary
                effort = next((l for l in reversed(lines) if l.strip()), None)
    except (ValueError, OSError):
        pass

    # Build date display
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        date_display = dt.strftime("%A, %B %d").replace(" 0", " ")
        generated = dt.strftime("%a, %b %d, %Y") + f" - {datetime.now().strftime('%-I:%M%p').lower()} PT"
    except ValueError:
        date_display = date_str
        generated = date_str

    # Build schedule components
    call_banners = build_call_banners(calendar)
    meeting_prep_boxes = build_meeting_prep(meeting_prep)
    today_focus = build_today_focus(calendar, pipeline_followup, client_deliverables, loop_review, date_str)

    # Missed debriefs from bootstrap (surface as Quick Win items)
    missed_debrief_items = []
    if bootstrap:
        for md in bootstrap.get("missed_debriefs", []):
            missed_debrief_items.append(make_item(
                id_=f"DEBRIEF-{len(missed_debrief_items)+1}",
                title=f"Run debrief: {md.get('name', 'Unknown')} ({md.get('meeting_date', 'recent')})",
                energy="deepfocus",
                time="10 min",
                needs_eyes="Meeting happened but was never debriefed. Run /q-debrief.",
                action_type="followup",
            ))
        for sp in bootstrap.get("stale_pending_items", []):
            if isinstance(sp, dict):
                missed_debrief_items.append(make_item(
                    id_=f"STALE-{len(missed_debrief_items)+1}",
                    title=f"Stale item: {sp.get('target', sp.get('id', 'unknown'))}",
                    energy="admin",
                    time="3 min",
                    needs_eyes="Carried forward - needs your eyes",
                    action_type="followup",
                ))

    # Build sections in enforced order
    sections = []

    # Quick Wins (includes missed debriefs from bootstrap)
    qw_items = build_quick_wins(hitlist) + strip_internal(missed_debrief_items)
    quick_win_ids = {item["id"] for item in qw_items}
    if qw_items:
        total_time = sum(int(re.search(r"(\d+)", i["time"]).group(1)) for i in qw_items if re.search(r"(\d+)", i["time"]))
        sections.append({
            "id": "quick-wins",
            "title": "Quick Wins",
            "accent": "green",
            "meta": f"{len(qw_items)} items, ~{total_time} min - start here",
            "collapsed": False,
            "items": strip_internal(qw_items),
        })

    # Open Loops
    ol_items = build_open_loops(loop_review)
    if ol_items:
        sections.append({
            "id": "open-loops",
            "title": "Open Loops",
            "accent": "red",
            "meta": f"{len(ol_items)} stale loops",
            "collapsed": False,
            "items": strip_internal(ol_items),
        })

    # Sycophancy Alert or Watch (after Open Loops, before Pipeline)
    syc_alert = build_sycophancy_alert_section(sycophancy_audit)
    if syc_alert:
        sections.append(syc_alert)
    else:
        syc_watch = build_sycophancy_watch_section(sycophancy_audit)
        if syc_watch:
            sections.append(syc_watch)

    # Pipeline Follow-ups
    pf_items = build_pipeline_followups(pipeline_followup)
    if pf_items:
        total_time = sum(int(re.search(r"(\d+)", i["time"]).group(1)) for i in pf_items if re.search(r"(\d+)", i["time"]))
        sections.append({
            "id": "pipeline-followups",
            "title": "Pipeline Follow-ups",
            "accent": "purple",
            "meta": f"{len(pf_items)} items, ~{total_time} min",
            "collapsed": False,
            "items": strip_internal(pf_items),
        })

    # Warm Intros (from warm-intros.json, added to Pipeline Follow-ups)
    if warm_intros and pf_items is not None:
        pass  # handled below
    warm_intro_items = []
    if warm_intros:
        for match in warm_intros.get("matches", []):
            if match.get("match_status") == "cold_outreach_only":
                continue
            connector = match.get("connector_name", "")
            target = match.get("target_name", "Unknown")
            firm = match.get("target_firm", "")
            context_parts = []
            if match.get("warm_intro_path"):
                context_parts.append(match["warm_intro_path"])
            if match.get("connector_last_contact"):
                context_parts.append(f"Last contact with {connector}: {match['connector_last_contact']}")

            item = make_item(
                id_=f"WI{len(warm_intro_items)+1}",
                title=f"Warm intro: ask {connector} about {target} ({firm})",
                energy="people",
                time="5 min",
                platform="LinkedIn",
                badge="KEY" if match.get("target_tier") == "A" else None,
                context=" | ".join(context_parts) if context_parts else None,
                needs_eyes=f"Draft intro request to {connector} - needs your eyes",
                action_type="followup",
            )
            warm_intro_items.append(item)
        strip_internal(warm_intro_items)

    # Inject warm intros into Pipeline Follow-ups section if it exists
    for s in sections:
        if s["id"] == "pipeline-followups" and warm_intro_items:
            s["items"].extend(warm_intro_items)
            s["meta"] = f"{len(s['items'])} items"
            break
    else:
        if warm_intro_items:
            sections.append({
                "id": "pipeline-followups",
                "title": "Pipeline Follow-ups",
                "accent": "purple",
                "meta": f"{len(warm_intro_items)} items",
                "collapsed": False,
                "items": warm_intro_items,
            })

    # LinkedIn Engagement (overflow from hitlist beyond Quick Wins cap)
    eng_items = build_engagement(hitlist, quick_win_ids)
    if eng_items:
        sections.append({
            "id": "linkedin-engagement",
            "title": "LinkedIn Engagement",
            "accent": "blue",
            "meta": f"{len(eng_items)} comments",
            "collapsed": False,
            "items": strip_internal(eng_items),
        })

    # New Leads
    nl_items = build_new_leads(leads, connection_mining)
    if nl_items:
        sections.append({
            "id": "new-leads",
            "title": "New Leads",
            "accent": "yellow",
            "meta": f"{len(nl_items)} prospects",
            "collapsed": False,
            "items": strip_internal(nl_items),
        })

    # Posts
    post_items = build_posts(signals, founder_brand_post, post_visuals)
    if post_items:
        sections.append({
            "id": "posts",
            "title": "Posts",
            "accent": "green",
            "meta": f"{len(post_items)} drafts ready",
            "collapsed": False,
            "items": strip_internal(post_items),
        })

    # Emails
    email_items = build_emails(hitlist, value_routing)
    if email_items:
        total_time = sum(int(re.search(r"(\d+)", i["time"]).group(1)) for i in email_items if re.search(r"(\d+)", i["time"]))
        sections.append({
            "id": "emails",
            "title": "Emails",
            "accent": "purple",
            "meta": f"{len(email_items)} items, ~{total_time} min",
            "collapsed": False,
            "items": strip_internal(email_items),
        })

    # Meeting Prep (collapsed)
    mp_items = build_meeting_prep_section(meeting_prep)
    if mp_items:
        sections.append({
            "id": "meeting-prep",
            "title": "Meeting Prep",
            "accent": "purple",
            "meta": f"{len(mp_items)} meetings",
            "collapsed": True,
            "items": strip_internal(mp_items),
        })

    # Investor update check
    morning_state_path = os.path.join(QROOT, "memory", "morning-state.md")
    inv_item = check_investor_update(morning_state_path, date_str)
    if inv_item:
        # Add to admin section or create one
        strip_internal([inv_item])
        found_admin = False
        for s in sections:
            if s["id"] == "emails":
                s["items"].append(inv_item)
                found_admin = True
                break
        if not found_admin:
            sections.append({
                "id": "admin",
                "title": "Admin",
                "accent": "gray",
                "meta": "1 item",
                "collapsed": False,
                "items": [inv_item],
            })

    # FYI (collapsed)
    fyi_notes, fyi_pipeline = build_fyi(positioning, marketing_health, temperature, sycophancy_audit, compliance)
    if fyi_notes or fyi_pipeline:
        fyi_section = {
            "id": "fyi",
            "title": "FYI - Pipeline & Signals",
            "accent": "gray",
            "meta": "reference only",
            "collapsed": True,
        }
        if fyi_notes:
            fyi_section["infoNotes"] = fyi_notes
        if fyi_pipeline:
            fyi_section["pipeline"] = fyi_pipeline
        sections.append(fyi_section)

    # Assemble final output
    schedule = {
        "bus_version": 1,
        "date": date_str,
        "generated_by": "synthesize-schedule.py",
        "dateDisplay": date_display,
        "generated": generated,
        "callBanners": call_banners,
        "effort": effort,
        "meetingPrep": meeting_prep_boxes,
        "sections": sections,
    }

    if effort:
        schedule["effort"] = effort
    if today_focus:
        schedule["todayFocus"] = today_focus

    # Validate against schema
    schema = load_schema("schedule-data.schema.json")
    if schema:
        errors = validate_schedule(schedule, schema)
        if errors:
            print("Schema validation errors:")
            for e in errors:
                print(f"  - {e}")
            sys.exit(2)

    # Write output
    output_path = os.path.join(OUTPUT_DIR, f"schedule-data-{date_str}.json")
    with open(output_path, "w") as f:
        json.dump(schedule, f, indent=2)
    print(f"Wrote {output_path}")
    print(f"Sections: {len(sections)}, Items: {sum(len(s.get('items', [])) for s in sections)}")


if __name__ == "__main__":
    main()
