# /q-reality-check — Challenger mode

Temporarily argue AGAINST current positioning to find weak spots. Stress-test claims, assumptions, and proof points against evidence. Run monthly or before major meetings.

## Setup guard

**FIRST:** Call `kipi_paths_info` MCP tool to get resolved directory paths. Use these paths for all file operations below.

Read `{config_dir}/founder-profile.md`. If it contains `{{SETUP_NEEDED}}`, STOP and tell the user:

> This system hasn't been configured yet. Run `/q-setup` first to set up your profile, integrations, and canonical files.

Do not proceed with any other steps.

## Preconditions

Read ALL canonical files:
1. `{config_dir}/canonical/talk-tracks.md`
2. `{config_dir}/canonical/objections.md`
3. `{config_dir}/canonical/discovery.md`
4. `{config_dir}/canonical/market-intelligence.md`
5. `{config_dir}/canonical/pricing-framework.md`
6. `{data_dir}/my-project/current-state.md`
7. `{data_dir}/my-project/competitive-landscape.md`
8. `{config_dir}/founder-profile.md`

## Integration checks

No external integrations required. Works entirely from canonical files.

## Process

1. **Claim audit** — List every factual claim in talk-tracks.md and current-state.md. For each:
   - Is it backed by evidence in discovery.md?
   - Is it still true based on current-state.md?
   - Could a competitor make the same claim?
2. **Objection stress test** — For each objection in objections.md:
   - Is the response actually convincing, or just hopeful?
   - What would a skeptical buyer say next?
   - Is there a proof point, or just an assertion?
3. **Competitive blind spots** — Review competitive-landscape.md:
   - Are there substitutes we're not tracking?
   - Has any competitor shipped something that weakens our position?
4. **Positioning drift** — Does our positioning still match what we actually do today?
   - Compare talk-tracks.md against current-state.md
   - Flag anything we claim but can't demo
5. **Output a report** with:
   - Weak claims (no proof)
   - Stale data (needs refresh)
   - Competitive risks
   - Recommended calibrations

## Output rules

- Be genuinely adversarial — this is not a feel-good exercise
- Every weakness must come with a concrete fix or investigation step
- Mark unproven claims with `{{NEEDS_PROOF}}`
- Don't sugarcoat, but pair hard truths with actionable next steps (respect AUDHD rules if enabled)
