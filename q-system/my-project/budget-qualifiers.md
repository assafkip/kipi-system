# Budget Qualifiers -- Can This Lead Pay?

{{SETUP_NEEDED}} -- Replace placeholders with your actual pricing and budget signals.

## Minimum Engagement Price
- Monthly retainer: ${{MIN_MONTHLY_RETAINER}} (e.g., $5,000)
- POC sprint: ${{MIN_POC_PRICE}} (e.g., $5,000)

## Keep Signals (evidence they can pay)
| Signal | What it means |
|--------|---------------|
| "my team", "our firm", "my practice" | Has employees/revenue, not a side project |
| Mentions revenue, clients, cases, deals | Active business with cash flow |
| "we're growing", "scaling", "hiring" | Revenue trajectory that supports consulting spend |
| Title: Partner, Principal, Managing Director, CEO, VP, Founder + company name | Decision-maker with budget authority |
| Industry: {{HIGH_BUDGET_INDUSTRIES}} | Industries where your pricing is reasonable |
| Quantified pain ("losing $X", "costs us $X per month") | Has budget to solve it |

## Skip Signals (cannot pay regardless of pain)
| Signal | Why skip |
|--------|----------|
| "just starting out", "pre-revenue" | No cash flow |
| "side hustle", "side project" | Not a real business |
| "student", "learning", "course project" | No budget |
| "no budget", "free tools only", "bootstrap" | Explicitly cannot pay |
| Solopreneur with no team or revenue mentioned | Likely sub-$100K revenue |
| "looking for free advice" | Not a buyer |

## How Agents Use This
- `05-lead-sourcing.md`: Budget signal is a scoring dimension. Score 0 = auto-discard.
- `05-connection-mining.md`: Budget qualification gate runs before scoring.
- `05-engagement-hitlist.md`: Budget gate runs before generating copy. Disqualified leads get `budget_disqualified: true` and no copy.
