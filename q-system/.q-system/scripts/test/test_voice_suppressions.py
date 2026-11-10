#!/usr/bin/env python3
"""K7: one bounded per-instance voice suppression file (prd-voicegate-skeleton-2026-11-09).

voice-lint.py is a BLOCKING gate that ships to every instance. The failure this file
exists to prevent is the quiet one: a malformed suppression file, a missing field or
a bad date that either suppresses something it should not, or raises and exits 1,
which Claude Code treats as non-blocking. Either way the gate fails open for every
draft. So every bad case below asserts three things: the draft is still judged (exit
2 for a blocking draft, never 1), the bad row is named in one report line, and the
suppression did not happen.

TEST ISOLATION (fable-discipline): every case builds its own instance under tmp_path,
sets CLAUDE_PROJECT_DIR to it, and points KIPI_EVIDENCE_REGISTRY at a file that does
not exist, so the resolver never reads the live registry. No case reads a real
instance's config. Dates are computed from the real UTC clock, because the reader
takes no clock override: a test-only parameter on a gate is a bypass surface.
"""
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
VOICE_LINT = SCRIPTS / "voice-lint.py"
SUBSTANCE = SCRIPTS / "voice-substance-lint.py"
READER = SCRIPTS / "voice_suppressions.py"

TODAY = datetime.now(timezone.utc).date()
DRAFT = "drafts/x-launch.md"  # inside is_published_path (`.*/x[-_][^/]*\.md$`)
# Blocks today: a banned word and an emdash, both BLOCK-class in voice-lint.
BLOCKING_BODY = "We leverage the queue — every night.\n"
# Warns today in voice-substance-lint: 100 words, zero anchors.
NO_ANCHOR_BODY = ("this is a plain sentence with nothing in it at all and it goes on. " * 7) + "\n"


def _d(days):
    return (TODAY + timedelta(days=days)).isoformat()


def _row(path=DRAFT, **over):
    row = {"path": path, "reason": "fixture draft kept as written",
           "owner": "sana", "created": _d(-1), "expires": _d(5)}
    row.update(over)
    return {k: v for k, v in row.items() if v is not _DROP}


_DROP = object()


def _instance(tmp_path, rows=None, raw=None):
    """<root>/q-consult/{canonical,config}; writes the suppression file only if asked."""
    root = tmp_path / "inst"
    (root / "q-consult" / "canonical").mkdir(parents=True)
    (root / "q-consult" / "config").mkdir()
    target = root / "q-consult" / "config" / "voice-suppressions.json"
    if rows is not None:
        target.write_text(json.dumps({"suppressions": rows}))
    if raw is not None:
        target.write_text(raw)
    return root


def _env(tmp_path, root):
    env = dict(os.environ)
    env.pop("CLAUDE_PROJECT_DIR", None)
    if root is not None:
        env["CLAUDE_PROJECT_DIR"] = str(root)
    env["KIPI_EVIDENCE_REGISTRY"] = str(tmp_path / "no-registry.json")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _hook(script, tmp_path, root, body, rel=DRAFT, base=None):
    base = base if base is not None else root
    draft = base / rel
    draft.parent.mkdir(parents=True, exist_ok=True)
    draft.write_text(body)
    payload = {"tool_name": "Write", "tool_input": {"file_path": str(draft)}}
    return subprocess.run([sys.executable, str(script)], input=json.dumps(payload),
                          capture_output=True, text=True, env=_env(tmp_path, root),
                          timeout=60)


def _ctx(r):
    out = (r.stdout or "").strip()
    if not out:
        return ""
    return json.loads(out)["hookSpecificOutput"]["additionalContext"]


def _said(r):
    return r.stderr + "\n" + _ctx(r)


# ------------------------------------------------------------------ voice-lint

