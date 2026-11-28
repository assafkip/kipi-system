#!/usr/bin/env python3
"""cap-ladder.py and the review cap: which PRs it sees, and the delta rung (ASK-5788).

Three gaps, each pinned here against the fixture world in test_cap_ladder.py:

1. A PR maps to its ticket from the ASK id in its title when its branch has none.
   PR #885 (sana/fleet-plan-weekly-45, ASK-5782 in the title) was capped and had
   no consumer.
2. A last review round that ends without an approval is a cap. The marker is
   written only when a 4th review is refused, so #909 waited until the
   orchestrator triggered that refusal by hand.
3. A PR approved at the cap whose head then moved (CI went red, PR #892) gets ONE
   delta review with the cap raised by one, never rung 1 and never a hand
   override of KIPI_REVIEW_MAX_ROUNDS. An approval of the current head is no cap.

RED ON MAIN: CAP_LADDER_TEST_ROOT=<main scripts dir> fails every case below.
Run: python3 q-system/.q-system/scripts/test/test_cap_ladder_review_caps.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("test_cap_ladder_cases_rc", str(HERE / "test_cap_ladder.py"))
T = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(T)

FAKE_REVIEWER = r'''#!/usr/bin/env python3
import json, os, sys
open(os.environ["W"] + "/reviewer.log", "a").write(json.dumps(
    {"argv": sys.argv[1:], "max_rounds": os.environ.get("KIPI_REVIEW_MAX_ROUNDS"),
     "api_keys": os.environ.get("KIPI_FLEET_API_KEYS")}) + "\n")
'''


def world(td: str) -> dict:
    env = T.make_world(Path(td))
    rv = Path(td) / "bin/reviewer"
    rv.write_text(FAKE_REVIEWER)
    rv.chmod(0o755)
    env["CAP_LADDER_REVIEWER"] = f"{sys.executable} {rv}"
    env["CAP_LADDER_TARGETS"] = json.dumps([{"slug": "o/r", "project": "kipi-system", "path": td}])
    (Path(td) / "reviews").mkdir(exist_ok=True)
    return env


def record(env: dict, pr: int, round_: int, verdict: str, head: str, blips: int = 0) -> None:
    """The record pr-review-agent.sh writes: `round` counts blips, `usable_round` does not."""
    (Path(env["CAP_LADDER_REVIEWS"]) / f"o_r__pr-{pr}.verdict.json").write_text(json.dumps(
        {"pr": pr, "verdict": verdict, "usable": True, "round": round_ + blips, "usable_round": round_,
         "head_sha": head}))


def closed(env: dict, pr: int) -> bool:
    return any(c[:3] == ["pr", "close", str(pr)] for c in T.log(env, "gh"))


def case_title_mapping() -> None:
    with tempfile.TemporaryDirectory() as td:
        env = world(td)
        T.world(env, **{"o/r": [{"number": 20, "headRefName": "fix/weekly-45", "headRefOid": "a" * 40,
                                 "title": "Weekly cap (ASK-2)", "baseRefName": "main", "url": "u/20",
                                 "state": "OPEN"}], "branches": {"fix/weekly-45": 2}})
        (Path(env["CAP_LADDER_REVIEWS"]) / ".round-cap-o_r-pr-20").write_text("")
        out = T.ladder(env, "--apply")
        gh = T.log(env, "gh")
        T.check("title: a capped PR with no ASK id in its branch climbs by the ASK id in its title",
                "ASK-2: rung 1" in out and closed(env, 20), out)
        T.check("title: it continues on its own branch, not a sana/ask-2 that does not exist",
                any(c[:2] == ["pr", "create"] and "fix/weekly-45" in c for c in gh), gh)


def case_last_round() -> None:
    with tempfile.TemporaryDirectory() as td:
        env = world(td)
        record(env, 10, 2, "REQUEST CHANGES", "a" * 40)
        T.ladder(env, "--apply")
        T.check("last round: a round-2 REQUEST CHANGES is not a cap", not closed(env, 10), T.log(env, "gh"))
        record(env, 10, 3, "REQUEST CHANGES", "a" * 40)
        out = T.ladder(env, "--apply")
        T.check("last round: round 3 ended REQUEST CHANGES with no marker is a cap (rung 1)",
                "ASK-1: rung 1" in out and closed(env, 10), out)
    with tempfile.TemporaryDirectory() as td:
        env = world(td)
        record(env, 10, 1, "REQUEST CHANGES", "a" * 40, blips=2)   # PR #913 round 1, finding 1
        T.ladder(env, "--apply")
        T.check("last round: two blips and one real review is not round 3", not closed(env, 10), T.log(env, "gh"))


def pr_row(n, branch, title, head="a" * 40):
    return {"number": n, "headRefName": branch, "headRefOid": head, "title": title,
            "baseRefName": "main", "url": f"u/{n}", "state": "OPEN"}


def case_title_precedence() -> None:
    """PR #913 round 1, finding 3: a PR that mentions a capped id never shadows its own PR."""
    with tempfile.TemporaryDirectory() as td:
        env = world(td)
        T.world(env, **{"o/r": [pr_row(20, "docs/notes", "docs: note the ASK-1 cap"),
                                pr_row(10, "sana/ask-1", "fix (ASK-1)")]})
        T.led(env, "record-capout", "ASK-1", "capped")
        T.ladder(env, "--apply")
        T.check("title: the ticket's own sana/ask-1 PR is closed, never the PR that mentions it",
                closed(env, 10) and not closed(env, 20), T.log(env, "gh"))
    with tempfile.TemporaryDirectory() as td:
        env = world(td)
        T.world(env, **{"o/r": [pr_row(20, "docs/notes", "docs: note the ASK-2 cap")]})
        T.led(env, "record-capout", "ASK-2", "capped")
        T.ladder(env, "--apply")
        T.check("title: a ticket-only cap never closes a title-mapped PR", not closed(env, 20), T.log(env, "gh"))
    with tempfile.TemporaryDirectory() as td:
        env = world(td)
        T.world(env, **{"o/r": [pr_row(20, "fix/x", "revert the ASK-456 fix for ASK-2")]})
        (Path(env["CAP_LADDER_REVIEWS"]) / ".round-cap-o_r-pr-20").write_text("")
        T.ladder(env, "--apply")
        T.check("title: two ASK ids map to no ticket", not closed(env, 20), T.log(env, "gh"))


