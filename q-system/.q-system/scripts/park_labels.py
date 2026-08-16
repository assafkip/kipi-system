#!/usr/bin/env python3
"""The labels that PARK an issue, in one place, for every consumer (ASK-872).

WHY THIS FILE EXISTS
--------------------
Three labels mean "a human or a gate decided this must not be worked right now",
and each routes somewhere different. `linear-worker.sh` applied all three in both
of its selectors, with a comment saying exactly why:

    564: # BOTH SELECTORS, OR THE FIX IS HALF DONE.

`review-redrive.py` is a THIRD consumer that dispatches the same agents at the
same issues, and on 2026-08-16 it applied none of them:

    $ grep -n "owner:assaf\\|needs-scope\\|blocked:capability" review-redrive.py
    (no output)

So a park stopped the fresh-pick path and not the redrive. Parking ASK-830 that
day was not enough on its own -- the PR had to be converted to draft as well,
because draft is the only thing the redrive actually honoured.

A FOURTH CONSUMER WITH ITS OWN COPY IS THIS SAME DEFECT AGAIN, which is why the
list is a module and not three more string literals. The two things a consumer
needs -- the set, and the human reason each one routes differently -- are the
same two things, so they live in one table rather than a set here and an
explanation in whichever docstring happened to get written.

WHAT THIS MODULE IS NOT
-----------------------
It answers "is this issue parked, and by what". It does NOT fetch labels: where
labels come from is the caller's problem (the worker already has them in the
board query it runs anyway; the redrive reads them itself). Folding a fetch in
here would make one of the two callers pay for a round trip it does not need.
"""

# Ordered, and the order is the reporting order when an issue carries more than
# one: the founder's hold outranks a machine refusal, because "hands off" is the
# answer a human gave and the other two are answers a runner gave.
PARK_LABELS = (
    ("owner:assaf", "founder decision, hands off"),
    ("needs-scope", "refused as unexecutable; the DoR drafter owns it"),
    ("blocked:capability", "the runner is missing a credential or a binary"),
)

PARK_LABEL_NAMES = tuple(name for name, _why in PARK_LABELS)


def parked_reason(labels):
    """(label, why) if any park label is present, else None.

    `labels` is any iterable of label-name strings. Returns the FIRST match in
    PARK_LABELS order, never a set: a caller that has to report which label
    stopped it cannot use a boolean, and a caller that only needs the boolean
    can read this as truthy.
    """
    have = set(labels or ())
    for name, why in PARK_LABELS:
        if name in have:
            return (name, why)
    return None


if __name__ == "__main__":
    # A shell consumer that needs the raw list (none today; the worker imports
    # this module directly). Kept one line long on purpose -- the moment it grows
    # a format flag, two consumers are parsing text where one could import.
    for _name, _why in PARK_LABELS:
        print("%s\t%s" % (_name, _why))
