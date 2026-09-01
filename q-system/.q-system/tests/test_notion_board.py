#!/usr/bin/env python3
"""RED FIRST. Issue mbl-board-section-bounded (prd-morning-brief-learns,
Codex finding-4). Every Notion call goes through an injected opener that
serves an in-memory page; nothing here reaches api.notion.com, and the live
path is refused under pytest (asserted). Credentials come from tmp_path files,
never ~/.config/kipi.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import io
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
MODULE = SCRIPTS / "notion_board.py"
NOW = dt.datetime(2026, 9, 8, 7, 0, tzinfo=dt.timezone.utc)
OWED = ["ASK-830  reviewer status", "DUE 2026-08-10  ASK-445  re-review", "loop captoken-pr  PR to guardrails",
        "withheld 1 more: 0 in Linear, 1 in open-loops", "(49 more assigned to you but labelled owner:sana)"]


@pytest.fixture(scope="module")
def board():
    assert MODULE.is_file(), f"missing: {MODULE}"
    spec = importlib.util.spec_from_file_location("notion_board", MODULE)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class FakeNotion:
    """A page of blocks behind the opener seam. Records every request."""

    def __init__(self, blocks=None, page_id="page-1"):
        self.page_id = page_id
        self.blocks = list(blocks or [])
        self.calls = []
        self.n = 0

    def _resp(self, payload):
        return io.BytesIO(json.dumps(payload).encode())

    def __call__(self, req, timeout):
        method, url = req.get_method(), req.full_url
        body = json.loads(req.data) if req.data else None
        self.calls.append((method, url, body))
        assert req.get_header("Notion-version") == "2022-06-28"
        if method == "GET" and f"/blocks/{self.page_id}/children" in url:
            return self._resp({"results": self.blocks, "has_more": False})
        if method == "PATCH" and f"/blocks/{self.page_id}/children" in url:
            new = []
            for child in body["children"]:
                self.n += 1
                blk = dict(child, id=f"b{self.n}")
                new.append(blk)
            after = body.get("after")
            if after:
                idx = next(i for i, b in enumerate(self.blocks) if b["id"] == after) + 1
                self.blocks[idx:idx] = new
            else:
                self.blocks += new
            return self._resp({"results": new})
        if method == "DELETE":
            bid = url.rsplit("/", 1)[1]
            self.blocks = [b for b in self.blocks if b["id"] != bid]
            return self._resp({"object": "block", "id": bid, "archived": True})
        raise AssertionError(f"unexpected {method} {url}")

    def text_under(self, heading):
        out, cur = [], None
        for b in self.blocks:
            if b["type"] == "heading_2":
                cur = b["heading_2"]["rich_text"][0]["text"]["content"]
            elif b["type"] == "bulleted_list_item" and cur == heading:
                out.append(b["bulleted_list_item"]["rich_text"][0]["text"]["content"])
        return out


def _h(text, bid):
    return {"object": "block", "id": bid, "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": text}, "plain_text": text}]}}


def _b(text, bid):
    return {"object": "block", "id": bid, "type": "bulleted_list_item",
            "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": text}, "plain_text": text}]}}


def _creds(tmp_path, page="page-1"):
    (tmp_path / "notion-token").write_text("secret-token")
    (tmp_path / "notion-board-page").write_text(page)
    return {"token_file": tmp_path / "notion-token", "page_file": tmp_path / "notion-board-page"}


def test_write_then_read_back_agree_on_three_items_and_the_count(board, tmp_path):
    fake = FakeNotion([_h("Top of mind", "h1"), _b("stale one", "s1"), _h("This week", "h2"), _b("keep me", "k1"), _h("Inbox", "h3")])
    rows, error = board.collect(NOW, {"owed": (OWED, None)}, opener=fake, **_creds(tmp_path))
    assert error is None and rows == ["board: written, read-back ok"], "the exact row the acceptance names"
    assert fake.text_under("Top of mind") == board.top_of_mind_lines(OWED)  # three items + count, with id suffixes
    assert fake.text_under("This week") == ["keep me"], "another bucket was touched"
    assert "stale one" not in fake.text_under("Top of mind")


def test_fresh_page_gets_its_three_headings(board, tmp_path):
    fake = FakeNotion([])
    rows, error = board.collect(NOW, {"owed": (OWED, None)}, opener=fake, **_creds(tmp_path))
    assert error is None
    assert [b["heading_2"]["rich_text"][0]["text"]["content"] for b in fake.blocks if b["type"] == "heading_2"] == list(board.BUCKETS)
    assert fake.text_under("Top of mind") == board.top_of_mind_lines(OWED)  # three items + count, with id suffixes


def test_an_opener_past_the_budget_is_a_timeout(board, tmp_path):
    def slow(req, timeout):
        time.sleep(0.5)
        return io.BytesIO(b'{"results": [], "has_more": false}')
    with pytest.raises(TimeoutError, match=r"board timed out \(0.05s\)"):
        board.collect(NOW, {"owed": (OWED, None)}, opener=slow, budget_s=0.05, **_creds(tmp_path))


def test_no_write_lands_after_the_timeout_was_reported(board, tmp_path):
    """Codex standard finding on this issue: abandoning the thread bounded the
    wait, not the writes. After the timeout, the worker must refuse its next
    request, so no DELETE or PATCH can land behind the brief's back."""
    class SlowFirstRead(FakeNotion):
        def __call__(self, req, timeout):
            if req.get_method() == "GET" and len(self.calls) == 0:
                self.calls.append(("GET-slow", req.full_url, None))
                time.sleep(0.15)  # past the budget
                return self._resp({"results": self.blocks, "has_more": False})
            return super().__call__(req, timeout)
    fake = SlowFirstRead([_h("Top of mind", "h1"), _b("stale one", "s1"), _h("This week", "h2"), _h("Inbox", "h3")])
    with pytest.raises(TimeoutError):
        board.collect(NOW, {"owed": (OWED, None)}, opener=fake, budget_s=0.05, **_creds(tmp_path))
    time.sleep(0.4)  # let the abandoned worker run on and try to write
    writes = [c for c in fake.calls if c[0] in ("DELETE", "PATCH")]
    assert writes == [], f"writes landed after the timeout: {writes}"
    assert fake.text_under("Top of mind") == ["stale one"], "the page changed after the brief said timed out"