def test_a_listed_path_is_skipped_by_voice_lint_and_says_who_and_until_when(tmp_path):
    """RED FIRST: today voice-lint blocks this draft (exit 2)."""
    root = _instance(tmp_path, rows=[_row()])
    r = _hook(VOICE_LINT, tmp_path, root, BLOCKING_BODY)
    assert r.returncode == 0, r.stderr
    said = _said(r)
    assert "sana" in said and "fixture draft kept as written" in said and _d(5) in said, said
    assert "violation" not in said, said
    # The skip must reach the channel the agent reads on exit 0.
    assert "SUPPRESSED" in _ctx(r), r.stdout


def test_a_row_spanning_exactly_30_days_still_skips(tmp_path):
    """Boundary control for the 31-day bad row below: 30 is allowed, so the bound is
    `> 30`, not `>= 30`."""
    root = _instance(tmp_path, rows=[_row(created=_d(-1), expires=_d(29))])
    r = _hook(VOICE_LINT, tmp_path, root, BLOCKING_BODY)
    assert r.returncode == 0, r.stderr


def test_an_expired_row_does_not_skip_and_the_path_is_reported(tmp_path):
    root = _instance(tmp_path, rows=[_row(created=_d(-10), expires=_d(-1))])
    r = _hook(VOICE_LINT, tmp_path, root, BLOCKING_BODY)
    assert r.returncode == 2, (r.returncode, r.stderr)
    assert "violation" in r.stderr
    assert "expired" in r.stderr and DRAFT in r.stderr, r.stderr


BAD_ROWS = [
    ("missing owner", [_row(owner=_DROP)], "owner"),
    ("unknown owner", [_row(owner="someone")], "owner"),
    ("owner is a list", [_row(owner=["sana"])], "owner"),
    ("missing reason", [_row(reason=_DROP)], "reason"),
    ("empty reason", [_row(reason="   ")], "reason"),
    ("bad date", [_row(expires="2026-13-45")], "date"),
    ("words for a date", [_row(created="yesterday")], "date"),
    ("compact date", [_row(expires=_d(5).replace("-", ""))], "date"),
    ("expires equal to today", [_row(expires=_d(0))], "expired"),
    ("expires over 30 days after created", [_row(created=_d(-1), expires=_d(30))], "30"),
    ("created in the future stretches the window", [_row(created=_d(20), expires=_d(45))], "created"),
    ("expires before created", [_row(created=_d(-1), expires=_d(-3))], "created"),
    ("a glob path", [_row(path="drafts/*.md")], "glob"),
    ("a bracket glob", [_row(path="drafts/x-launc[h].md")], "glob"),
    ("a parent segment", [_row(path="drafts/../drafts/x-launch.md")], ".."),
    ("a dot-slash path", [_row(path="./" + DRAFT)], "exact"),
    ("a row that is not an object", ["drafts/x-launch.md"], "object"),
]


@pytest.mark.parametrize("label, rows, reason", BAD_ROWS, ids=[b[0] for b in BAD_ROWS])
def test_a_bad_row_suppresses_nothing_is_named_and_never_exits_1(tmp_path, label, rows, reason):
    root = _instance(tmp_path, rows=rows)
    r = _hook(VOICE_LINT, tmp_path, root, BLOCKING_BODY)
    assert r.returncode == 2, (label, r.returncode, r.stderr)
    assert "violation" in r.stderr, r.stderr
    reports = [l for l in r.stderr.splitlines() if "voice-suppressions.json" in l]
    assert len(reports) == 1, r.stderr
    assert reason in reports[0], reports[0]


def test_an_absolute_path_row_suppresses_nothing(tmp_path):
    """Built per run: the absolute path must be the draft's own, or it proves nothing."""
    root = _instance(tmp_path)
    rows = [_row(path=str(root / DRAFT))]
    (root / "q-consult" / "config" / "voice-suppressions.json").write_text(
        json.dumps({"suppressions": rows}))
    r = _hook(VOICE_LINT, tmp_path, root, BLOCKING_BODY)
    assert r.returncode == 2, r.stderr
    reports = [l for l in r.stderr.splitlines() if "voice-suppressions.json" in l]
    assert len(reports) == 1 and "absolute" in reports[0], r.stderr


