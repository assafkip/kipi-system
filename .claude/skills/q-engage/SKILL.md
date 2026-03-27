# /q-engage — Social engagement mode

LinkedIn and social media engagement with two modes: Proactive (daily hitlist) and Reactive (respond to shared post).

## Setup guard

**FIRST:** Call `kipi_paths_info` MCP tool to get resolved directory paths. Use these paths for all file operations below.

Read `{config_dir}/founder-profile.md`. If it contains `{{SETUP_NEEDED}}`, STOP and tell the user:

> This system hasn't been configured yet. Run `/q-setup` first to set up your profile, integrations, and canonical files.

Do not proceed with any other steps.

## Preconditions

Read these files:
1. `{config_dir}/enabled-integrations.md`
2. `{config_dir}/founder-profile.md`
3. `{config_dir}/canonical/engagement-playbook.md` — comment strategy, style rules, do/don't patterns
4. `{config_dir}/canonical/market-intelligence.md` — context for evaluating posts
5. `{data_dir}/my-project/relationships.md` — existing contacts for context

## Integration checks

| Integration | Used for | If unavailable |
|------------|----------|----------------|
| Apify | Scraping target LinkedIn/X posts | User provides posts manually |
| Notion | Pulling targets, logging interactions | Work from relationships.md, log locally |
| Playwright | Sending LinkedIn DMs | Skip DM automation, draft DM text for manual send |

## Proactive mode (default)

1. Pull engagement targets from Notion (or relationships.md)
2. Scrape recent posts from targets via Apify (or ask user to provide)
3. Evaluate each post for **market intelligence** (6 lenses from engagement-playbook.md)
4. Route market signals to `{config_dir}/canonical/market-intelligence.md`
5. Generate engagement hitlist — sorted by priority, one comment per target
6. Each comment: ready to copy-paste, with link to the post

## Reactive mode (triggered by screenshot)

When user shares a post screenshot or URL:
1. Evaluate post content for market intelligence (6 lenses)
2. Generate **1 best comment** — system picks the style. Not 2-3 options.
3. If user wants alternatives, they ask.
4. Log interaction to Notion/relationships.md

## Output rules

- Apply `founder-voice` skill to all comments and DMs
- Apply `audhd-executive-function` skill if enabled — comments should be copy-paste ready
- System decides comment style, not the user (decision elimination)
- Never produce generic "great post!" comments — every comment must add value
