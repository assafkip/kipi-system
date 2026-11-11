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
import uuid
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

    It also matches the draft act route, and stays silent because this synthetic
    corpus holds none of that route's lessons: an act match alone must never open
    term overlap on a non-engineering turn (ASK-4208).
    """
    repo = _repo()
    rc, out = run(repo, "I want to write a post about voice cadence and draft rhythm")
    return rc == 0 and not out.strip()


def case_readme_is_not_a_lesson() -> bool:
    """README.md is the corpus's authoring instruction, not a lesson.

    Codex minor, PR #277: its vocabulary IS the corpus vocabulary, so it
    out-ranked real lessons on any lessons-related prompt. lessons-index.py
    already excludes it by name; this pins the second reader agreeing.
    """
    repo = _repo()
    (repo / "q-system" / "lessons" / "README.md").write_text(
        "---\nid: readme\nkind: pattern\ntitle: How to write a lesson\n"
        "date: 2026-08-01\n---\n\n"
        "A lesson records a gate, a hook, an allowlist, a timeout or a budget "
        "that failed, and the reproducer that shows it. Keep it HOW-only.\n",
        encoding="utf-8")
    _, out = run(repo, "widen the blocking gate allowlist so the hook fires")
    ctx = _ctx(out)
    return bool(ctx) and "readme" not in ctx and "How to write a lesson" not in ctx


def case_same_session_does_not_re_inject() -> bool:
    """Codex minor, PR #277: 48KB of byte-identical payload over six turns.

    Second turn, same session, same prompt: the lesson already shown must not
    be shown again.
    """
    repo = _repo()
    sid = "sess-dedupe-" + uuid.uuid4().hex  # fresh: the record persists on disk
    prompt = "widen the blocking gate allowlist so the hook fires"
    _, first = run(repo, prompt, raw=json.dumps(
        {"prompt": prompt, "session_id": sid}))
    _, second = run(repo, prompt, raw=json.dumps(
        {"prompt": prompt, "session_id": sid}))
    if not first.strip():
        return False
    if not second.strip():
        return True                      # nothing left to say: correct
    # NOT `!=` (Codex minor, PR #277). Two payloads differ for a hook that walks
    # the whole corpus three lessons at a time, which is the behaviour the
    # per-session budget exists to stop -- so a `!=` assertion goes green against
    # it and shows nothing. The property with teeth: no lesson SHOWN in turn one
    # appears again in turn two.
    a, b = _ctx(first), _ctx(second)
    return not any(f"[{lid}]" in a and f"[{lid}]" in b for lid in LESSONS)


def case_a_different_session_still_gets_it() -> bool:
    """The negative control for the dedupe.

    A dedupe scoped wider than one session makes the thing it dedupes
    disappear. This suite caught exactly that in the first revision -- it went
    7/8 then 5/8 on identical input, because a payload with no session_id fell
    back to one shared global key. A second session must be unaffected.
    """
    repo = _repo()
    prompt = "widen the blocking gate allowlist so the hook fires"
    _, a = run(repo, prompt, raw=json.dumps(
        {"prompt": prompt, "session_id": "one-" + uuid.uuid4().hex}))
    _, b = run(repo, prompt, raw=json.dumps(
        {"prompt": prompt, "session_id": "two-" + uuid.uuid4().hex}))
    return bool(a.strip()) and bool(b.strip()) and _ctx(a) == _ctx(b)


def case_repeated_runs_without_a_session_id_are_identical() -> bool:
    """No session id means NO dedupe, not a global one.

    Same call twice, no session_id, must give the same answer both times.
    """
    repo = _repo()
    prompt = "widen the blocking gate allowlist so the hook fires"
    _, a = run(repo, prompt)
    _, b = run(repo, prompt)
    return bool(a.strip()) and _ctx(a) == _ctx(b)


def case_ambiguous_words_no_longer_trigger() -> bool:
    """design / ship / budget have strong non-engineering senses here.

    The docstring promises this does not fire without engineering intent, and
    those words made it false (Codex minor, PR #277).
    """
    repo = _repo()
    for prompt in ("can you design a logo for the brand",
                   "when do we ship the newsletter to the list",
                   "what is our marketing budget for next month"):
        rc, out = run(repo, prompt)
        if rc != 0 or out.strip():
            return False
    return True


def case_engineering_words_still_trigger() -> bool:
    """The control for the narrowing: it must not have gutted the trigger."""
    repo = _repo()
    for prompt in ("merge it once the gate is green",
                   "commit the hook fix",
                   "the allowlist timeout is a defect"):
        rc, out = run(repo, prompt)
        if rc != 0 or not out.strip():
            return False
    return True

def _big_repo(n: int = 60) -> Path:
    """A corpus large enough that a per-turn cap is not a per-session cap."""
    tmp = Path(tempfile.mkdtemp())
    d = tmp / "q-system" / "lessons"
    d.mkdir(parents=True)
    body = ("A gate whose allowlist covers five destinations is blind everywhere "
            "else, and the timeout budget hides it. " * 30)
    for i in range(n):
        (d / f"lesson-{i:03d}.md").write_text(
            f"---\nid: lesson-{i:03d}\nkind: pattern\ntitle: Gate {i} allowlist "
            f"timeout budget\ndate: 2026-08-01\n---\n\n{body}\n",
            encoding="utf-8")
    return tmp


def _ceilings():
    import importlib.util as _ilu
    spec = _ilu.spec_from_file_location("li", HOOK)
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.SESSION_CEILING_CHARS, mod.PAYLOAD_CEILING_CHARS


def case_a_long_session_is_bounded() -> bool:
    """The case the dedupe made necessary (Codex major, PR #277).

    Before the dedupe, a long session got the SAME three lessons over and over:
    wasteful, bounded. After it, every turn brought three NEW ones, so a long
    session walked the entire corpus into context -- measured at 394,822 chars
    against a 375,528-byte corpus. One missing budget explains both.

    Sixty turns against a sixty-lesson corpus, summing what each turn injected.
    Without SESSION_CEILING_CHARS the sum reaches the whole corpus; with it the
    sum stops. Paired negative control below.
    """
    repo = _big_repo(60)
    sid = "sess-budget-" + uuid.uuid4().hex
    prompt = "widen the blocking gate allowlist because the timeout budget fires"
    total = 0
    for _ in range(60):
        _, out = run(repo, prompt, raw=json.dumps(
            {"prompt": prompt, "session_id": sid}))
        if out.strip():
            total += len(_ctx(out))
    # The ceiling is read BEFORE a turn spends, so the last turn can overshoot by
    # at most one payload. Beyond that is a walk, not a budget.
    session_ceiling, payload_ceiling = _ceilings()
    return 0 < total <= session_ceiling + payload_ceiling


def case_the_budget_is_not_just_the_corpus_being_small() -> bool:
    """Negative control for the case above.

    A 60-lesson corpus has to be able to exceed the ceiling, or the bound above
    is satisfied by arithmetic rather than by the budget.
    """
    repo = _big_repo(60)
    corpus = sum(len(f.read_text(encoding="utf-8"))
                 for f in (repo / "q-system" / "lessons").glob("*.md"))
    session_ceiling, _ = _ceilings()
    return corpus > session_ceiling


def case_non_object_json_is_silent() -> bool:
    """Valid JSON that is not an object has no .get (Codex nit, PR #277)."""
    repo = _repo()
    for raw in ("4", '"a string"', "[]", "null"):
        rc, out = run(repo, "", raw=raw)
        if rc != 0 or out.strip():
            return False
    return True

def case_the_envelope_carries_the_hook_event_name() -> bool:
    """Codex major, PR #277: without it the payload is DISCARDED.

    Every other case in this file reads the payload through `_ctx`, which
    reaches straight into hookSpecificOutput.additionalContext and never looks
    at the envelope around it. So the whole suite went green while the hook
    emitted an envelope Claude Code drops on the floor -- it fired, it ranked,
    it wrote to stdout, and not one word arrived.

    token-guard.py:1046 records the measurement this repo already paid for:
    the key is required, and its absence is silent.
    """
    repo = _repo()
    _, out = run(repo, "widen the blocking gate allowlist so the hook fires")
    if not out.strip():
        return False
    payload = json.loads(out)
    hso = payload.get("hookSpecificOutput")
    if not isinstance(hso, dict):
        return False
    # And nothing at the TOP level, which is the other half of the same scar.
    return (hso.get("hookEventName") == "UserPromptSubmit"
            and "additionalContext" in hso
            and "additionalContext" not in payload)


def case_an_oversized_top_lesson_does_not_starve_the_rest() -> bool:
    """Codex minor, PR #277: `break` let one long file block every other lesson.

    A top-ranked lesson bigger than the payload cap returned the header alone,
    and because a header-only payload returns 0 without recording anything, that
    same lesson ranked first again next turn and blocked the smaller relevant
    ones behind it for the whole session.
    """
    tmp = Path(tempfile.mkdtemp())
    d = tmp / "q-system" / "lessons"
    d.mkdir(parents=True)
    # One lesson far past the payload cap, sharing the prompt's vocabulary so it
    # ranks first, plus two small ones that must still get through.
    (d / "huge.md").write_text(
        "---\nid: huge\nkind: pattern\ntitle: Gate allowlist timeout budget\n"
        "date: 2026-08-01\n---\n\n"
        + ("gate allowlist timeout budget hook blocking " * 4000) + "\n",
        encoding="utf-8")
    for i, slug in enumerate(("small-a", "small-b")):
        (d / (slug + ".md")).write_text(
            f"---\nid: {slug}\nkind: pattern\ntitle: Gate {i} allowlist\n"
            "date: 2026-08-01\n---\n\n"
            "A gate allowlist that covers five destinations is blind everywhere "
            "else and the timeout budget hides it.\n",
            encoding="utf-8")
    _, out = run(tmp, "widen the blocking gate allowlist before the timeout budget fires")
    if not out.strip():
        return False
    ctx = _ctx(out)
    return "[small-a]" in ctx or "[small-b]" in ctx

def _skip_repo() -> Path:
    """A corpus whose TOP-ranked lesson is too large to fit, with two that fit."""
    tmp = Path(tempfile.mkdtemp())
    d = tmp / "q-system" / "lessons"
    d.mkdir(parents=True)
    (d / "huge.md").write_text(
        "---\nid: huge\nkind: pattern\ntitle: Gate allowlist timeout budget hook\n"
        "date: 2026-08-01\n---\n\n"
        + ("gate allowlist timeout budget hook blocking " * 4000) + "\n",
        encoding="utf-8")
    for slug in ("small-a", "small-b"):
        (d / (slug + ".md")).write_text(
            f"---\nid: {slug}\nkind: pattern\ntitle: Gate allowlist {slug}\n"
            "date: 2026-08-01\n---\n\n"
            "A gate allowlist covering five destinations is blind everywhere "
            "else and the timeout budget hides it.\n",
            encoding="utf-8")
    return tmp


def case_what_is_recorded_is_what_was_shown() -> bool:
    """Codex minor, PR #277 round 4. One stale index, two wrong halves.

    The emitted set was `picked[:len(parts) - 1]`, correct only while the loop
    stopped at the first oversized lesson. Turning that `break` into a `continue`
    broke the positional assumption in the same commit. Skip the first of three
    and the slice records the SKIPPED lesson as shown -- suppressing it for the
    rest of the session -- while the third, which really was shown, goes
    unrecorded and is re-injected next turn.

    Turn one shows the two small lessons. Turn two, same session, shows neither
    again -- which holds only when what was recorded is what was shown. This
    function is the checker.
    """
    repo = _skip_repo()
    sid = "sess-shown-" + uuid.uuid4().hex
    prompt = "widen the blocking gate allowlist before the timeout budget fires"
    _, first = run(repo, prompt, raw=json.dumps(
        {"prompt": prompt, "session_id": sid}))
    if not first.strip():
        return False
    a = _ctx(first)
    if "[small-a]" not in a and "[small-b]" not in a:
        return False
    _, second = run(repo, prompt, raw=json.dumps(
        {"prompt": prompt, "session_id": sid}))
    if not second.strip():
        return True                      # nothing left to show: correct
    b = _ctx(second)
    return not any(tag in a and tag in b for tag in ("[small-a]", "[small-b]"))


# ---------------------------------------------------------------------------
# REPLAY OF THE FOUR VOICELOOP INCIDENT PROMPTS (ASK-4208; deferred finding-14
# of prd-voicegate-skeleton-2026-11-09).
#
# Measured 2026-11-10 on this repo's own corpus (281 lessons), BEFORE the act
# route existed: 0 of the 5 target lessons surfaced on any of the 4 prompts.
# Two prompts never passed TRIGGER_RE and injected nothing; the other two
# ranked unrelated lessons first. A prompt that names a chat act ("draft the
# post", "show it to me") shares no words with a lesson that names a mechanism
# ("gate", "check"), so term overlap had nothing to match. The cases below are
# the pass condition the finding asked for, and they were red on that code.
#
# Runs against a COPY of the real corpus, because the corpus is what the hook
# selects from: synthetic lessons would prove the route reads its own table and
# nothing about whether these lessons reach these prompts.
#
# Sanitized for a public repo. Each prompt is verbatim except that the platform
# names were dropped (one per prompt in 1, 3 and 4). No platform name is a word
# the act route or TRIGGER_RE reads, and the baseline stayed 0 of 5 without
# them. No client, person, path or machine name was in any of the four.

REPLAY_TARGETS = (
    "a-check-must-be-able-to-fail-for-the-reason-you-care-abou",
    "zero-selected-items-is-a-failure-not-a-pass",
    "gates-must-recompute-not-read-self-reports",
    "bind-a-check-to-the-property-not-the-nearest-proxy",
    "assert-what-went-into-a-composed-artifact-not-just-that-it-c",
)
_ASSERT, _BIND = REPLAY_TARGETS[4], REPLAY_TARGETS[3]
_RECOMPUTE, _ZERO = REPLAY_TARGETS[2], REPLAY_TARGETS[1]

# (prompt, the target lessons that MUST surface on a fresh session). Exactly one
# each: the header plus the two SMALLEST targets is 6,271 bytes against the
# 6,000-byte lessons share, so no turn can carry two of them whole.
REPLAY = (
    ("you can only draft the post in a way that matches the build - make "
     "triple sure you are doing taht", {_ASSERT}),
    ("show it to me again", {_RECOMPUTE}),
    ("write me a post about building my own CRM", {_ASSERT}),
    ("Show me the post texts one at a time, numbered by topic name, and wait "
     "for my verdict on each", {_RECOMPUTE}),
)
# The same four prompts as ONE session: the dedupe walks each act's list, so
# four exit turns surface four different targets.
REPLAY_SESSION_ORDER = (_ASSERT, _RECOMPUTE, _BIND, _ZERO)

# Negative control: no target lesson before the change (measured), so any target
# here after it is flooding. Two are near misses on purpose: "post" with no
# drafting verb, and "show me" with no draft to show.
REPLAY_UNRELATED = (
    "what is the weather tomorrow",
    "fix the timeout in the scheduler script",
    "refactor the ledger writer so two processes cannot append at once",
    "the post office closes at five",
    "show me the logs from the nightly job",
    "draft the migration plan for the schema change",
)

_REAL_CORPUS = HOOK.parent.parent.parent / "lessons"


def _replay_repo() -> Path:
    import shutil
    tmp = Path(tempfile.mkdtemp())
    shutil.copytree(_REAL_CORPUS, tmp / "q-system" / "lessons")
    return tmp


def _replay_run(repo: Path, prompt: str, sid: str = "", tmpdir: str = ""):
    """The targets the hook actually SHOWED, read from its emitted payload."""
    payload = {"prompt": prompt}
    if sid:
        payload["session_id"] = sid
    env = {"CLAUDE_PROJECT_DIR": str(repo), "PATH": "/usr/bin:/bin"}
    if tmpdir:
        env["TMPDIR"] = tmpdir          # the session record lands in the test's dir
    p = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                       capture_output=True, text=True, env=env, check=False)
    shown = [t for t in REPLAY_TARGETS if f"=== [{t}]" in _ctx(p.stdout)]
    return p.returncode, shown


def case_replay_each_incident_prompt_surfaces_its_target_lesson() -> bool:
    repo, ok = _replay_repo(), True
    for prompt, want in REPLAY:
        rc, shown = _replay_run(repo, prompt)
        if rc != 0 or set(shown) != want:
            print(f"    replay: {prompt[:40]!r}: surfaced {len(shown)} of 5 "
                  f"{shown}, expected {sorted(want)}")
            ok = False
    return ok


def case_replay_one_session_walks_the_route() -> bool:
    repo, tmpdir = _replay_repo(), tempfile.mkdtemp()
    sid = "replay-" + uuid.uuid4().hex
    got = []
    for prompt, _want in REPLAY:
        _rc, shown = _replay_run(repo, prompt, sid=sid, tmpdir=tmpdir)
        got.append(shown)
    want = [[t] for t in REPLAY_SESSION_ORDER]
    if got != want:
        print(f"    replay session: surfaced {got}, expected {want}")
    return got == want


def case_replay_unrelated_prompts_gain_no_target_lesson() -> bool:
    repo, ok = _replay_repo(), True
    for prompt in REPLAY_UNRELATED:
        rc, shown = _replay_run(repo, prompt)
        if rc != 0 or shown:
            print(f"    control: {prompt!r} surfaced {shown}")
            ok = False
    return ok


def case_every_routed_lesson_exists_in_the_real_corpus() -> bool:
    """A renamed or removed lesson would leave its route pointing at nothing,
    and the hook skips a missing id silently. This is where that turns red."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("_li_routes", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    ids = {mod.parse_lesson(p)[0] for p in _REAL_CORPUS.glob("*.md")}
    routed = [lid for _act, _rx, lids in mod.ACT_ROUTES for lid in lids]
    missing = sorted(set(routed) - ids)
    if missing:
        print(f"    routed ids missing from the corpus: {missing}")
    return bool(routed) and not missing


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
