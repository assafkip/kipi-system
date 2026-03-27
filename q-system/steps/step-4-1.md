**Step 4.1 — Value-first intel routing (daily, high priority):**

Send today's signals directly to people who would be AFFECTED by them. Not prospects, not a pitch. People who'd get real value from knowing about this breach/CVE/advisory before it hits their inbox from a vendor. This is the best relationship-building move in the system.

- **WHO GETS THESE:**
  - **ALL contacts in Notion Contacts DB** (any Type, any Status) who match by industry, tools, or role. Not limited to DP prospects or VCs.
  - **Email contacts** from Gmail/relationships who aren't in Notion but would be affected. CISOs, security leaders, practitioners in your network.
  - The test: "Would this person's Tuesday change if they saw this signal right now?" If yes, send it.

- **MATCHING LOGIC (signal -> person):**
  - **By vendor/tool affected:** Signal mentions SailPoint vulnerability -> send to everyone you know who runs SailPoint. Signal mentions CrowdStrike issue -> send to CrowdStrike users in your network.
  - **By industry:** Healthcare breach -> healthcare security contacts. Financial sector advisory -> FinServ CISOs.
  - **By threat actor/campaign:** Nation-state campaign targeting defense -> government/defense contacts.
  - **By role relevance:** New TTP/MITRE update -> detection engineers. Compliance deadline -> GRC contacts. Board-level risk -> CISOs.
  - Pull industry/company/tools from Notion Contact records (Company, Notes fields) and from LinkedIn profile data if available.

- **LINK TO SPECIFIC REPORT (mandatory):**
  - Every value-drop DM/email MUST link to the specific report URL on the signals page, not the homepage.
  - Format: `https://{{YOUR_DOMAIN}}/signals/[report-slug]?utm_source=[source]&utm_medium=[medium]&utm_campaign=value-intel&utm_content=[person-slug]`
  - Fetch the signals page, identify the individual report URLs, use those in messages.
  - If no individual URL exists for a signal, link to the signals page with an anchor or the closest match.

- **MESSAGE FORMAT (copy-paste ready, run through /assaf-voice):**
  - LinkedIn DM and email versions for each.
  - Reference the specific signal and WHY it matters to THEM.
  - Link to the specific report.
  - No pitch. No {{YOUR_PRODUCT}} mention. Pure intel sharing.
  ```
  INTEL DROPS TO SEND TODAY

  SIGNAL: [breach/CVE/advisory title]
  Report: [specific URL on {{YOUR_DOMAIN}}/signals/report-slug]

  SEND TO (LinkedIn DM):
  1. [Name] ([Company], [Role]) - why: [they run the affected tool / in the affected industry]
     💬 "[copy-paste DM with link to specific report]"
     ⏱️ 2 min | Quick Win

  2. [Name] ([Company], [Role]) - why: [reason]
     💬 "[copy-paste DM]"
     ⏱️ 2 min | Quick Win

  SEND TO (Email):
  1. [Name] ([email]) - why: [reason]
     💬 "[copy-paste email with link to specific report]"
     ⏱️ 2 min | Quick Win
  ```

- **VOLUME:** No daily cap on sends. If 8 people in your network run SailPoint and there's a SailPoint advisory, send to all 8. The cap is relevance, not a number. But still max 1 value drop per person per week.

- **UTM link generation (MANDATORY for all outreach):**
  - Every link sent MUST include UTM parameters for tracking
  - Format: `https://{{YOUR_DOMAIN}}/signals/[report-slug]?utm_source=[source]&utm_medium=[medium]&utm_campaign=value-intel&utm_content=[person-slug]`
  - **utm_source:** `linkedin`, `email`, `twitter`
  - **utm_medium:** `dm`, `email`, `comment`
  - **utm_campaign:** `value-intel` (replaces old `value-drop` - this is intel sharing, not dropping)
  - **utm_content:** person slug (lowercase, hyphenated name)
  - Log the UTM link in Notion LinkedIn Tracker entry so we know which link was sent to whom

