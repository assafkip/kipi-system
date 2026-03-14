# Template: Outreach Email

> Used by `/q-market-create outreach [contact]`
> Three variants: cold, warm, intro

---

## Pre-Generation Steps

1. **Pull contact from CRM** (if exists) - history, pool, what they care about
2. **Determine email type:** Cold / Warm / Intro
3. **Check relationships.md** for any context
4. **DO NOT query NotebookLM** - outreach is relationship-specific

## Templates

### Cold Outreach

```
Subject: [Specific reference - their post, their company, their problem]

[Name] -

[1 sentence: why you're reaching out. Reference something specific about them.]

[1-2 sentences: the problem framing relevant to their role/industry. No jargon. Use their language.]

[1 sentence: what you'd like. One ask, not three.]

{{YOUR_NAME}}
```

**Rules:**
- 3-5 sentences total
- Subject line references something specific
- Never attach a deck unsolicited
- One question, not three
- Sign off as just your first name

### Warm Outreach

```
Subject: [Reference to prior touchpoint]

[Name] -

[1 sentence: reference to how you connected / what you discussed.]

[1-2 sentences: update or reason for reaching out now.]

[1 sentence: specific ask.]

{{YOUR_NAME}}
```

### Introduction Email (double opt-in)

```
Subject: Quick intro? {{YOUR_NAME}} <> [Their name]

[Introducer name] -

Would you be open to connecting me with [Name]? [1 sentence: why.]

[1 sentence: brief context for them to forward.]

No worries if the timing isn't right.

{{YOUR_NAME}}
```

## Rules

- Reference something specific about the recipient
- Never attach a deck unsolicited
- One question, not three
- Sign off with just your first name
- No "I'd love to" or "I'd be thrilled to"

## Output Format

Save to: `output/marketing/outreach/outreach-[contact-name]-YYYY-MM-DD.md`