def case_upper_case_lane() -> None:
    """PR #913 round 2, finding 1: sana/ASK-1 continues on sana/ASK-1, never sana/ask-1."""
    with tempfile.TemporaryDirectory() as td:
        env = world(td)
        T.world(env, **{"o/r": [pr_row(10, "sana/ASK-1", "fix (ASK-1)")], "branches": {"sana/ASK-1": 2}})
        T.led(env, "record-capout", "ASK-1", "capped")
        out = T.ladder(env, "--apply")
        gh = T.log(env, "gh")
        T.check("upper case: the successor opens from the PR's own branch spelling",
                closed(env, 10) and any(c[:2] == ["pr", "create"] and "sana/ASK-1" in c for c in gh), (out, gh))


def case_approved_head() -> None:
    with tempfile.TemporaryDirectory() as td:
        env = world(td)
        record(env, 10, 3, "APPROVE WITH NITS", "a" * 40)
        (Path(env["CAP_LADDER_REVIEWS"]) / ".round-cap-o_r-pr-10").write_text("")
        out = T.ladder(env, "--apply")
        T.check("approved: a marker over an approval of the current head climbs nothing",
                not closed(env, 10) and not T.log(env, "fable") and not T.log(env, "reviewer"), out)


def case_delta_rung() -> None:
    with tempfile.TemporaryDirectory() as td:
        env = world(td)
        record(env, 10, 3, "APPROVE", "c" * 40)          # approved, then a CI-fix commit moved the head
        out = T.ladder(env, "--apply")
        rv = T.log(env, "reviewer")
        T.check("delta: approved at the cap, then moved, runs ONE review with the cap raised by one",
                len(rv) == 1 and rv[0]["max_rounds"] == "4" and rv[0]["api_keys"] == "0"
                and rv[0]["argv"][:1] == ["10"] and "--post" in rv[0]["argv"]
                and rv[0]["argv"][rv[0]["argv"].index("--issue") + 1] == "ASK-1", (out, rv))
        T.check("delta: no RCA, no close, no rung spent",
                not closed(env, 10) and not T.log(env, "fable")
                and int((json.loads(Path(env["CAP_LADDER_STATE"]).read_text()).get("ASK-1") or {}).get("rung", 0)) == 0,
                out)
        T.at(env, 1)
        T.reset(env)
        (Path(td) / "reviewer.log").unlink()
        out = T.ladder(env, "--apply")
        T.check("delta: one per PR; a later moved head after it takes rung 1",
                not T.log(env, "reviewer") and "ASK-1: rung 1" in out and closed(env, 10), out)
    with tempfile.TemporaryDirectory() as td:
        env = world(td)
        rv = Path(td) / "bin/reviewer"
        rv.write_text(FAKE_REVIEWER + "sys.exit(1)\n")     # PR #913 round 1 finding 2, round 2 minor 2
        record(env, 10, 3, "APPROVE", "c" * 40)
        T.ladder(env, "--apply")
        T.at(env, 1)
        T.ladder(env, "--apply")
        T.check("delta: a review that never ran (rc 1) does not spend the one shot",
                len(T.log(env, "reviewer")) == 2 and not closed(env, 10), T.log(env, "gh"))


