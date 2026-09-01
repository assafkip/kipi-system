#!/usr/bin/env python3
"""RED FIRST. Issue mbl-roadmap-scope-classifier (prd-morning-brief-learns,
finding-1): the product/roadmap boundary was going to trust the friction
author's declared target, so a product proposal labelled `target=rule` would
have passed. This suite was written and seen to fail before roadmap_scope.py
existed (ImportError on the loader's explicit assertion).

The module is ONE deterministic classifier shared by every consumer
(friction-note.sh, weekly-improve.py, improve_ground.py). No LLM, no network.
`unknown` is a refusal everywhere: fail closed.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
MODULE = SCRIPTS / "roadmap_scope.py"


@pytest.fixture(scope="module")
def scope():
    assert MODULE.is_file(), f"missing script: {MODULE}"
    spec = importlib.util.spec_from_file_location("roadmap_scope", MODULE)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["roadmap_scope"] = mod
    spec.loader.exec_module(mod)
    return mod


# --- the exact bypass finding-1 names -------------------------------------

def test_product_proposal_labelled_rule_is_roadmap(scope):
    out = scope.classify("we should sell the morning brief as a product to other founders",
                         "rule")
    assert out["verdict"] == "roadmap"
    assert out["matched"], "a roadmap verdict must say what it matched"


@pytest.mark.parametrize("text", [
    "charge $99 per seat for the board",
    "publish this as a LinkedIn post tomorrow",
    "tell the client they should move to Notion",
    "launch a paid tier for the weekly digest",
])
def test_roadmap_text_wins_over_a_system_target(scope, text):
    assert scope.classify(text, "lint")["verdict"] == "roadmap", text


# --- fail closed -----------------------------------------------------------

def test_empty_text_is_unknown_not_system(scope):
    assert scope.classify("", "rule")["verdict"] == "unknown"
    assert scope.classify("   ", "rule")["verdict"] == "unknown"


def test_unrecognised_target_is_unknown_fail_closed(scope):
    out = scope.classify("the brief lists Sana's tickets as mine, change the owner rule", "vibes")
    assert out["verdict"] == "unknown"


def test_missing_target_is_unknown(scope):
    assert scope.classify("the brief lists Sana's tickets as mine", None)["verdict"] == "unknown"
    assert scope.classify("the brief lists Sana's tickets as mine", "")["verdict"] == "unknown"


def test_missing_target_with_roadmap_text_is_roadmap_not_unknown(scope):
    """The text is evidence on its own; a missing target must not hide it.
    Both verdicts are refusals for consumers, but the ledger keeps the reason."""
    out = scope.classify("sell the brief as a product", None)
    assert out["verdict"] == "roadmap" and out["matched"]


# --- system proposals pass ---------------------------------------------------

@pytest.mark.parametrize("text,target", [
    ("the brief lists Sana's tickets as mine, change the owner rule", "rule"),
    ("voice-lint should catch the rule-of-three in comments too", "lint"),
    ("route-overrides-to-learn.py has no plist, give it a weekly trigger", "trigger"),
    ("add Widgetcorp to the canonical glossary", "context"),
    ("the improve skill should print which corpora it read", "skill"),
])
def test_system_proposals_are_system(scope, text, target):
    out = scope.classify(text, target)
    assert out["verdict"] == "system", (text, out)


def test_roadmap_target_is_roadmap_even_with_bland_text(scope):
    assert scope.classify("tweak the wording", "product")["verdict"] == "roadmap"
    assert scope.classify("tweak the wording", "pricing")["verdict"] == "roadmap"


# --- the module is the ONLY home of the patterns, and it is offline ----------

def test_patterns_live_in_the_module_and_it_is_offline(scope):
    for name in ("PRODUCT", "PRICING", "PUBLISH", "CLIENT_ADVICE"):
        assert name in scope.ROADMAP_PATTERNS, name
    src = MODULE.read_text(encoding="utf-8")
    for banned in ("urllib", "requests", "http.client", "socket", "claude -p", "subprocess"):
        assert banned not in src, f"classifier must be offline and deterministic: {banned}"


def test_cli_exit_codes_system_roadmap_unknown():
    def run(target, text):
        return subprocess.run([sys.executable, str(MODULE), "--target", target, text],
                              capture_output=True, text=True)
    assert run("rule", "change the owner rule in the brief").returncode == 0
    assert run("rule", "sell the brief as a product").returncode == 2
    assert run("vibes", "change the owner rule").returncode == 3
    out = run("rule", "sell the brief as a product")
    assert json.loads(out.stdout)["verdict"] == "roadmap"


def test_cli_reads_text_from_stdin_when_no_positional():
    r = subprocess.run([sys.executable, str(MODULE), "--target", "rule"],
                       input="sell the brief as a product", capture_output=True, text=True)
    assert r.returncode == 2
