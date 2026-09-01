#!/usr/bin/env python3
"""notion_board.py -- the Notion morning board (plan item 2m, founder-liked:
Bloom's one board, three buckets, an agent narrows into it).

A registered optional section of morning-brief.py (stem "notion_board", key
"board"). The brief calls `collect(now, sources)` behind its guard, BEFORE the
Slack send, inside a bounded budget (Codex finding-4 on the PRD: a board
written after the send could never report its state in the message the
founder reads). The result is one row in the brief:

    board: written, read-back ok
    COULD NOT READ: board timed out (20.0s)
    COULD NOT READ: board failed (HTTPError)

Three buckets on one Notion page, as heading_2 blocks: "Top of mind",
"This week", "Inbox". This module rewrites ONLY the bullets under "Top of mind"
with the same three owed items and withheld count the Slack brief shows, then
reads the page back and reports agreement. It never touches the other two
buckets (a-write-only-integration-cannot-report-state: the read-back is the
only proof the write landed).

Credentials: ~/.config/kipi/notion-token and ~/.config/kipi/notion-board-page,
both founder-created (decision 2026-09-01), resolved via Path.home(), never a
literal home path (kipi-push-upstream's content tripwire refuses one). A
missing page-id file is the OFF switch: collect() returns None and the brief
renders no board section at all. This is the second Notion REST writer in the
fleet; the first (consulting's board_sync.py) is partitioned by token and
parent page, and this file never reads the consulting token's environment
variable nor names an ASK page (test_notion_board.py greps for both).

Under pytest, collect() refuses to reach the network unless an opener is
injected, the same chokepoint slack_founder.deliver has.
"""
from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request
from pathlib import Path

STATE_DIR = Path(os.environ.get("KIPI_STATE_DIR", str(Path.home() / ".config" / "kipi")))
TOKEN_FILE = STATE_DIR / "notion-token"
PAGE_FILE = STATE_DIR / "notion-board-page"
NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
BUCKETS = ("Top of mind", "This week", "Inbox")
TOP = BUCKETS[0]
BUDGET_S = 20.0
HTTP_TIMEOUT = 10


class NotionError(RuntimeError):
    pass


def _default_opener(req, timeout):
    return urllib.request.urlopen(req, timeout=timeout)


def _request(token: str, method: str, path: str, body=None, opener=None, timeout=HTTP_TIMEOUT) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(NOTION_API + path, data=data, method=method, headers={
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    })
    opener = opener or _default_opener
    try:
        with opener(req, timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raise NotionError(f"HTTP {exc.code} on {method} {path}") from exc
    try:
        answer = json.loads(raw) if raw else {}
    except ValueError as exc:
        raise NotionError(f"unparseable Notion answer on {method} {path}") from exc
    if answer.get("object") == "error":
        raise NotionError(f"{answer.get('code', 'error')} on {method} {path}")
    return answer


def _text(block: dict) -> str:
    kind = block.get("type", "")
    rich = (block.get(kind) or {}).get("rich_text") or []
    return "".join(r.get("plain_text") or (r.get("text") or {}).get("content", "") for r in rich).strip()


def read_page(token: str, page_id: str, opener=None, timeout=HTTP_TIMEOUT) -> list:
    """Every child block of the page, paginated."""
    blocks, cursor = [], None
    while True:
        path = f"/blocks/{page_id}/children?page_size=100" + (f"&start_cursor={cursor}" if cursor else "")
        answer = _request(token, "GET", path, opener=opener, timeout=timeout)
        blocks += answer.get("results") or []
        if not answer.get("has_more"):
            return blocks
        cursor = answer.get("next_cursor")


def parse_buckets(blocks: list) -> dict:
    """{bucket: {"heading_id": id|None, "items": [(block_id, text), ...]}}"""
    out = {b: {"heading_id": None, "items": []} for b in BUCKETS}
    current = None
    for blk in blocks:
        kind = blk.get("type")
        if kind in ("heading_1", "heading_2", "heading_3"):
            title = _text(blk)
            current = title if title in out else None
            if current:
                out[current]["heading_id"] = blk.get("id")
        elif kind == "bulleted_list_item" and current:
            out[current]["items"].append((blk.get("id"), _text(blk)))
    return out


def _bullet(text: str) -> dict:
    return {"object": "block", "type": "bulleted_list_item",
            "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": text[:2000]}}]}}