BAD_FILES = [
    ("malformed json", "{not json", "unreadable"),
    ("top level list", json.dumps([_row()]), "suppressions"),
    ("suppressions not a list", json.dumps({"suppressions": {"path": DRAFT}}), "suppressions"),
    # 3.12 raises RecursionError here (unreadable); 3.14 parses it into a list (top
    # level). Either way: one line, nothing suppressed, never exit 1.
    ("deep nesting", "[" * 100000 + "]" * 100000, "suppressing nothing"),
    ("empty file", "", "unreadable"),
]


@pytest.mark.parametrize("label, raw, reason", BAD_FILES, ids=[b[0] for b in BAD_FILES])
def test_a_bad_file_suppresses_nothing_is_named_and_never_exits_1(tmp_path, label, raw, reason):
    root = _instance(tmp_path, raw=raw)
    r = _hook(VOICE_LINT, tmp_path, root, BLOCKING_BODY)
    assert r.returncode == 2, (label, r.returncode, r.stderr[-400:])
    reports = [l for l in r.stderr.splitlines() if "voice-suppressions.json" in l]
    assert len(reports) == 1, r.stderr[-800:]
    assert reason in reports[0], reports[0]


def test_one_unhashable_owner_does_not_void_the_valid_rows(tmp_path):
    """Review finding-1: `[..] in frozenset` raised, and every row stopped skipping."""
    root = _instance(tmp_path, rows=[_row(path="drafts/other.md", owner={"a": 1}), _row()])
    r = _hook(VOICE_LINT, tmp_path, root, BLOCKING_BODY)
    assert r.returncode == 0, r.stderr
    bad = [l for l in r.stderr.splitlines() if "row 0" in l]
    assert len(bad) == 1 and "owner" in bad[0], r.stderr


def test_a_fifo_in_place_of_the_file_suppresses_nothing_and_does_not_hang(tmp_path):
    """Review finding-4: open() on a FIFO blocks until the hook timeout, which is a
    fail-open exit for a PostToolUse gate."""
    root = _instance(tmp_path)
    os.mkfifo(root / "q-consult" / "config" / "voice-suppressions.json")
    r = _hook(VOICE_LINT, tmp_path, root, BLOCKING_BODY)
    assert r.returncode == 2, r.stderr
    assert any("not a regular file" in l for l in r.stderr.splitlines()), r.stderr


def test_a_directory_in_place_of_the_file_suppresses_nothing(tmp_path):
    root = _instance(tmp_path)
    (root / "q-consult" / "config" / "voice-suppressions.json").mkdir()
    r = _hook(VOICE_LINT, tmp_path, root, BLOCKING_BODY)
    assert r.returncode == 2, r.stderr
    assert any("voice-suppressions.json" in l for l in r.stderr.splitlines()), r.stderr


def test_the_cli_reports_a_bad_file_and_exits_2_not_1(tmp_path):
    root = _instance(tmp_path, raw="{not json")
    draft = root / DRAFT
    draft.parent.mkdir(parents=True)
    draft.write_text(BLOCKING_BODY)
    r = subprocess.run([sys.executable, str(VOICE_LINT), str(draft)], capture_output=True,
                       text=True, env=_env(tmp_path, root), timeout=60)
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    assert "voice-suppressions.json" in r.stdout + r.stderr


def test_the_cli_says_suppressed_not_clean(tmp_path):
    root = _instance(tmp_path, rows=[_row()])
    draft = root / DRAFT
    draft.parent.mkdir(parents=True)
    draft.write_text(BLOCKING_BODY)
    r = subprocess.run([sys.executable, str(VOICE_LINT), str(draft)], capture_output=True,
                       text=True, env=_env(tmp_path, root), timeout=60)
    assert r.returncode == 0, r.stdout
    assert "SUPPRESSED" in r.stdout and "clean" not in r.stdout, r.stdout


# ---------------------------------------------------------- markers and no file

def test_without_the_file_a_blocking_draft_reads_exactly_as_today(tmp_path):
    """Today's contract, pinned: exit 2, the report on stderr, nothing on stdout."""
    root = _instance(tmp_path)
    r = _hook(VOICE_LINT, tmp_path, root, BLOCKING_BODY)
    assert r.returncode == 2
    assert r.stdout == ""
    assert r.stderr.startswith("voice-lint: "), r.stderr
    assert "suppress" not in r.stderr.lower() and "marker" not in r.stderr.lower(), r.stderr


