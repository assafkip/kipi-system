# Template: One-Pager (Gamma Document)

> Used by `/q-market-create one-pager [contact]`
> Generated via Gamma MCP as a document (format: "document")
> Personalized per-contact for meeting prep

---

## Pre-Generation Steps

1. **Pull contact from CRM** - Search Contacts DB for the person
2. **Read relationships.md** - Pull conversation history, what they care about
3. **Determine their pool** - VC / Prospect / Partner / Advisor / Government
4. **Query NotebookLM** for industry/company context
5. **Select relevant proof points** from proof-points.md
6. **Check objections.md** for persona-specific pushback to preempt

## Input Text Structure (for Gamma)

```
Create a 1-2 page briefing document for [Name], [Role] at [Company].

THEIR CONTEXT:
- Industry: [industry]
- Role focus: [what they care about]
- Known pain points: [from conversation history or industry research]
- Recent relevant events: [industry events, regulatory changes]

THE PROBLEM (tailored to their world):
[Industry-specific version of the problem you solve.]

THE SOLUTION (positioned for their lens):
[{{YOUR_METAPHOR}} / {{YOUR_CATEGORY}} framing appropriate for their technical level]
- For VCs: category creation + market size + moat
- For technical buyers: workflow impact + existing tool integration + time savings
- For prospects: specific use case + governance value
- For government: provenance + audit trail + compliance

PROOF POINTS:
[1-2 most relevant from proof-points.md]
[Relevant endorser if applicable]

NEXT STEP:
[Specific: schedule demo, pilot conversation, introduction, etc.]
```

## Rules

- Personalized to recipient's industry, role, pain points
- Lead with THEIR problem, not your solution
- 1-2 relevant proof points from their industry
- Specific next step (not generic CTA)

## Output Format

Save to: `output/marketing/one-pagers/one-pager-[contact-name]-YYYY-MM-DD.md`
