# Test Apify Connection

## How to Test

### Test 1: Can we reach the API?

**What to try:**
- Use the Apify MCP tool to list available actors
- If it returns a list: PASS
- If it errors with auth: FAIL (bad token)
- If it errors with "not found": FAIL (server not configured)

**On PASS:**
> "Apify is connected! I can see [N] available tools for research."

**On FAIL (auth):**
> "That access code didn't work. Let's try again:
> - Go to apify.com
> - Click your profile icon (top right) > Settings > Integrations
> - Copy the API token again (make sure you get the whole thing)
> - Paste it here"

**On FAIL (server):**
> "The research engine isn't set up yet. Let me walk you through it."
Then follow `guides/connect-apify.md`.

### Test 2: Quick scrape test

**What to try:**
- Run a minimal web scraper call (e.g., scrape a single public page title)
- If it returns data: PASS
- If it errors: check account credits

**On PASS:**
> "Everything works. I can research people and find posts for you."

**On FAIL:**
> "The connection works but I couldn't run a test search. This might mean your free credits are used up. Check your balance at apify.com > Settings > Billing."
