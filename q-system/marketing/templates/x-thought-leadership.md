# Template: X (Twitter) Thought Leadership Thread

> Used by `/q-market-create x [topic]`
> Punchier adaptation of LinkedIn thought leadership posts.

---

## Pre-Generation Steps

1. **Start from LinkedIn TL post** - the X thread is a punchier adaptation, not a repost
2. **Read canonical sources** - same as LinkedIn TL template
3. **Query NotebookLM** if original post used it

## Structure

```
TWEET 1 (HOOK):
[280 char max. The sharpest version of the insight. Take a position.]

TWEET 2:
[Supporting context or stat. Must stand alone if someone only sees this tweet.]

TWEET 3:
[The example or proof. Specifics.]

TWEET 4 (optional):
[Implication or question.]

TWEET 5 (optional):
[Link to longer form content if applicable]
```

## Rules

- Each tweet: 280 char max
- Each tweet must stand alone
- More opinionated than LinkedIn - take a position
- 3-5 tweets per thread
- No hashtags in tweets
- No product pitch

## Output Format

Save to: `output/marketing/x/x-tl-YYYY-MM-DD.md`

```markdown
# X Thread - [Date]

**Theme:** [theme name]
**Adapted from:** [LinkedIn post file if applicable]

---

TWEET 1:
[text]

TWEET 2:
[text]

TWEET 3:
[text]

---

**Guardrails:** [PASS/FAIL]
```
