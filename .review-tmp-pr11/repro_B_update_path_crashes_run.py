"""FINDING B: a Linear error on the UPDATE/REOPEN path escapes main().

`file_findings` guards exactly ONE network call (`fetch_remote_state`). The three
calls the PR adds or keeps inside the loop are unguarded:

    ls.reopen_state_id(team_id)                      # new in this PR
    ls.graphql(ls.ISSUE_UPDATE, ...)                 # new in this PR
    ls.graphql(ls.ISSUE_CREATE, ...)                 # pre-existing

linear-sync.graphql raises LinearAPIError on HTTP 4xx/5xx, on a network blip, and
on any GraphQL `errors` payload -- e.g. Linear rate limiting the 08:15 run, or the
never-exercised TEAM_STATES_QUERY / stateId input being rejected.

Consequences at 3am:
  1. the module docstring's "Exit 0 always (a health check that fails its own
     launchd job is noise)" is false -- the job exits non-zero with a traceback,
  2. STATE (~/.config/kipi/fleet-health-state.json) is NEVER written, so the state
     file still holds YESTERDAY's ran_at and reads as a healthy run,
  3. should_notify / notify_text are never reached -> no Slack ping at all,
  4. findings ordered after the failing one are never filed.

Part 1 proves the real file_findings propagates. Part 2 proves main() has no guard.
"""
import io
import sys
from contextlib import redirect_stdout

from repro_common import fh


class LinearAPIError(RuntimeError):
    pass


FINDING = {
    "key": "fleet-health/cron-shells-claude/cron-shells-claude",
    "detector": "cron-shells-claude",
    "subject": "cron-shells-claude",
    "title": "1 crontab line(s) shell `claude`",
    "body": "- `0 3 * * * claude -p 'sweep'`",
}
SECOND = dict(FINDING, key="fleet-health/launchd-dark/com.kipi.other",
              subject="com.kipi.other", title="launchd job is dark", body="x")


class RateLimitedLinear:
    """fetch_remote_state succeeds; the ISSUE_UPDATE mutation is rate limited."""

    ISSUE_CREATE = "ISSUE_CREATE"
    ISSUE_UPDATE = "ISSUE_UPDATE"

    def fetch_remote_state(self, _t, _r):
        return "team-1", {"id": "proj-1"}, {
            FINDING["key"]: {"linear_id": "id-1", "identifier": "ASK-150",
                             "description": "<!-- kipi-key: %s -->\nstale" % FINDING["key"],
                             "state_type": "unstarted", "state_name": "Todo"},
        }

    def read_ledger(self):
        return {}

    def append_ledger(self, records):
        return len(records)

    def reopen_state_id(self, _team_id):
        return "state-todo"

    def graphql(self, query, variables):
        raise LinearAPIError('HTTP 429: {"errors":[{"message":"rate limited"}]}')


print("--- part 1: the real file_findings does not contain the error ---")
try:
    fh.file_findings([FINDING, SECOND], apply=True, linear=RateLimitedLinear())
    print("NOT REPRODUCED: file_findings swallowed it")
    sys.exit(1)
except LinearAPIError as exc:
    print("propagated out of file_findings:", exc)
    print("=> the second finding (%s) was never even attempted" % SECOND["key"])

print()
print("--- part 2: main() has no guard around file_findings ---")
fh.DETECTORS = [{"id": "cron-shells-claude", "description": "d",
                 "detect": lambda _c: [dict(FINDING)],
                 "action": "file_issue", "lesson": "l"}]
fh.file_findings = lambda *a, **k: (_ for _ in ()).throw(
    LinearAPIError('HTTP 429: rate limited'))

state_before = fh.STATE
notified = []
fh.subprocess = type("S", (), {"run": staticmethod(lambda *a, **k: notified.append(a))})()

try:
    with redirect_stdout(io.StringIO()):
        rc = fh.main()
    print("NOT REPRODUCED: main() returned", rc)
    sys.exit(1)
except LinearAPIError as exc:
    print("main() raised:", exc)
    print("  -> launchd job exits non-zero, docstring claims 'Exit 0 always'")
    print("  -> STATE never written this run:", state_before)
    print("  -> Slack calls made:", len(notified))
print()
print("REPRODUCED: an update-path Linear error kills the run with no ping and no state write.")