def case_owns_title() -> None:
    spec = importlib.util.spec_from_file_location("cl_rc", str(T.LADDER))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "pr-reviews").mkdir()
        (Path(td) / "linear-worker-attempts.json").write_text(json.dumps({"ASK-1": {"capout": True}}))
        got = {
            "title on a human branch": m.ladder_owns("o/r", 3, "fix/thing", td, title="x (ASK-1)"),
            "no id anywhere": m.ladder_owns("o/r", 3, "fix/thing", td, title="x"),
            "lane branch, title id": m.ladder_owns("o/r", 3, "sana/ask-1-slug", td, title="x (ASK-1)"),
            "upper-case lane branch": m.ladder_owns("o/r", 3, "sana/ASK-1-slug", td, title="x (ASK-1)"),
        }
    T.check("ladder_owns: a ticket capout never makes a title-mapped PR the ladder's; lanes stay pr-owner's",
            not any(got.values()), got)
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "pr-reviews").mkdir()
        (Path(td) / "linear-worker-attempts.json").write_text("{}")
        (Path(td) / "pr-reviews" / ".round-cap-o_r-pr-3").write_text("")
        own = m.ladder_owns("o/r", 3, "fix/thing", td, title="x (ASK-1)")
        lane = m.ladder_owns("o/r", 3, "sana/ASK-1-rows", td, title="x (ASK-1)")
    T.check("ladder_owns: a title-mapped PR with its own review cap is the ladder's", bool(own), own)
    T.check("ladder_owns: an upper-case lane branch is a lane, never title-mapped (round 1, finding 4)",
            lane == "", lane)


def main() -> int:
    print("test_cap_ladder_review_caps.py")
    for case in (case_title_mapping, case_last_round, case_title_precedence, case_upper_case_lane, case_approved_head,
                 case_delta_rung, case_owns_title):
        case()
    print(f"\n{'FAIL' if T.FAILS else 'PASS'}: {len(T.FAILS)} failed")
    return 1 if T.FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
