# Founder Notifications (ENFORCED)

Every proactive founder-facing ping/alert goes through ONE channel:

```
bash q-system/.q-system/scripts/slack-notify.sh "one concise line"
```

This posts to a Slack Incoming Webhook (`~/.config/kipi/slack-webhook`, gitignored
secret, or `$KIPI_SLACK_WEBHOOK`). Reliable, reaches the founder's phone, works
headless. Silent no-op if the webhook isn't configured, so callers never break.

## Why this is the only channel

`osascript` / macOS desktop notifications are permission-gated and **silently dropped**
from a sandboxed or background process (no error, just nothing). They are BANNED for
founder pings. Slack is the single reliable path.

## When to ping (and when not to)

Ping for things the founder would want to know **when they may be away**:
- An autonomous run (heartbeat, scheduled job) failed, timed out, or hit BLOCKED.
- Something needs a founder decision before work can continue.
- A meaningful state change on a tracked item (a maintainer replied; a loop closed; a PR landed).
- A sycophancy/anti-drift alert that fires while they're away.

Do NOT ping for routine progress, things they're clearly watching live in-session, or
status that hasn't changed ("still waiting" every cycle is noise, not a ping).

## For the agent (interactive sessions)

When you'd otherwise reach for a desktop notification or `PushNotification` to alert the
founder about something time-sensitive and they may be away, use `slack-notify.sh` instead.
In-session alerts the founder is watching live don't need a Slack ping.

## Wiring

- Producer of pings: any script/agent that detects a founder-relevant event.
- The single sink: `q-system/.q-system/scripts/slack-notify.sh`.
- Already wired: the open-loops heartbeat (`open-loops-heartbeat.sh`) — on a meaningful
  change AND on an agent run failure/timeout.
- New always-on / scheduled alert emitters MUST route through `slack-notify.sh`, never osascript.
