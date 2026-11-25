"""The skeleton's default branch takes no unattended commit at all (ASK-4647, ASK-5583).

Scars: 89e9b619 "update prd-os ledgers" (ASK-4647) and then ffc287ff, cb9c8846,
170d0ecd ("content: add RCAs", "content: update canonical files", ASK-5583) landed
on the shared checkout's local main and were never pushed. Local main went ahead of
origin/main, so kipi-update.sh's provenance check refused every propagation and the
RCAs existed on one machine only. Holding only memory/ledgers (ASK-4647) moved the
drift to the next prefix, so the property is now on the branch, not on a path list.
"""
import importlib.util
import os

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "hooks", "auto-commit.py")
_spec = importlib.util.spec_from_file_location("auto_commit_hold", HOOK)
ac = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ac)

GROUPS = {("chore", "update prd-os ledgers"): [".prd-os/judgments-tip.json"],
          ("chore", "update session memory"): ["q-system/memory/x.json"],
          ("content", "update canonical files"): ["q-system/canonical/a.md"],
          ("content", "add RCAs"): ["q-system/output/rca/rca-x-2026-11-25.md"]}


def _copy():
    return {k: list(v) for k, v in GROUPS.items()}


class _Pager:
    def __init__(self):
        self.calls = []

    def __call__(self, paths):
        self.calls.append(list(paths))
        return True


def test_skeleton_main_commits_nothing(monkeypatch, tmp_path):
    monkeypatch.setenv("KIPI_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr(ac, "on_skeleton_default_branch", lambda: True)
    pager = _Pager()
    monkeypatch.setattr(ac, "page_held_content", pager)
    assert ac.hold_skeleton_default_branch(_copy()) == {}


def test_held_content_pages_sana_with_the_content_paths_only(monkeypatch, tmp_path):
    """Memory and ledgers are machine state; RCAs and canonical are work that has to
    reach origin, so those (and only those) go to Sana's queue to land by PR."""
    monkeypatch.setenv("KIPI_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr(ac, "on_skeleton_default_branch", lambda: True)
    pager = _Pager()
    monkeypatch.setattr(ac, "page_held_content", pager)
    ac.hold_skeleton_default_branch(_copy())
    assert pager.calls == [["q-system/canonical/a.md", "q-system/output/rca/rca-x-2026-11-25.md"]]


def test_only_memory_held_pages_nobody(monkeypatch, tmp_path):
    monkeypatch.setenv("KIPI_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr(ac, "on_skeleton_default_branch", lambda: True)
    pager = _Pager()
    monkeypatch.setattr(ac, "page_held_content", pager)
    ac.hold_skeleton_default_branch({("chore", "update session memory"): ["q-system/memory/x.json"]})
    assert pager.calls == []


def test_the_page_goes_out_once_per_held_set(monkeypatch, tmp_path):
    """The held files stay on disk, so every turn end re-derives the same hold.
    A page per turn is the report_skipped scar; once per held set is the contract."""
    monkeypatch.setenv("KIPI_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr(ac, "PROJ_DIR", str(tmp_path / "skel"))
    notify = tmp_path / "notify.sh"
    out = tmp_path / "pages.txt"
    notify.write_text(f'#!/bin/bash\necho "$1" >> {out}\n')
    monkeypatch.setenv("KIPI_AUTOCOMMIT_NOTIFY", str(notify))
    paths = ["q-system/output/rca/rca-x-2026-11-25.md"]
    assert ac.page_held_content(paths) is True
    assert ac.page_held_content(paths) is False
    assert out.read_text().count("\n") == 1
    assert "rca-x-2026-11-25.md" in out.read_text()
    # a new held set is a new event
    assert ac.page_held_content(paths + ["q-system/canonical/a.md"]) is True


def test_an_instance_or_feature_branch_still_commits_everything(monkeypatch):
    monkeypatch.setattr(ac, "on_skeleton_default_branch", lambda: False)
    assert ac.hold_skeleton_default_branch(_copy()) == GROUPS


def test_main_wires_the_hold():
    """The hold is only real if _commit_main calls it before committing."""
    src = open(HOOK, encoding="utf-8").read()
    body = src.split("def _commit_main", 1)[1].split("\ndef ", 1)[0]
    assert "hold_skeleton_default_branch(groups)" in body
    assert body.index("hold_skeleton_default_branch(groups)") < body.index("commit_group(")


def test_a_clean_tree_clears_the_held_marker_so_the_same_set_pages_again(monkeypatch, tmp_path):
    """PR #879 review round 2, major: the marker outlived the held set, so the same
    paths held a second time were never paged."""
    monkeypatch.setenv("KIPI_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr(ac, "PROJ_DIR", str(tmp_path / "skel"))
    notify = tmp_path / "notify.sh"
    out = tmp_path / "pages.txt"
    notify.write_text(f'#!/bin/bash\necho "$1" >> {out}\n')
    monkeypatch.setenv("KIPI_AUTOCOMMIT_NOTIFY", str(notify))
    paths = ["q-system/output/rca/rca-x-2026-11-25.md"]
    assert ac.page_held_content(paths) is True
    monkeypatch.setattr(ac, "is_remote_session", lambda: False)
    monkeypatch.setattr(ac, "fleet_update_in_progress", lambda: None)
    monkeypatch.setattr(ac, "another_commit_in_flight", lambda: None)
    monkeypatch.setattr(ac, "get_changed_files", lambda: set())
    monkeypatch.setattr(ac, "run", lambda cmd, **kw: type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})())
    ac._commit_main()
    assert ac.page_held_content(paths) is True


def test_a_refusal_on_skeleton_main_never_says_commit_it_yourself(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("KIPI_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr(ac, "page_refusal", lambda r: False)
    monkeypatch.setattr(ac, "on_skeleton_default_branch", lambda: True)
    ac.report_refusal([("q-system/canonical/decisions.md", "loses 198 lines")])
    text = capsys.readouterr().out
    assert "commit it yourself" not in text and "a PR" in text
    monkeypatch.setattr(ac, "on_skeleton_default_branch", lambda: False)
    ac.report_refusal([("q-system/canonical/decisions.md", "loses 198 lines")])
    assert "commit it yourself" in capsys.readouterr().out
