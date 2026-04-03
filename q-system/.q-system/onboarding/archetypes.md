# User Archetypes

When a new user starts setup, determine their archetype FIRST. This controls which integrations to offer and which parts of the system to emphasize.

## How to Detect

**The archetype question text lives in `setup-flow.md` Step 0.** Use that version (it has full explanations for each option). Do NOT use the short descriptions below - they're just for quick reference.

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
| Recommended | Chrome automation | LinkedIn profiles, posts, DMs, engagement |
| Optional | Apify | X/Twitter scraping for lead sourcing |
| Optional | Telegram | Message contacts directly |
| Optional | Gamma | Generate pitch decks and one-pagers |

### product-founder
**Focus:** Stay organized, occasional outreach, don't lose track of conversations

| Tier | Integration | Why |
|------|------------|-----|
| Required | Notion | Task tracking, light CRM |
| Recommended | Google Calendar | Know what's coming today |
| Optional | Gmail | Draft emails when needed |
| Optional | Apify | X/Twitter scraping for research |

### content-creator
**Focus:** Content pipeline, audience engagement, social presence

| Tier | Integration | Why |
|------|------------|-----|
| Required (CLI/Desktop) | Chrome automation | LinkedIn engagement, post scraping, DMs |
| Recommended | Notion | Content calendar, asset library |
| Optional | Apify | X/Twitter scraping for engagement |
| Optional | Gamma | Create visual content, slide decks |
| Optional | Google Calendar | Schedule content drops |

**Web users (claude.ai/code):** Chrome automation is not available. Recommend Notion as the primary integration instead. Say: "On the web version, I can't automate LinkedIn directly. I'd recommend connecting Notion to track your content pipeline. You can still use `/q-engage` to generate comments - you'll just paste them manually."

### operator
**Focus:** Keep the founder on track, manage calendar, follow up on actions

| Tier | Integration | Why |
|------|------------|-----|
| Required | Notion | CRM, action tracking, pipeline |
| Required | Google Calendar | Calendar management |
| Required | Gmail | Email drafts, follow-ups |
| Optional | Apify | X/Twitter research for the founder |

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
- Engagement hitlist without Chrome: "I can write better comments if I can see actual LinkedIn posts. Want to connect Chrome? Just say 'connect my chrome'."
- Research or competitive analysis without research mode: "I'm making claims here that I haven't verified. Want me to switch to research mode? I'll cite everything. Just say '/q-research'."

**Rules for suggestions:**
- Maximum once per session per integration
- Never pressure. Always frame as "whenever you're ready"
- If they say no or ignore it, don't ask again for 7 days
