**Step 8 — Output morning briefing (AUDHD executive function rules apply):**

> **GATE CHECK (mandatory before starting Step 8):**
> 1. Read the morning log from disk: `cat q-system/output/morning-log-DATE.json | python3 -c "import json,sys; steps=json.load(sys.stdin)['steps']; missing=[s for s in ['0f_connection_check','0a_checkpoint','0b_missed_debrief','0b.5_loop_escalation','0c_load_canonical','0d_load_voice','0e_load_audhd','1_calendar','1_gmail','1_notion_actions','1_notion_pipeline','3_linkedin_activity','3.5_dp_pipeline','3.8_dm_check','4.1_value_drops','5.8_temperature_scoring','5.85_pipeline_followup','5.86_loop_review','5.9_lead_sourcing','5.9b_engagement_hitlist','6_decision_compliance','7_positioning_freshness'] if s not in steps]; print(f'Missing: {missing}' if missing else 'All prior steps logged')"`
> 1b. Check for unresolved level 3 loops: `bash q-system/.q-system/loop-tracker.sh list 3` - if any exist, STOP. Force-close decisions must happen before HTML generation.
> 1c. Verify Deliverables Checklist (see preflight.md Section 5): day-specific content pieces, pipeline follow-ups, loop review items.
> 2. If missing list is empty: `bash q-system/.q-system/log-step.sh DATE gate-check step_8 true ""`
> 3. If missing list is not empty: `bash q-system/.q-system/log-step.sh DATE gate-check step_8 false "step1,step2"` then STOP and report.
> Cannot proceed until all prior steps are accounted for.

All output in this step must comply with the AUDHD executive function skill (loaded in Step 0e). Every item shown to the founder must be copy-paste ready or explicitly marked "needs your eyes." No dashboards without actions. No scores without recovery drafts. No cross-references. The briefing is a workbench, not a report.
```
📝 MISSED DEBRIEFS (from Step 1.1, only shown if any exist)
[person + time + pre-filled /q-debrief command]

▶️ START HERE
[single task - the highest-value, lowest-friction thing to do right now]
[why this one: "Hot prospect responded" or "5-min quick win clears your plate"]
[pre-filled command or copy-paste-ready text if applicable]

🎯 TODAY'S FOCUS (top 3-5 items, replaces scanning 15+ sections)
1. [action] - [why now] (Energy: Quick Win, 5 min)
2. [action] - [why now] (Energy: Quick Win, 10 min)
3. [action] - [why now] (Energy: Deep Focus, 20 min)
[These are the 3-5 most impactful things for today, pulled from all sections below. If you only have 30 minutes, do these. Everything else is gravy.]

📅 CALENDAR (this week)
[events list]

👤 MEETING PREP
[per-meeting briefs with LinkedIn + CRM + prep notes]

📧 UNLOGGED EMAILS (last 48h)
[emails from known contacts not in Interactions DB]

💬 LINKEDIN DMs + CONNECTIONS (from Step 3.8, auto-detected, 10-day lookback)
[Connection accepts with copy-paste first DMs]
[DM replies with copy-paste response suggestions]
[DMs needing reply with copy-paste responses]
[Pending connection request status]

🐦 X ACTIVITY
[new followers, replies to respond to, DM opportunities, QT/reply targets]
[X metrics on Mondays]

✅ ACTIONS DUE TODAY
[from Notion Actions DB]

🎯 INVESTOR PIPELINE
[upcoming follow-ups, status changes needed]

🤝 WARM INTRO OPPORTUNITIES (from Step 1.5)
[prospect -> connector -> suggested ask, or "No new prospects to match"]

🔄 LINKEDIN RE-ENGAGE
[comments with new activity + new post opportunities + overdue follow-ups]

📡 SIGNALS + X POSTS
[LinkedIn signal post + X signal post + X hot take + X BTS (Mon/Wed/Fri) + X visual idea (Wed)]

📨 INTEL DROPS TO SEND (from Step 4.1)
[signal-matched contacts with copy-paste DMs/emails and specific report links]

📊 SITE METRICS (Mondays only)
[weekly comparison or "N/A - not Monday"]

🌡️ PROSPECT TEMPERATURE (daily, from Step 5.8)
[Hot/Warm/Cool/Cold prospects with scores, trends, and one suggested action each]

🔍 UTM CLICK DETAIL (Mondays only, from Step 5.5)
[raw click data for score calibration]

💬 DAILY ENGAGEMENT HITLIST (from Step 5.9b) - COPY-PASTE READY

RELATIONSHIP ACTIONS (auto-generated, highest priority):
[Ready to connect: prospects with 2+ comments logged]
[Follow-up DMs due: accepted connections needing first DM]
[Value-drop DMs: first DM sent 7+ days ago, no reply]
[Replies to continue: prospects who responded]

NEW COMMENTS (warming up prospects):
[LinkedIn comments with post links + ready comments]
[X/Twitter replies with tweet links + ready replies]

OUTREACH:
[Connection requests to send today with ready messages]
[Reddit threads with ready comments]

Total: [X] actions ([Y] Quick Wins, [Z] Deep Focus, [W] People, [V] Admin), ~[X] min

🔎 PROBLEM-LANGUAGE PROSPECTS (from Step 5.9)
[new qualified decision-makers + champions talking about {{YOUR_PRODUCT}}'s problem]
[draft connection requests for each with inline copy-paste text and Copy button]
[Reddit threads with inline copy-paste comments and Copy button]

🧠 MARKET INTELLIGENCE (from Step 2.5 during lead sourcing)
[Only shown if new entries were added to canonical/market-intelligence.md today]
[New problem language captured: "verbatim quote" - [author], [platform]]
[New category signals: [description]]
[New objection previews: [description] - added to objections.md? yes/no]
[Market pattern alert: if 3+ posts pointed to same theme, flag it here]
[No action needed from founder - this is "here's what the market told us today"]

📣 MARKETING HEALTH (from Step 4.5)
[asset freshness, Gamma deck status, cadence progress, stale drafts]

🔄 PUBLISH RECONCILIATION (from Step 3.2, only if changes found)
[auto-detected publishes, direct publishes, cadence adjustments]

⚠️ DECISION COMPLIANCE
[any rule violations found — or "All clear"]

🔄 PENDING PROPAGATION
[positioning changes not yet in all files — or "All synced"]

🔧 CHECKPOINT DRIFT (from Step 7.5, only if drift found)
[files modified since last checkpoint, auto-recovery status]

📨 INVESTOR UPDATE DUE (from Step 9.5, only if triggered)
[trigger reason: "Design partner signed" or "30+ days since last update"]
[suggested: run /q-investor-update]
```
