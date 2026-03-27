**Step 2.5: Market intelligence extraction (during scoring, not a separate pass):**
While scoring each post, also evaluate whether it has **canonical value** beyond engagement. Not every post qualifies - only capture genuinely new signal. Apply these lenses:

| Lens | What to capture | Route to |
|------|----------------|----------|
| **Problem language** | Verbatim phrases where practitioners describe a pain we solve in THEIR words | `canonical/market-intelligence.md` Problem Language section + consider for `canonical/talk-tracks.md` |
| **Category signal** | "I wish there was..." / "Why doesn't someone build..." / describing our category without knowing it | `canonical/market-intelligence.md` Category Signals section |
| **Objection preview** | Concerns about tools like ours, skepticism about AI in security, "we tried X and it didn't work" | `canonical/market-intelligence.md` Objection Previews + `canonical/objections.md` if new |
| **Competitive intel** | Praise or complaints about tools in our landscape (detection platforms, TIPs, SOAR, GRC tools) | `canonical/market-intelligence.md` Competitive Intel + `my-project/competitive-landscape.md` if significant |
| **Buyer process** | How they evaluate, budget, get approval, implement. Procurement friction, decision timelines | `canonical/market-intelligence.md` Buyer Process section |
| **Narrative check** | Does this confirm or contradict our positioning? If 5+ people describe the problem differently than we do, flag it | `canonical/market-intelligence.md` Validation Log |

**Rules:**
- Only capture if it's genuinely new signal (not a repeat of what we already have)
- Verbatim quotes are more valuable than paraphrases
- One high-signal post with canonical value > 10 engagement-only posts
- If a post scores 20+ AND has canonical value, it's a priority capture
- Log entries go to `canonical/market-intelligence.md` with date, platform, author, URL, verbatim quote, lens, and one-sentence insight
- If 3+ posts in a single day point to the same theme, flag it as a **market pattern** in the morning briefing
