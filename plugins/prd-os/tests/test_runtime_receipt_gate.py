"""A runtime-control fix cannot close on source-only evidence.

RCA 2026-10-02: a token gate and a scanner were marked built because their source
read correctly. Neither had fired on the real caller, and the burn recurred
(RCA 2026-10-06). So an item whose text claims a gate / cap / meter / budget /
ledger / guard / limit / rate / quota fix needs a RUNTIME receipt to resolve: the
command run against the real caller, its observed output, and when it ran.

Reproducer: on the pre-fix runner, `spillover resolve <cap item> --resolution-ref
<closed issue>` exits 0. Here it must exit 2 and leave the item open.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

PLUGINS = Path(__file__).resolve().parents[2]
SCRIPTS = PLUGINS / "prd-os" / "scripts"
PRD_RUNNER = SCRIPTS / "prd_runner.py"
RECEIPT_MOD = SCRIPTS / "runtime_receipt.py"
DSSE_MIRROR = PLUGINS / "kipi-dsse" / "scripts" / "runtime_receipt.py"

sys.path.insert(0, str(SCRIPTS))
import prd_runner  # noqa: E402
import runtime_receipt as rr  # noqa: E402


# ---------------------------------------------------------------------------
# The classifier: one list, real-shaped examples both ways
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "cap the reviewer at two rounds",
    "Meter orchestrated agents and PR reviews: write a ledger row per run",
    "the scheduled job ignores the daily budget",
    "move the gate above the runner early return",
    "publish guard is skipped on the retry path",
    "add a rate-limit to the scraper",
    "per-call token quota is never read",
    "reviewer rounds are not capped",
    "the limit on concurrent workers is bypassed",
])
def test_runtime_control_items_classify(text):
    assert rr.claims_runtime_control(text), text


@pytest.mark.parametrize("text", [
    "gatekeeper copy on the landing page reads stiff",
    "capture the screenshot at phone width",
    "capitalize the headline",
    "generate the weekly report from the template",
    "accurate titles for the case study",
    "the delimiter in the csv export is wrong",
    "guardian-style serif for the hero",
    "obsidian export skips archived notes",
    "",
])
def test_ordinary_items_do_not_classify(text):
    """A gate that fires on copy edits gets switched off."""
    assert rr.claims_runtime_control(text) == [], text


def test_the_dsse_copy_is_the_same_file():
    """kipi-dsse stays import-independent of prd-os, so the module lives twice.
    This is what keeps the term list ONE list."""
    assert DSSE_MIRROR.read_bytes() == RECEIPT_MOD.read_bytes()


@pytest.mark.parametrize("cmd", [
    "grep -n run_model scripts/x.py",
    "rg 'ledger' .",
    "cat scripts/gate.py | head -40",
    "sed -n 1,80p scripts/gate.py",
    "git show HEAD:scripts/gate.py",
    "git grep cap",
    "python3 -c 'import gate'",
    "python3 -c 'import ast; ast.parse(open(\"g.py\").read())'",
    "python3 -m py_compile scripts/gate.py",
    "python3 -m pytest tests/ --collect-only",
    "env FOO=1 grep x y",
    "bash -c 'grep -c row ledger.jsonl'",
])
def test_source_only_commands_are_recognised(cmd):
    assert rr.command_is_source_only(cmd), cmd


@pytest.mark.parametrize("cmd", [
    "python3 jobs/run_reviewer.py --once",
    "bash scripts/job.sh && grep -c row ledger.jsonl",
    "claude -p hi --model haiku",
    "python3 -m pytest tests/test_gate.py",
    "python3 -c 'import job; job.main()'",
])
def test_real_calls_are_not_source_only(cmd):
    assert not rr.command_is_source_only(cmd), cmd


# ---------------------------------------------------------------------------
# spillover resolve: the CLI, run as a subprocess against a tmp .prd-os
# ---------------------------------------------------------------------------

@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    (r / ".prd-os" / "issues").mkdir(parents=True)
    (r / ".git").mkdir()
    (r / ".prd-os" / "config.json").write_text(json.dumps({
        "config_schema_version": 1, "prds_dir": ".prd-os/prds",
        "issues_dir": ".prd-os/issues", "findings_dir": ".prd-os/findings",
        "state_dir": ".claude/state"}))
    (r / ".prd-os" / "issues" / "iss-1.md").write_text(
        "---\nid: iss-1\nstatus: closed\n---\n\n# iss-1\n")
    return r


def _cli(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PRD_RUNNER), "--repo-root", str(repo), *args],
                          capture_output=True, text=True)


def _add(repo: Path, sid: str, desc: str) -> None:
    r = _cli(repo, "spillover", "add", "--source", "rca-x", "--desc", desc,
             "--id", sid, "--severity", "medium", "--no-promote")
    assert r.returncode == 0, r.stderr


def _row(repo: Path, sid: str) -> dict:
    rows = [json.loads(l) for l in (repo / ".prd-os" / "spillover.jsonl")
            .read_text().splitlines() if l.strip()]
    return [r for r in rows if r["id"] == sid][-1]


def _receipt(tmp_path: Path, command: str, output: str = "row written: 1",
             ran_at: str | None = None, name: str = "r.json") -> Path:
    p = tmp_path / name
    p.write_text(json.dumps({
        "command": command, "output": output, "exit_code": 0,
        "ran_at": ran_at or datetime.now(timezone.utc).isoformat(timespec="seconds")}))
    return p


def test_REPRODUCER_a_cap_item_does_not_resolve_on_a_ref_alone(repo):
    _add(repo, "sp-cap", "cap the reviewer at two rounds")
    r = _cli(repo, "spillover", "resolve", "sp-cap", "--resolution-ref", "iss-1")
    assert r.returncode == 2, f"resolved on source-only evidence: {r.stdout}{r.stderr}"
    assert "--runtime-receipt" in r.stderr and "capture" in r.stderr, r.stderr
    assert _row(repo, "sp-cap")["status"] == "open"


@pytest.mark.parametrize("exit_args", [
    ("--resolution-commit", "deadbeef"),
    ("--resolution-proof", "true", "--broken-at", "deadbeef"),
])
def test_every_fix_exit_is_gated_not_only_the_ref(repo, exit_args):
    _add(repo, "sp-cap", "cap the reviewer at two rounds")
    r = _cli(repo, "spillover", "resolve", "sp-cap", *exit_args)
    assert r.returncode == 2
    assert "--runtime-receipt" in r.stderr, r.stderr
    assert _row(repo, "sp-cap")["status"] == "open"


def test_a_source_only_receipt_is_refused(repo, tmp_path):
    _add(repo, "sp-cap", "cap the reviewer at two rounds")
    rec = _receipt(tmp_path, "grep -n MAX_ROUNDS scripts/reviewer.py", "12:MAX_ROUNDS = 2")
    r = _cli(repo, "spillover", "resolve", "sp-cap", "--resolution-ref", "iss-1",
             "--runtime-receipt", str(rec))
    assert r.returncode == 2
    assert "only reads source" in r.stderr, r.stderr
    assert _row(repo, "sp-cap")["status"] == "open"


@pytest.mark.parametrize("bad", [
    {"command": "python3 job.py", "ran_at": "2026-01-01T00:00:00+00:00"},   # no output
    {"output": "x", "ran_at": "2026-01-01T00:00:00+00:00"},                 # no command
    {"command": "python3 job.py", "output": "x"},                            # no timestamp
    {"command": "python3 job.py", "output": "x", "ran_at": "yesterday"},
    {"command": "python3 job.py", "output": "x",
     "ran_at": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()},
])
def test_an_incomplete_receipt_is_refused(repo, tmp_path, bad):
    _add(repo, "sp-cap", "cap the reviewer at two rounds")
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(bad))
    r = _cli(repo, "spillover", "resolve", "sp-cap", "--resolution-ref", "iss-1",
             "--runtime-receipt", str(p))
    assert r.returncode == 2, r.stdout
    assert _row(repo, "sp-cap")["status"] == "open"


def test_a_real_receipt_resolves_and_is_stored_on_the_row(repo, tmp_path):
    """Negative-fire: without this, refusing everything passes every test above."""
    _add(repo, "sp-cap", "cap the reviewer at two rounds")
    out = tmp_path / "real.json"
    cap = subprocess.run([sys.executable, str(RECEIPT_MOD), "capture", "--out", str(out),
                          "--", sys.executable, "-c", "print('rounds used: 2 of 2')"],
                         capture_output=True, text=True)
    assert cap.returncode == 0, cap.stderr
    r = _cli(repo, "spillover", "resolve", "sp-cap", "--resolution-ref", "iss-1",
             "--runtime-receipt", str(out))
    assert r.returncode == 0, r.stderr
    row = _row(repo, "sp-cap")
    assert row["status"] == "resolved"
    ref = row["runtime_receipt"]
    assert ref["path"] == str(out) and len(ref["sha256"]) == 64
    assert ref["command"].startswith(sys.executable) and ref["exit_code"] == 0
    assert ref["claim_terms"] == ["cap"]


def test_an_ordinary_item_still_resolves_on_a_ref_alone(repo):
    _add(repo, "sp-plain", "obsidian export skips archived notes")
    r = _cli(repo, "spillover", "resolve", "sp-plain", "--resolution-ref", "iss-1")
    assert r.returncode == 0, r.stderr
    assert "runtime_receipt" not in _row(repo, "sp-plain")


def test_void_needs_no_receipt(repo):
    """A void claims no fix, so it has nothing to prove at runtime."""
    _add(repo, "sp-cap", "cap the reviewer at two rounds")
    r = _cli(repo, "spillover", "resolve", "sp-cap", "--void", "duplicate")
    assert r.returncode == 0, r.stderr


# ---------------------------------------------------------------------------
# promoted-audit: the automated resolver must not become the bypass
# ---------------------------------------------------------------------------

class _Args:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def test_promoted_audit_leaves_a_runtime_claim_promoted(tmp_path, monkeypatch, capsys):
    prd = tmp_path / ".prd-os"
    (prd / "issues").mkdir(parents=True)
    (prd / "config.json").write_text(json.dumps({"version": 1}))
    cfg = prd_runner.load_config(tmp_path, strict=False)
    rows = [
        {"id": "sp-meter", "status": "promoted", "linear_ref": "ASK-1",
         "description": "meter the agent runs into the ledger", "severity": "major"},
        {"id": "sp-plain", "status": "promoted", "linear_ref": "ASK-2",
         "description": "export skips archived notes", "severity": "major"},
    ]
    prd_runner._spillover_path(cfg).write_text("".join(json.dumps(r) + "\n" for r in rows))
    monkeypatch.setattr(prd_runner, "_linear_issue_state",
                        lambda ident: {"name": "Done", "type": "completed"})
    prd_runner._spillover_promoted_audit(cfg, _Args(dry_run=False))
    after = {r["id"]: r["status"] for r in prd_runner._read_spillover(cfg).values()}
    assert after["sp-meter"] == "promoted", "a tracker 'Done' closed a runtime claim"
    assert after["sp-plain"] == "resolved"
    assert "RUNTIME RECEIPT" in capsys.readouterr().out
