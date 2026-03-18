# Auto-Fail Checklist

This file is the single source of truth for critical rules. Read by:
- Copy agents (before writing) as a pre-write checklist
- Compliance agent (after writing) as the audit ruleset

## Auto-Fail (block output)

### Misclassification
- Describes {{YOUR_PRODUCT}} using categories it is NOT (check canonical/positioning.md for "is not" list)
- Claims a capability the product does not have without {{UNVALIDATED}} marker
- Says "AI-powered" without specifics

### Overclaiming
- Claims a capability not in current-state.md as "works today"
- References unconfirmed partnerships, LOIs, or customer counts
- Says something is "built" or "live" when it is vision only - must add {{UNVALIDATED}}
- Fabricates content, reports, or deliverables that don't exist. Every claim must reference something real.

### Decision Rules
- Violates any active RULE in canonical/decisions.md

## Warn (flag, don't block)

### Voice
- DM or email starts with person's name instead of "I"
- Uses "circling back," "just checking in," "following up on my last message"
- Lists company names or years of experience in outreach
- Uses emdashes
- Uses "leverage," "delve," "innovative," "cutting-edge," "game-changing"
- Uses hedging: "might," "could potentially," "it's worth noting"

### Data Integrity
- Prospect company/role doesn't match what's in notion.json or contacts DB
- Profile URL is a guessed slug (not captured from browser address bar)
