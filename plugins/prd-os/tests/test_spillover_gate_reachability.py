"""ASK-789: green must be REACHABLE by doing the work, at the real ledger's scale.

WHAT ASK-789 ASKED FOR, AND WHAT WAS ALREADY THERE. The issue named its own pick --
"Option 1: scope by attribution ... Green becomes reachable by doing the work" -- and
that code had already shipped six days earlier (PR #131, 2026-08-08, ASK-526/527/532;
the issue was filed 2026-08-14). Measured against HEAD before writing this file:
`_scope_is_live` is called from `_active_scope`, and `_spillover_blocks` already
implements the combined attribution+severity rule. So the fix is not re-implemented
here. What was genuinely missing is the PROOF, which is acceptance criterion (b) of
the issue and the reason this file exists.

WHY test_spillover_gate_scope.py DOES NOT ALREADY COVER THIS. Those cases run against
ledgers of one to three items. A one-item ledger cannot distinguish "the scoping rule
works" from "there was nothing to filter". The real ledger measured on kipi-system
2026-08-16 was 815 open / 32 blocking-severity / 770 minor, and the whole claim of
ASK-789 is about behaviour at that shape. A filter proven only on a ledger smaller
than its own bucket size is proven on the wrong population.

WHAT `[:20]`-STYLE TRUNCATION WOULD HIDE. `cmd_gates` prints at most ten reported ids.
Asserting on the PRINTED tail would pass against unfixed code, because the tail is
truncated before the assertion ever sees it. Every case below asserts the EXIT CODE --
the one output no display cap can shorten -- and reads counts from the ledger rather
than from the screen.

THE PIPE HAZARD, MADE EXECUTABLE. ASK-789 says its own predecessor note reported a
false green because `gates run | tail` returns tail's status, not the gate's. That is
not folklore; `test_a_pipe_masks_the_gates_own_exit_code` reproduces it, so the hazard
is pinned by a test instead of by a sentence in an issue nobody re-reads.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
PRD_RUNNER = PLUGIN_ROOT / "scripts" / "prd_runner.py"

# Big enough that the blocking set is a small minority of the ledger, which is the
# real repo's shape (32 of 815). Small enough to stay a fast unit test.
BULK_INHERITED = 300


def run(repo: Path, *args: str) -> subprocess.CompletedProcess:
    """Direct invocation. NOTHING is piped: `.returncode` here is the gate's own
    exit status, which is the single property every case in this file turns on."""
    return subprocess.run(
        [sys.executable, str(PRD_RUNNER), "--repo-root", str(repo), *args],
        capture_output=True, text=True,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    (r / ".prd-os").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    subprocess.run(["git", "-C", str(r), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(r), "config", "user.name", "t"], check=True)
    (r / "README.md").write_text("x\n")
    subprocess.run(["git", "-C", str(r), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(r), "commit", "-q", "-m", "init"], check=True)
    (r / ".prd-os" / "config.json").write_text(json.dumps({
        "config_schema_version": 1,
        "prds_dir": ".prd-os/prds",
        "issues_dir": ".prd-os/issues",
        "findings_dir": ".prd-os/findings",
        "state_dir": ".claude/state",
    }))
    return r


def _live_issue(repo: Path, issue_id: str) -> None:
    """A TRACKED spec in a non-terminal state, then the active-issue pointer.

    Both halves are required: ASK-527 refuses to scope on a spec git cannot confirm,
    so a test that wrote only the pointer would silently fall through to the
    fail-closed path and its green would mean the opposite of what it claims."""
    d = repo / ".prd-os" / "issues"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{issue_id}.md"
    p.write_text(f"---\nid: {issue_id}\nstatus: in-progress\n---\n\nbody\n")
    subprocess.run(["git", "-C", str(repo), "add", "-f",
                    str(p.relative_to(repo))], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m",
                    f"add {issue_id}"], check=True)
    s = repo / ".claude" / "state"
    s.mkdir(parents=True, exist_ok=True)
    (s / "active-issue.json").write_text(json.dumps({"issue_id": issue_id}))


def _add(repo: Path, sid: str, source: str, severity: str = "minor") -> None:
    """One item THROUGH THE REAL CLI, so the row shape is the producer's."""
    r = run(repo, "spillover", "add", "--source", source, "--id", sid,
            "--severity", severity,
            "--desc", f"a real finding recorded by {source}")
    assert r.returncode == 0, f"seeding {sid} failed: {r.stdout}{r.stderr}"


def _ledger(repo: Path) -> Path:
    return repo / ".prd-os" / "spillover.jsonl"


def _bulk_inherited(repo: Path, count: int, severity: str = "minor") -> None:
    """Clone the PRODUCER's row shape `count` times.

    The template is a row the real `spillover add` just wrote, read back off disk --
    not a dict invented here. An invented fixture tests the shape I assumed rather
    than the shape the writer emits, and this ledger has already shipped one
    green-but-wrong test that way. Only `id` and `source` vary.
    """
    _add(repo, "sp-template", "template-source", severity)
    rows = [json.loads(x) for x in _ledger(repo).read_text().splitlines() if x.strip()]
    template = [r for r in rows if r["id"] == "sp-template"][-1]
    with _ledger(repo).open("a") as fh:
        for n in range(count):
            rec = dict(template)
            rec["id"] = f"sp-bulk{n:04d}"
            rec["source"] = f"some-old-issue-{n % 40}"
            fh.write(json.dumps(rec) + "\n")


def _open_count(repo: Path) -> int:
    """Collapse by id before counting. The ledger is APPEND-ONLY, so one item that
    was reclassified twice is three rows and one item; counting raw rows overstates
    a backlog and has done so before."""
    latest: dict[str, dict] = {}
    for line in _ledger(repo).read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            latest[r["id"]] = r
    return sum(1 for r in latest.values() if r.get("status") == "open")


