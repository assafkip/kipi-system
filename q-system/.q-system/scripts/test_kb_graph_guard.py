#!/usr/bin/env python3
"""Tests for kb-graph-guard.py. Runnable directly or via pytest.

Negative self-test discipline (fable-discipline): every positive case is
paired with a negative one proving the check can FAIL, so a green run means
something. All subprocess calls pin CLAUDE_PROJECT_DIR to the sandbox root --
inheriting the operator's env would guard the real repo, not the fixture.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).parent
GUARD = HERE / "kb-graph-guard.py"
spec = importlib.util.spec_from_file_location("kb_graph_guard", GUARD)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def make_instance(tmp: Path) -> tuple[Path, Path]:
    """Fake instance: repo root, q-dir KB, one case with targets+findings."""
    root = tmp / "repo"
    kb = root / "q-investigate" / "memory" / "graph.jsonl"
    kb.parent.mkdir(parents=True)
    kb.write_text("")
    target = root / "q-investigate" / "investigations" / "case-001-x" / \
        "investigation" / "targets"
    findings = root / "q-investigate" / "investigations" / "case-001-x" / \
        "investigation" / "findings"
    target.mkdir(parents=True)
    findings.mkdir(parents=True)
    return root, kb


def run_guard(root: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(root)
    return subprocess.run(
        [sys.executable, str(GUARD)], cwd=root, env=env,
        capture_output=True, text=True, timeout=30,
    )


def touch_later(path: Path, offset: float = 2.0) -> None:
    future = time.time() + offset
    path.touch()
    os.utime(path, (future, future))


def test_fresh_kb_passes() -> None:
    """KB newer than entity files -> exit 0. No entity files also passes."""
    with tempfile.TemporaryDirectory() as tmp:
        root, _ = make_instance(Path(tmp))
        assert run_guard(root).returncode == 0


def test_stale_kb_blocks() -> None:
    """Entity file NEWER than KB -> exit 2 with guidance. The reproducer."""
    with tempfile.TemporaryDirectory() as tmp:
        root, _ = make_instance(Path(tmp))
        target = next((root / "q-investigate" / "investigations").rglob("targets"))
        touch_later(target / "t-jane-doe.md")
        result = run_guard(root)
        assert result.returncode == 2, f"expected block, got {result.returncode}"
        assert "graph.jsonl" in result.stderr


def test_missing_kb_fails_open() -> None:
    """No graph.jsonl -> silent pass; seeder owns creation, not the guard."""
    with tempfile.TemporaryDirectory() as tmp:
        root, kb = make_instance(Path(tmp))
        kb.unlink()
        assert run_guard(root).returncode == 0


def test_root_layout_instances_are_watched_too() -> None:
    """Plain instance (no q-dir): <root>/investigations must still trip it."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "repo"
        kb = root / "memory" / "graph.jsonl"
        targets = root / "investigations" / "case-001-x" / "investigation" / "targets"
        kb.parent.mkdir(parents=True)
        targets.mkdir(parents=True)
        kb.write_text("")
        touch_later(targets / "t-x.md")
        assert run_guard(root).returncode == 2


def test_client_relationship_layout_is_watched() -> None:
    """Non-investigation instance: relationships.md newer than KB -> block.
    This is the fleet majority (client work), not a corner case."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "repo"
        kb = root / "memory" / "graph.jsonl"
        rel = root / "my-project" / "relationships.md"
        kb.parent.mkdir(parents=True)
        rel.parent.mkdir(parents=True)
        kb.write_text("")
        touch_later(rel)
        result = run_guard(root)
        assert result.returncode == 2, f"expected block, got {result.returncode}"


def test_canonical_notes_are_watched() -> None:
    """canonical/*.md (objections, discovery, market intel) count as entities."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "repo"
        kb = root / "q-clientx" / "memory" / "graph.jsonl"
        canon = root / "q-clientx" / "canonical"
        kb.parent.mkdir(parents=True)
        canon.mkdir(parents=True)
        kb.write_text("")
        touch_later(canon / "objections.md")
        assert run_guard(root).returncode == 2


def test_second_same_day_miss_escalates_once_then_releases(monkeypatch=None) -> None:
    """1st miss: warn (exit 2). 2nd miss same day: queue once, exit 0.
    Third pass stays quiet. Runs in-process so the fake queue applies."""
    with tempfile.TemporaryDirectory() as tmp:
        root, _ = make_instance(Path(tmp))
        queue_file = Path(tmp) / "queue.jsonl"
        calls: list[int] = []

        def fake_queue(root_arg: Path, kb_path: Path) -> bool:
            calls.append(1)
            queue_file.write_text(json.dumps({"queued": True}) + "\n")
            return True

        target = next((root / "q-investigate" / "investigations").rglob("targets"))
        touch_later(target / "t-jane-doe.md")

        old_env = os.environ.get("CLAUDE_PROJECT_DIR")
        os.environ["CLAUDE_PROJECT_DIR"] = str(root)
        orig_queue = guard.queue_escalation
        guard.queue_escalation = fake_queue
        try:
            rc1 = guard.main()
            state_file = root / ".claude" / "state" / "kb-graph-guard.json"
            assert rc1 == 2, f"first miss should block, got {rc1}"
            assert json.loads(state_file.read_text())["last_warned"]

            rc2 = guard.main()
            assert rc2 == 0, "second miss must release, not hold the session"
            assert len(calls) == 1, "exactly one escalation per day"
            assert queue_file.exists()

            rc3 = guard.main()
            assert rc3 == 0 and len(calls) == 1, "third pass stays quiet"
        finally:
            guard.queue_escalation = orig_queue
            if old_env is None:
                os.environ.pop("CLAUDE_PROJECT_DIR", None)
            else:
                os.environ["CLAUDE_PROJECT_DIR"] = old_env


def test_find_kb_prefers_qdir_over_root() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        qdir_kb = root / "q-investigate" / "memory" / "graph.jsonl"
        qdir_kb.parent.mkdir(parents=True)
        qdir_kb.write_text("")
        root_kb = root / "memory" / "graph.jsonl"
        root_kb.parent.mkdir(parents=True)
        root_kb.write_text("")
        assert guard.find_kb(root) == qdir_kb


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as exc:
                print(f"FAIL {name}: {exc}")
                failures += 1
    sys.exit(1 if failures else 0)
