#!/usr/bin/env python3
"""Self-test for lessons-inject.py.

Reproducer (2026-08-29): a session was handed 155 lesson TITLES at SessionStart,
treated the injection as delivery, opened none of them, and hit a scar that one of
those lessons describes exactly. The response was a promise in chat ("going forward
I'll read the corpus"), which nothing can hold.

The discriminating case is case_ranking_discriminates: two prompts with different
vocabulary must select DIFFERENT lessons. Without it, a selector that always returns
the same three lessons (the longest, the newest, the alphabetically first) passes
every other case here while being useless.

Hermetic: each case builds a temp repo with synthetic lessons.
Run: python3 test_lessons_inject.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

HOOK = Path(__file__).resolve().parent / "lessons-inject.py"

LESSONS = {
    "gate-scope": (
        "A gate's scope is part of the gate",
        "An allowlist gate that fires only on five destinations is blind everywhere "
        "else. Widening the allowlist trades silence for noise, and noise gets the "
        "hook bypassed. Check the blocking scope before trusting a green count.",
    ),
    "timeout-budget": (
        "A timeout is a budget defect",
        "A timeout shorter than the work it waits on is a budget defect, not a flake. "
        "Measure headroom as duration over budget across the whole population. "
        "Latency in seconds is the instrument.",
    ),
    "voice-cadence": (
        "Cadence without substance reads as AI",
        "A draft that copies the rhythm of the voice without a scar, a named thing or "
        "evidence still reads as generated prose. Substance beats cadence in every "
        "post and every reply.",
    ),
}


def _repo(with_lessons: bool = True) -> Path:
    tmp = Path(tempfile.mkdtemp())
    if with_lessons:
        d = tmp / "q-system" / "lessons"
        d.mkdir(parents=True)
        for slug, (title, body) in LESSONS.items():
            (d / f"{slug}.md").write_text(
                f"---\nid: {slug}\nkind: pattern\ntitle: {title}\ndate: 2026-08-01\n---\n\n{body}\n",
                encoding="utf-8",
            )
    return tmp


def run(repo: Path, prompt: str, raw: str | None = None):
    payload = raw if raw is not None else json.dumps({"prompt": prompt})
    p = subprocess.run(
        [sys.executable, str(HOOK)], input=payload, capture_output=True, text=True,
        env={"CLAUDE_PROJECT_DIR": str(repo), "PATH": "/usr/bin:/bin"}, check=False,
    )
    return p.returncode, p.stdout


def _ctx(out: str) -> str:
    if not out.strip():
        return ""
    return json.loads(out)["hookSpecificOutput"]["additionalContext"]


def case_engineering_prompt_injects_bodies() -> bool:
    """The reproducer: an engineering prompt must get lesson BODIES, not titles."""
    repo = _repo()
    rc, out = run(repo, "I need to fix the blocking gate hook and widen its allowlist")
    if rc != 0 or not out.strip():
        return False
    ctx = _ctx(out)
    # A BODY sentence, not just the title. Titles were the original failure.
    return "noise gets the hook bypassed" in ctx


def case_ranking_discriminates() -> bool:
    """THE negative control. Different vocabulary must pick different lessons.

    A selector that always returns the same rows passes every other case here.
    """
    repo = _repo()
    _, out_a = run(repo, "widen the blocking gate allowlist so the hook fires")
    _, out_b = run(repo, "the job blew its latency budget and hit a timeout in seconds")
    a, b = _ctx(out_a), _ctx(out_b)
    if not a or not b:
        return False
    a_gate = "gate-scope" in a
    b_time = "timeout-budget" in b
    # and they must not be the same payload
    return a_gate and b_time and a != b


def case_non_engineering_prompt_is_silent() -> bool:
    """Firing on every prompt is a token cost with no signal."""
    repo = _repo()
    rc, out = run(repo, "what is the weather in Tel Aviv today")
    return rc == 0 and not out.strip()


def case_missing_lessons_dir_fails_open() -> bool:
    repo = _repo(with_lessons=False)
    rc, out = run(repo, "fix the broken gate hook")
    return rc == 0 and not out.strip()


def case_malformed_stdin_fails_open() -> bool:
    repo = _repo()
    rc, out = run(repo, "", raw="{not json")
    return rc == 0 and not out.strip()


def case_payload_is_capped() -> bool:
    """A dump was measured making output worse. The cap is the whole point."""
    repo = _repo()
    rc, out = run(repo, "fix the gate hook timeout draft post budget allowlist")
    if rc != 0 or not out.strip():
        return False
    return len(_ctx(out)) <= 12000


def case_empty_prompt_is_silent() -> bool:
    repo = _repo()
    rc, out = run(repo, "")
    return rc == 0 and not out.strip()


def case_non_engineering_prompt_with_shared_vocabulary_is_silent() -> bool:
    """The trigger gate's ONLY real test.

    case_non_engineering_prompt_is_silent does NOT exercise the trigger: "weather
    in Tel Aviv" shares no vocabulary with any lesson, so the zero-score filter
    makes it silent and the gate is never reached. Measured 2026-08-29 by mutation:
    deleting TRIGGER_RE from the hook killed no test at all.

    This prompt is deliberately NON-engineering but DOES overlap the voice-cadence
    lesson (post, draft, cadence, rhythm). Only the trigger gate can keep it quiet.
    """
    repo = _repo()
    rc, out = run(repo, "I want to write a post about voice cadence and draft rhythm")
    return rc == 0 and not out.strip()


CASES = [v for k, v in sorted(globals().items()) if k.startswith("case_")]

if __name__ == "__main__":
    failed = 0
    for fn in CASES:
        try:
            ok = fn()
        except Exception as exc:
            ok = False
            print(f"  [ERROR] {fn.__name__}: {exc}")
        print(f"  [{'PASS' if ok else 'FAIL'}] {fn.__name__}")
        failed += 0 if ok else 1
    total = len(CASES)
    print(f"\n{total - failed}/{total} passed")
    sys.exit(1 if failed else 0)