def test_pytest_refuses_the_live_path_without_an_injected_opener(board, tmp_path):
    rows, error = board.collect(NOW, {"owed": (OWED, None)}, opener=None, **_creds(tmp_path))
    assert rows == [] and "refused" in error and "pytest" in error


def test_missing_page_file_means_off_and_no_network(board, tmp_path):
    fake = FakeNotion([])
    (tmp_path / "notion-token").write_text("secret-token")
    out = board.collect(NOW, {"owed": (OWED, None)}, opener=fake,
                        token_file=tmp_path / "notion-token", page_file=tmp_path / "absent")
    assert out is None and fake.calls == []


def test_missing_token_with_a_page_is_a_failure_not_off(board, tmp_path):
    (tmp_path / "notion-board-page").write_text("page-1")
    with pytest.raises(board.NotionError, match="notion-token missing"):
        board.collect(NOW, {"owed": (OWED, None)}, opener=FakeNotion(),
                      token_file=tmp_path / "absent", page_file=tmp_path / "notion-board-page")


def test_unreadable_owed_means_no_rewrite(board, tmp_path):
    fake = FakeNotion([_h("Top of mind", "h1"), _b("yesterday", "y1")])
    rows, error = board.collect(NOW, {"owed": ([], "linear 403")}, opener=fake, **_creds(tmp_path))
    assert rows == [] and "not rewritten" in error
    assert fake.text_under("Top of mind") == ["yesterday"] and all(m == "GET" for m, _, _ in fake.calls) or fake.calls == []


def test_read_back_mismatch_is_reported(board, tmp_path):
    class Lossy(FakeNotion):
        def __call__(self, req, timeout):
            if req.get_method() == "PATCH" and req.data and "after" in json.loads(req.data):
                self.calls.append(("PATCH-dropped", req.full_url, None))
                return self._resp({"results": []})  # the write silently did not land
            return super().__call__(req, timeout)
    fake = Lossy([_h("Top of mind", "h1"), _h("This week", "h2"), _h("Inbox", "h3")])
    rows, error = board.collect(NOW, {"owed": (OWED, None)}, opener=fake, **_creds(tmp_path))
    assert rows == [] and "read-back mismatch" in error


# --- issue mbl-board-item-identity (Codex finding-5): stable ids, moved stays moved

def test_item_lines_carry_a_stable_id_suffix(board):
    lines = board.top_of_mind_lines(OWED)
    assert lines[0].endswith("[ASK-830]") and lines[1].endswith("[ASK-445]")
    assert lines[2].endswith("[loop captoken-pr]")
    assert lines[3].startswith("withheld") and "[" not in lines[3]
    assert board.item_id("DUE 2026-08-10  ASK-445  re-review") == "ASK-445"
    assert board.item_id("loop captoken-pr  PR to guardrails") == "loop captoken-pr"
    assert board.item_id("withheld 1 more: 0 in Linear, 1 in open-loops") is None


