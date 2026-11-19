#!/usr/bin/env python3
"""Pins the send-time voice check, `voice_send_check.py` (ASK-4969 part 3 and part 5).

What it must hold:
  (a) the check runs on the BYTES that leave (the tool input), not on a draft file: a receipt
      minted for draft A never clears a send of text B;
  (b) a send of an AI-shaped text is refused, and so is a forced outage (a required part that
      ran 0), in an instance that has no q-consult/ at all;
  (c) a spent receipt skips the engine only when sha256, surface and verdict all match;
  (d) a send whose bytes the hook cannot read (a Gmail draftId) refuses, it does not pass.

TEST ISOLATION (fable-discipline): the engine is the stub from test_voice_full_gate (the
refusal rule under test is the real one); receipts go to a temp dir via KIPI_VOICE_RECEIPTS;
the hook timing log goes to a temp file. Nothing reads a live corpus or ledger.
CONTROL FIRST: test_clean_text_passes_and_mints_a_receipt, so a refusal cannot come from a
check that refuses everything.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
from test_voice_full_gate import AI_SHAPED, _result, _stub_engine  # noqa: E402

import voice_send_check as vsc  # noqa: E402

TEMPLATE = REPO / "settings-template.json"
SENDERS = ("mcp__claude_ai_Gmail__send_message", "mcp__claude_ai_Gmail__reply",
           "mcp__claude_ai_Gmail__forward")


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---- what leaves ----------------------------------------------------------------------

def test_text_that_leaves_is_subject_and_body():
    t = vsc.text_that_leaves("mcp__claude_ai_Gmail__send_message",
                             {"subject": "Hello", "body": "Plain body."})
    assert "Hello" in t and "Plain body." in t


def test_html_body_is_read_as_text():
    t = vsc.text_that_leaves("mcp__claude_ai_Gmail__send_message",
                             {"htmlBody": "<p>We <b>leverage</b> &amp; grow</p>"})
    assert "leverage" in t and "<p>" not in t and "& grow" in t


def test_a_draft_id_send_is_unreadable():
    assert vsc.text_that_leaves("mcp__claude_ai_Gmail__send_message", {"draftId": "r-1"}) is None


def test_the_tool_list_is_the_gmail_senders():
    assert set(vsc.SEND_TOOLS) >= set(SENDERS)


# ---- the control and the receipt ------------------------------------------------------

def test_clean_text_passes_and_mints_a_receipt(tmp_path):
    root = _stub_engine(tmp_path, _result())
    v = vsc.send_check("A short note.", "client-email", receipts_dir=tmp_path / "r",
                       engine_root=root)
    assert v.ok, v.reasons
    rec = json.loads(next((tmp_path / "r").glob("*.json")).read_text())
    assert rec["sha256"] == _sha("A short note.") and rec["verdict"] == "PASS"


def test_a_spent_receipt_does_not_rerun_the_engine(tmp_path):
    good = _stub_engine(tmp_path / "a", _result())
    vsc.send_check("A short note.", "client-email", receipts_dir=tmp_path / "r", engine_root=good)
    broken = _stub_engine(tmp_path / "b", body="raise RuntimeError('engine must not run')")
    v = vsc.send_check("A short note.", "client-email", receipts_dir=tmp_path / "r",
                       engine_root=broken)
    assert v.ok and any("receipt" in n for n in v.notes)


def test_a_receipt_for_the_draft_does_not_clear_different_bytes(tmp_path):
    """(a) the point of the send-time check: the draft was clean, the bytes that leave are not."""
    clean = _stub_engine(tmp_path / "a", _result())
    assert vsc.send_check("A short note.", "client-email", receipts_dir=tmp_path / "r",
                          engine_root=clean).ok
    dirty = _stub_engine(tmp_path / "b", _result(hard=["banned-word: 'leverage'"]))
    v = vsc.send_check(AI_SHAPED, "client-email", receipts_dir=tmp_path / "r", engine_root=dirty)
    assert v.verdict == "REFUSE"


def test_a_receipt_for_another_surface_is_not_spent(tmp_path):
    clean = _stub_engine(tmp_path / "a", _result())
    vsc.send_check("A short note.", "client-email", receipts_dir=tmp_path / "r", engine_root=clean)
    dirty = _stub_engine(tmp_path / "b", _result(hard=["x"]))
    v = vsc.send_check("A short note.", "linkedin", receipts_dir=tmp_path / "r", engine_root=dirty)
    assert v.verdict == "REFUSE"


def test_a_forged_receipt_with_the_wrong_hash_is_not_spent(tmp_path):
    r = tmp_path / "r"
    r.mkdir()
    sha = _sha("A short note.")
    (r / ("%s-client-email.json" % sha)).write_text(json.dumps(
        {"sha256": "0" * 64, "surface": "client-email", "verdict": "PASS"}))
    dirty = _stub_engine(tmp_path / "b", _result(hard=["x"]))
    assert vsc.send_check("A short note.", "client-email", receipts_dir=r,
                          engine_root=dirty).verdict == "REFUSE"


def test_a_refusal_mints_no_receipt(tmp_path):
    dirty = _stub_engine(tmp_path, _result(hard=["x"]))
    vsc.send_check("note", "client-email", receipts_dir=tmp_path / "r", engine_root=dirty)
    assert not list((tmp_path / "r").glob("*.json")) if (tmp_path / "r").exists() else True


def test_an_outage_refuses_and_mints_nothing(tmp_path):
    parts = {"hard-rows": {"ran": 1, "of": 1}, "authorship": {"ran": 0, "of": 1}}
    root = _stub_engine(tmp_path, _result(parts=parts))
    v = vsc.send_check("note", "client-email", receipts_dir=tmp_path / "r", engine_root=root)
    assert v.verdict == "OUTAGE"
    assert not (tmp_path / "r").exists() or not list((tmp_path / "r").glob("*.json"))


# ---- the hook, run the way an instance runs it ---------------------------------------

def _instance(tmp_path):
    """An instance with NO q-consult/: the shipped scripts only, as a synced instance has them."""
    inst = tmp_path / "inst"
    scripts = inst / "q-system" / ".q-system" / "scripts"
    scripts.mkdir(parents=True)
    src = REPO / "q-system" / ".q-system" / "scripts"
    for name in ("voice-hook-run.sh", "voice_hook_run.py", "voice-send-check.py"):
        shutil.copy(src / name, scripts / name)
    plug = inst / "plugins" / "kipi-core"
    shutil.copytree(REPO / "plugins" / "kipi-core" / "scripts", plug / "scripts",
                    ignore=shutil.ignore_patterns("test", "__pycache__"))
    shutil.copytree(REPO / "plugins" / "kipi-core" / "voiceloop", plug / "voiceloop",
                    ignore=shutil.ignore_patterns("tests", "__pycache__"))
    assert not (inst / "q-consult").exists()
    return inst


def _send_hook_command():
    data = json.loads(TEMPLATE.read_text())
    cmds = [(g.get("matcher", ""), h) for g in data["hooks"].get("PreToolUse", [])
            for h in g["hooks"] if "voice-send-check" in h.get("command", "")]
    assert len(cmds) == 1, cmds
    return cmds[0]


def _fire(tmp_path, engine_root, tool_input, tool="mcp__claude_ai_Gmail__send_message"):
    inst = _instance(tmp_path)
    _, hook = _send_hook_command()
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(inst), KIPI_VOICE_ENGINE_ROOT=str(engine_root),
               KIPI_VOICE_RECEIPTS=str(tmp_path / "receipts"),
               KIPI_VOICE_HOOK_LOG=str(tmp_path / "timing.jsonl"))
    if LIVE:
        # The real engine refuses to run its critic under pytest; the ledger and gate-day
        # redirects below (set by the live test) keep it off the live data paths.
        env.pop("PYTEST_CURRENT_TEST", None)
    payload = json.dumps({"hook_event_name": "PreToolUse", "tool_name": tool,
                          "tool_input": tool_input})
    return subprocess.run(["/bin/sh", "-c", hook["command"]], input=payload, env=env,
                          capture_output=True, text=True, timeout=120)


def test_hook_is_wired_on_every_sender_with_room_to_run():
    matcher, hook = _send_hook_command()
    for tool in SENDERS:
        assert re.fullmatch(matcher, tool), tool
    inner = float(hook["command"].split("--timeout")[1].split()[0])
    assert inner > 120 and inner < hook["timeout"], (inner, hook["timeout"])  # engine bound is 600 s default


def test_hook_passes_a_clean_send_in_an_instance_without_q_consult(tmp_path):
    root = _stub_engine(tmp_path / "e", _result())
    r = _fire(tmp_path, root, {"to": ["a@b.c"], "subject": "Hi", "body": "A short note."})
    assert r.returncode == 0, r.stderr


def test_hook_refuses_an_ai_shaped_send_in_an_instance_without_q_consult(tmp_path):
    root = _stub_engine(tmp_path / "e", _result(hard=["banned-word: 'leverage'"]))
    r = _fire(tmp_path, root, {"to": ["a@b.c"], "subject": "Hi", "body": AI_SHAPED})
    assert r.returncode == 2 and "REFUSE" in r.stderr, (r.returncode, r.stderr)


def test_hook_refuses_a_forced_outage(tmp_path):
    parts = {"hard-rows": {"ran": 1, "of": 1}, "authorship": {"ran": 0, "of": 1}}
    root = _stub_engine(tmp_path / "e", _result(parts=parts))
    r = _fire(tmp_path, root, {"to": ["a@b.c"], "subject": "Hi", "body": "A short note."})
    assert r.returncode == 2 and "OUTAGE" in r.stderr, (r.returncode, r.stderr)


def test_hook_refuses_when_the_engine_is_absent(tmp_path):
    r = _fire(tmp_path, tmp_path / "no-engine", {"subject": "Hi", "body": "A short note."})
    assert r.returncode == 2


def test_hook_refuses_a_draft_id_send(tmp_path):
    root = _stub_engine(tmp_path / "e", _result())
    r = _fire(tmp_path, root, {"draftId": "r-123"})
    assert r.returncode == 2 and "draftId" in r.stderr


def test_hook_ignores_a_tool_that_does_not_send(tmp_path):
    root = _stub_engine(tmp_path / "e", _result(hard=["x"]))
    r = _fire(tmp_path, root, {"query": "x"}, tool="mcp__claude_ai_Gmail__search_threads")
    assert r.returncode == 0


# ---- PR #859 round 1: unclassified tools, override, log, TTL ---------------------------

def test_an_unclassified_gmail_tool_is_refused_not_passed(tmp_path):
    root = _stub_engine(tmp_path / "e", _result())
    r = _fire(tmp_path, root, {"body": "x"}, tool="mcp__claude_ai_Gmail__send_message_v2")
    assert r.returncode == 2 and "not classified" in r.stderr, (r.returncode, r.stderr)


def test_every_known_non_sending_gmail_tool_passes(tmp_path):
    root = _stub_engine(tmp_path / "e", _result(hard=["x"]))
    for i, tool in enumerate(sorted(vsc.NON_SENDING_GMAIL)[:3]):
        assert _fire(tmp_path / str(i), root, {"q": "x"}, tool=tool).returncode == 0, tool


def test_the_matcher_reaches_every_gmail_tool_name():
    matcher, _ = _send_hook_command()
    for tool in list(vsc.SEND_TOOLS) + sorted(vsc.NON_SENDING_GMAIL) + [vsc.GMAIL_PREFIX + "brand_new"]:
        assert re.fullmatch(matcher, tool), tool


def test_report_mode_passes_and_logs_but_the_default_refuses(tmp_path):
    root = _stub_engine(tmp_path / "e", _result(hard=["banned-word: 'x'"]))
    log = tmp_path / "send-log.jsonl"
    os.environ["KIPI_VOICE_SEND_LOG"] = str(log)
    try:
        refused = _fire(tmp_path / "a", root, {"subject": "s", "body": "A note."})
        os.environ["KIPI_VOICE_SEND_MODE"] = "report"
        passed = _fire(tmp_path / "b", root, {"subject": "s", "body": "A note."})
    finally:
        os.environ.pop("KIPI_VOICE_SEND_MODE", None)
        os.environ.pop("KIPI_VOICE_SEND_LOG", None)
    assert refused.returncode == 2 and passed.returncode == 0
    rows = [json.loads(x) for x in log.read_text().splitlines()]
    assert [r["decision"] for r in rows] == ["refuse", "report-only-pass"], rows


def test_an_expired_receipt_is_not_spent(tmp_path):
    clean = _stub_engine(tmp_path / "a", _result())
    r = tmp_path / "r"
    vsc.send_check("A short note.", "client-email", receipts_dir=r, engine_root=clean)
    f = next(r.glob("*.json"))
    rec = json.loads(f.read_text())
    rec["ts"] = 0
    f.write_text(json.dumps(rec))
    dirty = _stub_engine(tmp_path / "b", _result(hard=["x"]))
    assert vsc.send_check("A short note.", "client-email", receipts_dir=r,
                          engine_root=dirty).verdict == "REFUSE"


# ---- live: the real engine, the real outage lever ------------------------------------

LIVE = os.environ.get("KIPI_FULL_GATE_LIVE") == "1"
ENGINE = Path.home() / "projects" / "consulting" / "q-consult"


@pytest.mark.skipif(not (LIVE and (ENGINE / "pipeline" / "gate_draft.py").is_file()),
                    reason="live proof: set KIPI_FULL_GATE_LIVE=1 with the consulting checkout present")
def test_live_ai_shaped_send_refused_and_forced_authorship_outage_refused(tmp_path):
    inst_env = {"KIPI_USAGE_LEDGER": str(tmp_path / "usage.jsonl"),
                "KIPI_MODEL_GATE_DIR": str(tmp_path / "gate")}
    os.environ.update(inst_env)
    r = _fire(tmp_path / "a", ENGINE, {"subject": "Update", "body": AI_SHAPED})
    assert r.returncode == 2 and "REFUSE" in r.stderr, r.stderr[-600:]
    os.environ["KIPI_LUAR_MIN_FREE_GB"] = "1000000"
    try:
        r2 = _fire(tmp_path / "b", ENGINE, {"subject": "Update", "body": "Short plain note."})
    finally:
        os.environ.pop("KIPI_LUAR_MIN_FREE_GB", None)
    # Refused for the outage: authorship ran 0 and is listed as an outage. The verdict word may
    # be REFUSE or OUTAGE depending on whether a short note also trips a band row (it did, live);
    # what matters is that a part that ran 0 is on the record and the send is refused.
    verdict = json.loads(r2.stderr[r2.stderr.index("{"):])
    assert r2.returncode == 2 and verdict["parts"]["authorship"]["ran"] == 0, r2.stderr[-600:]
    assert any(o[1] == "authorship" for o in verdict["outages"]), verdict["outages"]
