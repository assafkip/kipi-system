"""Pins dispatch-stall-check.py (ASK-3064): a dispatcher that is alive and
dispatching nothing is detected, repaired for the known class, restarted, and
escalated once if that does not work.

WHY THE FIXTURES ARE REAL: every .log fixture was cut with sed from the live
~/.config/kipi/dispatch.log (2026-10-24 stall, 2026-10-24 recovery, 2026-09-23
healthy). The two gh fixtures are the real `gh pr view` and `gh api .../git/ref`
output for PR #559 / sana/ask-2058. An invented line would test the author's idea
of the log; the producer's line is what the dispatcher actually wrote.

ISOLATION: every state file, out-log and effect is a tmp path or a fake. Nothing
here calls gh, launchctl or slack-notify.sh; the module's `run`, `kickstart`,
`notify` and `linear_comment` are replaced, and the dry-run test makes them raise.
"""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "dispatch-stall-check.py"
FIX = HERE / "fixtures" / "dispatch-stall"
REPO = HERE.parents[3]


def load():
    spec = importlib.util.spec_from_file_location("dsc_under_test", str(SCRIPT))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def m():
    return load()


def lines(name):
    return (FIX / name).read_text().splitlines()


def split_turns(raw):
    """Split a fixture into per-turn line lists at each 'preflight REFUSED' start."""
    out, cur = [], []
    for ln in raw:
        if "preflight REFUSED" in ln and cur:
            out.append(cur)
            cur = []
        cur.append(ln)
    out.append(cur)
    return out


STALL = split_turns(lines("stall-2026-10-24.log"))      # 14:22 14:37 14:53 15:08
REC = lines("recovery-2026-10-24.log")
BRAG_TURN = REC[0:4]       # dispatch: ... entering brag ... nothing ready (23:01:34)
RECOVERY_TURN = REC[4:]    # the turn that logged "dispatched ASK-2058" at 23:03:23


def flat(*groups):
    return [ln for g in groups for ln in g]


def ts(s):
    return load().parse_ts(s)


# ---- detection ----

def test_fixture_shapes():
    assert len(STALL) == 4
    assert any("dispatched ASK-2058 (confirmed running)" in ln for ln in RECOVERY_TURN)
    assert any("entering brag" in ln for ln in BRAG_TURN)


def test_real_stall_fires_on_turn_three_and_names_issue_and_class(m):
    turns = m.parse_turns(flat(*STALL))
    fires, counts = m.scan(turns)
    assert len(fires) == 1
    f = fires[0]
    assert f["issue"] == "ASK-2058" and f["repo"] == "home"
    assert f["ts"] == "2026-10-24T14:53:07Z"      # turn 3, the 14:53 one
    assert f["info"] == {"class": "branch-guard", "pr": 554,
                         "actual": "sana/ask-2058-guard", "expect": "sana/ask-2058"}


def test_two_stalled_turns_do_not_fire(m):
    fires, _ = m.scan(m.parse_turns(flat(*STALL[:2])))
    assert fires == []


def test_healthy_excerpt_triggers_nothing(m):
    turns = m.parse_turns(lines("healthy-2026-09-23.log"))
    assert turns, "fixture must parse into at least one turn"
    fires, counts = m.scan(turns)
    assert fires == [] and counts == {}


def test_other_repos_nothing_ready_does_not_reset_the_count(m):
    # Real brag turn sits between kipi-system's stalled turns, exactly as on
    # 2026-10-24 23:01. A reset-all on "nothing ready" would hide the stall.
    log = flat(STALL[0], STALL[1], BRAG_TURN, STALL[2])
    fires, _ = m.scan(m.parse_turns(log))
    assert [f["issue"] for f in fires] == ["ASK-2058"]


def test_dispatch_in_the_same_repo_ends_the_stall(m):
    log = flat(STALL[0], STALL[1], RECOVERY_TURN, STALL[2])
    fires, counts = m.scan(m.parse_turns(log))
    assert fires == []


