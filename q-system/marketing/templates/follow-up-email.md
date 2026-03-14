# Template: Follow-Up Email

> Used by `/q-market-create follow-up [contact]`
> Sent after meetings. Pulls from debrief notes when available.

---

## Pre-Generation Steps

1. **Check for debrief** - Has `/q-debrief [contact]` been run? Pull what resonated, next step, open items.
2. **Pull from CRM** - Interactions DB for latest meeting, Contact for context
3. **Check relationships.md** for conversation history
4. **DO NOT query NotebookLM** - follow-ups are relationship-specific

## Templates

### Post-Investor Meeting

```
Subject: [Reference to something discussed - not "Great meeting"]

[Name] -

[1 sentence: reference something specific they said or asked about. Use their words.]

[1-2 sentences: address their key question or provide what you promised. Include demo link if discussed.]

[1 sentence: clear next step with timeline.]

{{YOUR_NAME}}
```

### Post-Prospect / Design Partner Meeting

```
Subject: [Topic discussed] - next steps

[Name] -

[1 sentence: reference something specific from the conversation.]

[1-2 sentences: what you discussed doing next. Be specific - scope, use case, timeline.]

[1 sentence: what you need from them / what you'll send.]

{{YOUR_NAME}}
```

### Post-Event / Conference

```
Subject: [Event name] - [topic discussed]

[Name] -

[1 sentence: reference where you met and what you talked about.]

[1 sentence: the one thing most relevant to them from your conversation.]

[1 sentence: specific next step.]

{{YOUR_NAME}}
```

## Rules

- 2-4 sentences total
- Reference something THEY said (from debrief if available)
- Include what you promised (demo link, deck, intro, etc.)
- Clear next step with timeline
- Send within 24 hours of meeting
- No "It was great meeting you" opener (wasted sentence)

## Output Format

Save to: `output/marketing/outreach/follow-up-[contact-name]-YYYY-MM-DD.md`
