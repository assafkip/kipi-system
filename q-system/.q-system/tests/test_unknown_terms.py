#!/usr/bin/env python3
"""RED FIRST. Issue mbl-unknown-term-detector (prd-morning-brief-learns,
Codex finding-13). The detector is a registered optional section of the
morning brief; this suite proves precision on a planted fixture, purity (no
network, no second pull), and the registry contract. It never touches
q-system/canonical/ (a tmp copy of the fixture's canonical text stands in).
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
MODULE = SCRIPTS / "unknown_terms.py"
FIXTURE = HERE / "fixtures" / "unknown_terms_precision.json"
NOW = dt.datetime(2026, 9, 8, 7, 0, tzinfo=dt.timezone.utc)


@pytest.fixture(scope="module")
def mod():
    assert MODULE.is_file(), f"missing: {MODULE}"
    spec = importlib.util.spec_from_file_location("unknown_terms", MODULE)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def fixture():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert len(data["planted_unknowns"]) == 5 and len(data["planted_decoys"]) == 10
    return data


def _canonical(tmp_path, text):
    d = tmp_path / "canonical"
    d.mkdir()
    (d / "decisions.md").write_text(text, encoding="utf-8")
    return d


def _sources(fx):
    return {"calendar": (fx["calendar_rows"], None), "mail": (fx["mail_rows"], None),
            "owed": ([], None), "overnight": ([], None)}


def test_precision_at_least_four_of_five_and_zero_decoys(mod, fixture, tmp_path):
    canon = _canonical(tmp_path, fixture["canonical_text"])
    rows, error = mod.collect(NOW, _sources(fixture), canonical_dir=canon, texts=fixture["texts"])
    assert error is None
    found = set(rows)
    hits = found & set(fixture["planted_unknowns"])
    assert len(hits) >= 4, f"only {sorted(hits)} of the planted unknowns surfaced; got {rows}"
    leaked = found & set(fixture["planted_decoys"])
    assert not leaked, f"decoys surfaced: {sorted(leaked)}"


def test_cap_is_five(mod, tmp_path):
    canon = _canonical(tmp_path, "nothing here\n")
    rows = [f"09:00  Meet Alphax{i} and Betax{i} today (Assaf)" for i in range(6)]
    out, err = mod.collect(NOW, {"calendar": (rows, None), "mail": ([], None)}, canonical_dir=canon)
    assert err is None and len(out) == mod.CAP == 5


def test_a_term_present_in_canonical_is_not_unknown(mod, tmp_path):
    canon = _canonical(tmp_path, "We work with Brightspeed weekly.\n")
    # Both terms MID-sentence: a sentence-initial term is dropped by a different
    # rule, and a test that put Brightspeed first passed with the vocabulary
    # check deleted (mutation survivor, 2026-09-01).
    src = {"calendar": (["09:00  Pilot kickoff with Brightspeed and Zephyrine (Assaf)"], None), "mail": ([], None)}
    out, _ = mod.collect(NOW, src, canonical_dir=canon)
    assert "Brightspeed" not in out and "Zephyrine" in out


def test_sentence_initial_word_is_dropped_unless_it_recurs(mod, tmp_path):
    canon = _canonical(tmp_path, "nothing\n")
    src = {"calendar": ([], None), "mail": (["Someone  Question about the export (1h)",
                                              "Someone  Re: the Hyperion export (1h)",
                                              "Someone  Hyperion again (1h)"], None)}
    out, _ = mod.collect(NOW, src, canonical_dir=canon)
    assert "Question" not in out and "Hyperion" in out


def test_sentence_initial_is_judged_per_sentence_not_per_fragment(mod, tmp_path):
    """Both Codex reviewers on this issue: only the fragment's first token was
    treated as sentence-initial."""
    canon = _canonical(tmp_path, "nothing\n")
    text = "We discussed it. Question remains open.\nNext steps tomorrow. The Zephyrine board is ready."
    out, _ = mod.collect(NOW, {"calendar": ([], None), "mail": ([], None)}, canonical_dir=canon, texts=[text])
    assert "Question" not in out and "Next" not in out and "We" not in out
    assert "Zephyrine" in out


def test_colon_is_not_a_sentence_boundary_and_greetings_and_acronyms_are_dropped(mod, tmp_path):
    canon = _canonical(tmp_path, "nothing\n")
    src = {"calendar": ([], None), "mail": (["Someone  Introduction: Quillfeather pilot (1h)",
                                              "Someone  Re: the SOW for Hyperion, again Hyperion (1h)"], None)}
    out, _ = mod.collect(NOW, src, canonical_dir=canon, texts=["Hi Assaf,\nThe Zephyrine board is ready."])
    assert "Quillfeather" in out, "a colon must not start a new sentence"
    assert "Assaf" not in out, "a greeting line names a person"
    assert "SOW" not in out and "Hyperion" in out and "Zephyrine" in out


def test_canonical_vocabulary_includes_nested_directories(mod, tmp_path):
    canon = _canonical(tmp_path, "nothing\n")
    (canon / "clients").mkdir()
    (canon / "clients" / "brightspeed.md").write_text("Brightspeed is a client.\n", encoding="utf-8")
    src = {"calendar": (["09:00  Pilot kickoff with Brightspeed and Zephyrine (Assaf)"], None), "mail": ([], None)}
    out, _ = mod.collect(NOW, src, canonical_dir=canon)
    assert "Brightspeed" not in out and "Zephyrine" in out


def test_attendees_and_senders_are_not_terms(mod, tmp_path):
    canon = _canonical(tmp_path, "nothing\n")
    src = {"calendar": (["09:00  Pilot kickoff (Assaf, Marta Kowalski)"], None),
           "mail": (["Dominic Reyes  Re: pilot kickoff (2h)"], None)}
    out, _ = mod.collect(NOW, src, canonical_dir=canon)
    for name in ("Assaf", "Marta", "Kowalski", "Dominic", "Reyes"):
        assert name not in out


def test_signature_block_is_stripped(mod, tmp_path):
    canon = _canonical(tmp_path, "nothing\n")
    text = "The Zephyrine board is live.\n--\nMarta Kowalski\nHead of Ops, Brightspeed"
    out, _ = mod.collect(NOW, {"calendar": ([], None), "mail": ([], None)}, canonical_dir=canon, texts=[text])
    assert "Zephyrine" in out and "Kowalski" not in out and "Brightspeed" not in out


def test_missing_inputs_are_an_error_not_an_empty_section(mod, tmp_path):
    canon = _canonical(tmp_path, "nothing\n")
    out, err = mod.collect(NOW, {"calendar": ([], None)}, canonical_dir=canon)
    assert out == [] and err and "mail" in err
    out2, err2 = mod.collect(NOW, {"calendar": ([], "boom"), "mail": ([], "boom")}, canonical_dir=canon)
    assert err2 and "unreadable" in err2


def test_module_is_pure_and_registered(mod):
    src = MODULE.read_text(encoding="utf-8")
    for banned in ("urllib", "requests", "http.client", "socket", "subprocess", "run_claude"):
        assert banned not in src, banned
    brief = (SCRIPTS / "morning-brief.py").read_text(encoding="utf-8")
    assert '("unknown_terms.py", "unknown_terms", "Terms I do not know")' in brief


def test_this_file_runs_its_own_tests_under_python3():
    r = subprocess.run([sys.executable, __file__, "-k", "no_such_test_zzz"], capture_output=True, text=True)
    assert r.returncode != 0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", *sys.argv[1:]]))