def test_unknown_skip_class_is_detected_as_unknown(m):
    turn = ["2026-10-24T10:%02d:00Z dispatch: 1 of 20 registered repo(s) opted in for "
            "cross-repo dispatch" % i for i in (0,)]
    log = []
    for i in range(3):
        log += ["2026-10-24T10:%02d:00Z dispatch: 1 of 20 registered repo(s) opted in "
                "for cross-repo dispatch" % (i * 15),
                "2026-10-24T10:%02d:05Z skip ASK-9999: something nobody classified" % (i * 15)]
    fires, _ = m.scan(m.parse_turns(log))
    assert fires and fires[0]["info"]["class"] == "unknown"


def test_replay_over_the_real_log_prefix_names_today(tmp_path):
    p = tmp_path / "d.log"
    p.write_text("\n".join(flat(*STALL)) + "\n")
    out = subprocess.run([sys.executable, str(SCRIPT), "--replay", "--log", str(p)],
                         capture_output=True, text=True)
    assert out.returncode == 0
    assert "2026-10-24T14:53:07Z would FIRE ASK-2058" in out.stdout
    assert "PR #554 sana/ask-2058-guard -> sana/ask-2058" in out.stdout


# ---- repair + restart + escalation, with fakes ----

class Fx:
    """Records every outside call. gh answers come from the real fixtures."""

    def __init__(self, m, ref_exists=True, ref_sha=None, open_pr_on_target=""):
        self.gh, self.kicks, self.notes, self.comments = [], 0, [], []
        pv = json.loads((FIX / "gh-pr-view-559.json").read_text())
        pv["headRefName"] = "sana/ask-2058-guard"      # the stalled PR's head
        self.pv = pv
        ref = json.loads((FIX / "gh-ref-sana-ask-2058.json").read_text())
        if ref_sha:
            ref["object"]["sha"] = ref_sha
        self.ref, self.ref_exists, self.open_pr = ref, ref_exists, open_pr_on_target
        m.run = self.run
        m.kickstart = self.kick
        m.notify = self.note
        m.linear_comment = lambda issue, body: (self.comments.append((issue, body)) or (True, "commented"))

    def run(self, cmd, cwd=None):
        self.gh.append(list(cmd))
        if cmd[:3] == ["gh", "pr", "view"]:
            return 0, json.dumps(self.pv)
        if cmd[:3] == ["gh", "repo", "view"]:
            return 0, "assafkip/kipi-system\n"
        if cmd[:2] == ["gh", "api"] and "-X" not in cmd:
            return (0, json.dumps(self.ref)) if self.ref_exists else (1, "HTTP 404")
        if cmd[:4] == ["gh", "api", "-X", "POST"]:
            return 0, "{}"
        if cmd[:3] == ["gh", "pr", "list"]:
            return 0, self.open_pr
        if cmd[:3] == ["gh", "pr", "create"]:
            return 0, "https://github.com/assafkip/kipi-system/pull/559\n"
        if cmd[:3] == ["gh", "pr", "close"]:
            return 0, ""
        return 127, "unexpected: %r" % (cmd,)

    def kick(self):
        self.kicks += 1
        return 0, ""

    def note(self, msg):
        self.notes.append(msg)
        return 0, ""


def kinds(fx):
    out = []
    for c in fx.gh:
        if c[:2] == ["gh", "api"]:
            out.append("gh api POST" if "-X" in c else "gh api GET")
        else:
            out.append(" ".join(c[:3]))
    return out


FORBIDDEN = ("--force", "-f force", "--delete-branch", "delete", "-D", "push", "--admin",
             "--force-with-lease", "reset", "DELETE")


def assert_nothing_destructive(fx):
    for c in fx.gh:
        for bad in FORBIDDEN:
            assert bad not in c, "destructive arg %r in %r" % (bad, c)
        assert "DELETE" not in " ".join(c)
        assert c[:4] != ["gh", "api", "-X", "PATCH"]


def three_turn_log():
    return flat(*STALL[:3])


