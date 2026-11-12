"""The skeleton's auto-commit leaves .prd-os ledgers uncommitted on main (ASK-4647).

Scar: 89e9b619 "update prd-os ledgers" landed on the shared checkout's main,
local main went ahead of origin/main, and propagation failed 3 nights running.
"""
import importlib.util
import os

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "hooks", "auto-commit.py")
_spec = importlib.util.spec_from_file_location("auto_commit_hold", HOOK)
ac = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ac)

GROUPS = {("chore", "update prd-os ledgers"): [".prd-os/judgments-tip.json"],
          ("chore", "update session memory"): ["q-system/memory/x.json"],
          ("content", "update canonical files"): ["q-system/canonical/a.md"]}


def test_skeleton_main_holds_prd_os_ledgers_and_memory(monkeypatch):
    monkeypatch.setattr(ac, "on_skeleton_default_branch", lambda: True)
    kept = ac.hold_skeleton_memory({k: list(v) for k, v in GROUPS.items()})
    assert kept == {("content", "update canonical files"): ["q-system/canonical/a.md"]}


def test_an_instance_or_feature_branch_still_commits_ledgers(monkeypatch):
    monkeypatch.setattr(ac, "on_skeleton_default_branch", lambda: False)
    kept = ac.hold_skeleton_memory({k: list(v) for k, v in GROUPS.items()})
    assert kept == GROUPS
