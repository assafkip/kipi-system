# Founder Notifications (ENFORCED)

## The one truth about slack-notify.sh (founder-directed 2026-08-10)

`q-system/.q-system/scripts/slack-notify.sh` is **THE FLEET ALERT PATH. It files
a Linear ticket for Sana. It pages nobody.** Verbatim founder directive, in the
script's own header: "I dont want to see any of these. Any of the ones that
need attention should go to Sana - not me."

This file previously described slack-notify.sh as the founder-ping channel.
That was true before 2026-08-10 and STALE afterward; on 2026-08-18 a feature
shipped against the stale description and its "founder page" landed in Sana's
queue. The rule doc now matches the script.

## Routing

- **Engineering signals** (a job failed, a counter drifted, a loop closed, a
  gate went red): `bash q-system/.q-system/scripts/slack-notify.sh "one line"`.
  It becomes a Linear ticket in Sana's triage. Silent no-op if unconfigured.
- **Founder-facing pings** are the EXCEPTION, not the default. They exist only
  for things the founder explicitly asked to be told about, and they go
  through his webhook directly -- wiring one is his call per instance, never a
  default a feature ships with.
- osascript / desktop notifications remain BANNED for any alert: silently
  dropped from sandboxed processes.

## When to alert (and when not to)

Alert Sana's queue for: autonomous-run failures, BLOCKED runs, drift
detections, dead loops. Do NOT alert for routine progress or per-event noise;
alert on state change, once.

## Wiring

- The single sink stays `slack-notify.sh`; its destination is Sana's Linear
  triage via `alert-to-linear.py`.
- Emitters: open-loops heartbeat, the corpus-similarity drift counter
  (voice-stop-gate.py `authorship_page`), and any new always-on job.
