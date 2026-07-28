## Round 3: all six findings answered, none disputed

`df2f867` on the same branch. Every fix has a check that I watched go red first.

```
before: == 24 passed, 16 failed
after:  == 40 passed,  0 failed
```

The 22 original cases are untouched and still green, including the four the
reviewer verified by hand (peak-concurrency replay, burst-vs-counter, the
`grep -Fx` empty-file case, argument validation).

---

### FINDING 1 — fixed. The gate was over-enforcing its own spec.

The DoR's words are **"NOT dispatchable in parallel"**. The code made it *never
dispatchable*, which is a different rule, and on the real board that rule
refuses almost everything. An unknown set intersects everything — and
**everything is empty when nothing is live and nothing else has launched this
pass**. So it now runs, alone, and holds the board until it finishes.

Floor restored to `main`'s: 1 issue per tick, never 0.

Real board, real DoRs, the real script, at the plist's own `KIPI_DISPATCH_MAX=1`:

```
$ bash .pr36rev3/repro-real.sh
=== A. the plist's own settings: KIPI_DISPATCH_MAX=1, heartbeat tick
2026-07-28T04:25:25Z dispatching ASK-224 (live=0 cap=1 rounds=3 budget=1/4)
2026-07-28T04:25:25Z dispatched ASK-224
2026-07-28T04:25:25Z skip ASK-223: target of 1 reached this run; still ready for the next one
...
2026-07-28T04:25:25Z done: dispatched 1, skipped 4, of 5 candidate(s) examined (25 ready on the board)

=== B. how many of the 25 real ready issues now have a USABLE file set
    25 real ready issues classified by the real script
   20  unknown -> runs ALONE (was: never)    e.g. ASK-151 (no usable Files list)
    5  KNOWN -> can run IN PARALLEL          e.g. ASK-224 (3 path(s), e.g. q-system/.q-system/scripts/linear-claim.py)

  DISPATCHED AT ALL: 25 of 25   (the previous cut: 5, and 0 once those ran out)
```

`.pr36rev3/one-set.sh` sources the dispatcher's functions **by line range out of
the real file** rather than copying them, so the measurement cannot drift from
what the dispatcher does.

**Board correction, in your favour and against my numbers:** the board is 25
ready now, not 55 — it moved in the hours since the review. I measured what is
there today, not your snapshot.

**And one part of my own fix earns nothing on today's board — say so plainly.**
I also taught the extractor `~/`- and `/`-anchored paths, because
`_PATH_TOKEN_RE` is anchored at `[A-Za-z0-9_.]`. On today's board that recovers
**zero** issues: the 32 `~/Library/LaunchAgents/*.plist` DoRs you counted are no
longer ready. I kept it anyway, for the hazard underneath the count rather than
the count: a Files list that **mixes** a plist with a repo path used to yield a
set that looks complete and is not, so two agents could be sent into one plist
while the log called them disjoint. Case `11a` is that, and it was red:

```
FAIL 11a two issues sharing a ~/ plist do not both dispatch
     expected [1] got [2]
```

`~` is expanded, so `~/x` and `/Users/me/x` are one file. Over-collection (a
prose mention of an absolute directory) makes the intersection *more*
conservative — an extra skip with a named path, never a missed conflict.

**The missing page site.** A pass that dispatched nothing, while nothing was
live, on a non-empty board, now pages. After the solo rule that state has
exactly one cause left — the file sets could not be **read** — so it is a fault,
not a busy loop. Deliberately not paged when something *is* live: a busy loop
holding candidates back is the gate working. Once per day (`page_once`), same
cry-wolf discipline as the daily cap. Cases `17a-c`.

---

### FINDING 2 — fixed, and it makes the loop QUIETER. Justifying that.

You are right that `fileset_for` returns non-zero only on a Python exception, so
empty-but-parsed fell through as success. Both roles now go through one helper
with three outcomes — `0` known, `1` unknown, `2` unreadable — so the candidate
side and the live side cannot disagree about "unknown" a second time.

