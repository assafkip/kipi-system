# Scoring Config

Single source of truth for lead scoring, temperature signals, and strategic targeting.
Read by agents that score prospects or generate outreach.

## Regulatory/Compliance Bonus Sectors
Read `{{QROOT}}/canonical/engagement-playbook.md` for domain-specific targeting rules and sector bonuses.
Bonus: +3 to lead score, +1 to temperature. Angle: "regulators now agree with the problem you're describing."

## Lead Scoring (5 dimensions, 0-5 each, max 25 + bonus)
- **Pain Signal**: real operational problem described? (5 = "we have no way to track...", 0 = generic opinion). Read `{{QROOT}}/canonical/talk-tracks.md` for validated buyer pain language that scores 5 automatically from buyer roles.
- **First-Person Proof**: their own experience? (5 = "I spent 3 days...", 0 = retweeted article)
- **Role Fit**: buyer? (5 = {{TARGET_PERSONA}} or equivalent decision-maker, 0 = student/vendor)
- **Engagement Opportunity**: can you add value? (5 = specific pain, 0 = 50 generic replies already)
- **Multi-Team Pain**: touches multiple teams? (5 = cross-functional, 0 = single tool complaint)

## Lead Tiers
- Tier A (20-25): Send outreach today
- Tier B (15-19): Engage today (comment, then DM)
- Tier C (10-14): Add to warm list
- Below 10: Discard

## Temperature Signal Weights
| Signal | Weight |
|--------|--------|
| DM reply received | +3 |
| Email reply received | +3 |
| Demo request / scheduling link | +4 |
| Connection accepted (7 days) | +2 |
| Comment on your post | +2 |
| Like on your post | +1 |
| Link click (UTM) | +2 |
| Profile view (notification) | +2 |
| Post share/repost (notification) | +3 |
| No contact 14+ days | -1 |
| No contact 30+ days | -2 |

## Temperature Buckets
- Hot: 8+
- Warm: 4-7
- Cool: 1-3
- Cold: 0 or below