def say_sink():
    out = []
    return out, out.append


def test_apply_repairs_in_order_kicks_once_and_records_state(m):
    fx = Fx(m, ref_exists=False)
    state, (out, say) = {}, say_sink()
    m.tick(m.parse_turns(three_turn_log()), ts("2026-10-24T14:56:00Z"), state, True, "/repo", say)
    # ref BEFORE the replacement PR BEFORE closing the old one: a crash midway
    # leaves the old PR open and working.
    assert kinds(fx) == ["gh pr view", "gh repo view", "gh api GET", "gh api POST",
                         "gh pr list", "gh pr create", "gh pr close"]
    post = [c for c in fx.gh if c[:4] == ["gh", "api", "-X", "POST"]][0]
    assert "ref=refs/heads/sana/ask-2058" in post
    assert "sha=ae6591e9bbdabb93e517a6ba9edb2b26abe8d80f" in post
    close = [c for c in fx.gh if c[:3] == ["gh", "pr", "close"]][0]
    assert close[3] == "554" and "--delete-branch" not in close
    assert_nothing_destructive(fx)
    assert fx.kicks == 1 and fx.notes == []
    assert fx.comments and fx.comments[0][0] == "ASK-2058"
    assert state["home|ASK-2058"]["kicked_at"] == "2026-10-24T14:56:00Z"
    assert any("repair ok" in line for line in out)


def test_second_tick_before_a_new_turn_waits_and_does_not_restart_or_ticket(m):
    fx = Fx(m, ref_exists=False)
    state, (out, say) = {}, say_sink()
    turns = m.parse_turns(three_turn_log())
    m.tick(turns, ts("2026-10-24T14:56:00Z"), state, True, "/repo", say)
    m.tick(turns, ts("2026-10-24T15:05:00Z"), state, True, "/repo", say)
    assert fx.kicks == 1 and fx.notes == []
    assert any("waiting for a turn" in line for line in out)


def test_still_stalled_after_the_restart_files_exactly_one_ticket(m):
    fx = Fx(m, ref_exists=False)
    state, (out, say) = {}, say_sink()
    m.tick(m.parse_turns(three_turn_log()), ts("2026-10-24T14:56:00Z"), state, True, "/repo", say)
    four = m.parse_turns(flat(*STALL))          # the 15:08 turn stalled again
    m.tick(four, ts("2026-10-24T15:10:00Z"), state, True, "/repo", say)
    m.tick(four, ts("2026-10-24T15:20:00Z"), state, True, "/repo", say)
    assert fx.kicks == 1
    assert len(fx.notes) == 1 and "ASK-2058" in fx.notes[0]
    assert "founder" not in fx.notes[0].lower()


def test_dispatcher_silent_after_the_restart_also_ticket(m):
    fx = Fx(m, ref_exists=False)
    state, (out, say) = {}, say_sink()
    turns = m.parse_turns(three_turn_log())
    m.tick(turns, ts("2026-10-24T14:56:00Z"), state, True, "/repo", say)
    m.tick(turns, ts("2026-10-24T15:30:00Z"), state, True, "/repo", say)   # > 2 intervals
    assert len(fx.notes) == 1


def test_recovery_clears_state_and_says_when_it_dispatched(m):
    fx = Fx(m, ref_exists=False)
    state, (out, say) = {}, say_sink()
    m.tick(m.parse_turns(three_turn_log()), ts("2026-10-24T14:56:00Z"), state, True, "/repo", say)
    healed = m.parse_turns(flat(*STALL, BRAG_TURN, RECOVERY_TURN))
    m.tick(healed, ts("2026-10-24T23:05:00Z"), state, True, "/repo", say)
    assert state == {}
    assert any("recovered ASK-2058" in l and "23:03:23Z" in l for l in out)


