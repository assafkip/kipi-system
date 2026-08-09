"""ASK-533: the grounding guard's coverage check must not fail open silently.

THE DEFECT. `code_claim_grounding_guard.py` is the Stop hook, so it runs unattended
on every turn fleet-wide. Its check two (subsystem coverage) reads the manifest via
`system_manifest.load()`, and every degraded path converges on the same silent no-op:

  - manifest ABSENT           -> load() returns {}          (system_manifest.py:57)
  - manifest CORRUPT JSON     -> load() returns {}          (system_manifest.py:61)
  - module UNIMPORTABLE       -> _manifest = None           (guard:46-49)
  - mentions() raises         -> evaluate_subsystems -> []  (guard:158)

So the coverage guarantee is weakest on exactly the corrupted or unavailable evidence
that should alarm it. `system_manifest.check()` DOES fail closed on corrupt JSON
(:76-79) -- but nothing on the runtime path calls it, so that correctness is unreached.

THE ASYMMETRY THAT MAKES THIS SUBTLE, and why "just fail closed" is wrong:
ABSENT is CORRECT behaviour. Most instances declare no data path and must no-op; that
is documented at system_manifest.py:54-55 and is the state every instance starts in.
Only PRESENT-BUT-UNREADABLE is the defect. A fix that treats absent and corrupt alike
would wedge the entire fleet on a Stop hook that fires every turn, which is why
test_absent_manifest_stays_a_silent_noop below is a REQUIRED negative control and not
an afterthought: it is the test that fails if the fix is too broad.

WARN PHASE. This ships reporting, not blocking. The guard emits a warning and records
a row so the real fleet-wide rate can be measured against actual runs BEFORE anyone
decides fail-closed is safe. Flipping on reasoning alone is how a Stop hook takes the
fleet down.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
GUARD = SCRIPTS / "code_claim_grounding_guard.py"


def _repo(tmp_path: Path) -> Path:
    """A throwaway instance root. Never the live tree (fable-discipline)."""
    r = tmp_path / "repo"
    (r / "q-system" / "canonical").mkdir(parents=True)
    return r


def _manifest_file(repo: Path) -> Path:
    return repo / "q-system" / "canonical" / "system-manifest.json"


def _load_module():
    sys.path.insert(0, str(SCRIPTS))
    import importlib
    import system_manifest
    importlib.reload(system_manifest)
    return system_manifest


# --- layer 1: the loader can tell the three states apart ---------------------

def test_absent_manifest_stays_a_silent_noop(tmp_path):
    """NEGATIVE CONTROL. Absent is correct, not degraded.

    If this ever goes red, the fix has become "treat any missing manifest as broken",
    which on a Stop hook that runs every turn is a fleet-wide wedge. This test is the
    thing standing between a fail-closed flip and an outage.
    """
    m = _load_module()
    status, _ = m.health(_repo(tmp_path))
    assert status == m.MANIFEST_ABSENT, (
        f"an absent manifest was reported as {status!r}; most instances have no "
        "manifest and MUST no-op silently")


def test_corrupt_manifest_is_reported_not_swallowed(tmp_path):
    """The runtime path must distinguish 'no manifest' from 'cannot read it'."""
    m = _load_module()
    repo = _repo(tmp_path)
    _manifest_file(repo).write_text('{"subsystems": [ this is not json')
    status, detail = m.health(repo)
    assert status == m.MANIFEST_UNREADABLE, (
        f"a corrupt manifest reported {status!r}; load() swallows the exception and "
        "returns {}, which is indistinguishable from absent")
    assert detail, "no reason given; an operator cannot act on a bare status"


def test_non_object_manifest_is_reported(tmp_path):
    """Valid JSON, wrong shape. `load()` returns {} here too (system_manifest.py:63)."""
    m = _load_module()
    repo = _repo(tmp_path)
    _manifest_file(repo).write_text('["not", "an", "object"]')
    status, _ = m.health(repo)
    assert status == m.MANIFEST_UNREADABLE, (
        f"a top-level-array manifest reported {status!r}")


def test_healthy_manifest_reports_ok(tmp_path):
    """The guard must not cry wolf on a good manifest, or it trains the operator to
    ignore it -- which costs the real alert later."""
    m = _load_module()
    repo = _repo(tmp_path)
    _manifest_file(repo).write_text(json.dumps({
        "version": 1,
        "subsystems": [{"id": "s1", "name": "S One",
                        "members": [{"ref": "a.py", "kind": "file"}]}]}))
    status, _ = m.health(repo)
    assert status == m.MANIFEST_OK, f"a valid manifest reported {status!r}"


# --- layer 2: the guard surfaces it, and does NOT block in the warn phase ----

def _run_guard(repo: Path, transcript: Path, env_extra=None):
    import os
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(repo))
    env.pop("KIPI_GROUNDING_MANIFEST_ENFORCE", None)
    if env_extra:
        env.update(env_extra)
    payload = json.dumps({"transcript_path": str(transcript), "stop_hook_active": False})
    return subprocess.run([sys.executable, str(GUARD)], input=payload,
                          capture_output=True, text=True, env=env)


def _transcript(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "t.jsonl"
    p.write_text(json.dumps({
        "message": {"role": "assistant",
                    "content": [{"type": "text", "text": text}]}}) + "\n")
    return p


def test_guard_warns_on_a_corrupt_manifest_but_does_not_block(tmp_path):
    """WARN PHASE, both halves in one assertion pair.

    It must SAY something (silence is the defect) and must NOT exit 2 (blocking on a
    Stop hook before the rate is measured is the outage). Splitting these into two
    tests would let a fix satisfy one and regress the other unnoticed.
    """
    repo = _repo(tmp_path)
    _manifest_file(repo).write_text("{oops")
    r = _run_guard(repo, _transcript(tmp_path, "a harmless sentence"))
    assert r.returncode == 0, (
        f"the warn phase BLOCKED (exit {r.returncode}); this hook fires every turn "
        f"fleet-wide and a bad manifest anywhere would wedge every session.\n{r.stderr}")
    assert "manifest" in r.stderr.lower() and "unreadable" in r.stderr.lower(), (
        f"corrupt manifest produced no operator-facing warning.\nstderr={r.stderr!r}")


def test_guard_is_silent_when_no_manifest_exists(tmp_path):
    """NEGATIVE CONTROL at the guard layer. Every instance starts here."""
    repo = _repo(tmp_path)
    r = _run_guard(repo, _transcript(tmp_path, "a harmless sentence"))
    assert r.returncode == 0, f"absent manifest blocked: {r.stderr}"
    assert "unreadable" not in r.stderr.lower(), (
        f"absent manifest produced a degraded warning; this is the false-alarm "
        f"path that gets the gate switched off.\nstderr={r.stderr!r}")


def test_unimportable_manifest_module_is_reported(tmp_path):
    """The third door. The guard's bare `except Exception: _manifest = None` means a
    syntax error or a missing dependency in system_manifest.py silently disables check
    two forever, with no signal at all."""
    repo = _repo(tmp_path)
    r = _run_guard(repo, _transcript(tmp_path, "a harmless sentence"),
                   env_extra={"KIPI_GROUNDING_FORCE_IMPORT_FAILURE": "1"})
    assert r.returncode == 0, f"warn phase blocked: {r.stderr}"
    assert "manifest" in r.stderr.lower(), (
        f"an unimportable system_manifest module produced NO warning; check two is "
        f"silently dead.\nstderr={r.stderr!r}")


def test_enforce_flag_turns_the_warning_into_a_block(tmp_path):
    """The flip is a config change, not a code change -- but it stays OFF until the
    warn-phase rate is measured against real runs. This test pins the mechanism so the
    later decision is one env var, and pins that it is not on by default."""
    repo = _repo(tmp_path)
    _manifest_file(repo).write_text("{oops")
    r = _run_guard(repo, _transcript(tmp_path, "a harmless sentence"),
                   env_extra={"KIPI_GROUNDING_MANIFEST_ENFORCE": "1"})
    assert r.returncode == 2, (
        f"the enforce flag did not block (exit {r.returncode}); the flip mechanism "
        f"does not work, so the warn phase leads nowhere.\n{r.stderr}")


def test_structurally_invalid_object_is_unreadable_not_ok(tmp_path):
    """Valid JSON, a real dict, and still unusable.

    Codex round 1 on PR #132, MAJOR. The first cut of health() validated ONLY the top
    level, so this exact input reported `ok` while subsystems() returned [] and
    coverage silently did nothing -- the same fail-open ASK-533 exists to close,
    reintroduced one level deeper by the fix for it.

    Reproducer output before the fix:
        health = ('ok', '')
        check  = ['subsystems[0]: not an object', ...]
        subsystems = []
    """
    m = _load_module()
    repo = _repo(tmp_path)
    _manifest_file(repo).write_text('{"subsystems": "not-a-list"}')
    status, detail = m.health(repo)
    assert status == m.MANIFEST_UNREADABLE, (
        f"a structurally invalid manifest reported {status!r} while check() calls it "
        f"invalid and subsystems() yields nothing to cover")
    assert detail, "no reason given; the operator cannot act on a bare status"


def test_health_agrees_with_check_on_every_shape(tmp_path):
    """The anti-drift property, stated directly: two functions answering 'is this
    manifest usable?' with different rules is how they come apart. check() is the
    authority; health() must never call a manifest ok that check() rejects."""
    m = _load_module()
    repo = _repo(tmp_path)
    shapes = [
        # Wrong TYPE for the container. `{}` is the one that slipped round 1: Python
        # iterates a dict's keys, and an EMPTY dict yields none, so the validation
        # loop ran zero times and reported clean (Codex round 2, PR #132).
        '{"subsystems": {}}',
        '{"subsystems": {"a": 1}}',
        '{"subsystems": 0}',
        '{"subsystems": null}',
        '{"subsystems": "not-a-list"}',
        '{"subsystems": [{"id": "", "name": "x", "members": [{"ref": "a"}]}]}',
        '{"subsystems": [{"id": "s", "name": "S", "members": []}]}',
        '{"subsystems": [{"id": "s", "name": "", "members": [{"ref": "a"}]}]}',
    ]
    for raw in shapes:
        _manifest_file(repo).write_text(raw)
        status, _ = m.health(repo)
        problems = m.check(repo)
        assert bool(problems) == (status == m.MANIFEST_UNREADABLE), (
            f"health={status!r} but check() returned {len(problems)} problem(s) "
            f"for {raw!r}; the two disagree about the same file")


def test_guard_warns_on_a_structurally_invalid_manifest(tmp_path):
    """The guard-level half the reviewer asked for: the malformed OBJECT must reach
    the operator, not just be classified correctly in a helper."""
    repo = _repo(tmp_path)
    _manifest_file(repo).write_text('{"subsystems": "not-a-list"}')
    r = _run_guard(repo, _transcript(tmp_path, "a harmless sentence"))
    assert r.returncode == 0, f"warn phase blocked: {r.stderr}"
    assert "unreadable" in r.stderr.lower(), (
        f"a structurally invalid manifest produced no warning; coverage is off and "
        f"nobody is told.\nstderr={r.stderr!r}")


def test_empty_wrong_type_container_is_unreadable(tmp_path):
    """`{"subsystems": {}}` -- the exact input that survived round 1.

    Python iterates a dict's KEYS, so an empty dict yields nothing, the validation
    loop ran zero times, check() returned [], health() said ok, and the Stop hook ran
    with zero coverage and an empty stderr. A non-empty string was caught only by
    accident (its characters each failed the per-item object test), which is why the
    round-1 test set passed while the defect was live.
    """
    m = _load_module()
    repo = _repo(tmp_path)
    _manifest_file(repo).write_text('{"subsystems": {}}')
    status, detail = m.health(repo)
    assert status == m.MANIFEST_UNREADABLE, (
        f"an empty wrong-type container reported {status!r}; coverage is silently off")
    assert "list" in detail.lower(), f"detail does not name the problem: {detail!r}"


def test_empty_but_correctly_typed_manifest_stays_ok(tmp_path):
    """NEGATIVE CONTROL for round 2's fix. "Nothing declared yet" is legitimate.

    `{}` and `{"subsystems": []}` mean the same thing as having no manifest, and that
    is the state an instance sits in while someone is authoring one. Rejecting them
    would wedge every session on a hook that fires every turn -- the outage this issue
    is being careful to avoid. This is the test that fails if the fix over-broadens.
    """
    m = _load_module()
    repo = _repo(tmp_path)
    for raw in ('{}', '{"subsystems": []}'):
        _manifest_file(repo).write_text(raw)
        status, _ = m.health(repo)
        assert status == m.MANIFEST_OK, (
            f"{raw} reported {status!r}; an empty manifest is a legitimate state, not "
            "a broken one")


def test_accessors_do_not_crash_on_a_wrong_type_container(tmp_path):
    """`subsystems()` RAISED on a non-iterable container, on every turn, invisibly.

    `{"subsystems": 0}` and `{"subsystems": null}` both gave
    `TypeError: not iterable`. The guard's broad `except Exception` around mentions()
    swallowed it into an empty result, so the crash never surfaced anywhere -- the
    same swallow-the-reason pattern this whole issue is about, one layer down.
    Accessors return empty; health()/check() are the things that SAY it is broken.
    """
    m = _load_module()
    repo = _repo(tmp_path)
    for raw in ('{"subsystems": 0}', '{"subsystems": null}', '{"subsystems": {}}'):
        _manifest_file(repo).write_text(raw)
        assert m.subsystems(repo) == [], f"{raw} did not yield an empty set"
        assert m.mentions(repo, "some prose") == [], f"{raw} broke mentions()"
        assert m.health(repo)[0] == m.MANIFEST_UNREADABLE, (
            f"{raw} was not reported as unreadable")


def _stub_notifier(repo: Path) -> Path:
    """A stand-in slack-notify.sh that RECORDS what it was called with.

    Asserting on stderr proves the guard talked to itself. This asserts the alarm's
    own recorder fired, which is the thing that reaches a human who is not watching
    the terminal.
    """
    d = repo / "q-system" / ".q-system" / "scripts"
    d.mkdir(parents=True, exist_ok=True)
    sink = repo / "paged.txt"
    sh = d / "slack-notify.sh"
    sh.write_text(f'#!/bin/bash\nprintf "%s\\n" "$1" >> "{sink}"\n')
    sh.chmod(0o755)
    return sink


def test_an_unreadable_manifest_pages_a_human_not_just_stderr(tmp_path):
    """Codex round 3, PR #132, MAJOR. A Stop hook that exits 0 has no operator-visible
    channel -- stderr is not surfaced on a pass. So on the run that matters most, the
    3am scheduled agent that exits normally, the warning reached nobody at all."""
    repo = _repo(tmp_path)
    sink = _stub_notifier(repo)
    _manifest_file(repo).write_text("{oops")
    r = _run_guard(repo, _transcript(tmp_path, "a harmless sentence"))
    assert r.returncode == 0, f"warn phase blocked: {r.stderr}"
    assert sink.is_file(), (
        "nobody was paged; the warning existed only on stderr, which a Stop hook "
        "exiting 0 does not surface")
    body = sink.read_text()
    assert "manifest" in body.lower() and "system_manifest.py check" in body, (
        f"the page does not say what broke or what to run: {body!r}")


def test_the_page_is_deduped_so_it_cannot_become_per_turn_noise(tmp_path):
    """The manifest state is stable, so an undeduped ping fires EVERY turn. A checker
    that cries wolf trains the operator to ignore it, which costs the real alert
    later -- the reason false alarms rank as major in this repo's own severity
    anchors. Keyed on the problem, not the turn."""
    repo = _repo(tmp_path)
    sink = _stub_notifier(repo)
    _manifest_file(repo).write_text("{oops")
    for _ in range(3):
        _run_guard(repo, _transcript(tmp_path, "a harmless sentence"))
    assert sink.is_file(), "never paged at all"
    assert len(sink.read_text().strip().splitlines()) == 1, (
        f"paged {len(sink.read_text().strip().splitlines())} times across 3 turns; "
        "this is the per-turn noise that gets an alarm muted")


def test_a_healthy_manifest_never_pages(tmp_path):
    """NEGATIVE CONTROL on the alarm itself: it must be silent when nothing is wrong,
    or every one of the assertions above is satisfied by an alarm that always fires."""
    repo = _repo(tmp_path)
    sink = _stub_notifier(repo)
    _manifest_file(repo).write_text(json.dumps({
        "version": 1,
        "subsystems": [{"id": "s1", "name": "S One",
                        "members": [{"ref": "a.py", "kind": "file"}]}]}))
    _run_guard(repo, _transcript(tmp_path, "a harmless sentence"))
    assert not sink.exists(), f"paged on a HEALTHY manifest: {sink.read_text()!r}"


def test_warning_reaches_the_agent_via_the_documented_stop_channel(tmp_path):
    """Exit 0 + hookSpecificOutput.additionalContext, the ONE shape the Claude Code
    hooks reference documents for a non-blocking Stop message.

    Deliberately not `systemMessage` or `continue`: both appear only in the generic
    JSON section and are undocumented for Stop. Shipping an unverified field is how
    you get a channel that silently does nothing -- the exact defect class ASK-533 is
    about, which would make the fix an instance of the bug.

    The NESTING is the assertion that matters. A top-level `additionalContext` is
    silently ignored by Claude Code (scar: token-guard.py:743), so a test that merely
    grepped stdout for the word would pass against a payload that does nothing.
    """
    repo = _repo(tmp_path)
    _manifest_file(repo).write_text("{oops")
    r = _run_guard(repo, _transcript(tmp_path, "a harmless sentence"))
    assert r.returncode == 0, f"warn phase blocked: {r.stderr}"
    payload = json.loads(r.stdout.strip().splitlines()[0])
    hso = payload["hookSpecificOutput"]
    assert hso["hookEventName"] == "Stop", (
        f"wrong hookEventName {hso.get('hookEventName')!r}; the payload is discarded")
    assert "unreadable" in hso["additionalContext"].lower(), (
        f"context does not name the problem: {hso['additionalContext']!r}")
    assert "additionalContext" not in payload, (
        "additionalContext is at the TOP LEVEL, where Claude Code silently ignores it")


def test_no_stdout_payload_when_the_manifest_is_healthy(tmp_path):
    """NEGATIVE CONTROL. A hook that emits a warning payload unconditionally is worse
    than one that emits none: it injects noise into every single turn fleet-wide."""
    repo = _repo(tmp_path)
    _manifest_file(repo).write_text(json.dumps({
        "version": 1,
        "subsystems": [{"id": "s1", "name": "S One",
                        "members": [{"ref": "a.py", "kind": "file"}]}]}))
    r = _run_guard(repo, _transcript(tmp_path, "a harmless sentence"))
    assert r.stdout.strip() == "", f"emitted a payload on a healthy manifest: {r.stdout!r}"


if __name__ == "__main__":
    # The capability gate runs `python3 <file>`, NOT pytest (capability-gate.py:423).
    # Without this block the module would merely DEFINE its tests and exit 0 -- a
    # declared capability test that cannot fail, which is the exact absence this
    # repo's gate exists to catch.
    import subprocess
    raise SystemExit(subprocess.run(
        [sys.executable, "-m", "pytest", str(Path(__file__).resolve()), "-q"]
    ).returncode)
