#!/usr/bin/env python3
"""Pins the DETECTED claim in `.claude/rules/voice-loop-anywhere.md`.

Named by that rule's enforcement block, which is what makes the claim
substantiable rather than a word an author typed.

TEST ISOLATION (fable-discipline): every case runs against a STUB `voiceloop`
placed on PATH and a temp corpus directory. Nothing here reads the founder's real
corpus at ~/projects/consulting/q-consult/voice, and nothing here invokes the real
engine. The stub is the point: these cases pin THIS HOOK's contract -- scope,
self-match exemption, skip marker, and that a missing gate announces itself --
not voiceloop's scoring, which is the public package's own business.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[1] / "voiceloop-band-lint.py"

# A path is a "draft" only if voice-lint's own is_published_path says so. This
# one is inside that scope (matches the `.*/outreach/.*\.md$` rule).
IN_SCOPE = "outreach/some-note.md"
OUT_OF_SCOPE = "notes/internal-memo.md"
# The remedy text, named once so a case can assert it is ABSENT for an
# engine fault and PRESENT for a real finding.
SKIP_HINT = "to silence this file deliberately"


def _sealed_path(bin_dir):
    """PATH containing ONLY the stub dir plus system bins.

    WHY SEALED (mutation M4, 2026-08-29): the first version of this file did
    `f"{bin_dir}:{os.environ['PATH']}"`, which left the founder's real
    ~/.local/bin/voiceloop reachable. So `with_stub=False` did not remove the
    engine at all -- the hook found the REAL voiceloop, ran it against a temp
    corpus, and the test's `assert "NOT CHECKED" in stderr` matched a string
    voiceloop prints about its own lexicon. The test passed without ever
    reaching the branch it names, and it touched the live engine while this
    file's docstring claimed it never does. A mutant that deleted the hook's
    entire missing-engine message survived, which is how it was caught.
    """
    return f"{bin_dir}:/usr/bin:/bin"


def _stub_voiceloop(bin_dir, rc, stdout):
    """A fake `voiceloop` on PATH, so no test touches the live engine or corpus."""
    stub = bin_dir / "voiceloop"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        f"cat <<'OUT'\n{stdout}\nOUT\n"
        f"exit {rc}\n"
    )
    stub.chmod(0o755)
    return stub


def _run(tmp_path, rel_path, body, *, rc=1, stdout="band: sentence_mean: 43.0 outside [5.75, 16.22]",
         with_stub=True, corpus=None, tool_name="Write"):
    draft = tmp_path / rel_path
    draft.parent.mkdir(parents=True, exist_ok=True)
    draft.write_text(body)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    if with_stub:
        _stub_voiceloop(bin_dir, rc, stdout)

    corpus_dir = corpus if corpus is not None else (tmp_path / "corpus")
    corpus_dir.mkdir(parents=True, exist_ok=True)

    env = dict(os.environ)
    env["PATH"] = _sealed_path(bin_dir)
    env["VOICE_LOOP_CORPUS"] = str(corpus_dir)

    payload = {"tool_name": tool_name, "tool_input": {"file_path": str(draft)}}
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload), capture_output=True, text=True, env=env, timeout=60,
    )


def test_detected_never_blocks_even_when_voiceloop_finds_something(tmp_path):
    """The DETECTED half of the claim: findings surface, the write still lands."""
    r = _run(tmp_path, IN_SCOPE, "a long winded draft\n", rc=1)
    assert r.returncode == 0, f"DETECTED must exit 0, got {r.returncode}"
    assert "sentence_mean" in r.stderr, r.stderr


def test_finding_is_actually_surfaced_not_swallowed(tmp_path):
    """A hook that exits 0 and says nothing is indistinguishable from no hook."""
    r = _run(tmp_path, IN_SCOPE, "a long winded draft\n", rc=1)
    assert "voiceloop" in r.stderr
    assert str(tmp_path) in r.stderr, "the report must name the file it judged"


def test_clean_draft_produces_no_noise(tmp_path):
    r = _run(tmp_path, IN_SCOPE, "short one.\n", rc=0, stdout="0 finding(s)")
    assert r.returncode == 0
    assert r.stderr.strip() == "", f"clean draft must be silent, got: {r.stderr}"


def test_out_of_scope_path_fast_exits(tmp_path):
    """Token discipline: the hook must not run voiceloop on every Edit."""
    r = _run(tmp_path, OUT_OF_SCOPE, "whatever\n", rc=1)
    assert r.returncode == 0
    assert r.stderr.strip() == "", f"out-of-scope must be silent, got: {r.stderr}"


def test_corpus_member_is_exempt_from_self_match(tmp_path):
    """Measured false positive 2026-08-29: a corpus file echoes the corpus."""
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    r = _run(tmp_path, "corpus/outreach/exemplar.md", "corpus text\n",
             rc=1, corpus=corpus)
    assert r.returncode == 0
    assert r.stderr.strip() == "", f"corpus member must be skipped, got: {r.stderr}"


def test_skip_marker_silences_one_file(tmp_path):
    r = _run(tmp_path, IN_SCOPE, "draft\n<!-- voiceloop-band-lint-skip -->\n", rc=1)
    assert r.returncode == 0
    assert r.stderr.strip() == ""


def test_missing_engine_announces_itself(tmp_path):
    """THE SCAR: a half-run check must not read like a clean one."""
    r = _run(tmp_path, IN_SCOPE, "draft\n", with_stub=False)
    assert r.returncode == 0
    assert "NOT CHECKED" in r.stderr, r.stderr


def test_missing_corpus_announces_itself(tmp_path):
    missing = tmp_path / "no-such-corpus"
    draft = tmp_path / IN_SCOPE
    draft.parent.mkdir(parents=True, exist_ok=True)
    draft.write_text("draft\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    _stub_voiceloop(bin_dir, 1, "band: x")
    env = dict(os.environ)
    env["PATH"] = _sealed_path(bin_dir)
    env["VOICE_LOOP_CORPUS"] = str(missing)
    payload = {"tool_name": "Write", "tool_input": {"file_path": str(draft)}}
    r = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                       capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0
    assert "NOT CHECKED" in r.stderr, r.stderr


def test_non_write_tool_is_ignored(tmp_path):
    r = _run(tmp_path, IN_SCOPE, "draft\n", rc=1, tool_name="Read")
    assert r.returncode == 0
    assert r.stderr.strip() == ""


def _ctx(result):
    """The additionalContext this hook emits on stdout, or "" if it emitted none."""
    out = (result.stdout or "").strip()
    if not out:
        return ""
    return json.loads(out)["hookSpecificOutput"]["additionalContext"]


def test_the_finding_reaches_the_channel_the_agent_actually_reads(tmp_path):
    """Codex major, PR #278. stderr on exit 0 goes NOWHERE.

    The PostToolUse contract feeds stderr to Claude only on exit 2. This hook
    exits 0 by design -- it DETECTS, it does not block -- so every finding it
    produced was written to a channel nobody reads, and the DETECTED claim
    surfaced exactly nothing.

    The existing cases all assert on r.stderr, which is why none of them could
    see it: they were reading the channel the hook writes to, not the one the
    agent receives.
    """
    r = _run(tmp_path, IN_SCOPE, "a long winded draft\n", rc=1)
    assert r.returncode == 0
    ctx = _ctx(r)
    assert ctx, "exit 0 + stderr only is invisible to the agent; needs additionalContext"
    assert "sentence_mean" in ctx, ctx
    payload = json.loads(r.stdout)
    # The nesting is load-bearing: a TOP-LEVEL additionalContext is silently
    # ignored (scar at token-guard.py:743), which would reproduce this defect.
    assert payload["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
    assert "additionalContext" not in payload, "must be nested, not top-level"


def test_a_clean_draft_emits_nothing_on_either_channel(tmp_path):
    """Control for the case above: it must not just always emit."""
    r = _run(tmp_path, IN_SCOPE, "short one.\n", rc=0, stdout="0 finding(s)")
    assert r.returncode == 0
    assert r.stderr.strip() == ""
    assert (r.stdout or "").strip() == "", r.stdout


def test_a_missing_fingerprint_is_not_reported_as_a_style_finding(tmp_path):
    """Codex minor, PR #278.

    `voiceloop score` emits `fingerprint: no fingerprint.json ...` as a finding
    and exits 1, so branching on the return code alone reported "the corpus has
    no fingerprint" as though the DRAFT had a style problem -- on every draft
    write, in any instance whose corpus was never fingerprinted. A false
    positive that arrives constantly is how a detector gets ignored.
    """
    r = _run(tmp_path, IN_SCOPE, "a draft\n", rc=1,
             stdout=("fingerprint: no fingerprint.json; run `voiceloop fingerprint` "
                     "to compute bands before scoring distance\n"
                     "1 finding(s) against 0 exemplar(s)"))
    assert r.returncode == 0
    ctx = _ctx(r)
    assert "NOT CHECKED" in ctx, ctx
    assert "fingerprint" in ctx, ctx


def test_a_real_finding_alongside_a_missing_fingerprint_is_still_reported(tmp_path):
    """Control: the fingerprint filter must not swallow genuine findings."""
    r = _run(tmp_path, IN_SCOPE, "a draft\n", rc=1,
             stdout=("fingerprint: no fingerprint.json; run `voiceloop fingerprint`\n"
                     "shape: templated opener detected\n"
                     "2 finding(s) against 0 exemplar(s)"))
    ctx = _ctx(r)
    assert "templated opener" in ctx, ctx
    assert "DETECTED" in ctx, ctx


def test_a_non_utf8_draft_exits_zero_and_says_so(tmp_path):
    """Codex minor, PR #278: this raised UnicodeDecodeError and exited 1.

    The docstring promises exit 0 on every path, and a PostToolUse hook exiting
    1 reads as a failed hook -- on a file this script has no opinion about. Not
    silent either: a draft it cannot read is a draft it did not check.
    """
    draft = tmp_path / IN_SCOPE
    draft.parent.mkdir(parents=True, exist_ok=True)
    draft.write_bytes(b"\xff\xfe not utf-8 at all \x00\x01")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    _stub_voiceloop(bin_dir, 1, "band: something")
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir(parents=True, exist_ok=True)

    env = dict(os.environ)
    env["PATH"] = _sealed_path(bin_dir)
    env["VOICE_LOOP_CORPUS"] = str(corpus_dir)
    payload = {"tool_name": "Write", "tool_input": {"file_path": str(draft)}}
    r = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                       capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "NOT CHECKED" in _ctx(r), r.stdout


def test_a_crashed_engine_is_not_a_finding_about_the_draft(tmp_path):
    """Codex major, PR #278 round 2.

    A `voiceloop` that crashes exits nonzero and prints a traceback. The
    previous version put that in the findings bucket and appended "add the skip
    marker to silence this file" -- which permanently disables the detector on a
    file that was never the problem. The tally line is the discriminator: a
    completed score always prints one.
    """
    r = _run(tmp_path, IN_SCOPE, "a draft\n", rc=2,
             stdout="Traceback (most recent call last):\n  ValueError: boom")
    assert r.returncode == 0
    ctx = _ctx(r)
    assert "NOT CHECKED" in ctx, ctx
    assert "ENGINE fault" in ctx, ctx
    assert SKIP_HINT not in ctx, "must not offer the skip marker for an engine fault"


def test_a_silent_nonzero_exit_still_says_something(tmp_path):
    """Codex minor, same round: this emitted nothing on either channel.

    A gate that fails and says nothing is indistinguishable from a gate that
    passed, which is the defect class this whole hook exists to avoid.
    """
    r = _run(tmp_path, IN_SCOPE, "a draft\n", rc=1, stdout="")
    assert r.returncode == 0
    assert "NOT CHECKED" in _ctx(r), r.stdout


def _argv_stub(bin_dir, rc, stdout):
    """A stub that also records the argv it was called with, one line."""
    stub = bin_dir / "voiceloop"
    log = bin_dir / "argv.log"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        f'echo "$*" > "{log}"\n'
        f"cat <<'OUT'\n{stdout}\nOUT\n"
        f"exit {rc}\n"
    )
    stub.chmod(0o755)
    return log


def _run_recording(tmp_path, rel_path, *, rc=0, stdout="0 finding(s) against 5 exemplar(s)"):
    draft = tmp_path / rel_path
    draft.parent.mkdir(parents=True, exist_ok=True)
    draft.write_text("a draft\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    log = _argv_stub(bin_dir, rc, stdout)
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir(exist_ok=True)
    env = dict(os.environ)
    env["PATH"] = _sealed_path(bin_dir)
    env["VOICE_LOOP_CORPUS"] = str(corpus_dir)
    payload = {"tool_name": "Write", "tool_input": {"file_path": str(draft)}}
    r = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                       capture_output=True, text=True, env=env, timeout=60)
    argv = log.read_text().split() if log.exists() else []
    return r, argv


@pytest.mark.parametrize("rel_path, channel", [
    ("outreach/linkedin-post-launch.md", "linkedin"),
    ("drafts/x-thread-hooks.md", "x"),
    ("posts/twitter/launch.md", "x"),
    ("q-system/output/substack-issue-4.md", "substack"),
    ("articles/medium-why-gates.md", "medium"),
    ("outreach/email-followup-dana.md", "email"),
    ("outreach/dm-chris.md", "dm"),
    ("social/reply-to-thread.md", "comment"),
    # PR #470 review nits, each reproduced by the reviewer as returning the wrong channel:
    ("outreach/linkedin-comment-to-dana.md", "comment"),  # nit 1: was linkedin (20-word floor)
    ("outreach/email.md", "email"),                       # nit 2: bare name was None
    ("drafts/x.md", "x"),
    ("outreach/dm.md", "dm"),
    ("outreach/LinkedIn-post.md", "linkedin"),            # nit 3: capitalised was None
    ("outreach/Email-to-dana.md", "email"),
    # kipi-system#564 review round 2: the threads rows were unpinned.
    ("drafts/threads-post-2026-10-29.md", "threads"),
    ("drafts/threads-reply-to-dana.md", "comment"),
])
def test_a_draft_with_a_known_channel_gets_the_full_review(tmp_path, rel_path, channel):
    """Founder 2026-09-29: the voice loop runs IN FULL on its own.

    `review` is the full path (score plus the gate roster and channel rules), but
    it defaults to channel x, so the channel has to come from the draft's path.
    """
    r, argv = _run_recording(tmp_path, rel_path)
    assert r.returncode == 0
    assert argv[:3] == ["review", "--channel", channel], argv


def test_a_draft_with_no_known_channel_keeps_score(tmp_path):
    """Control: an unmapped path must not be reviewed as X.

    Measured 2026-09-29 on a doc run through `review` at the x default: markdown
    and length were reported as X-timeline problems. No channel means no channel
    rules, so the unmapped path keeps the score it had.
    """
    r, argv = _run_recording(tmp_path, IN_SCOPE)
    assert r.returncode == 0
    assert argv[:1] == ["score"], argv


def test_a_linkedin_word_inside_another_name_is_not_a_channel(tmp_path):
    """Control: `x` must match as a name segment, never as a letter in a word."""
    r, argv = _run_recording(tmp_path, "outreach/fix-list-draft-plan.md")
    assert argv[:1] == ["score"], argv


def test_a_review_tally_counts_as_a_completed_run(tmp_path):
    """`review` prints `N finding(s) on channel c against M exemplar(s)`.

    The score-shaped tally regex does not match that line, so without this every
    review finding would be reported as an ENGINE fault and lose its skip hint.
    """
    r, _ = _run_recording(
        tmp_path, "outreach/linkedin-post-a.md", rc=1,
        stdout=("substance-fragment: 12 words, under the 20-word floor for linkedin\n"
                "1 finding(s) on channel linkedin against 161 exemplar(s)"))
    ctx = _ctx(r)
    assert "substance-fragment" in ctx, ctx
    assert "ENGINE fault" not in ctx, ctx
    assert SKIP_HINT in ctx, ctx
    assert "linkedin" in ctx and "review" in ctx, ctx


def test_a_real_finding_still_carries_the_skip_marker(tmp_path):
    """Control: the engine-fault branch must not swallow genuine findings."""
    r = _run(tmp_path, IN_SCOPE, "a draft\n", rc=1,
             stdout=("band: sentence_mean: 43.0 outside [5.75, 16.22]\n"
                     "1 finding(s) against 115 exemplar(s)"))
    ctx = _ctx(r)
    assert "sentence_mean" in ctx, ctx
    assert SKIP_HINT in ctx, ctx


# --------------------------------------------------------------------------- K8
# Instance voice-check.json (prd-voicegate-skeleton-2026-11-09, spec K8). The
# manifest maps a surface to a LANE and a lane to an engine_channel. The engine
# only knows the channels CHANNEL_BY_PATH emits (it defaults unknown ones to x
# rules and applies length rules only to x and threads), so a lane name must
# never reach argv: finding-6.
import shutil
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "voice-check"
TABLE_CHANNELS = {"comment", "linkedin", "x", "threads", "substack", "medium", "email", "dm"}


def _instance(tmp_path, fixture=None, raw=None):
    """A temp instance: <root>/q-consult/{canonical,config}. Never a live tree."""
    root = tmp_path / "inst"
    (root / "q-consult" / "canonical").mkdir(parents=True)
    (root / "q-consult" / "config").mkdir()
    target = root / "q-consult" / "config" / "voice-check.json"
    if fixture:
        shutil.copy(FIXTURES / fixture, target)
    if raw is not None:
        target.write_text(raw)
    return root


def _run_k8(tmp_path, root, rel_path="drafts/x-launch.md", *, rc=0,
            stdout="0 finding(s) on channel x against 5 exemplar(s)"):
    draft = root / rel_path
    draft.parent.mkdir(parents=True, exist_ok=True)
    draft.write_text("a draft\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    log = _argv_stub(bin_dir, rc, stdout)
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir(exist_ok=True)
    env = dict(os.environ)
    env["PATH"] = _sealed_path(bin_dir)
    env["VOICE_LOOP_CORPUS"] = str(corpus_dir)
    env["CLAUDE_PROJECT_DIR"] = str(root)
    # Isolation: the resolver reads a registry; point it at nothing, never the live one.
    env["KIPI_EVIDENCE_REGISTRY"] = str(tmp_path / "no-registry.json")
    payload = {"tool_name": "Write", "tool_input": {"file_path": str(draft)}}
    r = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                       capture_output=True, text=True, env=env, timeout=60)
    argv = log.read_text().split() if log.exists() else []
    return r, argv


def test_manifest_lane_picks_the_engine_channel_for_an_x_draft(tmp_path):
    """RED FIRST: today this runs channel x; the manifest says threads."""
    root = _instance(tmp_path, "voice-check.json")
    r, argv = _run_k8(tmp_path, root)
    assert argv[:3] == ["review", "--channel", "threads"], argv


def test_x_and_threads_each_read_their_own_surface_row(tmp_path):
    """split.json gives the two surfaces different lanes, so a hook that read only
    one row (or hard-coded a result) cannot satisfy both asserts."""
    root = _instance(tmp_path, "split.json")
    _, argv_x = _run_k8(tmp_path, root, "drafts/x-launch.md")
    assert argv_x[:3] == ["review", "--channel", "medium"], argv_x
    _, argv_t = _run_k8(tmp_path, root, "drafts/threads-post-1.md")
    assert argv_t[:3] == ["review", "--channel", "threads"], argv_t


def test_the_engine_never_receives_a_lane_name(tmp_path):
    root = _instance(tmp_path, "voice-check.json")
    r, argv = _run_k8(tmp_path, root)
    assert argv[2] in TABLE_CHANNELS and argv[2] != "short", argv


def test_no_manifest_leaves_the_table_result_unchanged(tmp_path):
    root = _instance(tmp_path)
    r, argv = _run_k8(tmp_path, root)
    assert argv[:3] == ["review", "--channel", "x"], argv
    assert r.stderr.strip() == "" and (r.stdout or "").strip() == ""


@pytest.mark.parametrize("fixture, reason", [
    ("malformed.json", "unreadable"),
    ("bad-channel.json", "short"),
    ("unknown-lane.json", "nowhere"),
    ("list-channel.json", "not a channel"),
])
def test_a_bad_manifest_reports_one_line_then_uses_the_table(tmp_path, fixture, reason):
    root = _instance(tmp_path, fixture)
    r, argv = _run_k8(tmp_path, root)
    assert r.returncode == 0
    assert argv[:3] == ["review", "--channel", "x"], argv
    notes = [l for l in _ctx(r).splitlines() if "voice-check.json" in l]
    assert len(notes) == 1, _ctx(r)
    assert reason in notes[0], notes[0]


def test_a_draft_with_no_table_channel_ignores_the_manifest(tmp_path):
    root = _instance(tmp_path, "voice-check.json")
    r, argv = _run_k8(tmp_path, root, "outreach/some-note.md")
    assert argv[0] == "score", argv


def test_ambiguous_instance_dirs_are_reported_then_the_table_runs(tmp_path):
    root = _instance(tmp_path, "voice-check.json")
    (root / "q-other" / "canonical").mkdir(parents=True)
    r, argv = _run_k8(tmp_path, root)
    assert argv[:3] == ["review", "--channel", "x"], argv
    assert "q-other" in _ctx(r) and "q-consult" in _ctx(r), _ctx(r)


@pytest.mark.skipif(shutil.which("voiceloop") is None, reason="voiceloop not installed")
def test_real_engine_an_overlength_x_draft_still_reports_its_length_row(tmp_path):
    """With the real package: the manifest must not turn x into a lane the engine
    does not know. Temp corpus only; the live corpus is never read."""
    root = _instance(tmp_path, "voice-check.json")
    draft = root / "drafts" / "x-long.md"
    draft.parent.mkdir(parents=True)
    draft.write_text("word " * 400)
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    env = dict(os.environ)
    env["VOICE_LOOP_CORPUS"] = str(corpus)
    env["CLAUDE_PROJECT_DIR"] = str(root)
    env["KIPI_EVIDENCE_REGISTRY"] = str(tmp_path / "no-registry.json")
    payload = {"tool_name": "Write", "tool_input": {"file_path": str(draft)}}
    r = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                       capture_output=True, text=True, env=env, timeout=60)
    assert "past-the-fold" in _ctx(r), r.stdout + r.stderr
