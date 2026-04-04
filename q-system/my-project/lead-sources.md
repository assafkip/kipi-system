# Lead Sources Configuration

> Configures where the morning pipeline looks for leads and engagement targets. Populated during setup or via `/q-calibrate`.

## X Accounts to Monitor

> Agents scan these handles for reply/QT opportunities (last 48h). Keep to 5-10 max.

| Handle | Why |
|--------|-----|
| <!-- @handle1 --> | <!-- reason --> |

## Reddit Subreddits

> Used by lead sourcing (Phase 5) for RSS feed scraping. Rotated daily per commands.md schedule.

| Subreddit | Focus | Day Rotation |
|-----------|-------|-------------|
| r/cybersecurity | General security practitioner pain | Mon/Wed/Fri |
| r/netsec | Technical security | Mon/Wed/Fri |
| r/blueteamsec | Blue team / detection engineering | Tue/Thu |
| r/AskNetsec | Security career + tool questions | Tue/Thu |

## Medium Tags

> Used by lead sourcing for RSS feed scraping (`medium.com/feed/tag/TAG`).

| Tag (kebab-case) | Maps to pain category |
|-------------------|----------------------|
| <!-- detection-engineering --> | <!-- CAT1 --> |
| <!-- incident-response --> | <!-- CAT4 --> |
| <!-- cybersecurity --> | <!-- General --> |
| <!-- security-operations --> | <!-- CROSS --> |

## LinkedIn Search Queries

> Used by lead sourcing Chrome scraping. Rotation defined in commands.md.
> Reference: `canonical/market-intelligence.md` for search terms.

## Instagram Hashtags

> Niche compound tags only. Broad tags (#marketing, #tech) are banned. Rotation follows same day-of-week pattern as Reddit.

| Hashtag | Pain Category | Schedule |
|---------|--------------|----------|
| <!-- #threatintelligence --> | <!-- CAT1 --> | <!-- Mon/Wed/Fri --> |

## Instagram Creators

> Accounts your ICP follows. Profile-scraped weekly (Mondays). Max 20.

| Handle | Why | Last Scraped |
|--------|-----|-------------|
| <!-- @handle --> | <!-- reason --> | <!-- YYYY-MM-DD --> |

## TikTok Keywords

> Search queries. TikTok keyword search is high-signal. Rotation follows day-of-week pattern.

| Query | Pain Category | Schedule |
|-------|--------------|----------|
| <!-- "threat intelligence tools" --> | <!-- CAT1 --> | <!-- Mon/Wed/Fri --> |

## TikTok Hashtags

> Niche tags only. Same rotation logic as Reddit.

| Hashtag | Pain Category | Schedule |
|---------|--------------|----------|
| <!-- #cybersecurity --> | <!-- General --> | <!-- Mon/Wed/Fri --> |

## TikTok Creators

> Creators producing content your ICP watches. Profile-scraped weekly (Mondays). Max 20.

| Handle | Why | Last Scraped |
|--------|-----|-------------|
| <!-- @handle --> | <!-- reason --> | <!-- YYYY-MM-DD --> |

## GitHub Repos to Watch (Mondays)

> Checked for new contributors/stars as lead signals.

| Repo | Why |
|------|-----|
| <!-- org/repo --> | <!-- reason --> |
