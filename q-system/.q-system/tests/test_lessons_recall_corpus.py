#!/usr/bin/env python3
"""RED FIRST. Issue lr-recall-names-its-corpus (prd-lessons-rail-and-up-rail,
plan 3d, CAP-3). Three wrong "the fleet has X" claims in one planning session
came from recall answering from whichever checkout the session sat on, with no
line saying which. Now the corpus is explicit (--corpus, then KIPI_LESSONS_DIR,
then the file-relative default), printed on every search, and --both spans the
KIPI_LESSONS_CORPORA entries that exist, deduplicated by real path.

Every corpus here is a tmp directory. tf-idf keeps only terms with df > 1, so
each fixture corpus holds three lessons that share vocabulary.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
RECALL = SCRIPTS / "lessons_recall.py"
sys.path.insert(0, str(SCRIPTS))
import lessons_recall  # noqa: E402


def _lesson(d: Path, name: str, title: str, body: str):
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.md").write_text(f"---\ntitle: {title}\ndate: 2026-08-01\n---\n{body}\n")


def _corpus_a(tmp_path):
    d = tmp_path / "kipi" / "q-system" / "lessons"
    _lesson(d, "gate-fails-closed", "A gate fails closed", "a gate that cannot fail is decoration; every gate fails closed and names the input that turns it red")
    _lesson(d, "gate-mutation", "Mutate the gate", "mutation testing proves the gate can fail; a green gate nobody saw red is decoration")
    _lesson(d, "lint-threes", "Lint the rule of three", "a lint catches the rule of three; the lint fails closed on comma triplets")
    return d


def _corpus_b(tmp_path):
    d = tmp_path / "consulting" / "q-system" / "lessons"
    _lesson(d, "invoice-late", "Invoices go out on delivery day", "send the invoice the day the deliverable ships; a late invoice is a late payment")
    _lesson(d, "invoice-terms", "Net-15 on every invoice", "every invoice carries net-15 terms; the invoice template pins it")
    # "invoice" sits in two of three files on purpose: tf-idf gives a term that is
    # in EVERY document zero weight, so a fixture with it everywhere never scores.
    _lesson(d, "proposal-scope", "Scope on the proposal", "a proposal names its scope line by line; the deliverable mirrors the proposal")
    return d


def _run(args, env_extra=None, cwd=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("KIPI_LESSONS")}
    env.update(env_extra or {})
    return subprocess.run([sys.executable, str(RECALL), *args], capture_output=True, text=True, env=env, cwd=cwd)


def test_search_prints_which_corpus_it_read(tmp_path):
    a = _corpus_a(tmp_path)
    r = _run(["--corpus", str(a), "search", "gate fails closed"])
    assert r.returncode == 0, r.stderr
    first = r.stdout.splitlines()[0]
    assert first.startswith("corpus: ") and str(a.resolve()) in first and "(3 lessons)" in first, first
    assert "gate-fails-closed" in r.stdout


def test_precedence_is_flag_then_env_then_default(tmp_path):
    a, b = _corpus_a(tmp_path), _corpus_b(tmp_path)
    flag = _run(["--corpus", str(a), "search", "invoice"], {"KIPI_LESSONS_DIR": str(b)})
    assert str(a.resolve()) in flag.stdout.splitlines()[0], "--corpus outranks KIPI_LESSONS_DIR"
    env = _run(["search", "invoice"], {"KIPI_LESSONS_DIR": str(b)})
    assert str(b.resolve()) in env.stdout.splitlines()[0] and "invoice-late" in env.stdout, "KIPI_LESSONS_DIR outranks the default"
    default = _run(["search", "invoice"])
    assert str(lessons_recall.default_corpus()) in default.stdout.splitlines()[0]


def test_same_query_against_two_corpora_yields_different_hits_and_says_which(tmp_path):
    a, b = _corpus_a(tmp_path), _corpus_b(tmp_path)
    ra = _run(["--corpus", str(a), "search", "invoice terms"])
    rb = _run(["--corpus", str(b), "search", "invoice terms"])
    assert "invoice-terms" not in ra.stdout and "invoice-terms" in rb.stdout
    assert str(a.resolve()) in ra.stdout.splitlines()[0] and str(b.resolve()) in rb.stdout.splitlines()[0]


def test_both_adds_every_existing_corpora_entry_and_tags_each_hit(tmp_path):
    a, b = _corpus_a(tmp_path), _corpus_b(tmp_path)
    missing = tmp_path / "absent" / "lessons"
    r = _run(["--corpus", str(a), "--both", "search", "invoice gate"],
             {"KIPI_LESSONS_CORPORA": f"{b}:{missing}"})
    assert r.returncode == 0, r.stderr
    head = r.stdout.splitlines()[0]
    assert head.startswith("corpus: ") and f"{a.resolve()} (3)" in head and f"{b.resolve()} (3)" in head, head
    assert f"corpus missing: {missing}" in r.stdout
    assert "[kipi]" in r.stdout and "[consulting]" in r.stdout, r.stdout


def test_both_dedups_a_symlinked_duplicate_by_real_path(tmp_path):
    a = _corpus_a(tmp_path)
    link = tmp_path / "link-to-kipi"
    link.symlink_to(a.parent.parent)
    linked = link / "q-system" / "lessons"
    plain = _run(["--corpus", str(a), "search", "gate"])
    both = _run(["--corpus", str(a), "--both", "search", "gate"], {"KIPI_LESSONS_CORPORA": str(linked)})
    head = both.stdout.splitlines()[0]
    assert head.count("(3") == 1 and "+" not in head, f"the symlinked copy must be searched once: {head}"
    plain_hits = [l for l in plain.stdout.splitlines()[1:] if l.strip().startswith(("0.", "1."))]
    both_hits = [l for l in both.stdout.splitlines()[1:] if l.strip().startswith(("0.", "1."))]
    assert [h.split()[0] for h in plain_hits] == [h.split()[0] for h in both_hits], "ranking and scores unchanged"
    assert len(both_hits) == len(plain_hits)


def test_both_tags_hits_even_when_dedup_leaves_one_corpus(tmp_path):
    """Codex (issue 4, both passes): tagging keyed on the corpus COUNT went
    untagged when the extra entries were missing or symlinked duplicates."""
    a = _corpus_a(tmp_path)
    link = tmp_path / "link-to-kipi"
    link.symlink_to(a.parent.parent)
    r = _run(["--corpus", str(a), "--both", "search", "gate"],
             {"KIPI_LESSONS_CORPORA": f"{link / 'q-system' / 'lessons'}:{tmp_path / 'absent'}"})
    hits = [l for l in r.stdout.splitlines() if l.strip().startswith(("0.", "1."))]
    assert hits and all("[kipi]" in h for h in hits), r.stdout


def test_both_makes_similar_duplicates_and_stats_read_every_corpus(tmp_path):
    """Codex adversarial (issue 4): the corpus line claimed every corpus was
    read while similar, duplicates and stats read only the first."""
    a, b = _corpus_a(tmp_path), _corpus_b(tmp_path)
    env = {"KIPI_LESSONS_CORPORA": str(b)}
    draft = tmp_path / "draft.md"
    draft.write_text("---\ntitle: draft\n---\nsend the invoice the day the deliverable ships; a late invoice is a late payment\n")
    sim = _run(["--corpus", str(a), "--both", "similar", str(draft)], env)
    assert sim.returncode == 2 and "[consulting]" in sim.stdout, "a draft matching the SECOND corpus must merge"
    (b / "gate-fails-closed-copy.md").write_text((a / "gate-fails-closed.md").read_text())
    dup = _run(["--corpus", str(a), "--both", "duplicates"], env)
    lines = dup.stdout.splitlines()
    assert "  1.00  [kipi] gate-fails-closed.md" in lines and "        [consulting] gate-fails-closed-copy.md" in lines, dup.stdout
    pairs = int(lines[1].split()[0])
    assert pairs >= 1
    single = _run(["--corpus", str(a), "duplicates"]).stdout.splitlines()[1]
    assert int(single.split()[0]) < pairs, "the cross-corpus pair exists only when both corpora are read"
    st = _run(["--corpus", str(a), "--both", "stats"], env)
    assert "lessons          7" in st.stdout and f"duplicate pairs  {pairs}" in st.stdout, st.stdout


def test_resolve_corpora_is_the_single_place_precedence_lives(tmp_path):
    a, b = _corpus_a(tmp_path), _corpus_b(tmp_path)
    env = {"KIPI_LESSONS_DIR": str(b), "KIPI_LESSONS_CORPORA": f"{a}:{a}:{tmp_path / 'nope'}"}
    found, missing = lessons_recall.resolve_corpora(None, both=True, env=env)
    assert found == [str(b.resolve()), str(a.resolve())]
    assert missing == [str(tmp_path / "nope")]
    found, _ = lessons_recall.resolve_corpora(str(a), both=False, env=env)
    assert found == [str(a.resolve())]


def test_existing_subcommands_and_exit_codes_are_unchanged(tmp_path):
    a = _corpus_a(tmp_path)
    draft = tmp_path / "draft.md"
    draft.write_text("---\ntitle: draft\n---\na gate that cannot fail is decoration; every gate fails closed and names the input that turns it red\n")
    assert _run(["--corpus", str(a), "similar", str(draft)]).returncode == 2, "MERGE still exits 2"
    far = tmp_path / "far.md"
    far.write_text("---\ntitle: far\n---\nunrelated words about penguins and glaciers\n")
    assert _run(["--corpus", str(a), "similar", str(far)]).returncode == 0
    d = _run(["--corpus", str(a), "duplicates"])
    assert d.returncode == 0 and "pair(s) at or above" in d.stdout
    s = _run(["--corpus", str(a), "stats"])
    assert s.returncode == 0 and "lessons          3" in s.stdout
    assert lessons_recall.search("gate", lessons_dir=str(a))[0][1].endswith(".md"), "the importable search keeps its (score, path) shape"


def test_the_one_importing_caller_still_runs():
    callers = subprocess.run(["grep", "-rl", "lessons_recall", str(HERE.parent.parent.parent / "plugins"), str(SCRIPTS)],
                             capture_output=True, text=True).stdout.split()
    py = [c for c in callers if c.endswith("improve_ground.py")]
    assert py, callers
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", str(Path(py[0]).with_name("test_improve_ground.py"))],
                       capture_output=True, text=True, env=dict(os.environ, KIPI_SELFTEST_INNER="1"))
    assert r.returncode == 0, r.stdout[-800:]


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
