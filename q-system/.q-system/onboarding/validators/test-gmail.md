# Test Gmail Connection

## How to Test

### Test 1: Can we read the inbox?

**What to try:**
- Use the Gmail MCP tool to list recent messages (limit 5)
- If it returns messages: PASS
- If it errors with auth: FAIL (auth issue)
- If it errors with "not found" or "unavailable": FAIL (server not configured)

**On PASS:**
> "Gmail is connected! I can see your recent emails."

**On FAIL (auth):**
> "The connection didn't work. This usually means the sign-in needs to be refreshed:
> - Go back to your Claude settings
> - Find Gmail in your connected tools
> - Try disconnecting and reconnecting it"

**On FAIL (server not configured):**
> "Gmail isn't set up yet. Let me walk you through connecting it."
Then follow `guides/connect-gmail.md`.

### Test 2: Can we get profile info?

**What to try:**
- Use Gmail MCP to get the user's profile/email address
- If it returns an email: PASS (and save the email to founder-profile.md)
- If it fails: not critical, skip

**On PASS:**
> "Connected as [their email]."
