"""FINDING A: Linear unreachable => every finding silently dropped, no Slack, exit 0.

The PR's whole thesis (CrontabUnavailable, run_detectors "error", should_notify)
is: a run that COULD NOT LOOK must never read as clean. That rule is applied to
the DETECT half and not to the FILE half.

`file_findings` catches every exception from `fetch_remote_state`, sets
`skipped_no_key = len(findings)`, and returns. `should_notify` only consults
created / updated / reopened / blind_detectors -- `skipped_no_key` is not in the
expression. So a Linear outage at 08:15 produces: one stderr line nobody reads,
exit 0, a state file that looks healthy, and NO Slack ping, while a brand-new
`cron-shells-claude` finding is thrown away.
"""
from repro_common import fh


class DeadLinear:
    """Linear is down / the API key is missing. The shape file_findings must survive."""

    def fetch_remote_state(self, _team_key, _repo):
        raise RuntimeError("network: [Errno 8] nodename nor servname provided")


FINDING = {
    "key": "fleet-health/cron-shells-claude/cron-shells-claude",
    "detector": "cron-shells-claude",
    "subject": "cron-shells-claude",
    "title": "1 crontab line(s) shell `claude` - cron has no keychain access",
    "body": "- `0 3 * * * claude -p 'sweep'`",
}

outcome = fh.file_findings([FINDING], apply=True, linear=DeadLinear())
per_detector = {"cron-shells-claude": 1, "schedule-duplicate": 0}

print("outcome        :", outcome)
print("per_detector   :", per_detector)
print("should_notify  :", fh.should_notify(outcome, per_detector, apply=True))
print("notify_text    :", fh.notify_text(outcome, per_detector))
print()
print("A REAL finding was produced (per_detector says 1), NOTHING was filed")
print("(skipped_no_key=%d), and the operator is told:" % outcome["skipped_no_key"])
print("   Slack ping sent? ", fh.should_notify(outcome, per_detector, apply=True))
print()
assert outcome["skipped_no_key"] == 1, "expected the finding to be dropped"
assert fh.should_notify(outcome, per_detector, apply=True) is False, \
    "expected NO ping -- if this asserts, the bug is fixed"
print("REPRODUCED: 1 finding dropped on the floor, zero operator signal, exit 0.")