def _heading(text: str) -> dict:
    return {"object": "block", "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": text}}]}}


def write_top_of_mind(token: str, page_id: str, lines: list, opener=None, timeout=HTTP_TIMEOUT) -> None:
    """Rewrite ONLY the bullets under "Top of mind". Missing headings are
    created (all three, in order) so a fresh page becomes the board."""
    buckets = parse_buckets(read_page(token, page_id, opener, timeout))
    if any(buckets[b]["heading_id"] is None for b in BUCKETS):
        missing = [_heading(b) for b in BUCKETS if buckets[b]["heading_id"] is None]
        _request(token, "PATCH", f"/blocks/{page_id}/children", {"children": missing}, opener, timeout)
        buckets = parse_buckets(read_page(token, page_id, opener, timeout))
    for block_id, _ in buckets[TOP]["items"]:
        _request(token, "DELETE", f"/blocks/{block_id}", opener=opener, timeout=timeout)
    if lines:
        _request(token, "PATCH", f"/blocks/{page_id}/children",
                 {"children": [_bullet(l) for l in lines], "after": buckets[TOP]["heading_id"]},
                 opener, timeout)


def read_back(token: str, page_id: str, opener=None, timeout=HTTP_TIMEOUT) -> list:
    return [t for _, t in parse_buckets(read_page(token, page_id, opener, timeout))[TOP]["items"]]


def top_of_mind_lines(owed_rows: list) -> list:
    """The SAME three items and withheld count the Slack brief shows: lead rows
    (never the counted tail in parentheses), then the withheld line."""
    leads = [r for r in owed_rows if not r.startswith("(") and not r.startswith("withheld")]
    withheld = [r for r in owed_rows if r.startswith("withheld")]
    return leads[:3] + withheld[:1]


def _credentials(token_file=None, page_file=None):
    tf = Path(token_file) if token_file else TOKEN_FILE
    pf = Path(page_file) if page_file else PAGE_FILE
    if not pf.is_file():
        return None, None  # OFF: no page configured, no section
    page_id = pf.read_text(encoding="utf-8").strip()
    if not tf.is_file():
        raise NotionError("notion-token missing")
    return tf.read_text(encoding="utf-8").strip(), page_id


def _bounded(fn, budget_s: float):
    box: dict = {}

    def run():
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001
            box["exc"] = exc

    worker = threading.Thread(target=run, name="notion-board", daemon=True)
    worker.start()
    worker.join(timeout=budget_s)
    if worker.is_alive():
        raise TimeoutError(f"board timed out ({budget_s}s)")
    if "exc" in box:
        raise box["exc"]
    return box.get("value")


def collect(now, sources: dict, opener=None, budget_s: float = BUDGET_S,
            token_file=None, page_file=None):
    """Registry contract: (rows, error), or None when the board is OFF.

    Raises on failure so the brief's guard renders COULD NOT READ with the
    exception TYPE only; the message goes to the local log."""
    token, page_id = _credentials(token_file, page_file)
    if page_id is None:
        return None
    if opener is None and os.environ.get("PYTEST_CURRENT_TEST"):
        return [], "refused: running under pytest; the live board is never written by a test"
    owed_rows, owed_err = sources.get("owed", ([], "owed not collected"))
    if owed_err:
        return [], f"owed section unreadable, board not rewritten ({owed_err})"
    lines = top_of_mind_lines(owed_rows)

    def work():
        write_top_of_mind(token, page_id, lines, opener)
        return read_back(token, page_id, opener)

    seen = _bounded(work, budget_s)
    if seen != lines:
        return [], f"read-back mismatch: wrote {len(lines)} line(s), page shows {len(seen)}"
    return [f"board: written, read-back ok ({len(lines)} line(s))"], None
