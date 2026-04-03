# Test Google Calendar Connection

## How to Test

### Test 1: Can we list calendars?

**What to try:**
- Use the Google Calendar MCP tool to list available calendars
- If it returns calendars: PASS
- If it errors: FAIL

**On PASS:**
> "Calendar connected! I can see [N] calendars including [primary calendar name]."

**On FAIL:**
> "I can't reach your calendar. Let's fix it:
> - Go to your Claude settings and check that Google Calendar is connected
> - Try disconnecting and reconnecting
> - Make sure you granted calendar permissions when signing in"

### Test 2: Can we see today's events?

**What to try:**
- Query today's events from the primary calendar
- If it returns events: PASS with detail
- If it returns empty: PASS (just no events today)
- If it errors: FAIL

**On PASS (with events):**
> "Working! You have [N] events today. Your next one is [event name] at [time]."

**On PASS (no events):**
> "Connected! No events on your calendar today, but I'll be able to see them going forward."