def test_repair_refuses_when_the_target_branch_holds_other_work(m):
    fx = Fx(m, ref_exists=True, ref_sha="0" * 40)
    state, (out, say) = {}, say_sink()
    m.tick(m.parse_turns(three_turn_log()), ts("2026-10-24T14:56:00Z"), state, True, "/repo", say)
    assert not any(c[:3] == ["gh", "pr", "create"] for c in fx.gh)
    assert not any(c[:3] == ["gh", "pr", "close"] for c in fx.gh)
    assert not any(c[:4] == ["gh", "api", "-X", "POST"] for c in fx.gh)
    assert fx.kicks == 1                      # a failed repair still restarts once
    assert state["home|ASK-2058"]["repair"].startswith("sana/ask-2058 already exists")


def test_rerun_resumes_when_ref_and_replacement_pr_already_exist(m):
    fx = Fx(m, ref_exists=True, open_pr_on_target="559")
    state, (out, say) = {}, say_sink()
    m.tick(m.parse_turns(three_turn_log()), ts("2026-10-24T14:56:00Z"), state, True, "/repo", say)
    assert not any(c[:3] == ["gh", "pr", "create"] for c in fx.gh)
    assert not any(c[:4] == ["gh", "api", "-X", "POST"] for c in fx.gh)
    assert any(c[:3] == ["gh", "pr", "close"] for c in fx.gh)
    assert_nothing_destructive(fx)


def test_repair_refuses_a_pr_that_is_not_the_logged_one(m):
    fx = Fx(m, ref_exists=False)
    fx.pv["state"] = "CLOSED"
    state, (out, say) = {}, say_sink()
    m.tick(m.parse_turns(three_turn_log()), ts("2026-10-24T14:56:00Z"), state, True, "/repo", say)
    assert kinds(fx) == ["gh pr view"] and fx.kicks == 1


def test_unknown_class_kicks_once_touches_no_github(m):
    fx = Fx(m)
    log = []
    for i in range(3):
        log += ["2026-10-24T10:%02d:00Z dispatch: 1 of 20 registered repo(s) opted in "
                "for cross-repo dispatch" % (i * 15),
                "2026-10-24T10:%02d:05Z skip ASK-9999: something nobody classified" % (i * 15)]
    state, (out, say) = {}, say_sink()
    m.tick(m.parse_turns(log), ts("2026-10-24T10:32:00Z"), state, True, "/repo", say)
    assert fx.gh == [] and fx.kicks == 1 and fx.notes == []


def test_dry_run_has_no_effects_and_writes_no_state(m):
    def boom(*a, **k):
        raise AssertionError("dry run reached an effect")
    m.run = m.kickstart = m.notify = m.linear_comment = boom
    state, (out, say) = {}, say_sink()
    m.tick(m.parse_turns(three_turn_log()), ts("2026-10-24T14:56:00Z"), state, False, "/repo", say)
    assert state == {}
    assert any("DRY: would push PR #554" in l for l in out)
    assert any("DRY: would kickstart" in l for l in out)


def test_healthy_tick_logs_an_ok_line(m):
    Fx(m)
    state, (out, say) = {}, say_sink()
    m.tick(m.parse_turns(lines("healthy-2026-09-23.log")), ts("2026-09-23T03:12:00Z"),
           state, True, "/repo", say)
    assert out and out[0].startswith("ok: no stall")


def test_stall_older_than_the_window_is_not_active(m):
    Fx(m)
    state, (out, say) = {}, say_sink()
    m.tick(m.parse_turns(three_turn_log()), ts("2026-10-25T09:00:00Z"), state, True, "/repo", say)
    assert out[0].startswith("ok: no stall")


# ---- wiring ----

def test_plist_template_is_wired_to_the_script_with_apply():
    plist = (HERE.parent / "com.kipi.dispatch-stall-check.plist").read_text()
    assert "<string>com.kipi.dispatch-stall-check</string>" in plist
    assert "dispatch-stall-check.py" in plist and "--apply" in plist
    assert re.search(r"<key>StartInterval</key>\s*<integer>900</integer>", plist)
    assert "__KIPI_REPO__" in plist and "__HOME__" in plist
    assert (SCRIPT).exists()
