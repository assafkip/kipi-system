#!/usr/bin/env python3
"""RED FIRST. lessons_notion_sync.py mirrors the corpus into the founder's
Notion lessons database: upsert by corpus id, founder-owned columns never
overwritten, off without credentials, never live under pytest.

Every corpus here is tmp and every request goes to a fake opener.
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "scripts" / "lessons_notion_sync.py"


def _mod():
    spec = importlib.util.spec_from_file_location("lessons_notion_sync", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class FakeNotion:
    """A database of rows behind the opener seam. Records every request."""

    def __init__(self, rows=None):
        self.rows = dict(rows or {})  # corpus id -> page id
        self.calls = []
        self.n = 0

    def _resp(self, payload):
        return io.BytesIO(json.dumps(payload).encode())

    def __call__(self, req, timeout):
        method, url = req.get_method(), req.full_url
        body = json.loads(req.data) if req.data else None
        self.calls.append((method, url, body))
        assert req.get_header("Notion-version") == "2022-06-28"
        if method == "POST" and url.endswith("/query"):
            results = [{"id": pid, "properties": {"Id": {"rich_text": [{"plain_text": cid}]}}} for cid, pid in self.rows.items()]
            return self._resp({"results": results, "has_more": False})
        if method == "POST" and url.endswith("/pages"):
            self.n += 1
            cid = body["properties"]["Id"]["rich_text"][0]["text"]["content"]
            self.rows[cid] = f"page-{self.n}"
            return self._resp({"id": f"page-{self.n}"})
        if method == "PATCH" and "/pages/" in url:
            return self._resp({"id": url.rsplit("/", 1)[1]})
        raise AssertionError(f"unexpected {method} {url}")


def _corpus(tmp_path):
    d = tmp_path / "lessons"
    d.mkdir()
    (d / "README.md").write_text("# not a lesson\n")
    (d / "a-first-lesson.md").write_text("---\nid: a-first-lesson\nkind: pattern\ntitle: A first lesson\ndate: 2026-09-02\n---\n\nWhat happened in prd-lessons-rail-and-up-rail-2026-09-02.\n\nHow to apply:\n\n1. Do the thing this way.\n2. Then that.\n")
    (d / "b-second.md").write_text("---\nid: b-second\nkind: scar\ntitle: B second\ndate: 2026-08-01\n---\n\nAn older one from an rca-something-2026-08-01.\n")
    return d


def test_parse_reads_frontmatter_rule_and_provenance(tmp_path):
    m = _mod()
    lessons = m.corpus(_corpus(tmp_path))
    assert [l["id"] for l in lessons] == ["a-first-lesson", "b-second"], "README is not a lesson"
    a = lessons[0]
    assert a["title"] == "A first lesson" and a["kind"] == "pattern" and a["date"] == "2026-09-02"
    assert a["rule"] == "Do the thing this way." and a["came_from"] == "prd-lessons-rail-and-up-rail-2026-09-02" and a["origin"] == "build review"
    assert lessons[1]["origin"] == "rca" and lessons[1]["rule"] == ""


def test_first_sync_creates_a_row_per_lesson_with_status_in_corpus(tmp_path):
    m = _mod()
    fake = FakeNotion()
    report = m.sync("tok", "db1", m.corpus(_corpus(tmp_path)), opener=fake, out=lambda s: None)
    assert report == {"ok": True, "created": 2, "updated": 0, "total": 2}
    creates = [b for meth, url, b in fake.calls if meth == "POST" and url.endswith("/pages")]
    assert all(b["parent"] == {"database_id": "db1"} for b in creates)
    first = next(b for b in creates if b["properties"]["Id"]["rich_text"][0]["text"]["content"] == "a-first-lesson")
    assert first["properties"]["Status"]["select"]["name"] == "in corpus"
    assert first["properties"]["Origin"]["select"]["name"] == "build review"
    assert first["properties"]["Learned"]["date"]["start"] == "2026-09-02"
    assert first["properties"]["Rule"]["rich_text"][0]["text"]["content"] == "Do the thing this way."
    assert any("How to apply" in blk["paragraph"]["rich_text"][0]["text"]["content"] for blk in first["children"])


def test_second_sync_updates_and_never_touches_founder_columns(tmp_path):
    m = _mod()
    fake = FakeNotion({"a-first-lesson": "page-a"})
    report = m.sync("tok", "db1", m.corpus(_corpus(tmp_path)), opener=fake, out=lambda s: None)
    assert report["created"] == 1 and report["updated"] == 1
    patch = next(b for meth, url, b in fake.calls if meth == "PATCH" and url.endswith("/page-a"))
    assert "Status" not in patch["properties"] and "Notes" not in patch["properties"] and "Origin" not in patch["properties"]
    assert "Synced" in patch["properties"] and "Rule" in patch["properties"]
    assert "children" not in patch, "content is written at creation, not rewritten over the founder's edits"


def test_off_without_credentials_touches_nothing(tmp_path):
    env = dict(os.environ, KIPI_STATE_DIR=str(tmp_path / "no-creds"))
    r = subprocess.run([sys.executable, str(SCRIPT), "--lessons-dir", str(_corpus(tmp_path))], capture_output=True, text=True, env=env)
    assert r.returncode == 0 and json.loads(r.stdout.strip())["off"] is True


def test_refuses_the_live_database_under_pytest(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    (state / "notion-token").write_text("t")
    (state / "notion-lessons-db").write_text("db")
    env = dict(os.environ, KIPI_STATE_DIR=str(state))
    r = subprocess.run([sys.executable, str(SCRIPT), "--lessons-dir", str(_corpus(tmp_path))], capture_output=True, text=True, env=env)
    assert r.returncode == 2 and "refused" in r.stdout


def test_dry_run_counts_and_touches_nothing(tmp_path):
    env = dict(os.environ, KIPI_STATE_DIR=str(tmp_path / "no-creds"))
    r = subprocess.run([sys.executable, str(SCRIPT), "--dry-run", "--lessons-dir", str(_corpus(tmp_path))], capture_output=True, text=True, env=env)
    assert r.returncode == 0 and json.loads(r.stdout.strip())["would_sync"] == 2


def test_the_nightly_job_runs_the_sync_after_publish_and_it_is_non_fatal():
    job = (HERE.parent / "scripts" / "lessons-daily.sh").read_text()
    assert "lessons_notion_sync.py" in job
    assert job.index("lessons_notion_sync.py") > job.index("KIPI_PERSIST_CMD"), "after publish"
    assert job.index("lessons_notion_sync.py") < job.index('if [ "$PUB" -gt 0 ]; then'), "before propagation"
    assert "notion sync failed" in job, "a Notion outage must not fail the lessons job"


def test_a_failing_sync_does_not_fail_the_lessons_job(tmp_path):
    """Behavioural, not textual: the job runs with every seam stubbed and the
    sync forced to fail; it still exits 0 and logs the failure."""
    job = HERE.parent / "scripts" / "lessons-daily.sh"
    log = tmp_path / "lessons-daily.log"
    env = dict(os.environ, KIPI_CLAUDE_BIN="/usr/bin/true",
               KIPI_DISTILL_CMD="printf '%s' '{\"published\": [\"x\"], \"held\": []}'",
               KIPI_PERSIST_CMD="true", KIPI_PROPAGATE_CMD="true", KIPI_NOTIFY_CMD="true",
               KIPI_NOTION_SYNC_CMD="echo notion down; exit 7",
               KIPI_LESSONS_LOG=str(log), KIPI_STREAK_FILE=str(tmp_path / "streak.json"),
               KIPI_ESCALATIONS_FILE=str(tmp_path / "esc.jsonl"))
    r = subprocess.run(["/bin/bash", str(job)], capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0, r.stderr[-300:]
    text = log.read_text()
    assert "notion down" in text and "notion sync failed (non-fatal" in text
    assert "FAILURE" not in text


def test_this_file_runs_its_own_tests_under_python3():
    if os.environ.get("KIPI_SELFTEST_INNER"):
        pytest.skip("inner run")
    env = dict(os.environ, KIPI_SELFTEST_INNER="1")
    ok = subprocess.run([sys.executable, __file__], capture_output=True, text=True, env=env)
    assert ok.returncode == 0 and "passed" in ok.stdout, ok.stdout[-600:]
    none = subprocess.run([sys.executable, __file__, "-k", "no_such_test_zzz"], capture_output=True, text=True, env=env)
    assert none.returncode != 0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", *sys.argv[1:]]))
