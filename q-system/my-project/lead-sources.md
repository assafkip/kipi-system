# Lead Sources -- Where to Find People Who Need What You Built

{{SETUP_NEEDED}}

## Core Principle

Search for OPERATIONAL PAIN, not AI interest. Your ICP says "I'm the bottleneck," "nothing talks to each other," "I spent all weekend on admin." They don't use AI vocabulary. They describe symptoms.

## Pain Signal Keywords

**DROP these keywords (attract vendors, not practitioners):**
- ~~AI~~, ~~chatgpt~~, ~~automate~~, ~~automation~~, ~~workflow~~

**USE these keywords (real practitioner language):**

| Category | Keywords / Phrases |
|----------|-------------------|
| Time pain | "spent all weekend", "hours on admin", "working nights", "half my time" |
| Tool pain | "nothing talks to each other", "too many apps", "scattered across", "spreadsheet hell" |
| Capacity pain | "I'm the bottleneck", "can't take on more clients", "hit a ceiling", "at capacity" |
| Quality pain | "falling through the cracks", "keep making mistakes", "missed deadlines" |
| Hiring pain | "can't afford to hire", "too much for just me" |
| Identity pain | "didn't become a [role] to do admin", "wearing too many hats" |
| Help-seeking | "how do other firms handle", "anyone else struggle with", "is there a better way" |
| **Buying signal (general)** | "looking for a consultant", "can anyone recommend", "need someone to help", "who can I hire" |

### Service-Line-Specific Keywords

{{Add keywords for each service line from founder-profile.md. Example:}}

| Service Line | Pain Keywords | Buying Signal Keywords |
|-------------|---------------|----------------------|
| {{service_line_1}} | {{pain keywords}} | {{buying signal keywords}} |
| {{service_line_2}} | {{pain keywords}} | {{buying signal keywords}} |
| {{service_line_3}} | {{pain keywords}} | {{buying signal keywords}} |

---

## Daily Rotation (organized by service line cluster)

Each day targets a different service line cluster so you scan different communities and match different pain patterns. Read `founder-profile.md` service_lines section for your service line definitions.

| Day | Cluster | Subreddits / Sources | Method |
|-----|---------|---------------------|--------|
| Mon | **Service Line 1** | {{subreddits for SL1}} | /new/ JSON API, pain-filtered |
| Tue | **Service Line 2** | {{subreddits for SL2}} | /new/ JSON API, pain-filtered |
| Wed | **Industry verticals** | {{subreddits from verticals.md}} | /new/ JSON API, pain-filtered |
| Thu | **Service Line 3 / AI builders** | {{subreddits for SL3}} | /new/ JSON API, pain-filtered |
| Fri | **CATCH-UP + INBOUND** | All missed platforms + own content engagement | Mixed |

### Friday: Catch-Up + Inbound Day

Friday is the most important mining day -- catches gaps and harvests inbound.

1. **Catch-up scan (FIRST):** Check Weekly Scan Tracker. Any platform with no scan this week gets scanned NOW.
2. **Inbound signal check (HIGHEST PRIORITY):** Check engagement on own posts across all platforms. Commenters who say "this is exactly my problem" are the warmest leads.
3. **Response checks:** Check warming tracker for responses.
4. **Exploratory (IF TIME):** 1 Tier 3 sub + GitHub Discussions + HN. Low-yield, only after catch-up and inbound.

---

## Budget Qualifiers

Read `{{QROOT}}/my-project/budget-qualifiers.md` for the full keep/skip table. Every lead gets budget-qualified before copy is generated. High pain + no budget = skip.

---

## Technical Config

**Reddit method:** curl with browser user agent to Reddit JSON API
```bash
curl -s -H "User-Agent: Mozilla/5.0" "https://www.reddit.com/r/[SUBREDDIT]/new.json?limit=30"
```

**Known issues:**
- Apify Reddit scraper ignores `restrict_sr` in search URLs -- always use /new/ or /top/ URLs
- LinkedIn pain-language search returns vendors, not practitioners
- X/Twitter keyword search returns vendors/automation agencies
- Generic subs (r/Entrepreneur, r/smallbusiness, r/freelance) produce 0 ICP in most niches

## Platforms Beyond Reddit

| Platform | Method | When |
|----------|--------|------|
| X/Twitter | Apify tweet-scraper, monitor specific handles | Per rotation |
| LinkedIn | Chrome search for connection mining, Apify for post scraping | Per rotation |
| Hacker News | Algolia API for "Ask HN" threads | Friday exploratory |
| GitHub Discussions | n8n, activepieces, dify repos | Friday exploratory |
