# Social Reaction Gate (ENFORCED)

Fires when the founder shares someone else's content and asks to react to it. Whether it fires is measured -- advisory, on demand, never blocking -- by `q-system/.q-system/scripts/skill-trigger-eval.py`; the scope of the label above is pinned by `q-system/.q-system/scripts/test/test-social-reaction-gate-rule-wired.sh`, and the last section says what that does and does not cover.

## Before Drafting Any Reaction

1. **Extract the poster's claims.** List specific claims/positions. No interpretation.
2. **Show extracted claims to the founder.** Do not draft until confirmed.
3. **Draft the reaction** using engagement playbook style rules + founder voice skill.
4. **Self-check for drift.** Verify the reaction doesn't pitch or name-drop your product unless explicitly asked. Reactions are about the poster's ideas.

## What Counts as a Reaction

- Comment on someone's post; reply to their comment or thread; quote-post or repost with commentary
- DM referencing someone's public content; email response to a shared article or newsletter

## What the ENFORCED label above covers

**The honest labelling only, pinned by that test.** Steps 1-4 are not gated and that is not a TODO: a reaction is chat output with no file artifact for a PostToolUse hook to inspect, and whether this gate fires at all is a model decision -- the judgment half of `skill-hook-pairing.md`'s decision rule, which gets no hook.
The measurement runs against `q-system/.q-system/skill-evals/social-reaction-gate.json`, the same posture founder-voice, rca and fable-discipline already have. Read its silence narrowly: it sees whether the gate triggers, never whether the claims you extracted were the poster's actual ones.