def test_moved_stays_moved(board, tmp_path):
    """Yesterday the founder dragged ASK-445 to 'This week'. Today's owed rows
    still include it. The rewrite must not drag it back."""
    fake = FakeNotion([_h("Top of mind", "h1"), _b("old [ASK-830]", "o1"),
                       _h("This week", "h2"), _b("re-review [ASK-445]", "w1"), _h("Inbox", "h3")])
    rows, error = board.collect(NOW, {"owed": (OWED, None)}, opener=fake, **_creds(tmp_path))
    assert error is None and rows == ["board: written, read-back ok"]
    top = fake.text_under("Top of mind")
    assert not any("ASK-445" in t for t in top), top
    assert any("ASK-830" in t for t in top) and any("captoken-pr" in t for t in top)
    assert fake.text_under("This week") == ["re-review [ASK-445]"]


def test_every_lead_line_carries_an_id_even_without_a_recognisable_one(board):
    """Codex standard finding on this issue: a row with no ASK/loop id was
    written bare. Now it gets a stable content hash, stable across rewrites."""
    rows = ["DUE 2026-08-10  sign the lease renewal", "withheld 1 more: 1 in Linear, 0 in open-loops"]
    lines = board.top_of_mind_lines(rows)
    assert re.search(r"\[row-[0-9a-f]{8}\]$", lines[0]), lines
    assert board.item_id(lines[0]) == board.item_id(rows[0]), "the suffix must not change the id"
    assert "[" not in lines[1]


def test_an_id_anywhere_outside_top_of_mind_is_honoured(board, tmp_path):
    """Before the first heading, under a heading this module does not know, or
    as a bare identifier without brackets: all count as moved."""
    fake = FakeNotion([_b("parked: ASK-830 waits on legal", "p0"),
                       _h("Top of mind", "h1"),
                       _h("Someday", "hx"), _b("re-review [ASK-445]", "x1"),
                       _h("This week", "h2"), _h("Inbox", "h3")])
    rows, error = board.collect(NOW, {"owed": (OWED, None)}, opener=fake, **_creds(tmp_path))
    assert error is None
    top = fake.text_under("Top of mind")
    assert not any("ASK-830" in t or "ASK-445" in t for t in top), top
    assert any("captoken-pr" in t for t in top)


def test_only_top_of_mind_blocks_are_ever_deleted_or_appended(board, tmp_path):
    fake = FakeNotion([_h("Top of mind", "h1"), _b("old [ASK-830]", "o1"),
                       _h("This week", "h2"), _b("keep [ASK-445]", "w1"),
                       _h("Inbox", "h3"), _b("inbox item", "i1")])
    board.collect(NOW, {"owed": (OWED, None)}, opener=fake, **_creds(tmp_path))
    deleted = [url.rsplit("/", 1)[1] for m, url, _ in fake.calls if m == "DELETE"]
    assert deleted == ["o1"], deleted
    appends = [body for m, _, body in fake.calls if m == "PATCH"]
    assert all(body.get("after") == "h1" for body in appends), appends


def test_the_page_is_read_once_before_writing(board, tmp_path):
    fake = FakeNotion([_h("Top of mind", "h1"), _h("This week", "h2"), _h("Inbox", "h3")])
    board.collect(NOW, {"owed": (OWED, None)}, opener=fake, **_creds(tmp_path))
    gets = [m for m, _, _ in fake.calls if m == "GET"]
    assert len(gets) == 2, f"one read to reconcile, one to read back; got {len(gets)}"


def test_never_ask_token_never_ask_page_never_home_literal(board):
    src = MODULE.read_text(encoding="utf-8")
    assert "NOTION_TOKEN_ASK" not in src
    assert "314bf98c" not in src and "3b1bf98c" not in src, "an ASK page or database id is named"
    assert "/Users/" not in src
    assert "Path.home()" in src


def test_this_file_runs_its_own_tests_under_python3():
    import os
    if os.environ.get("KIPI_SELFTEST_INNER"):
        pytest.skip("inner run")
    env = dict(os.environ, KIPI_SELFTEST_INNER="1")
    ok = subprocess.run([sys.executable, __file__], capture_output=True, text=True, env=env)
    assert ok.returncode == 0 and "passed" in ok.stdout, ok.stdout[-600:]
    none = subprocess.run([sys.executable, __file__, "-k", "no_such_test_zzz"], capture_output=True, text=True, env=env)
    assert none.returncode != 0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", *sys.argv[1:]]))
