#!/usr/bin/env python3
"""The one definition of "a state the picker will offer", shared by its writers.

WHY THIS IS CONSTANTS AND NOT THE PREDICATE (ASK-288, 2026-08-02). An earlier
version of this file held `ready()` itself, and linear-worker.sh delegated to it.
That broke a gate, and the gate was right: test-terminal-states.sh enumerates the
loop's abnormal exits FROM SOURCE, out of linear-worker.sh, and refuses to
certify one that has no declared machine consumer. Moving the predicate here
moved six exits out of the file the validator reads -- so the registry rows for
owner-assaf, not-owner-sana, state-not-open, out-of-repo and no-dor matched
nothing, and the exits themselves became invisible to the gate. That is not a
stale registry, it is coverage loss: the gate could no longer see the exits at
all. Reverting the predicate was cheaper and safer than reshaping a fleet-shared
gate to chase an optional refactor.

WHAT REMAINS HERE, AND WHY IT HAS TO. linear-sync.py's un-block needs to know
which states the picker will offer, and it had grown its OWN tuple with `triage`
added -- two copies of one truth, which is how an un-block reports success while
landing the issue somewhere the picker still refuses (codex review of PR #69).
The constant lives here, linear-sync.py imports it, and
test-capability-block-expiry.sh asserts the worker's inline literal still agrees
with it. A constant plus a drift test costs one file; a second copy of the
PREDICATE costs a gate.
"""

# Must stay equal to the tuple written inline in linear-worker.sh's ready().
# The drift guard in test-capability-block-expiry.sh reads that literal out of
# the worker and compares; it fails if either side moves alone.
PICKABLE_STATE_TYPES = ("backlog", "unstarted")

# The labels that hold an issue out of the pool. `blocked:capability` is the one
# that never expired on its own, which is the whole of ASK-288 -- it records a
# point-in-time verdict about the ENVIRONMENT and the environment moves under it.
# See capability_block_expiry.py.
HOLD_LABELS = ("needs-scope", "blocked:capability")
