"""FINDING C: a rollup key that is in the local ledger but not in the health
project goes permanently silent AND reports an all-clear.

`known = set(ledger) | set(remote_keys)`. The ledger is a local append-only file;
`remote_keys` is only the issues inside project "kipi-system".

Move the rollup issue to another Linear project -- an ordinary triage action, and
the exact thing an operator does when they decide the cron cleanup belongs to a
different workstream -- and from then on:

  tracked = remote_keys.get(key)  -> None
  result["existing"] += 1 ; continue

Forever. The crontab can grow from 1 offending line to 5; the body is never
rewritten, the issue is never reopened, and the ONE Slack line the whole design
rests on says: "Board has them; nothing to do now."

That is the same silent-all-clear failure mode CrontabUnavailable and the "error"
state were built to eliminate, one layer over, and nothing counts it.
"""
from repro_common import fh

KEY = "fleet-health/cron-shells-claude/cron-shells-claude"


def rollup(n_lines):
    """What the detector emits for n offending crontab lines, keyed like main()."""
    cron = "".join(f"{i} 3 * * * claude -p 'job {i}'\n" for i in range(n_lines))
    out = fh.detect_cron_shells_claude(None, cron_text=cron)
    for f in out:
        f["key"] = fh.finding_key("cron-shells-claude", f["subject"])
        f["detector"] = "cron-shells-claude"
    return out


class MovedOutOfProject:
    """The issue exists in Linear and in the ledger, just not in HEALTH_PROJECT."""

    ISSUE_CREATE = "ISSUE_CREATE"
    ISSUE_UPDATE = "ISSUE_UPDATE"

    def __init__(self):
        self.mutations = []

    def fetch_remote_state(self, _t, _r):
        return "team-1", {"id": "proj-1"}, {}          # project query no longer sees it

    def read_ledger(self):
        return {KEY: {"linear_id": "id-1", "identifier": "ASK-150"}}

    def append_ledger(self, records):
        return len(records)

    def reopen_state_id(self, _t):
        return "state-todo"

    def graphql(self, query, variables):
        self.mutations.append(query)
        return {"issueUpdate": {"success": True, "issue": {"id": "id-1"}}}


fake = MovedOutOfProject()

day1 = fh.file_findings(rollup(1), apply=True, linear=fake)
print("day 1  (1 offending line) :", day1)

day60 = fh.file_findings(rollup(5), apply=True, linear=fake)
print("day 60 (5 offending lines):", day60)
print("linear mutations issued   :", fake.mutations)
print()
per_detector = {"cron-shells-claude": 1}
print("should_notify :", fh.should_notify(day60, per_detector, apply=True))
print("notify_text   :", fh.notify_text(day60, per_detector))
print()

assert day60["existing"] == 1 and day60["updated"] == 0 and day60["reopened"] == 0
assert fake.mutations == [], "expected zero writes"
assert fh.should_notify(day60, per_detector, apply=True) is False
print("REPRODUCED: the crontab grew 1 -> 5 offending claude lines. Zero Linear")
print("writes, zero Slack pings, and the only text the operator would ever see is")
print("'Board has them; nothing to do now.' The 4 new lines exist nowhere.")