# --- acceptance (b): green is reachable from a realistic ledger ----------------

def test_green_is_reachable_at_realistic_scale(repo):
    """THE POINT OF ASK-789. Hundreds of items inherited from other work, a live
    scope that owns none of them, and the gate must go GREEN -- because an engineer
    can only ever resolve what their own work created."""
    _live_issue(repo, "ASK-789")
    _bulk_inherited(repo, BULK_INHERITED)
    assert _open_count(repo) >= BULK_INHERITED, "the bulk seed did not land"
    g = run(repo, "gates", "run")
    assert g.returncode == 0, (
        f"green is still unreachable with {_open_count(repo)} inherited items open "
        f"and none attributable to the active scope.\n{g.stdout}\n{g.stderr}")


def test_the_green_run_still_says_the_real_number_out_loud(repo):
    """A reachable green must not be a quiet one. Asserts the LITERAL count: a
    baseline captured from the same run cannot detect a change that moves both
    sides, and an operator with ADHD treats a number that stops printing as gone."""
    _live_issue(repo, "ASK-789")
    _bulk_inherited(repo, BULK_INHERITED)
    total = _open_count(repo)
    g = run(repo, "gates", "run")
    assert g.returncode == 0
    out = g.stdout + g.stderr
    assert str(total) in out, (
        f"the green run never printed its own open-item count ({total}).\n{out}")
    assert "no open spillover" not in out, (
        f"the run claimed an empty ledger while {total} items were open.\n{out}")


# --- acceptance (b), the negative control -------------------------------------

def test_an_attributable_item_still_goes_red_at_the_same_scale(repo):
    """THE CONTROL THAT MAKES THE GREEN ABOVE MEAN SOMETHING. Identical ledger,
    identical scope, ONE added item the active issue owns. If this ever passes
    green, the scoping has become the hand-clear it was built to avoid."""
    _live_issue(repo, "ASK-789")
    _bulk_inherited(repo, BULK_INHERITED)
    _add(repo, "sp-mine", "ASK-789", "major")
    g = run(repo, "gates", "run")
    assert g.returncode != 0, (
        "the work's OWN open major did not turn its gate red -- attribution is "
        f"letting through exactly what it exists to catch.\n{g.stdout}\n{g.stderr}")
    assert "sp-mine" in (g.stdout + g.stderr), "the blocking item was not named"


def test_the_gate_flips_on_attribution_alone(repo):
    """Same ledger, same severity, same count -- only the SOURCE differs. Isolates
    attribution as the variable, so a green cannot be credited to scale or severity."""
    _live_issue(repo, "ASK-789")
    _bulk_inherited(repo, 50)
    _add(repo, "sp-someone-elses", "a-different-issue", "major")
    assert run(repo, "gates", "run").returncode == 0, "an inherited major blocked"
    _add(repo, "sp-ours", "ASK-789", "major")
    assert run(repo, "gates", "run").returncode != 0, "our own major did not block"


def test_an_inherited_blocker_still_wedges_the_scope(repo):
    """The KNOWN COST, kept visible on purpose. `blocker` is the one severity that
    crosses attribution, and on 2026-08-16 exactly three such items were what held
    every scope on kipi-system red. Pinned so the cost stays a decision rather than
    a surprise."""
    _live_issue(repo, "ASK-789")
    _bulk_inherited(repo, 50)
    _add(repo, "sp-inherited-blocker", "someone-elses-issue", "blocker")
    g = run(repo, "gates", "run")
    assert g.returncode != 0, (
        "an inherited `blocker` stopped wedging every scope; that is the escape "
        "hatch severity is supposed to keep.")
    assert "sp-inherited-blocker" in (g.stdout + g.stderr)


# --- acceptance (c): the exit code, read directly -----------------------------

def test_a_pipe_masks_the_gates_own_exit_code(repo):
    """ASK-789's acceptance (c), made executable rather than remembered.

    A RED gate reports GREEN the moment its output is piped, because the shell
    returns the LAST command's status. This is how a red gate got recorded as
    passing in a transcript. The fix is not in the gate -- there is nothing to fix
    in it -- it is that every assertion in this file reads the direct status.
    """
    _live_issue(repo, "ASK-789")
    _add(repo, "sp-mine", "ASK-789", "major")

    direct = run(repo, "gates", "run")
    assert direct.returncode == 1, "precondition: the gate must be RED here"

    piped = subprocess.run(
        f"{sys.executable} {PRD_RUNNER} --repo-root {repo} gates run | tail -1",
        shell=True, capture_output=True, text=True)
    assert piped.returncode == 0, (
        "the pipe hazard did not reproduce; if the shell stopped swallowing the "
        "status this test is obsolete and should be deleted, not loosened.")
    assert direct.returncode != piped.returncode, (
        "direct and piped status agreed, so this case proves nothing")


def test_unscoped_is_still_fail_closed_over_the_whole_pile(repo):
    """ASK-789 must not have bought its green by handing out an amnesty.

    With NO live scope, nothing is attributable, and the run answers for every open
    item. Clearing `active-issue.json` must never be a cheaper way to a green gate
    than doing the work -- that is the hand-clear no-orphan-findings.md refuses.
    """
    _bulk_inherited(repo, 50, severity="major")
    g = run(repo, "gates", "run")
    assert g.returncode != 0, (
        "an unscoped run went GREEN over an open ledger of majors, so 'have no "
        f"active issue' is now the cheapest bypass in the repo.\n{g.stdout}")
