#!/usr/bin/env python3
"""Pins the skeleton's ONE voice entry point, `voice_full_gate.py` (ASK-4969, ASK-4327).

What it must hold:
  (a) an AI-shaped paragraph is refused;
  (b) a required part that ran 0 refuses, also when the engine returns NO parts at all;
  (c) a forced authorship outage refuses;
  and the engine being absent, crashing, hanging or printing garbage refuses too. A judgment
  note alone does not refuse (RULE-2026-11-04-C).

TEST ISOLATION (fable-discipline). Two layers.
  - The STUB ENGINE tests run everywhere, CI included. The stub replaces only the
    engine's output (`pipeline.gate_draft.evaluate`) inside a temp dir. The refusal rule
    under test is the REAL one in this checkout. Nothing reads a live corpus or ledger.
  - The LIVE tests run the real consulting engine read-only, and only when it is present
    AND `KIPI_FULL_GATE_LIVE=1`: one run is about 70 s and makes critic model calls, so an
    unasked local suite must not spend that. Skips name the reason.

CONTROL FIRST: `test_clean_result_passes` is the verified-good control. Without it, every
refusal below could come from a wrapper that refuses everything.
"""
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
SCRIPT = REPO / "plugins" / "kipi-core" / "scripts" / "voice_full_gate.py"
sys.path.insert(0, str(SCRIPT.parent))

AI_SHAPED = (
    "In today's fast-paced digital landscape, it's crucial to leverage cutting-edge "
    "solutions. Moreover, organizations must navigate the ever-evolving complexities of "
    "threat intelligence. By embracing a holistic approach, teams can unlock unprecedented "
    "value and foster seamless collaboration across stakeholders. Ultimately, the journey "
    "toward resilience is not just a destination, it's a mindset."
)

ALL_RAN = {"hard-rows": {"ran": 1, "of": 1}, "repairs": {"ran": 1, "of": 1},
           "bands": {"ran": 1, "of": 1}, "authorship": {"ran": 1, "of": 1}}


def _stub_engine(tmp_path, result=None, body=None):
    """A temp engine root whose `pipeline.gate_draft.evaluate` returns `result`.

    `body` replaces the whole evaluate body, for the crash / hang / garbage cases."""
    root = tmp_path / "engine"
    (root / "pipeline").mkdir(parents=True)
    (root / "pipeline" / "__init__.py").write_text("")
    if body is None:
        body = "return json.loads(%r)" % json.dumps(result)
    (root / "pipeline" / "gate_draft.py").write_text(textwrap.dedent("""\
        import json, sys, time
        def evaluate(text, surface, source_text=None):
            {body}
        """).format(body=body))
    return root


def _gate():
    import voice_full_gate
    return voice_full_gate


def _result(**over):
    out = {"hard": [], "notes": [], "parts": dict(ALL_RAN), "outages": []}
    out.update(over)
    return out


# ---- the control ---------------------------------------------------------------------

def test_clean_result_passes(tmp_path):
    v = _gate().check("a post", "linkedin", engine_root=_stub_engine(tmp_path, _result()))
    assert v.verdict == "PASS" and v.ok, v.reasons


def test_judgment_note_alone_does_not_refuse(tmp_path):
    root = _stub_engine(tmp_path, _result(notes=["critic tells-a-story: warn"]))
    v = _gate().check("a post", "linkedin", engine_root=root)
    assert v.ok and v.notes == ["critic tells-a-story: warn"]


# ---- (a) a hard row refuses -----------------------------------------------------------

def test_hard_row_refuses(tmp_path):
    root = _stub_engine(tmp_path, _result(hard=["banned-word: banned word: 'leverage'"]))
    v = _gate().check(AI_SHAPED, "linkedin", engine_root=root)
    assert v.verdict == "REFUSE" and not v.ok
    assert any("banned-word" in r for r in v.reasons)


# ---- (b) a required part that ran 0 refuses (ASK-4327) --------------------------------

def test_required_part_ran_zero_refuses(tmp_path):
    parts = dict(ALL_RAN, critic={"ran": 0, "of": 15})
    v = _gate().check("a post", "linkedin", engine_root=_stub_engine(tmp_path, _result(parts=parts)))
    assert v.verdict == "OUTAGE" and not v.ok
    assert any("critic" in r and "ran 0" in r for r in v.reasons), v.reasons


def test_part_that_examined_nothing_refuses(tmp_path):
    """ran 0 of 0: a part with no units is a part that examined nothing, not a pass."""
    parts = dict(ALL_RAN, critic={"ran": 0, "of": 0})
    v = _gate().check("a post", "linkedin", engine_root=_stub_engine(tmp_path, _result(parts=parts)))
    assert not v.ok and v.verdict == "OUTAGE"


def test_no_required_parts_at_all_refuses(tmp_path):
    """An empty parts map is how an ungated surface or a manifest that did not load comes
    back from evaluate. Zero parts ran, so nothing was checked."""
    v = _gate().check("a post", "linkedin", engine_root=_stub_engine(tmp_path, _result(parts={})))
    assert not v.ok and v.verdict == "OUTAGE"