- **RULES:**
  - NO {{YOUR_PRODUCT}} pitch. Zero. This is a practitioner sharing intel with their network.
  - Max 1 per person per week (don't spam)
  - The signal must be genuinely relevant to their specific situation. "Would their Tuesday change?" If no, don't send.
  - All copy goes through /assaf-voice before output. Casual, direct, helpful.
  - Log to Notion LinkedIn Tracker DB after sending (Type: Outreach DM, note: "Intel drop - [signal topic]", UTM link)
  - After 3 intel drops with no response AND no link clicks in GA, stop. They're not reading them.
  - **Email sign-off:** just "Assaf" (no Best/Cheers/Regards)

- **Create Actions** for each intel drop: (Energy: Quick Win, Time: 2 min, Priority: Today, Type: LinkedIn or Follow-up Email)

**Step 4 (continued) — Marketing content generation:**
- **If Tuesday or Thursday:** Also generate thought leadership posts from the editorial calendar theme:
  - Read `marketing/editorial-calendar.md` for this week's assigned theme + topic
  - Read `marketing/content-themes.md` for theme's canonical sources
  - Follow `marketing/templates/linkedin-thought-leadership.md` template for LinkedIn
  - Follow `marketing/templates/x-thought-leadership.md` template for X (3-5 tweet thread, sharper/more opinionated than LinkedIn, each tweet stands alone)
  - Query NotebookLM if theme benefits from research grounding (see content-themes.md per-theme guidance)
  - **Generate LinkedIn carousel via Gamma:** Call `mcp__gamma__generate_gamma` with format "presentation", inputText = 3-5 key insights from the TL post (one per slide), textMode "condense". This becomes a carousel PDF the founder uploads alongside the text post. Save Gamma URL + PDF export link.
  - **Generate X social card via Gamma:** Call `mcp__gamma__generate_gamma` with format "social", inputText = the sharpest line from the TL post. Single image card for the lead tweet.
  - Save LinkedIn to `output/marketing/linkedin/linkedin-tl-YYYY-MM-DD.md` (include Gamma carousel URL + PDF link)
  - Save X thread to `output/marketing/x/x-tl-YYYY-MM-DD.md` (include Gamma social card URL)
  - Create Content Pipeline DB entry (Type: LinkedIn Post, Status: Drafted, Theme: [number])
- **If Friday:** Also generate a Medium article draft from this week's assigned topic:
  - Read `marketing/editorial-calendar.md` for Medium topic
  - Follow `marketing/templates/medium-article.md` template (multiple NotebookLM queries)
  - **Generate Medium header image via Gamma:** Call `mcp__gamma__generate_gamma` with format "social", inputText = article title + key stat or framing question. Save Gamma URL.
  - **Generate sharing card via Gamma:** Call `mcp__gamma__generate_gamma` with format "social", inputText = article title + one-line summary. For LinkedIn/X cross-promotion when article publishes.
  - Save to `output/marketing/medium/medium-YYYY-MM-DD-[slug].md` (include Gamma header URL + sharing card URL)
  - Create Content Pipeline DB entry (Type: Medium Article, Status: Drafted, Scheduled: Sunday)
- **If Saturday or Sunday:** Also generate a Substack newsletter from this week's assigned topic:
  - Read `marketing/editorial-calendar.md` for Substack topic
  - Follow `marketing/templates/substack-newsletter.md` template
  - Can repurpose/expand the Medium article with added commentary, or be original content
  - **Generate newsletter header via Gamma:** Call `mcp__gamma__generate_gamma` with format "social", inputText = newsletter title + key insight.
  - Save to `output/marketing/substack/substack-YYYY-MM-DD-[slug].md` (include Gamma header URL)
  - Create Content Pipeline DB entry (Type: Substack Newsletter, Status: Drafted, Scheduled: Sunday)
