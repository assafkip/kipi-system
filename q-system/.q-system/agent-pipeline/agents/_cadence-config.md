# Cadence Config

Single source of truth for all posting, outreach, and engagement frequency decisions.
Read by agents that generate content or manage prospect touchpoints.
Updated when strategy changes - not by agents, only by the founder.

## Sources
- `q-system/marketing/content-themes.md` (platform-specific cadence)
- `q-system/canonical/engagement-playbook.md` (outreach timing)
- LinkedIn limits research: LinkedSDR, PhantomBuster, Evaboot (2025-2026)
- B2B outreach cadence: SalesBread, Callbox, Martal (2025-2026)
- Reddit B2B: Syndr, influencers-time (2025)

## Posting Cadence

| Platform | Frequency | Notes |
|----------|-----------|-------|
| LinkedIn | 3-5 posts/week | Tue-Thu peak. Not daily. Quality > quantity. |
| X | 3-5 posts/day (incl. replies/quotes) | Hot takes, signal reactions, thread replies. Higher volume than LinkedIn. |
| Reddit | 1 substantive post or comment/week in relevant subreddits | Depth wins. Communities spot vendors fast. Lead with help, not links. |
| Medium | 1 article/month | Only when signal has enough depth. No filler articles. |

## Outreach Cadence (per prospect)

| Touchpoint | Timing | Channel |
|------------|--------|---------|
| Initial outreach | Day 0 | Connection request + note OR DM if already connected |
| Follow-up 1 | Day 3 | Different angle. Comment on their post or value-drop. |
| Follow-up 2 | Day 7-8 | New value piece (signal, article, resource) |
| Follow-up 3 | Day 14 | Final value touch |
| Breakup / park | Day 21 | Acknowledge silence, leave door open. Move to Cooling. |

## Platform Limits

| Limit | Number | Risk |
|-------|--------|------|
| LinkedIn connection requests | 15/day, 80/week | Conservative. Platform allows ~100/week but throttles aggressive senders. |
| LinkedIn DMs to non-connections | 0 (InMail only) | We don't use InMail. Connect first. |
| Value-drop cooldown per prospect | 5 days minimum | From cold-email skill: 3-7 day gap between touches. |
| Max daily hitlist actions | 15 | 6-8 touchpoints per prospect over 2-3 weeks. 15 actions across all prospects is sustainable. |
| DM follow-up timeout (auto-Cooling) | 14 days no reply | Aligns with Follow-up 3 timing. |
| Auto-close (Passed) | 21 days no reply after 3+ touches | Breakup timing from cold-email skill. |

## Apify Actor Reference

| Platform | Actor ID | Use Case | Max Results |
|----------|----------|----------|-------------|
| X/Twitter | `curious_coder/twitter-scraper` | Post scraping, search | 100 |
| Instagram | `apify/instagram-hashtag-scraper` | Hashtag discovery | 50/hashtag |
| Instagram | `apify/instagram-profile-scraper` | Creator monitoring | 20 posts/profile |
| Instagram | `apify/instagram-post-scraper` | Founder's own metrics | 30 days |
| Instagram | `apify/instagram-comment-scraper` | Comment mining (future) | 100/post |
| TikTok | `clockworks/tiktok-scraper` | Keyword + hashtag search | 50/query |
| TikTok | `clockworks/tiktok-profile-scraper` | Creator monitoring | 20 videos/profile |
| TikTok | `clockworks/tiktok-comments-scraper` | Comment mining (future) | 100/video |

**Budget cap:** Do not exceed $2 total Apify spend per morning run across IG + TikTok combined.

## Engagement Cadence

| Activity | Frequency | Cap |
|----------|-----------|-----|
| Comments on prospect posts | 1 per prospect per week | Avoid looking like a stalker |
| Comments total | 5-10/day | Mix of prospects + genuine community engagement |
| DM replies | Same day if possible | Responsiveness signals interest |
| New connection requests | 10-15/day | Stay under LinkedIn radar |