def test_outage_row_alone_refuses(tmp_path):
    v = _gate().check("a post", "linkedin", engine_root=_stub_engine(
        tmp_path, _result(outages=[["model", "critic", "no critic row returned a verdict"]])))
    assert not v.ok and v.verdict == "OUTAGE"


# ---- (c) a forced authorship outage refuses -------------------------------------------

def test_authorship_outage_refuses(tmp_path):
    parts = dict(ALL_RAN, authorship={"ran": 0, "of": 1})
    root = _stub_engine(tmp_path, _result(
        parts=parts, outages=[["machine", "authorship", "LUAR env could not be built"]]))
    v = _gate().check("a post", "linkedin", engine_root=root)
    assert v.verdict == "OUTAGE" and not v.ok
    assert any("authorship" in r for r in v.reasons)


# ---- the engine itself failing refuses ------------------------------------------------

def test_missing_engine_refuses(tmp_path):
    v = _gate().check("a post", "linkedin", engine_root=tmp_path / "nowhere")
    assert v.verdict == "OUTAGE" and not v.ok
    assert any("engine" in r for r in v.reasons)


def test_engine_crash_refuses(tmp_path):
    root = _stub_engine(tmp_path, body="raise RuntimeError('boom')")
    v = _gate().check("a post", "linkedin", engine_root=root)
    assert v.verdict == "OUTAGE" and not v.ok
    assert any("boom" in r for r in v.reasons), v.reasons


def test_engine_hang_refuses(tmp_path):
    root = _stub_engine(tmp_path, body="time.sleep(30)")
    v = _gate().check("a post", "linkedin", engine_root=root, timeout=2)
    assert v.verdict == "OUTAGE" and not v.ok
    assert any("timed out" in r for r in v.reasons)


def test_engine_garbage_refuses(tmp_path):
    root = _stub_engine(tmp_path, body="print('not json'); sys.exit(0)")
    v = _gate().check("a post", "linkedin", engine_root=root)
    assert v.verdict == "OUTAGE" and not v.ok


# ---- the CLI is the same function -----------------------------------------------------

def _cli(tmp_path, root, text="a post", *extra):
    draft = tmp_path / "draft.md"
    draft.write_text(text)
    return subprocess.run([sys.executable, str(SCRIPT), "--surface", "linkedin",
                           "--engine-root", str(root), str(draft), *extra],
                          capture_output=True, text=True, timeout=60)


def test_cli_pass_exits_0(tmp_path):
    out = _cli(tmp_path, _stub_engine(tmp_path, _result()))
    assert out.returncode == 0, out.stdout + out.stderr
    assert json.loads(out.stdout)["verdict"] == "PASS"


def test_cli_ran_zero_exits_2(tmp_path):
    parts = dict(ALL_RAN, authorship={"ran": 0, "of": 1})
    out = _cli(tmp_path, _stub_engine(tmp_path, _result(parts=parts)))
    assert out.returncode == 2
    assert json.loads(out.stdout)["verdict"] == "OUTAGE"


def test_cli_hard_exits_2(tmp_path):
    out = _cli(tmp_path, _stub_engine(tmp_path, _result(hard=["double-dash: --"])))
    assert out.returncode == 2
    assert json.loads(out.stdout)["verdict"] == "REFUSE"


# ---- live: the real engine, read-only, opt-in -----------------------------------------

def _live_root():
    if os.environ.get("KIPI_FULL_GATE_LIVE") != "1":
        pytest.skip("live engine run is opt-in: set KIPI_FULL_GATE_LIVE=1 (about 70 s, "
                    "critic model calls)")
    root = _gate().default_engine_root()
    if not (root / "pipeline" / "gate_draft.py").is_file():
        pytest.skip("the consulting engine is not on this machine (%s); CI has no sibling "
                    "repo" % root)
    return root


def _live_env():
    # The engine strips nothing for us: a model or env backend that keys off pytest must
    # see the run the founder's exits see.
    return {k: v for k, v in os.environ.items() if k != "PYTEST_CURRENT_TEST"}


def test_live_ai_shaped_paragraph_refused():
    root = _live_root()
    v = _gate().check(AI_SHAPED, "linkedin", engine_root=root, env=_live_env())
    assert not v.ok, v.reasons
    assert v.verdict == "REFUSE", v.reasons


def test_live_forced_authorship_outage_refused():
    root = _live_root()
    env = _live_env()
    # Force the declared LUAR env to refuse to build: it demands this much free disk first.
    env["KIPI_LUAR_MIN_FREE_GB"] = "1000000"
    env["KIPI_LUAR_CACHE_DIR"] = "/nonexistent-kipi-luar-cache"
    clean = "We shipped the parser on Tuesday. It broke on the first real file."
    v = _gate().check(clean, "linkedin", engine_root=root, env=env)
    assert not v.ok
    assert v.parts.get("authorship", {}).get("ran") == 0, (v.parts, v.reasons)
