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