def test_without_the_file_the_in_file_marker_still_skips_silently(tmp_path):
    root = _instance(tmp_path)
    r = _hook(VOICE_LINT, tmp_path, root, BLOCKING_BODY + "<!-- voice-lint-skip -->\n")
    assert (r.returncode, r.stdout, r.stderr) == (0, "", "")


def test_outside_any_instance_the_marker_still_skips_silently(tmp_path):
    """No CLAUDE_PROJECT_DIR and no git: discovery finds no root, today's behaviour."""
    plain = tmp_path / "plain"
    r = _hook(VOICE_LINT, tmp_path, None, BLOCKING_BODY + "<!-- voice-lint-skip -->\n",
              base=plain)
    assert (r.returncode, r.stdout, r.stderr) == (0, "", "")


def test_with_the_file_the_in_file_marker_no_longer_skips_and_the_lint_says_so(tmp_path):
    root = _instance(tmp_path, rows=[_row(path="drafts/some-other-draft.md")])
    r = _hook(VOICE_LINT, tmp_path, root, BLOCKING_BODY + "<!-- voice-lint-skip -->\n")
    assert r.returncode == 2, r.stderr
    assert "violation" in r.stderr
    assert "voice-lint-skip" in r.stderr and "ignored" in r.stderr, r.stderr


def test_a_malformed_file_still_turns_markers_off(tmp_path):
    """Breaking the file must not be a way to get the old bypass back."""
    root = _instance(tmp_path, raw="{not json")
    r = _hook(VOICE_LINT, tmp_path, root, BLOCKING_BODY + "<!-- voice-lint-skip -->\n")
    assert r.returncode == 2, r.stderr
    assert "ignored" in r.stderr, r.stderr


def test_an_ambiguous_instance_with_the_file_suppresses_nothing_and_says_so(tmp_path):
    root = _instance(tmp_path, rows=[_row()])
    (root / "q-other" / "canonical").mkdir(parents=True)
    r = _hook(VOICE_LINT, tmp_path, root, BLOCKING_BODY + "<!-- voice-lint-skip -->\n")
    assert r.returncode == 2, r.stderr
    assert "NOT READ" in r.stderr and "q-other" in r.stderr, r.stderr


# -------------------------------------------------------- voice-substance-lint

def test_substance_lint_skips_a_listed_path_and_prints_the_row(tmp_path):
    bare = _hook(SUBSTANCE, tmp_path / "a", _instance(tmp_path / "a"), NO_ANCHOR_BODY)
    assert "no-substance-anchor" in bare.stderr, "control: this draft must warn without a row"
    root = _instance(tmp_path / "b", rows=[_row()])
    r = _hook(SUBSTANCE, tmp_path / "b", root, NO_ANCHOR_BODY)
    assert r.returncode == 0
    assert "no-substance-anchor" not in _said(r), _said(r)
    assert "sana" in _ctx(r) and _d(5) in _ctx(r), r.stdout


def test_substance_lint_reports_a_bad_row_and_still_warns(tmp_path):
    root = _instance(tmp_path, rows=[_row(owner=_DROP)])
    r = _hook(SUBSTANCE, tmp_path, root, NO_ANCHOR_BODY)
    assert r.returncode == 0
    assert "no-substance-anchor" in r.stderr
    assert sum("voice-suppressions.json" in l for l in r.stderr.splitlines()) == 1, r.stderr


def test_substance_lint_ignores_the_marker_where_the_file_exists(tmp_path):
    body = NO_ANCHOR_BODY + "<!-- voice-lint-skip -->\n"
    plain = _hook(SUBSTANCE, tmp_path / "a", _instance(tmp_path / "a"), body)
    assert (plain.returncode, plain.stdout, plain.stderr) == (0, "", "")
    root = _instance(tmp_path / "b", rows=[_row(path="drafts/other.md")])
    r = _hook(SUBSTANCE, tmp_path / "b", root, body)
    assert "no-substance-anchor" in r.stderr and "ignored" in r.stderr, r.stderr


