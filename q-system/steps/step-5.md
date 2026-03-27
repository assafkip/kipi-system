**Step 5 — Weekly site metrics (MONDAYS ONLY — skip other days):**
- **Chrome browser** (`mcp__claude-in-chrome__*`): Navigate to Google Analytics (analytics.google.com, authuser=2, property a385692819p526076376)
- **Pull last 7 days:** Active users, sessions, new users, avg engagement time
- **Compare to prior 7 days:** Up/down/flat for each metric
- **Check by channel:** Direct vs Organic Social vs Organic Search vs Referral — is social growing?
- **Check landing pages:** /signals engagement time (benchmark: 21s), /demo active users, homepage bounce
- **Check key events** (once configured): demo_started, signals_engaged, suggestion_submitted counts
- **Flag anomalies:** Bot traffic spikes (Russia/other non-ICP countries), sudden drops, engagement time changes
- **Output:**
  ```
  📊 SITE METRICS (week of [date])

  Users: [X] ([+/-X] vs prior week)
  Sessions: [X] ([+/-X])
  New users: [X] ([+/-X])
  Avg engagement: [Xs] ([+/-Xs])

  CHANNELS:
  Direct: [X] | Social: [X] | Search: [X] | Referral: [X]

  TOP PAGES:
  /signals: [Xs] avg engagement, [X] sessions
  /demo: [X] active users
  /: [Xs] avg engagement

  KEY EVENTS: [counts or "not yet configured"]

  ⚠️ ANOMALIES: [bot traffic, drops, etc. — or "Clean"]
  ```
- **Benchmark targets** (set Feb 28 baseline): 55 MAU, 80 sessions, 14s avg engagement, 6 organic social sessions. Track progress weekly.
