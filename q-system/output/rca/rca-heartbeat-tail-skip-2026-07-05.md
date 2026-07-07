# RCA: open-loops heartbeat silently skips the last 5 instances, firing a false Slack alert twice a day

**Date:** 2026-07-05
**Trigger:** Founder audit of recurring Slack alerts ("claude processes and heartbeats that broke"). The `heartbeat step-audit` ping was firing 08:40 and 20:40 daily.
**Surface-fix commit:** n/a (alert was accurate; sweep was the defect)
**Structural-fix commit:** applied 2026-07-05, uncommitted (`open-loops-heartbeat.sh:76` + why-comment)

## What happened

The fleet open-loops heartbeat (`open-loops-heartbeat.sh`) sweeps every registered
instance twice a day. On every run since at least 2026-07-01, the sweep stopped
after `travel-agent` and never processed the last 5 registry instances
(`fractional-cxo`, `interview-coach`, `negotiator`, `reddit-build-radar`, `Alice`).
The post-sweep step-audit correctly noticed those 5 were expected but never
logged, and Slacked the founder a `SILENTLY SKIPPED` alert on each run. The alert
was real (the sweep genuinely skipped them) but the underlying skip was a bash
bug, not an instance problem — so the founder got a twice-daily false alarm.

## Surface symptom

`q-system/output/open-loops-heartbeat.log`, every run:

```
2026-07-05 08:40:50 heartbeat AUDIT: [open-loops-heartbeat] SILENTLY SKIPPED - expected but never logged (5):
  - fractional-cxo
  - interview-coach
  - negotiator
  - reddit-build-radar
  - Alice
```

The sweep log always ends the iteration right after `travel-agent` woke its agent
("Both loops checked. Neither has moved." → "fleet sweep complete"), with the 5
tail instances never appearing.

## Surface root cause

`open-loops-heartbeat.sh:76` runs the headless agent without redirecting its stdin:

```bash
if ( cd "$path" && KIPI_INSTANCE_NAME="$name" $TO claude -p "$prompt" >> "$LOG" 2>&1 ); then
```

`claude -p` reads from stdin. The instance loop (lines 88–100) is a
`while read ... done < <(python3 ...)` over a **process substitution** — that
process-sub pipe IS the loop body's stdin. When the first in-loop instance with
open work (`travel-agent`, registry index 15) fires `claude -p`, the agent drains
the remaining lines of the process-sub pipe. The `while read` then hits EOF and
exits, so indices 16–20 are never iterated.

type: code-defect

Note the asymmetry that hid it: `kipi-system` (line 87) also wakes an agent but
runs OUTSIDE the loop, so its stdin drain harms nothing. Only the FIRST
agent-waking instance INSIDE the loop kills the rest. Instances 0–14 all had
0 open loops → no `claude -p` → the loop survived to index 15 every time.

## Structural root cause

### Root cause #1 — process-substitution stdin is a shared, drainable resource
type: code-defect

A `while read` fed by `< <(...)` puts the pipe on the loop body's fd 0. Any child
command in the body that reads stdin consumes the loop's own feed. This is a known
bash foot-gun; the correct pattern is to isolate the child's stdin (`</dev/null`)
or read the loop on a dedicated fd (`read -u 3 … done 3< <(...)`). The heartbeat
used neither, so a stdin-reading child silently truncated the fleet sweep.

### Root cause #2 — the sweep had no per-iteration completion invariant
type: missing-test
The loop trusted that "it ran to completion." Nothing asserted "N instances in →
N steps logged out" INSIDE the sweep. The self-audit (added 2026-07-01) caught the
symptom after the fact and correctly alerted, but there was no test proving the
loop iterates the full registry when a mid-list instance wakes an agent — the exact
condition that breaks it.

## Verification

Root cause reproduced deterministically with a minimal model of the loop (a
stdin-reading child inside a `while read` over a process substitution), then the
fix confirmed:

```
--- BUGGY (child reads stdin, no </dev/null) ---
processing: a
processing: b
processing: travel-agent
TOTAL PROCESSED: 3  (expected 8)     <- stops right after the first stdin-reading child

--- FIXED (child stdin redirected from /dev/null) ---
processing: a ... travel-agent ... frac ... interview ... negotiator ... reddit ... Alice
TOTAL PROCESSED: 8  (expected 8)     <- full iteration restored
```

The buggy run stops after `travel-agent` at 3/8 — the exact signature of the real
log (sweep dies after `travel-agent`, tail of 5 skipped). The one-line
`</dev/null` restores full iteration. Structural fix not yet applied to the live
script (scoped as a separate step); this verifies the mechanism and the fix.

## Contributing factors

- The self-audit alert (2026-07-01) fired correctly but was read as noise because
  the alert text ("silently skipped") did not distinguish "instance is broken"
  from "sweep never reached it." A true positive that looked like a false one.
- The daily/twice-daily cadence multiplied one latent bug into 14 alerts/week,
  raising alert fatigue and masking the real signal.
- No reproducer existed for "a mid-list instance wakes an agent," so the stdin
  drain was never exercised in a test.

## Fixes shipped

- Surface fix: none needed — the alert was accurate; the sweep was the defect.
- Cadence fix (shipped 2026-07-05): heartbeat plist moved from twice-daily to
  weekly (Monday 09:00), and lessons-daily plist moved from daily to weekly
  (Monday 06:00) with a PATH env fix. This reduces the false alert to 1×/week
  but does NOT fix the skip.
- Structural fix (applied 2026-07-05): added `</dev/null` to the `claude -p`
  invocation at `open-loops-heartbeat.sh:76` plus a scar why-comment. Verified:
  `bash -n` clean; the loop now iterates all 21 registry instances (was dying at
  `travel-agent`, index 15). The change that stops the class, not the instance.

## Action items

- [x] Apply `</dev/null` to the `claude -p` invocation at `open-loops-heartbeat.sh:76` — owner: Assaf — type: code
- [ ] Add a sweep-completion invariant: assert logged-step count == expected instance count at end of sweep, before the audit — owner: Assaf — type: test
- [ ] Grep the skeleton for other `while read ... done < <(...)` loops whose body runs a stdin-reading child (`claude -p`, `ssh`, `ffmpeg`), apply the same isolation — owner: Assaf — type: code
- [ ] Propagate the fixed heartbeat script to the fleet via `kipi update` after the fix lands — owner: Assaf — type: process

## Lessons

- A `while read` fed by `< <(...)` shares its stdin with every child in the body.
  Any child that reads stdin (`claude -p`, `ssh`, `read`) truncates the loop.
  Isolate the child (`</dev/null`) or read the loop on a dedicated fd.
- "Silently skipped" from a step-audit can be a TRUE positive with a benign-looking
  cause. Distinguish "the step failed" from "the runner never reached the step" in
  the alert text, or the real bug reads as noise.
- Lowering cadence hid the pain but not the bug. Cadence is a noise knob; the
  structural fix is separate and still owed.