# --------------------------------------------------------------- the reader

def _reader():
    spec = importlib.util.spec_from_file_location("_k7_reader_under_test", READER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_reader_never_raises_on_a_symlink_loop(tmp_path, monkeypatch):
    root = _instance(tmp_path)
    target = root / "q-consult" / "config" / "voice-suppressions.json"
    target.symlink_to(target)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    monkeypatch.setenv("KIPI_EVIDENCE_REGISTRY", str(tmp_path / "no-registry.json"))
    decision = _reader().check(str(root / DRAFT))
    assert decision.present and not decision.skip
    assert decision.notes and "voice-suppressions.json" in decision.notes[0]


def test_the_reader_bounds_an_oversized_file(tmp_path, monkeypatch):
    rows = [_row(path=f"drafts/x-{i}.md") for i in range(4000)] + [_row()]
    root = _instance(tmp_path, rows=rows)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    monkeypatch.setenv("KIPI_EVIDENCE_REGISTRY", str(tmp_path / "no-registry.json"))
    decision = _reader().check(str(root / DRAFT))
    assert decision.present and not decision.skip
    assert len(decision.notes) == 1 and "too large" in decision.notes[0], decision.notes


def test_many_bad_rows_are_reported_in_a_bounded_number_of_lines(tmp_path, monkeypatch):
    rows = [_row(path=f"drafts/x-{i}.md", owner="nobody") for i in range(40)]
    root = _instance(tmp_path, rows=rows)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    monkeypatch.setenv("KIPI_EVIDENCE_REGISTRY", str(tmp_path / "no-registry.json"))
    decision = _reader().check(str(root / DRAFT))
    assert not decision.skip
    assert len(decision.notes) <= 6 and "35 more" in decision.notes[-1], decision.notes


def test_many_expired_rows_are_reported_in_a_bounded_number_of_lines(tmp_path, monkeypatch):
    """Review finding-5: one note per expired row put 600 KB into additionalContext."""
    rows = [_row(created=_d(-20), expires=_d(-1)) for _ in range(40)]
    root = _instance(tmp_path, rows=rows)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    monkeypatch.setenv("KIPI_EVIDENCE_REGISTRY", str(tmp_path / "no-registry.json"))
    decision = _reader().check(str(root / DRAFT))
    assert not decision.skip
    assert len(decision.notes) <= 6 and "35 more expired" in decision.notes[-1], decision.notes


# --------------------------------------------------------------------- census

_MARKER_RE = re.compile(r"\bvoice[\w-]*-skip\b")


def _marker_readers_missing_the_reader(scripts_dir):
    """Every non-test script under scripts_dir that names a voice skip marker must load
    voice_suppressions.py. A script that names a marker and not the reader is a second
    suppression path the file cannot see."""
    missing, definers = [], []
    for path in sorted(scripts_dir.rglob("*")):
        rel = path.relative_to(scripts_dir)
        if not path.is_file() or path.suffix in (".pyc", ".json", ".md"):
            continue
        if any(part in ("test", "tests", "fixtures", "__pycache__") for part in rel.parts):
            continue
        if path.name.startswith(("test_", "test-")):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if not _MARKER_RE.search(text):
            continue
        definers.append(str(rel))
        if path.name != "voice_suppressions.py" and not _loads_the_reader(text):
            missing.append(str(rel))
    return definers, missing


def _loads_the_reader(text):
    """A real load, read from the AST: the string 'voice_suppressions.py' as code (a
    comment is not in the AST) and a `.check(` call. Review finding-3: a substring test
    passed a file that only named the reader in a comment. A shell script cannot load
    a Python module, so a marker in one is always reported."""
    import ast
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return False
    names = {n.value for n in ast.walk(tree)
             if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    calls = {n.func.attr for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    return "voice_suppressions.py" in names and "check" in calls


def test_every_script_that_names_a_voice_skip_marker_loads_the_reader():
    definers, missing = _marker_readers_missing_the_reader(SCRIPTS)
    # Non-empty floor: a census that finds nothing passes by finding nothing.
    for name in ("voice-lint.py", "voice-substance-lint.py", "voiceloop-band-lint.py"):
        assert name in definers, definers
    assert missing == [], f"marker readers that bypass voice_suppressions.py: {missing}"


def test_the_census_catches_a_marker_reader_that_skips_the_reader(tmp_path):
    """Negative control: the census must be able to fail."""
    (tmp_path / "rogue-lint.py").write_text('SKIP = "voice-lint-skip"\n')
    (tmp_path / "comment-lint.py").write_text('SKIP = "voice-lint-skip"  # voice_suppressions.py\n')
    (tmp_path / "rogue.sh").write_text('grep -q voice-lint-skip "$1" && exit 0\n')
    (tmp_path / "good-lint.py").write_text(
        'SKIP = "voice-lint-skip"\nTARGET = "voice_suppressions.py"\nm.check(path)\n')
    _, missing = _marker_readers_missing_the_reader(tmp_path)
    assert missing == ["comment-lint.py", "rogue-lint.py", "rogue.sh"], missing


def test_a_draft_outside_the_instance_root_keeps_its_marker(tmp_path):
    """ASK-4277. Instance A holds the file; the draft lives in sibling repo B. No legal
    row can name it (.. and absolute paths are refused), so turning its marker off
    leaves no way to suppress it. Out of root, markers behave as before K7."""
    root = _instance(tmp_path, rows=[_row(path="drafts/some-other-draft.md")])
    sibling = tmp_path / "repo-b"
    r = _hook(VOICE_LINT, tmp_path, root, BLOCKING_BODY + "<!-- voice-lint-skip -->\n",
              base=sibling)
    assert (r.returncode, r.stdout, r.stderr) == (0, "", "")


def test_an_out_of_root_draft_without_a_marker_still_blocks(tmp_path):
    """The negative control: the silent exit above is the marker, not a blind lint."""
    root = _instance(tmp_path, rows=[_row(path="drafts/some-other-draft.md")])
    r = _hook(VOICE_LINT, tmp_path, root, BLOCKING_BODY, base=tmp_path / "repo-b")
    assert r.returncode == 2, r.stderr
    assert "ignored" not in r.stderr, r.stderr


STOP_GATE = SCRIPTS / "voice-stop-gate.py"


def _stop_gate(tmp_path, root, draft):
    """Run a COPY of the Stop gate placed in the instance, so INSTANCE_ROOT is <root>."""
    scripts = root / "q-system" / ".q-system" / "scripts"
    if not scripts.exists():
        shutil.copytree(SCRIPTS, scripts, ignore=shutil.ignore_patterns("test", "__pycache__"))
    transcript = tmp_path / "t.jsonl"
    msg = {"role": "assistant", "content": [{"type": "text", "text":
           "Here's the post:\n\n" + draft}]}
    transcript.write_text(json.dumps({"type": "assistant", "message": msg}) + "\n")
    payload = {"transcript_path": str(transcript), "session_id": "s"}
    return subprocess.run([sys.executable, str(scripts / "voice-stop-gate.py")],
                          input=json.dumps(payload), capture_output=True, text=True,
                          env=_env(tmp_path, root), timeout=120)


def test_the_stop_gate_does_not_honor_a_marker_where_the_file_exists(tmp_path):
    """ASK-4277 review finding 1: the Stop gate lints a temp draft. Out of root it would
    clear on a bare marker, which voice-enforcement.md says this gate never honors."""
    root = _instance(tmp_path, rows=[_row(path="drafts/some-other-draft.md")])
    body = BLOCKING_BODY * 3
    marked = _stop_gate(tmp_path, root, body + "<!-- voice-lint-skip -->\n")
    plain = _stop_gate(tmp_path, root, body)
    assert plain.returncode == 2, plain.stderr  # control: the gate does block this body
    assert marked.returncode == 2, marked.stderr
