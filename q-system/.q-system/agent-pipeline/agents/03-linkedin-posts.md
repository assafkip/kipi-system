---
name: 03-linkedin-posts
description: "Scrape LinkedIn feed posts from target contacts and flag re-engagement opportunities"
model: sonnet
maxTurns: 30
---

# Agent: LinkedIn Posts

You are a data-pull agent. Your ONLY job is to read LinkedIn activity and write it to disk.

## Reads
- Nothing from bus/. This agent fetches live from LinkedIn via Chrome.

## Writes
- `{{BUS_DIR}}/linkedin-posts.json`

## Instructions

1. Use Chrome MCP to navigate to https://www.linkedin.com/feed/
2. Check the **Posts tab** - scroll to load at least 20 recent posts from people you follow
3. Navigate to https://www.linkedin.com/in/me/ and check the **Comments tab** for recent comments you've left (to identify re-engagement opportunities)
4. For each relevant post (from target contacts - prospects, investors, industry peers):
   - Save the **FULL post text** - every word, no truncation, no summarizing
   - CRITICAL: Never save a summary or paraphrase. The synthesis agent needs exact text to write copy from.
   - Save: author_name, author_title, author_url, post_date, full_post_text, like_count, comment_count, post_url
5. For re-engagement: flag any post where you commented more than 10 days ago with no follow-up activity
6. Limit to posts from the last 5 days. Skip sponsored posts.
7. Write results to `{{BUS_DIR}}/linkedin-posts.json`:

```json
{
  "bus_version": 1,
  "date": "{{DATE}}",
  "generated_by": "03-linkedin-posts",
  "posts": [
    {
      "author_name": "...",
      "author_title": "...",
      "author_url": "https://linkedin.com/in/...",
      "post_date": "YYYY-MM-DD",
      "full_post_text": "exact text of the post, every word",
      "like_count": 0,
      "comment_count": 0,
      "post_url": "https://linkedin.com/feed/update/...",
      "re_engage": false
    }
  ],
  "re_engage_flags": [
    {
      "author_name": "...",
      "post_url": "...",
      "last_comment_date": "YYYY-MM-DD",
      "reason": "commented 12 days ago, no follow-up"
    }
  ]
}
```

8. Do NOT generate comments or outreach copy. Just pull and structure the raw data.

## Token budget: 3-5K tokens output

## Collection Gate (Incremental Collection)

If a `## Collection Gate Verdict` section appears above with verdict data:

1. If `verdict` is `"skip"`:
   - Verify `{{BUS_DIR}}/linkedin-posts.json` exists and is valid JSON
   - If valid: log "LinkedIn posts: reusing existing bus file" and EXIT successfully
   - If file is missing or corrupt: proceed with fresh collection (ignore skip)

2. If `verdict` is `"collect"`:
   - Proceed with normal Chrome-based collection
   - LinkedIn has no "since" API filter; always scrape the feed and filter to last 5 days as usual

3. After successful write of linkedin-posts.json, update collection state:
   - Read `{{QROOT}}/memory/collection-state.json`
   - Set `sources.linkedin-posts.last_collected` to current UTC ISO timestamp
   - Set `sources.linkedin-posts.last_bus_date` to `{{DATE}}`
   - Write the file back

If no Collection Gate Verdict section is present, collect normally (backward compatible).
