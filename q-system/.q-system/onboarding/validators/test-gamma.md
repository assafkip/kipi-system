# Test Gamma Connection

## How to Test

### Test 1: Can we reach Gamma?

**What to try:**
- Use the Gamma MCP tool to check availability (list tools or check auth)
- If it responds: PASS
- If it errors: FAIL

**On PASS:**
> "Gamma is connected! I can create decks and presentations for you."

**On FAIL:**
> "Gamma isn't connected. This is optional - you can create decks without it.
>
> If you want to try again:
> - Check your Claude settings for Gamma in the integrations list
> - Try disconnecting and reconnecting
>
> Or we can skip this and come back to it later."

### Test 2: Quick generation test (optional, costs credits)

Only run this if explicitly asked. Generating a test deck uses Gamma credits.

**What to try:**
- Generate a minimal 1-slide presentation with a test title
- If it returns a link: PASS
- If it fails: check account

**On PASS:**
> "Here's a test presentation to confirm it works: [link]. You can delete it from your Gamma account."