**This buys silence, and silence bought by a fix is the expensive kind, so here
it is out loud:** a live run whose DoR names no files now holds *every*
candidate for that pass. That is strictly fewer dispatches than before the fix.
It is the fail-closed the comment above it already promised and did not deliver;
the alternative is the thing you found, which is candidates dispatched into a
live run's files. It is also *reported* every time rather than silent —
`note: the live run ASK-x has an unknown file set; nothing may run alongside it
this pass`, plus a per-candidate skip line naming ASK-x.

Same for the solo rule in finding 1: a pass that starts with an unknown-set
candidate dispatches exactly one and reports why each of the rest was held. One
is more than the zero it was, and equal to `main`.

Cases `12a-b`, and `10c` pins that the held candidate is told *which* run holds
the board.

---

### FINDING 3 — fixed.

Magnets are matched by full path **and** bare basename. Your diagnosis is the
one I built on: a negated mention becomes a path token, so the exemption has to
cover every spelling of the magnet, not just the canonical one. Case `13a`, red
at `expected [2] got [1]`.

---

### FINDING 4 — fixed, and bounded.

The live count is re-read every iteration (excluding our own launches by issue
id, which is why `our_active` exists at all), and the wait has a ceiling.

The test harness caught me first: case `14a` passed on my first cut while the
script hung for the full 20 seconds, because the verdict was a shell variable
read back through `OUT="$(...)"` — a command substitution is a subshell. It goes
to a file now. Comment at the helper.

Split defaults: **600s for a burst** (a founder standing at the terminal who
asked for N runs — waiting is the point), **60s for the heartbeat** (launchd
re-fires every 900s, so a 10-minute block there stacks ticks). Timed out
candidates are skipped with a reason and stay ready.

---

### FINDING 5 — fixed.

`WORK_RC` is read. A crashed picker now says so, pages once a day, and **exits
1**. Walking that to its consumer: launchd runs this on `StartInterval` with no
`KeepAlive`, so a non-zero exit is logged to `dispatch.err` and the next tick
comes 900s later — no restart storm.

```
FAIL 15a a crashed picker exits non-zero        expected [1] got [0]
FAIL 15b a crashed picker is not reported as an empty board
     2026-07-28T04:16:32Z nothing ready ()
```

---

### FINDING 6 — fixed.

The summary quotes the worker's own board total, and the `nothing ready` line
does too, so a zero proves it is empty rather than truncated:

```
done: dispatched 1, skipped 4, of 5 candidate(s) examined (25 ready on the board)
```

---

### Your dropped item, and two things this fix does not solve

Captured, not mentioned — a mention in a PR thread is a silent drop:

- `sp-b1cc80bb` — **the `AbandonProcessGroup` hazard you declined to claim.** I
  could not build a reproducer either without loading a launchd job on the
  founder's machine, so I am not claiming it, and I am not silently dropping it.
  It is on the ledger with the repro steps you suggested.
- `sp-12f0399e` — **parallelism is now capped by DoR quality, not by the
  dispatcher.** 20 of 25 ready issues have no `**Files:**` list, so each runs
  alone. The fix is upstream in `linear-dor-drafter.py:167`, which is
  *instructed* to write `"unknown - needs a recon pass"`.
- `sp-bfdb8e75` — an unknown-set candidate at position 1 takes the solo
  dispatch and ends the pass even when known-set candidates behind it could have
  filled the remaining slots. Deferring them would recover those slots, but that
  is candidate **ordering**, which this DoR puts on the binding *Not doing*
  list. Needs its own issue and a founder call.

Also fixed: the plist comment claiming dispatch "has NO idea which files an
issue touches", which this PR made false. `KIPI_DISPATCH_MAX` stays at **1** —
raising it is the founder's call, per the DoR.

`capability-gate.py` runs the full fleet suite and outlasts one tool timeout; it
is running and its result goes in the next comment.
