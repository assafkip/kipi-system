# User Archetypes

When a new user starts setup, determine their archetype FIRST. This controls which integrations to offer and which parts of the system to emphasize.

## How to Detect

Ask ONE question:

> "What best describes how you'll use this?
>
> A) I'm building a company and need help with sales, outreach, and pipeline
> B) I'm building a company and mostly need help staying organized and shipping
> C) I create content and want to grow my audience and engagement
> D) I run operations for a founder or executive
> E) I just want to try it out with zero setup"

Map the answer:

| Answer | Archetype ID | Label |
|--------|-------------|-------|
| A | `gtm-founder` | GTM Founder |
| B | `product-founder` | Product Founder |
| C | `content-creator` | Content Creator |
| D | `operator` | Operator / Chief of Staff |
| E | `minimal` | Explorer |

Save the archetype ID to `my-project/founder-profile.md` under `## Archetype`.

## Integration Maps

Each archetype has a required, recommended, and optional tier. Only walk the user through required + recommended. Mention optional once at the end.

### gtm-founder
**Focus:** Pipeline management, outreach, meeting prep, relationship tracking

| Tier | Integration | Why |
|------|------------|-----|
| Required | Notion | CRM: contacts, pipeline, actions |
| Required | Google Calendar | Meeting prep in morning routine |
| Required | Gmail | Draft follow-ups, track threads |
| Recommended | Apify | Scrape LinkedIn profiles, find leads |
| Optional | Chrome automation | Send LinkedIn DMs from the system |
| Optional | Telegram | Message contacts directly |
| Optional | Gamma | Generate pitch decks and one-pagers |

### product-founder
**Focus:** Stay organized, occasional outreach, don't lose track of conversations

| Tier | Integration | Why |
|------|------------|-----|
| Required | Notion | Task tracking, light CRM |
| Recommended | Google Calendar | Know what's coming today |
| Optional | Gmail | Draft emails when needed |
| Optional | Apify | Research competitors or prospects |

### content-creator
**Focus:** Content pipeline, audience engagement, social presence

| Tier | Integration | Why |
|------|------------|-----|
| Required | Apify | Scrape social posts, track engagement |
| Recommended | Notion | Content calendar, asset library |
| Recommended | Chrome automation | Engage on LinkedIn, reply to comments |
| Optional | Gamma | Create visual content, slide decks |
| Optional | Google Calendar | Schedule content drops |

### operator
**Focus:** Keep the founder on track, manage calendar, follow up on actions

| Tier | Integration | Why |
|------|------------|-----|
| Required | Notion | CRM, action tracking, pipeline |
| Required | Google Calendar | Calendar management |
| Required | Gmail | Email drafts, follow-ups |
| Optional | Apify | Research for the founder |

### minimal
**Focus:** Try the system with zero friction

| Tier | Integration | Why |
|------|------------|-----|
| None required | -- | Everything runs on local files |

Tell the user: "You're all set. The system works with just local files. Whenever you want to connect a tool, just say 'connect my notion' or 'connect my calendar' and I'll walk you through it."

## Progressive Enhancement

After setup, the system should detect when an unconnected integration would help and gently suggest it. Examples:

- Morning routine without Calendar: "I can't see your meetings today. Want to connect Google Calendar? Just say 'connect my calendar'."
- Debrief without Notion: "I saved this debrief to local files. If you connect Notion, I can track all your relationships in one place."
- Engagement hitlist without Apify: "I can write better comments if I can see actual LinkedIn posts. Want to connect Apify?"

**Rules for suggestions:**
- Maximum once per session per integration
- Never pressure. Always frame as "whenever you're ready"
- If they say no or ignore it, don't ask again for 7 days
