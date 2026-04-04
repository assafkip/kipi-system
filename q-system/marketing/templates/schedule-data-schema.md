# Daily Schedule Data Schema

> This is the JSON schema that Claude produces during `/q-morning` Step 11. The build script injects this data into `daily-schedule-template.html` to produce the final HTML.

## How It Works

1. Claude generates a JSON file at `output/schedule-data-YYYY-MM-DD.json`
2. Build script runs: `python3 marketing/templates/build-schedule.py output/schedule-data-YYYY-MM-DD.json output/daily-schedule-YYYY-MM-DD.html`
3. HTML opens in browser

Claude NEVER writes raw HTML. Claude ONLY writes JSON conforming to this schema.

## Top-Level Schema

```json
{
  "date": "2026-03-12",
  "dateDisplay": "Thursday, March 12",
  "generated": "Thu, Mar 12, 2026 - 9:05am PT",
  "effort": "14 Peaks call + debrief done. LinkedIn post published. 13 comments posted.",
  "callBanners": [],
  "meetingPrep": [],
  "sections": []
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `date` | string | YES | ISO date `YYYY-MM-DD` |
| `dateDisplay` | string | YES | Human-readable date for header |
| `generated` | string | YES | Timestamp string for header |
| `effort` | string | NO | Yesterday's effort summary (no "Yesterday:" prefix, template adds it) |
| `todayFocus` | array | NO | Top 3-5 prioritized items for today (CT1). Shows as a prominent focus section before all other content. Each item: `{"text": "Reply to hot prospect DM", "time": "5 min", "energy": "quickwin"}` |
| `callBanners` | array | NO | Today's calls/meetings shown as prominent banners |
| `meetingPrep` | array | NO | Meeting prep boxes shown below banners |
| `sections` | array | YES | Main content sections (see below) |

## Call Banner

```json
{
  "time": "2:00pm PT",
  "info": "<strong>Sim</strong> - Design Partner Discovery (45 min)",
  "detail": "Google Meet: <a href='https://meet.google.com/abc'>meet.google.com/abc</a>"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `time` | string | YES | Time display |
| `info` | string | YES | HTML allowed. Use `<strong>` for name |
| `detail` | string | NO | HTML allowed. Links, notes |

## Meeting Prep

```json
{
  "title": "PREP: Sim - 2:00pm",
  "items": [
    "<strong>Context:</strong> Design partner prospect from Feb 19 batch",
    "<strong>Goal:</strong> Pure discovery. Ask what tools, where learning breaks down",
    "<strong>Demo:</strong> Show demo2 only if pain aligns"
  ]
}
```

## Section

```json
{
  "id": "quick-wins",
  "title": "Quick Wins",
  "accent": "green",
  "meta": "3 items, ~8 min - start here",
  "collapsed": false,
  "items": [],
  "infoNotes": [],
  "pipeline": []
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | YES | Unique section ID |
| `title` | string | YES | Section header text |
| `accent` | string | YES | Color key: `green`, `blue`, `purple`, `red`, `yellow`, `pink`, `gray`, `indigo`, `white`. Or a hex color |
| `meta` | string | NO | Right-side text (item count, time estimate) |
| `collapsed` | boolean | NO | Start collapsed (default: false). Use for FYI/info sections |
| `items` | array | NO | Action items with checkboxes and copy blocks |
| `infoNotes` | array | NO | Array of HTML strings for info-only display |
| `pipeline` | array | NO | Pipeline grid cells: `[{"value": 5, "label": "Active"}]` |

### Accent Color Guide

| Section Type | Accent |
|-------------|--------|
| Quick Wins | `green` |
| LinkedIn Engagement | `blue` |
| New Leads / Connection Requests | `yellow` |
| RSA / Special Outreach | `pink` |
| Posts / Content | `green` or `yellow` |
| Meeting Prep | `purple` |
| Emails / Deep Focus | `purple` |
| FYI / Pipeline | `gray` |

## Action Item

```json
{
  "id": "cowgill",
  "title": "Reply to John Cowgill (Costanoa) - he wants RSA meeting Mar 25",
  "energy": "quickwin",
  "time": "2 min",
  "platform": "Email",
  "badge": null,
  "extraTags": [],
  "daysAgo": null,
  "context": "<span style='color:#34d399'>He replied!</span> \"Thanks Assaf. Let's find time Wednesday March 25.\"",
  "links": [
    {"text": "Open email", "url": "mailto:john@costanoa.vc?subject=Re:%20RSA"}
  ],
  "copyBlocks": [
    {
      "label": "Email Reply | Subject: Re: RSA",
      "text": "No worries at all. Wednesday March 25 works great.\n\nAssaf"
    }
  ],
  "needsEyes": null
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | YES | Unique item ID. MUST match the action card ID used in `log-step.py add-card` (e.g., C1, C2, DM1). This is the join key between the HTML, localStorage, the exported JSON, and the morning log. Used for checkbox/skip persistence and next-morning pickup. |
| `title` | string | YES | Action title. Keep concise |
| `energy` | string | YES | `quickwin`, `deepfocus`, `people`, or `admin` |
| `time` | string | YES | Estimated time: `2 min`, `5 min`, `10 min`, `15 min`, `30 min` |
| `platform` | string | NO | `LinkedIn`, `X`, `Email`, `Slack`, `Reddit`, etc |
| `badge` | string | NO | `WIN` (green) or `KEY` (red) for important items |
| `extraTags` | array | NO | Custom tags: `[{"text": "TIER A", "color": "#ef4444"}]` |
| `daysAgo` | string | NO | Red text for staleness: `15 DAYS` |
| `context` | string | NO | HTML allowed. Relationship context shown below title |
| `links` | array | NO | Clickable links: `[{"text": "View post", "url": "https://..."}]` |
| `copyBlocks` | array | NO | Copy-paste blocks (see below) |
| `needsEyes` | string | NO | Yellow warning box text for items needing user judgment |

### Copy Block

```json
{
  "label": "LinkedIn DM",
  "text": "I saw your post about being first IT hire twice..."
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `label` | string | YES | Label above text: `Comment`, `LinkedIn DM`, `Email Reply | Subject: ...`, `Connection Request Note` |
| `text` | string | YES | The actual copy-paste text. Use `\n` for newlines |

### Extra Tag

```json
{"text": "TIER A", "color": "#ef4444"}
{"text": "RSA", "color": "#ec4899"}
```

## Section Ordering (ENFORCED)

Sections MUST appear in this order (skip empty ones):

1. **Quick Wins** (`green`) - scheduling replies, short DMs, comments (2-3 min each)
2. **Open Loops** (`red`) - loops at level 2+ (7+ days old). Force-close items have skip=park UX. HIGHEST PRIORITY after quick wins.
3. **Pipeline Follow-ups** (`purple`) - existing warm prospects, overdue actions, DP follow-ups. BEFORE new leads.
4. **LinkedIn Engagement** (`blue`) - comments on prospect posts
5. **New Leads** (`yellow`) - connection requests, X replies
5. **Special Outreach** (`pink`) - RSA, events, batch campaigns (only when applicable)
6. **Posts** (`green`/`yellow`) - social content to publish (collapsed if already published)
7. **Emails** (`purple`) - longer follow-ups
8. **Meeting Prep** (`purple`, collapsed) - upcoming call prep
9. **FYI** (`gray`, collapsed) - pipeline, signals, info-only

## Item Ordering Within Sections (ENFORCED)

Items within each section sorted by friction (lowest first):
1. Replies to people who contacted YOU first (lowest friction)
2. Follow-ups where ball is in your court
3. New outreach to warm contacts
4. New outreach to cold contacts

## Complete Example

```json
{
  "date": "2026-03-12",
  "dateDisplay": "Thursday, March 12",
  "generated": "Thu, Mar 12, 2026 - 9:05am PT",
  "effort": "4 DMs sent, 3 comments posted, 1 debrief completed, LinkedIn post published.",
  "callBanners": [
    {
      "time": "2:00pm PT",
      "info": "<strong>Sim</strong> - Design Partner Discovery (45 min)",
      "detail": "Google Meet: <a href='https://meet.google.com/vvr-rokt-zws'>meet.google.com/vvr-rokt-zws</a>"
    }
  ],
  "meetingPrep": [],
  "sections": [
    {
      "id": "quick-wins",
      "title": "Quick Wins",
      "accent": "green",
      "meta": "2 items, ~5 min - start here",
      "collapsed": false,
      "items": [
        {
          "id": "cowgill-reply",
          "title": "Reply to John Cowgill (Costanoa) - RSA meeting Mar 25",
          "energy": "quickwin",
          "time": "2 min",
          "platform": "Email",
          "badge": "WIN",
          "context": "<span style='color:#34d399'>He replied!</span> Wants to meet Wed Mar 25 at RSA.",
          "links": [{"text": "Open email", "url": "mailto:john@costanoa.vc"}],
          "copyBlocks": [
            {
              "label": "Email Reply",
              "text": "No worries at all. Wednesday March 25 works great.\n\nAssaf"
            }
          ]
        },
        {
          "id": "comment-mamica",
          "title": "Comment on Michal Mamica's post - alert fatigue",
          "energy": "quickwin",
          "time": "2 min",
          "platform": "LinkedIn",
          "context": "Senior Security Engineer. Posted 1 day ago. \"Nobody owns the decision of what happens next.\"",
          "links": [{"text": "Find post", "url": "https://linkedin.com/search/..."}],
          "copyBlocks": [
            {
              "label": "Comment",
              "text": "That line about nobody owning the decision is the real gap..."
            }
          ]
        }
      ]
    },
    {
      "id": "fyi",
      "title": "FYI - Pipeline & Signals",
      "accent": "gray",
      "meta": "reference only",
      "collapsed": true,
      "infoNotes": [
        "<strong>Costanoa:</strong> Back on track. RSA meeting Mar 25.",
        "<strong>14 Peaks:</strong> Follow-up sent. Awaiting internal review."
      ],
      "pipeline": [
        {"value": 5, "label": "Active"},
        {"value": 3, "label": "Outreach"},
        {"value": 2, "label": "Demo Done"},
        {"value": 1, "label": "Cooling"}
      ]
    }
  ]
}
```
