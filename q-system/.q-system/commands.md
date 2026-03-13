# Q Instance Commands

> These are conventions for interacting with the Q Founder OS. Use them as natural language triggers.

| Command | Purpose | Mode |
|---------|---------|------|
| `/q-begin` | Start a new session. Read all canonical files to load current state. | - |
| `/q-status` | Report current state from `my-project/progress.md`. | - |
| `/q-calibrate` | Update canonical files based on new information or feedback. | CALIBRATE |
| `/q-create [type] [audience]` | Generate a specific output (talk track, email, slide text, memo). | CREATE |
| `/q-debrief [person]` | Process a conversation using the debrief template. **Highest-priority.** | DEBRIEF |
| `/q-plan` | Review relationships, objections, proof gaps. Propose next actions. | PLAN |
| `/q-draft [type] [audience]` | Generate a one-off output to `output/drafts/`. | CREATE |
| `/q-checkpoint` | Save canonical state. Verify consistency. Log to progress.md. | - |
| `/q-end` | End session. Auto-checkpoints, then summarizes all changes. | - |
| `/q-sync-notion` | Sync local files with Notion CRM (if configured). | CALIBRATE |
| `/q-morning` | Full morning briefing. See workflow below. | - |
| `/q-engage` | Social engagement mode. Proactive hitlists + reactive comments. | CREATE |
| `/q-investor-update` | Draft investor update email. | CREATE |
| `/q-market-plan` | Weekly content planning. | CREATE |
| `/q-market-create [type]` | Generate marketing content (linkedin, x, medium, email, deck). | CREATE |
| `/q-market-review [file]` | Validate content against guardrails. PASS/FAIL. | - |
| `/q-market-publish [file]` | Mark content published. Update tracking. | - |
| `/q-market-status` | Content pipeline snapshot. | - |

## Usage Notes

- **`/q-morning` is the only command you need to start a day.** It auto-checkpoints, catches missed debriefs, and loads canonical state.
- **Debriefs happen automatically.** Paste a conversation transcript and the system auto-runs `/q-debrief`.
- **Modes are not sequential.** Switch freely.

## Example Flows

### After a meeting:
1. `/q-debrief [person]` - process the conversation
2. `/q-calibrate` - update canonical files if positioning shifted
3. `/q-draft email [person]` - draft follow-up

### Preparing for a meeting:
1. `/q-begin` - load current state
2. `/q-create talk-track [audience]` - generate tailored talking points
3. `/q-draft talking-points [person]` - person-specific prep

### Social engagement:

**Proactive mode (`/q-engage`):**
1. Pull contacts for active prospects / investors / partners
2. For each target: pull their recent social posts (via Apify or browser)
3. Cross-reference engagement tracker (enforce 1 comment/person/week)
4. Generate copy-paste ready comments
5. Output hitlist with copy buttons and links
6. After founder posts, log to tracker

**Reactive mode (screenshot shared):**
1. Identify person, role, company from screenshot
2. Check CRM for history
3. Generate 2-3 comments (Insight / Connector / Question styles)
4. Log to tracker after founder picks one

### Relationship Progression Engine

The system manages prospect relationships. The founder only:
1. Copy-pastes engagement actions from the hitlist
2. Reports what happened ("commented on X's post", "Y accepted")

Everything else is automated: logging, status updates, next-step generation, follow-up scheduling.

**Relationship ladder:**
```
STAGE 1: WARM UP
  Actions: Comment on 2-3 of their posts over 1-2 weeks
  Advance trigger: 2-3 comments posted

STAGE 2: CONNECT
  Actions: Send connection request
  Advance trigger: Request accepted

STAGE 3: FIRST DM
  Actions: Send value-first DM (no pitch)
  Advance trigger: They reply
  Timeout: 10 days no reply = value-drop. 14 days = Cooling.

STAGE 4: CONVERSATION
  Actions: Continue DM conversation, aim toward a call
  Advance trigger: Call scheduled

STAGE 5: DEMO/CALL
  Actions: Run the call, then debrief
  Advance trigger: /q-debrief completed
```

## Morning Briefing (`/q-morning`)

**Step 0 - Session bootstrap:**
- 0a: Checkpoint previous session
- 0b: Missed debrief detection (check calendar for unlogged meetings)
- 0c: Load canonical state (`/q-begin`)
- 0d: Load voice skill
- 0e: Load executive function skill (if AUDHD mode enabled)

**Step 1 - Parallel data pull:**
- Calendar: Pull events for the current week
- Email: Search last 48 hours, cross-ref against contacts
- CRM: Pull overdue/due-today actions, pipeline follow-ups
- Pipeline: Check investor/prospect pipeline status

**Step 1.5 - Warm intro matching:**
- Cross-reference new prospects against existing contacts for warm paths
- Warm intro always beats cold outreach

**Step 2 - Meeting prep:**
- For each meeting this week: pull attendee profiles, CRM history, research
- Generate talking points based on their interests + your positioning

**Step 3 - Social activity review:**
- Check own posts for engagement, flag re-engagement opportunities
- Check target contacts for new posts to engage with
- Cross-reference engagement tracker for follow-ups due

**Step 3.5 - Pipeline check:**
- Count prospects by status
- Auto-close dead loops (3 touches + no response + 14 days)
- Flag pipeline health

**Step 4 - Content generation:**
- Fetch relevant signals/news for your industry
- Generate social posts (platform-specific)
- Generate thought leadership content (on schedule days)

**Step 4.1 - Value-first signal routing:**
- Match today's signals to contacts by industry/role
- Generate personalized value-drop messages
- No pitch, pure intel sharing

**Step 5 - Analytics (weekly):**
- Site metrics
- Content performance
- Prospect engagement tracking

**Step 5.9 - Lead sourcing (daily):**
- Phase 1: Run scrapers across platforms
- Phase 2: Read and qualify every result (no keyword filter)
- Phase 3: Generate personalized outreach
- Phase 4: Create CRM entries

**Step 5.9b - Daily engagement hitlist:**
- Pull recent posts from pipeline prospects
- Generate copy-paste comments, DMs, connection requests
- Must include all engagement types with sections even if empty

**Steps 6-7 - Compliance checks:**
- Decision rule compliance
- Positioning freshness

**Step 8 - Output briefing**

**Step 9 - Push actions to CRM**

**Step 10 - Update daily checklists**

**Step 11 - MANDATORY: Generate daily schedule HTML and open in browser**
- Use `q-system/marketing/templates/daily-schedule-template.html` as base
- This is the primary deliverable. Never end without it.
- Must follow AUDHD executive function rules if enabled
- Dark theme, checkboxes, copy buttons, energy filters, localStorage persistence
