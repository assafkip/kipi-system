#!/usr/bin/env python3
"""The worker's ready() predicate, in ONE place both the worker and its tests read.

WHY THIS FILE EXISTS (ASK-284, 2026-08-02). This predicate used to live only
inside a quoted heredoc in linear-worker.sh. That made it untestable: any test
asking "is ASK-140 pickable?" had to hand-copy the conditions, and a hand-copy of
a checker is a second checker that drifts from the first. A reproducer that
proves an issue is pickable against a COPY of the rule proves nothing about the
loop -- it proves the copy agrees with itself.

It also made the rule fragile in a way that already bit twice: inside a $( )
command substitution bash tracks quote state through the heredoc, so a single
apostrophe in a Python COMMENT swallowed the rest of the substitution and the
whole script died at "unexpected EOF" (ASK-275). A backtick opens a nested
command substitution the same way. Logic that lives in a real .py file has
neither hazard.

The worker imports this; so does capability_block_expiry.py; so do the tests.
Changing a pick rule means changing it here, once.
"""

# The states a pickable issue may be in. `started` is deliberately excluded: an
# issue someone (or some runner) is already on must not be handed out a second
# time. This is the condition that makes label-removal ALONE insufficient to
# un-stick a parked issue -- ASK-140/134/133/132 all sit at `started`, so an
# expiry that drops the label and stops there clears one test and silently fails
# the other, while reporting success.
PICKABLE_STATE_TYPES = ("backlog", "unstarted")

# Labels that take an issue out of the pool, and the reason each one is terminal.
#   owner:assaf        -- a founder decision; hands off.
#   needs-scope        -- Sana refused: the SPEC is wrong. Routes to the drafter.
#   blocked:capability -- Sana refused: the spec is fine, the RUNNER is not
#                         equipped. Routes to whoever owns the config.
# blocked:capability is the one that never expired on its own, which is the whole
# of ASK-284: it records a point-in-time verdict about the ENVIRONMENT and the
# environment changes underneath it. See capability_block_expiry.py.
HOLD_LABELS = ("needs-scope", "blocked:capability")


def labels_of(issue):
    return {n["name"] for n in (issue.get("labels") or {}).get("nodes", [])}


def project_of(issue):
    return (issue.get("project") or {}).get("name")


def in_repo(issue, repo_project):
    # Unset project is NOT this repo. "Target unknown" and "target is here" are
    # different claims, and treating the first as the second is how 18 foreign
    # issues got into this queue in the first place.
    return project_of(issue) == repo_project


def has_dor(issue):
    return "Definition of Ready" in (issue.get("description") or "")


def ready(issue, repo_project):
    """True when the picker may hand this issue to a runner."""
    labels = labels_of(issue)
    if "owner:assaf" in labels:
        return False
    if "owner:sana" not in labels:
        return False
    if any(hold in labels for hold in HOLD_LABELS):
        return False
    if (issue.get("state") or {}).get("type") not in PICKABLE_STATE_TYPES:
        return False
    if not in_repo(issue, repo_project):
        return False
    return has_dor(issue)


def ready_ignoring_project(issue):
    """Everything the project filter is ABOUT to drop, counted before it drops it.

    A queue that silently falls from 29 to 11 is indistinguishable from a broken
    query, and "it got quiet" is the failure mode that filter could most easily
    cause.
    """
    labels = labels_of(issue)
    return (
        "owner:assaf" not in labels
        and "owner:sana" in labels
        and not any(hold in labels for hold in HOLD_LABELS)
        and (issue.get("state") or {}).get("type") in PICKABLE_STATE_TYPES
        and has_dor(issue)
    )
