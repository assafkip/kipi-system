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
