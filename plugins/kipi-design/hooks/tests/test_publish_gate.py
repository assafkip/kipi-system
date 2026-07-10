"""Reproducers for publish_gate.py — the PreToolUse design-room publish gate
(issue dr-publish-hook, PRD prd-design-room-publish-gate-2026-07-05).

Red-first: before the hook, an Artifact publish of an un-converged design-room
page has zero resistance (postmortem DR-2026-07-04-01 — the exact escape). Each
test drives the hook script with a simulated tool call on stdin and asserts the
fail-closed behavior. Run-states are built with the REAL design_room_run chain
primitives so the hook's chain verification is exercised honestly.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1] / "publish_gate.py"
REPO_ROOT = Path(__file__).resolve().parents[4]
GTM_SCRIPTS = REPO_ROOT / "gtm" / "scripts"
sys.path.insert(0, str(GTM_SCRIPTS))

import design_room_pipeline  # noqa: E402
import design_room_run as drr  # noqa: E402

GRAPH = design_room_pipeline.load()


def call(tool_name: str, tool_input: dict) -> subprocess.CompletedProcess:
    payload = json.dumps({"tool_name": tool_name, "tool_input": tool_input})
    return subprocess.run([sys.executable, str(HOOK)], input=payload,
                          capture_output=True, text=True, timeout=60)


def _make_project(tmp_path: Path) -> Path:
    proj = tmp_path / "proj"
    (proj / "design-room" / "build").mkdir(parents=True)
    (proj / "design-room" / "build" / "index.html").write_text(
        "<html><body>page</body></html>")
    return proj


_BUILT_PRODUCER = next((s.id for s in GRAPH.stages if "built_html" in s.produces), "build")


def _write_runstate(proj: Path, stages: list[str], built_html: str | None,
                    record_hash: bool = True) -> Path:
    """Build a chain-valid run-state with the given stage receipts (+ a record
    receipt for built_html when given), using the real _hash so the hook's
    _verify_chain accepts it. The build stage receipt records the produced-hash of
    built_html (schema v2) unless record_hash=False (a legacy pre-D2 receipt)."""
    genesis = {"project": str(proj), "created_at": "2026-07-05T00:00:00+00:00",
               "runner_version": "1.0"}
    state = {f: None for f in GRAPH.run_state_artifacts}
    state["project"] = str(proj)
    state["genesis"] = genesis
    state["receipts"] = []
    prev = drr._hash(genesis)
    if built_html is not None:
        rec = {"kind": "record", "field": "built_html", "value": built_html,
               "at": "2026-07-05T00:00:01+00:00", "prev": prev}
        state["receipts"].append(rec)
        state["built_html"] = built_html
        prev = drr._hash(rec)
    built_file = proj / "design-room" / built_html if built_html else None
    for st in stages:
        rec = {"kind": "stage", "stage": st, "checkers": [], "exit": 0,
               "at": "2026-07-05T00:00:02+00:00", "prev": prev}
        if (st == _BUILT_PRODUCER and record_hash and built_file
                and built_file.is_file()):
            rec["produced_hashes"] = {
                "built_html": hashlib.sha256(built_file.read_bytes()).hexdigest()}
        state["receipts"].append(rec)
        prev = drr._hash(rec)
    sp = proj / "design-room" / "run-state.json"
    sp.write_text(json.dumps(state, indent=2))
    return sp


# --- the incident: un-converged design-room Artifact publish -------------------

def test_unconverged_design_page_artifact_blocked(tmp_path):
    proj = _make_project(tmp_path)
    built = "build/index.html"
    _write_runstate(proj, stages=["runtime-contract", "build"], built_html=built)
    r = call("Artifact", {"file_path": str(proj / "design-room" / built)})
    assert r.returncode == 2, (r.returncode, r.stderr)
    assert "convergence" in r.stderr.lower()


def test_converged_design_page_artifact_allowed(tmp_path):
    proj = _make_project(tmp_path)
    built = "build/index.html"
    _write_runstate(proj, stages=["runtime-contract", "build", "convergence-lead-last"],
                    built_html=built)
    r = call("Artifact", {"file_path": str(proj / "design-room" / built)})
    assert r.returncode == 0, r.stderr


def test_post_convergence_edit_blocked_by_content_hash(tmp_path):
    # sp-7bcd3b43: the run converged, but the built page is hand-edited AFTER
    # convergence. Path matches, but the content hash no longer matches the recorded
    # produced_hash -> block (path-only binding missed this).
    proj = _make_project(tmp_path)
    built = "build/index.html"
    _write_runstate(proj, stages=["runtime-contract", _BUILT_PRODUCER,
                                   "convergence-lead-last"], built_html=built)
    (proj / "design-room" / built).write_text("<html><body>HAND-EDITED</body></html>")
    r = call("Artifact", {"file_path": str(proj / "design-room" / built)})
    assert r.returncode == 2, (r.returncode, r.stderr)
    assert "changed since convergence" in r.stderr.lower() or "content hash" in r.stderr.lower()


def test_legacy_receipt_without_produced_hash_fails_closed(tmp_path):
    # A converged run whose build receipt records no produced_hash (legacy pre-D2)
    # cannot prove content integrity -> fail closed, not path-only pass.
    proj = _make_project(tmp_path)
    built = "build/index.html"
    _write_runstate(proj, stages=["runtime-contract", _BUILT_PRODUCER,
                                   "convergence-lead-last"], built_html=built,
                    record_hash=False)
    r = call("Artifact", {"file_path": str(proj / "design-room" / built)})
    assert r.returncode == 2
    assert "produced-hash" in r.stderr.lower() or "produced_hash" in r.stderr.lower()


def test_untracked_design_page_blocked(tmp_path):
    # A design-room build page with no run-state beside it -> fail closed.
    proj = _make_project(tmp_path)
    r = call("Artifact", {"file_path": str(proj / "design-room" / "build" / "index.html")})
    assert r.returncode == 2
    assert "run-state" in r.stderr.lower() or "tracked" in r.stderr.lower()


def test_broken_chain_blocked(tmp_path):
    proj = _make_project(tmp_path)
    sp = _write_runstate(proj, stages=["runtime-contract", "build", "convergence-lead-last"],
                         built_html="build/index.html")
    state = json.loads(sp.read_text())
    state["receipts"][1]["exit"] = 99  # tamper -> chain break
    sp.write_text(json.dumps(state))
    r = call("Artifact", {"file_path": str(proj / "design-room" / "build" / "index.html")})
    assert r.returncode == 2


def test_publishing_wrong_file_blocked(tmp_path):
    # Converged run, but publishing a DIFFERENT file than the recorded built_html.
    proj = _make_project(tmp_path)
    _write_runstate(proj, stages=["runtime-contract", "build", "convergence-lead-last"],
                    built_html="build/index.html")
    other = proj / "design-room" / "build" / "other.html"
    other.write_text("<html><body>stale</body></html>")
    r = call("Artifact", {"file_path": str(other)})
    assert r.returncode == 2


# --- non-design-room payloads pass ---------------------------------------------

def test_non_design_room_artifact_passes(tmp_path):
    page = tmp_path / "report.html"
    page.write_text("<html><body>report</body></html>")
    r = call("Artifact", {"file_path": str(page)})
    assert r.returncode == 0, r.stderr


def test_no_file_path_passes(tmp_path):
    r = call("Artifact", {"favicon": "x"})
    assert r.returncode == 0


# --- SendUserFile ---------------------------------------------------------------

def test_send_user_file_unconverged_blocked(tmp_path):
    proj = _make_project(tmp_path)
    _write_runstate(proj, stages=["runtime-contract", "build"], built_html="build/index.html")
    r = call("SendUserFile", {"files": [str(proj / "design-room" / "build" / "index.html")],
                              "status": "normal"})
    assert r.returncode == 2


def test_send_user_file_dict_element(tmp_path):
    proj = _make_project(tmp_path)
    _write_runstate(proj, stages=["runtime-contract", "build"], built_html="build/index.html")
    r = call("SendUserFile", {"files": [{"path": str(proj / "design-room" / "build" / "index.html")}]})
    assert r.returncode == 2


# --- deploy_to_vercel ----------------------------------------------------------

def test_vercel_deploy_unconverged_dir_blocked(tmp_path):
    proj = _make_project(tmp_path)
    _write_runstate(proj, stages=["runtime-contract", "build"], built_html="build/index.html")
    r = call("mcp__plugin_vercel_vercel__deploy_to_vercel",
             {"cwd": str(proj / "design-room" / "build")})
    assert r.returncode == 2


def test_vercel_deploy_no_path_fails_closed(tmp_path):
    # A deploy whose target cannot be resolved is blocked, not waved through.
    r = call("mcp__plugin_vercel_vercel__deploy_to_vercel", {})
    assert r.returncode == 2


def test_vercel_deploy_non_design_dir_passes(tmp_path):
    d = tmp_path / "site"
    d.mkdir()
    r = call("mcp__plugin_vercel_vercel__deploy_to_vercel", {"cwd": str(d)})
    assert r.returncode == 0


def test_symlinked_design_page_still_blocked(tmp_path):
    # codex-review blocker: a design-room page that is a symlink to outside must
    # still be recognized as design-room (resolving-first hid the ancestor).
    proj = _make_project(tmp_path)
    _write_runstate(proj, stages=["runtime-contract", "build"], built_html="build/index.html")
    real = tmp_path / "elsewhere.html"
    real.write_text("<html><body>x</body></html>")
    link = proj / "design-room" / "build" / "linked.html"
    link.unlink(missing_ok=True)
    link.symlink_to(real)
    r = call("Artifact", {"file_path": str(link)})
    assert r.returncode == 2


def test_unparseable_input_fails_closed():
    r = subprocess.run([sys.executable, str(HOOK)], input="not json {",
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 2


def test_missing_tool_input_fails_closed():
    payload = json.dumps({"tool_name": "Artifact"})  # no tool_input
    r = subprocess.run([sys.executable, str(HOOK)], input=payload,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 2


def test_send_user_file_dict_mixed_keys_checks_all(tmp_path):
    # codex-review: a dict element with a non-design 'path' and a design-room
    # 'file_path' must still be inspected on every key.
    proj = _make_project(tmp_path)
    _write_runstate(proj, stages=["runtime-contract", "build"], built_html="build/index.html")
    decoy = tmp_path / "decoy.html"
    decoy.write_text("<html></html>")
    r = call("SendUserFile", {"files": [
        {"path": str(decoy), "file_path": str(proj / "design-room" / "build" / "index.html")}
    ]})
    assert r.returncode == 2


def test_selftest_passes():
    r = subprocess.run([sys.executable, str(HOOK), "--selftest"],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr + r.stdout
