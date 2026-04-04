# Template: Cold Outreach

> Used by `/q-engage dp-outreach` and `/q-engage` reactive mode
> LinkedIn connection requests, first DMs, value drops
> For email outreach, see `outreach-email.md`

---

## Pre-Generation Steps

1. **Pull contact from CRM** (if exists) - history, pool, what they care about
2. **Check relationships.md** for any prior context
3. **Find their recent post or content** - need a specific hook, not a generic opener
4. **Gather links:**
   - Target profile: `{{TARGET_PROFILE_URL}}`
   - Their post to reference: `{{TARGET_POST_URL}}`
   - Resource for value drop: `{{VALUE_DROP_URL}}`

## Structure

### Connection Request (300 char max)

```
[X] mutuals. I [credibility hook]. Would be good to connect.
```

### First DM (after connection accept)

```
I [noticed/saw/been thinking about] [something specific about them].
[One sentence connecting their work to your perspective].
[One question about their experience, not a pitch].
```

### Follow-up Value Drop (7-10 days after no reply)

```
[Saw/Found] [relevant signal/article/report].
Given your work on [their specific thing], thought worth flagging: [link]
```

## Rules

- Connection request: under 300 characters
- First DM: under 500 characters
- Value drop: under 300 characters
- Reference mutual connection count in connection requests
- One credibility signal, not a resume list
- "Would be good to connect" not "I'd love to connect"
- Start DMs with "I" not their name
- Reference something specific (their post, role, company challenge)
- Ask a genuine question in first DM, no pitch, no product mention
- Value drop: lead with value, not "following up"
- No mention of previous message in value drop
- Link to something genuinely useful to them

## Output Format

Save to: `output/marketing/outreach/cold-[contact-name]-YYYY-MM-DD.md`

## Post-Generation

1. All copy through voice skill
2. Log outreach in CRM (if connected)
