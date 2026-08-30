"""Tests for findings_writer.py.

The writer is the deterministic normalization layer between Codex output and
the findings JSONL file. These tests lock every validation rule the schema
relies on, plus the disposition-update invariants that `/prd-approve` depends
on for the gate check.
"""

from __future__ import annotations

import json
from pathlib import Path


def _seed_prd_spec(repo: Path, prd_id: str) -> Path:
    """Write a minimal PRD spec mirroring the runner's template shape.

    Codex-sourced `add` calls stamp `codex_reviewed_at` onto the PRD
    frontmatter as a side effect. Tests that invoke `add --source codex-*`
    therefore need a real spec file to stamp against.
    """
    prds_dir = repo / ".prd-os/prds"
    prds_dir.mkdir(parents=True, exist_ok=True)
    path = prds_dir / f"{prd_id}.md"
    path.write_text(
        "---\n"
        f"id: {prd_id}\n"
        f"title: {prd_id} fixture\n"
        "status: draft\n"
        f"findings_path: .prd-os/findings/{prd_id}-findings.jsonl\n"
        "---\n\n"
        f"Fixture for {prd_id}.\n"
    )
    return path


def _bootstrap(repo: Path, write_config, *, prd_ids: tuple[str, ...] = ("prd-x",)) -> None:
    write_config(
        repo,
        {
            "config_schema_version": 1,
            "prds_dir": ".prd-os/prds",
            "issues_dir": ".prd-os/issues",
            "findings_dir": ".prd-os/findings",
            "state_dir": ".claude/state",
        },
    )
    for prd_id in prd_ids:
        _seed_prd_spec(repo, prd_id)


def _findings_file(repo: Path, prd_id: str) -> Path:
    return repo / ".prd-os/findings" / f"{prd_id}-findings.jsonl"


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# add
# ---------------------------------------------------------------------------


def test_add_assigns_sequential_ids(fake_repo, write_config, run_findings_writer):
    _bootstrap(fake_repo, write_config)
    stdin = json.dumps([
        {"severity": "blocker", "body": "first concern"},
        {"severity": "minor", "body": "second concern"},
    ])
    r = run_findings_writer(
        fake_repo, "add", "prd-x", "--source", "codex-review", stdin_text=stdin
    )
    assert r.returncode == 0, r.stderr
    recs = _read_jsonl(_findings_file(fake_repo, "prd-x"))
    assert [r["id"] for r in recs] == ["finding-1", "finding-2"]
    assert all(r["disposition"] == "pending" for r in recs)
    assert all(r["prd_id"] == "prd-x" for r in recs)
    assert all(r["source"] == "codex-review" for r in recs)


def test_add_continues_ids_across_invocations(fake_repo, write_config, run_findings_writer):
    _bootstrap(fake_repo, write_config)
    run_findings_writer(
        fake_repo,
        "add",
        "prd-x",
        "--source",
        "codex-review",
        stdin_text=json.dumps([{"severity": "minor", "body": "first"}]),
    )
    run_findings_writer(
        fake_repo,
        "add",
        "prd-x",
        "--source",
        "codex-adversarial",
        stdin_text=json.dumps([{"severity": "major", "body": "second"}]),
    )
    recs = _read_jsonl(_findings_file(fake_repo, "prd-x"))
    assert [r["id"] for r in recs] == ["finding-1", "finding-2"]
    assert recs[0]["source"] == "codex-review"
    assert recs[1]["source"] == "codex-adversarial"


def test_add_rejects_unknown_severity(fake_repo, write_config, run_findings_writer):
    _bootstrap(fake_repo, write_config)
    r = run_findings_writer(
        fake_repo,
        "add",
        "prd-x",
        "--source",
        "codex-review",
        stdin_text=json.dumps([{"severity": "critical", "body": "nope"}]),
    )
    assert r.returncode == 2
    assert "severity" in r.stderr


def test_add_rejects_empty_body(fake_repo, write_config, run_findings_writer):
    _bootstrap(fake_repo, write_config)
    r = run_findings_writer(
        fake_repo,
        "add",
        "prd-x",
        "--source",
        "codex-review",
        stdin_text=json.dumps([{"severity": "major", "body": "   "}]),
    )
    assert r.returncode == 2
    assert "body" in r.stderr


def test_add_rejects_unknown_source(fake_repo, write_config, run_findings_writer):
    _bootstrap(fake_repo, write_config)
    r = run_findings_writer(
        fake_repo,
        "add",
        "prd-x",
        "--source",
        "gpt-review",
        stdin_text=json.dumps([{"severity": "major", "body": "x"}]),
    )
    assert r.returncode == 2
    assert "source" in r.stderr


def test_add_rejects_extra_keys_in_input(fake_repo, write_config, run_findings_writer):
    """Drifted Codex output that smuggles extra fields must be rejected. The
    writer's input shape is exactly {severity, body} — anything else means the
    LLM-to-writer translation is wrong.
    """
    _bootstrap(fake_repo, write_config)
    r = run_findings_writer(
        fake_repo,
        "add",
        "prd-x",
        "--source",
        "codex-review",
        stdin_text=json.dumps(
            [{"severity": "major", "body": "x", "id": "smuggled", "disposition": "accepted"}]
        ),
    )
    assert r.returncode == 2
    assert "unexpected" in r.stderr.lower()


def test_add_rejects_non_array_input(fake_repo, write_config, run_findings_writer):
    _bootstrap(fake_repo, write_config)
    r = run_findings_writer(
        fake_repo,
        "add",
        "prd-x",
        "--source",
        "codex-review",
        stdin_text=json.dumps({"severity": "major", "body": "x"}),
    )
    assert r.returncode == 2


def test_add_rejects_empty_array(fake_repo, write_config, run_findings_writer):
    _bootstrap(fake_repo, write_config)
    r = run_findings_writer(
        fake_repo,
        "add",
        "prd-x",
        "--source",
        "codex-review",
        stdin_text="[]",
    )
    assert r.returncode == 2


def test_add_rejects_malformed_stdin(fake_repo, write_config, run_findings_writer):
    _bootstrap(fake_repo, write_config)
    r = run_findings_writer(
        fake_repo,
        "add",
        "prd-x",
        "--source",
        "codex-review",
        stdin_text="{not json",
    )
    assert r.returncode == 2


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


def test_list_empty_when_no_file(fake_repo, write_config, run_findings_writer):
    _bootstrap(fake_repo, write_config)
    r = run_findings_writer(fake_repo, "list", "prd-none")
    assert r.returncode == 0
    assert json.loads(r.stdout) == []


def test_list_returns_all_by_default(fake_repo, write_config, run_findings_writer):
    _bootstrap(fake_repo, write_config)
    run_findings_writer(
        fake_repo,
        "add",
        "prd-x",
        "--source",
        "codex-review",
        stdin_text=json.dumps(
            [
                {"severity": "blocker", "body": "a"},
                {"severity": "nit", "body": "b"},
            ]
        ),
    )
    r = run_findings_writer(fake_repo, "list", "prd-x")
    assert r.returncode == 0
    out = json.loads(r.stdout)
    assert len(out) == 2


def test_list_only_pending_filters(fake_repo, write_config, run_findings_writer):
    _bootstrap(fake_repo, write_config)
    run_findings_writer(
        fake_repo,
        "add",
        "prd-x",
        "--source",
        "codex-review",
        stdin_text=json.dumps(
            [
                {"severity": "blocker", "body": "a"},
                {"severity": "minor", "body": "b"},
            ]
        ),
    )
    run_findings_writer(
        fake_repo, "set-disposition", "prd-x", "finding-1", "accepted"
    )
    r = run_findings_writer(fake_repo, "list", "prd-x", "--only-pending")
    assert r.returncode == 0
    pending = json.loads(r.stdout)
    assert [p["id"] for p in pending] == ["finding-2"]


def test_list_surfaces_corrupt_file(fake_repo, write_config, run_findings_writer):
    _bootstrap(fake_repo, write_config)
    path = _findings_file(fake_repo, "prd-bad")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json\n")
    r = run_findings_writer(fake_repo, "list", "prd-bad")
    assert r.returncode == 2


# ---------------------------------------------------------------------------
# set-disposition
# ---------------------------------------------------------------------------


def _seed_one_pending(repo, run_findings_writer):
    run_findings_writer(
        repo,
        "add",
        "prd-x",
        "--source",
        "codex-review",
        stdin_text=json.dumps([{"severity": "major", "body": "fix me"}]),
    )


def test_set_disposition_accepted(fake_repo, write_config, run_findings_writer):
    _bootstrap(fake_repo, write_config)
    _seed_one_pending(fake_repo, run_findings_writer)
    r = run_findings_writer(
        fake_repo, "set-disposition", "prd-x", "finding-1", "accepted"
    )
    assert r.returncode == 0, r.stderr
    rec = _read_jsonl(_findings_file(fake_repo, "prd-x"))[0]
    assert rec["disposition"] == "accepted"
    assert rec["resolved_at"]


def test_set_disposition_rejected_requires_rationale(
    fake_repo, write_config, run_findings_writer
):
    _bootstrap(fake_repo, write_config)
    _seed_one_pending(fake_repo, run_findings_writer)
    r = run_findings_writer(
        fake_repo, "set-disposition", "prd-x", "finding-1", "rejected"
    )
    assert r.returncode == 2
    assert "rationale" in r.stderr


def test_set_disposition_deferred_with_rationale(
    fake_repo, write_config, run_findings_writer
):
    _bootstrap(fake_repo, write_config)
    _seed_one_pending(fake_repo, run_findings_writer)
    r = run_findings_writer(
        fake_repo,
        "set-disposition",
        "prd-x",
        "finding-1",
        "deferred",
        "--rationale",
        "Tracking in next PRD",
    )
    assert r.returncode == 0, r.stderr
    rec = _read_jsonl(_findings_file(fake_repo, "prd-x"))[0]
    assert rec["disposition"] == "deferred"
    assert rec["rationale"] == "Tracking in next PRD"
    assert rec["resolved_at"]


def test_set_disposition_back_to_pending_clears_resolved_at(
    fake_repo, write_config, run_findings_writer
):
    _bootstrap(fake_repo, write_config)
    _seed_one_pending(fake_repo, run_findings_writer)
    run_findings_writer(
        fake_repo, "set-disposition", "prd-x", "finding-1", "accepted"
    )
    r = run_findings_writer(
        fake_repo, "set-disposition", "prd-x", "finding-1", "pending"
    )
    assert r.returncode == 0, r.stderr
    rec = _read_jsonl(_findings_file(fake_repo, "prd-x"))[0]
    assert rec["disposition"] == "pending"
    assert "resolved_at" not in rec


def test_set_disposition_unknown_finding(fake_repo, write_config, run_findings_writer):
    _bootstrap(fake_repo, write_config)
    _seed_one_pending(fake_repo, run_findings_writer)
    r = run_findings_writer(
        fake_repo, "set-disposition", "prd-x", "finding-99", "accepted"
    )
    assert r.returncode == 2
    assert "not found" in r.stderr.lower()


def test_set_disposition_unknown_value(fake_repo, write_config, run_findings_writer):
    _bootstrap(fake_repo, write_config)
    _seed_one_pending(fake_repo, run_findings_writer)
    r = run_findings_writer(
        fake_repo, "set-disposition", "prd-x", "finding-1", "wontfix"
    )
    assert r.returncode == 2


# ---------------------------------------------------------------------------
# integration with prd_runner approval gate
# ---------------------------------------------------------------------------


def test_findings_writer_output_unblocks_approval(
    fake_repo, write_config, run_findings_writer, run_prd_runner
):
    _bootstrap(fake_repo, write_config)
    assert run_prd_runner(fake_repo, "new", "gate-flow").returncode == 0
    state = json.loads((fake_repo / ".claude/state/active-prd.json").read_text())
    prd_id = state["prd_id"]
    run_findings_writer(
        fake_repo,
        "add",
        prd_id,
        "--source",
        "codex-review",
        stdin_text=json.dumps([{"severity": "minor", "body": "small thing"}]),
    )
    assert run_prd_runner(fake_repo, "advance", "draft").returncode == 0
    assert run_prd_runner(fake_repo, "advance", "in-review").returncode == 0
    # Blocked: one pending finding.
    r_block = run_prd_runner(fake_repo, "advance", "approved")
    assert r_block.returncode == 2
    assert "pending" in r_block.stderr.lower()
    # Resolve and retry.
    assert run_findings_writer(
        fake_repo, "set-disposition", prd_id, "finding-1", "accepted"
    ).returncode == 0
    # G1: every accepted finding needs a manifest entry for approval.
    spec_path = fake_repo / ".prd-os/prds" / f"{prd_id}.md"
    spec_text = spec_path.read_text()
    manifest = json.dumps(
        [
            {
                "id": "issue-1",
                "title": "fix 1",
                "finding_id": "finding-1",
                "allowed_files": ["src/a.py"],
                "required_checks": ["pytest"], "bypass_exempt": "test fixture",
            }
        ],
        indent=2,
    )
    spec_path.write_text(
        spec_text.replace("```json\n[]\n```", f"```json\n{manifest}\n```")
    )
    r_ok = run_prd_runner(fake_repo, "advance", "approved")
    assert r_ok.returncode == 0, r_ok.stderr


# ---------------------------------------------------------------------------
# codex_reviewed_at stamping (anti-bypass for approval gate)
# ---------------------------------------------------------------------------


def _read_prd_frontmatter(repo: Path, prd_id: str) -> str:
    return (repo / ".prd-os/prds" / f"{prd_id}.md").read_text()


def test_add_with_codex_source_stamps_prd_frontmatter(
    fake_repo, write_config, run_findings_writer
):
    _bootstrap(fake_repo, write_config)
    r = run_findings_writer(
        fake_repo,
        "add",
        "prd-x",
        "--source",
        "codex-review",
        stdin_text=json.dumps([{"severity": "minor", "body": "n/a"}]),
    )
    assert r.returncode == 0, r.stderr
    fm = _read_prd_frontmatter(fake_repo, "prd-x")
    assert "codex_reviewed_at:" in fm
    payload = json.loads(r.stdout)
    assert payload["codex_reviewed_stamped"] is True


def test_add_with_manual_source_does_not_stamp(
    fake_repo, write_config, run_findings_writer
):
    _bootstrap(fake_repo, write_config)
    r = run_findings_writer(
        fake_repo,
        "add",
        "prd-x",
        "--source",
        "manual",
        stdin_text=json.dumps([{"severity": "minor", "body": "n/a"}]),
    )
    assert r.returncode == 0, r.stderr
    fm = _read_prd_frontmatter(fake_repo, "prd-x")
    assert "codex_reviewed_at:" not in fm


def test_add_second_codex_call_refreshes_stamp(
    fake_repo, write_config, run_findings_writer
):
    _bootstrap(fake_repo, write_config)
    run_findings_writer(
        fake_repo,
        "add",
        "prd-x",
        "--source",
        "codex-review",
        stdin_text=json.dumps([{"severity": "minor", "body": "a"}]),
    )
    fm1 = _read_prd_frontmatter(fake_repo, "prd-x")
    # Second call replaces the field in place, not duplicates it.
    run_findings_writer(
        fake_repo,
        "add",
        "prd-x",
        "--source",
        "codex-adversarial",
        stdin_text=json.dumps([{"severity": "minor", "body": "b"}]),
    )
    fm2 = _read_prd_frontmatter(fake_repo, "prd-x")
    assert fm2.count("codex_reviewed_at:") == 1
    # The spec must still parse: both stamps are within the frontmatter block.
    assert fm2.startswith("---\n")
    assert "\n---\n" in fm2[4:]


def test_add_codex_source_fails_when_no_prd_spec(
    fake_repo, write_config, run_findings_writer
):
    """If the PRD spec is missing the writer refuses rather than silently
    dropping the stamp. Silent drop would let the approval gate be
    bypassed via a findings file without the matching spec.
    """
    # Intentionally do NOT seed prd-x. Config only.
    _bootstrap(fake_repo, write_config, prd_ids=())
    r = run_findings_writer(
        fake_repo,
        "add",
        "prd-ghost",
        "--source",
        "codex-review",
        stdin_text=json.dumps([{"severity": "minor", "body": "x"}]),
    )
    assert r.returncode == 2
    assert "not found" in r.stderr.lower()


def test_record_review_stamps_without_writing_findings(
    fake_repo, write_config, run_findings_writer
):
    _bootstrap(fake_repo, write_config)
    r = run_findings_writer(
        fake_repo, "record-review", "prd-x", "--source", "codex-review"
    )
    assert r.returncode == 0, r.stderr
    fm = _read_prd_frontmatter(fake_repo, "prd-x")
    assert "codex_reviewed_at:" in fm
    findings = _findings_file(fake_repo, "prd-x")
    assert not findings.exists()  # no findings created


def test_record_review_rejects_manual_source(
    fake_repo, write_config, run_findings_writer
):
    _bootstrap(fake_repo, write_config)
    r = run_findings_writer(
        fake_repo, "record-review", "prd-x", "--source", "manual"
    )
    assert r.returncode == 2
    assert "codex" in r.stderr.lower()


# --- Truthful reviewer provenance (slice 0, 2026-07-26) --------------------
# When Codex is unavailable, the reviewer is a Claude
# senior-staff-engineer subagent. With only codex-* accepted, that reviewer had
# two bad options: stamp `codex-adversarial` and write a FALSE provenance
# record, or skip the stamp and never be able to approve. These lock the honest
# third option: sources that say what actually ran.


def test_add_accepts_claude_reviewer_sources(
    fake_repo, write_config, run_findings_writer
):
    """(a) the new sources are accepted, and (c) the stamp is written."""
    for source in ("claude-review", "claude-adversarial"):
        _bootstrap(fake_repo, write_config)
        r = run_findings_writer(
            fake_repo,
            "add",
            "prd-x",
            "--source",
            source,
            stdin_text=json.dumps([{"severity": "major", "body": f"via {source}"}]),
        )
        assert r.returncode == 0, f"{source}: {r.stderr}"
        records = [
            json.loads(line)
            for line in _findings_file(fake_repo, "prd-x")
            .read_text()
            .splitlines()
            if line.strip()
        ]
        assert records[-1]["source"] == source
        fm = _read_prd_frontmatter(fake_repo, "prd-x")
        assert "codex_reviewed_at:" in fm, f"{source} did not stamp the review proof"


def test_reviewer_stamp_records_the_true_source(
    fake_repo, write_config, run_findings_writer
):
    """`reviewed_by` carries who actually reviewed.

    The timestamp key is still `codex_reviewed_at` for approval-gate
    compatibility (rename is spillover sp-b386aba4). Left alone, that key name
    would itself be the lie once a Claude pass can stamp it -- so the truth
    lives in `reviewed_by` beside it.
    """
    for source in ("claude-adversarial", "codex-review"):
        _bootstrap(fake_repo, write_config)
        r = run_findings_writer(
            fake_repo, "record-review", "prd-x", "--source", source
        )
        assert r.returncode == 0, r.stderr
        fm = _read_prd_frontmatter(fake_repo, "prd-x")
        assert f"reviewed_by: {source}" in fm, (
            f"stamp does not name its real reviewer; frontmatter was:\n{fm}"
        )


def test_record_review_accepts_claude_sources(
    fake_repo, write_config, run_findings_writer
):
    _bootstrap(fake_repo, write_config)
    r = run_findings_writer(
        fake_repo, "record-review", "prd-x", "--source", "claude-adversarial"
    )
    assert r.returncode == 0, r.stderr
    assert "codex_reviewed_at:" in _read_prd_frontmatter(fake_repo, "prd-x")


def test_reviewer_source_widening_is_exact(
    fake_repo, write_config, run_findings_writer
):
    """(b) unknown sources are still rejected -- the negative self-test.

    A widened allowlist is only safe if it widened by exactly the two intended
    names. Near-misses and other vendors must still be refused, on BOTH the
    `add` path and the `record-review` stamp path.
    """
    near_misses = ("claude", "claude-adversary", "claude-review-2", "gpt-review", "")
    for source in near_misses:
        _bootstrap(fake_repo, write_config)
        r = run_findings_writer(
            fake_repo,
            "add",
            "prd-x",
            "--source",
            source,
            stdin_text=json.dumps([{"severity": "major", "body": "x"}]),
        )
        assert r.returncode == 2, f"{source!r} was accepted by add but must not be"

        r = run_findings_writer(
            fake_repo, "record-review", "prd-x", "--source", source
        )
        assert r.returncode == 2, f"{source!r} was accepted by record-review"


def test_record_review_still_refuses_author_own_words(
    fake_repo, write_config, run_findings_writer
):
    """`manual` and `plan` are the author's own words, never an independent pass."""
    for source in ("manual", "plan"):
        _bootstrap(fake_repo, write_config)
        r = run_findings_writer(
            fake_repo, "record-review", "prd-x", "--source", source
        )
        assert r.returncode == 2, f"{source} must not stamp a review proof"
        fm = _read_prd_frontmatter(fake_repo, "prd-x")
        assert "codex_reviewed_at:" not in fm


def test_stamp_never_eats_the_following_frontmatter_line(
    fake_repo, write_config, run_findings_writer
):
    """An empty-valued key must not let the stamp regex consume the next line.

    Adversarial review 2026-07-26 drove this to a real exploit: `\\s*` matches a
    newline even under re.M, so stamping a frontmatter that carried a bare
    `reviewed_by:` deleted the `findings_path:` line below it -- and with no
    findings_path, the approval gate reported "no findings" and advanced a PRD
    holding an untriaged BLOCKER. Every key below the stamp must survive.
    """
    _bootstrap(fake_repo, write_config)
    spec = fake_repo / ".prd-os/prds/prd-x.md"
    original = spec.read_text()
    # bare keys with empty values, directly above the line the gate depends on
    spec.write_text(
        original.replace(
            "findings_path:",
            "reviewed_by:\ncodex_reviewed_at:\nfindings_path:",
        )
    )

    r = run_findings_writer(
        fake_repo, "record-review", "prd-x", "--source", "claude-review"
    )
    assert r.returncode == 0, r.stderr

    fm = _read_prd_frontmatter(fake_repo, "prd-x")
    assert "findings_path:" in fm, (
        "the stamp ate the findings_path line; the approval gate would then read "
        f"'no findings' and advance an untriaged PRD. Frontmatter:\n{fm}"
    )
    assert "reviewed_by: claude-review" in fm
    assert "codex_reviewed_at:" in fm
    # and the stamp the writer claims it wrote is actually on disk
    assert len([l for l in fm.splitlines() if l.startswith("reviewed_by:")]) == 1
    assert len([l for l in fm.splitlines() if l.startswith("codex_reviewed_at:")]) == 1


def test_stamp_survives_when_the_key_is_last_in_frontmatter(
    fake_repo, write_config, run_findings_writer
):
    """`reviewed_by` last must not swallow the timestamp the same call appended."""
    _bootstrap(fake_repo, write_config)
    spec = fake_repo / ".prd-os/prds/prd-x.md"
    text = spec.read_text()
    head, sep, body = text.partition("\n---\n\n")
    spec.write_text(head + "\nreviewed_by:" + sep + body)

    r = run_findings_writer(
        fake_repo, "record-review", "prd-x", "--source", "claude-adversarial"
    )
    assert r.returncode == 0, r.stderr
    fm = _read_prd_frontmatter(fake_repo, "prd-x")
    assert "codex_reviewed_at:" in fm, (
        "the writer reported success but the timestamp is not on disk -- a false "
        f"receipt. Frontmatter:\n{fm}"
    )
    assert "reviewed_by: claude-adversarial" in fm


def test_writer_sources_match_the_published_schema(fake_repo, write_config):
    """The schema findings_writer names as its contract must list what it emits.

    Drift here is silent: nothing validates against the schema at runtime, so
    the published contract can quietly stop describing reality.
    """
    import importlib.util

    repo = Path(__file__).resolve().parents[3]
    schema = json.loads(
        (repo / "plugins/prd-os/schemas/findings.schema.json").read_text()
    )
    spec = importlib.util.spec_from_file_location(
        "fw", repo / "plugins/prd-os/scripts/findings_writer.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    enum = set(schema["properties"]["source"]["enum"])
    assert set(module.SOURCES) == enum, (
        f"writer emits {sorted(set(module.SOURCES) - enum)} that the schema "
        f"rejects; schema allows {sorted(enum - set(module.SOURCES))} the writer "
        "never emits"
    )


def test_record_review_fails_when_no_prd_spec(
    fake_repo, write_config, run_findings_writer
):
    _bootstrap(fake_repo, write_config, prd_ids=())
    r = run_findings_writer(
        fake_repo, "record-review", "prd-ghost", "--source", "codex-review"
    )
    assert r.returncode == 2
    assert "not found" in r.stderr.lower() or "spec" in r.stderr.lower()


def test_add_codex_without_spec_writes_no_findings(
    fake_repo, write_config, run_findings_writer
):
    """Atomicity: if the stamp cannot be written, findings must not be
    written either. Missing PRD spec = no file writes at all.
    """
    _bootstrap(fake_repo, write_config, prd_ids=())
    findings = _findings_file(fake_repo, "prd-ghost")
    assert not findings.exists()
    r = run_findings_writer(
        fake_repo,
        "add",
        "prd-ghost",
        "--source",
        "codex-review",
        stdin_text=json.dumps([{"severity": "minor", "body": "x"}]),
    )
    assert r.returncode == 2
    # No orphaned findings file.
    assert not findings.exists()


def test_add_codex_with_malformed_frontmatter_writes_no_findings(
    fake_repo, write_config, run_findings_writer
):
    _bootstrap(fake_repo, write_config, prd_ids=())
    # Seed a spec with broken frontmatter (no closing fence).
    spec = fake_repo / ".prd-os/prds/prd-broken.md"
    spec.parent.mkdir(parents=True, exist_ok=True)
    spec.write_text("---\nid: prd-broken\ntitle: broken\n\nbody without close\n")
    findings = _findings_file(fake_repo, "prd-broken")
    r = run_findings_writer(
        fake_repo,
        "add",
        "prd-broken",
        "--source",
        "codex-review",
        stdin_text=json.dumps([{"severity": "minor", "body": "x"}]),
    )
    assert r.returncode == 2
    assert not findings.exists()


def test_add_rolls_back_findings_when_stamp_write_fails(
    fake_repo, write_config, run_findings_writer
):
    """The real concern: findings_write succeeds, stamp_write fails.
    Simulated by making the PRD spec read-only so the final write_text
    raises PermissionError. Pre-existing findings must be restored.
    """
    import os

    _bootstrap(fake_repo, write_config, prd_ids=("prd-ro",))
    # Seed one accepted finding from a prior run to prove the rollback
    # restores full pre-state, not just "file empty".
    assert run_findings_writer(
        fake_repo,
        "add",
        "prd-ro",
        "--source",
        "manual",
        stdin_text=json.dumps([{"severity": "minor", "body": "preexisting"}]),
    ).returncode == 0
    findings = _findings_file(fake_repo, "prd-ro")
    pre_bytes = findings.read_bytes()

    spec = fake_repo / ".prd-os/prds/prd-ro.md"
    os.chmod(spec, 0o444)
    try:
        r = run_findings_writer(
            fake_repo,
            "add",
            "prd-ro",
            "--source",
            "codex-review",
            stdin_text=json.dumps([{"severity": "major", "body": "new one"}]),
        )
    finally:
        os.chmod(spec, 0o644)
    assert r.returncode == 2
    assert "rolled back" in r.stderr.lower() or "stamp" in r.stderr.lower()
    # Findings file is byte-identical to pre-state.
    assert findings.read_bytes() == pre_bytes


def test_record_review_unblocks_approval_with_no_findings(
    fake_repo, write_config, run_findings_writer, run_prd_runner
):
    """The clean-pass path: Codex runs, finds nothing, /prd-review calls
    record-review. Approval should succeed (no findings, but stamp present).
    """
    _bootstrap(fake_repo, write_config, prd_ids=())
    assert run_prd_runner(fake_repo, "new", "clean-pass").returncode == 0
    state = json.loads((fake_repo / ".claude/state/active-prd.json").read_text())
    prd_id = state["prd_id"]
    assert run_prd_runner(fake_repo, "advance", "draft").returncode == 0
    assert run_prd_runner(fake_repo, "advance", "in-review").returncode == 0
    # Without the stamp: blocked.
    r_block = run_prd_runner(fake_repo, "advance", "approved")
    assert r_block.returncode == 2
    assert "codex_reviewed_at" in r_block.stderr
    # Stamp it, then approval succeeds.
    assert run_findings_writer(
        fake_repo, "record-review", prd_id, "--source", "codex-review"
    ).returncode == 0
    r_ok = run_prd_runner(fake_repo, "advance", "approved")
    assert r_ok.returncode == 0, r_ok.stderr


def test_plan_source_never_stamps_codex(fake_repo, write_config, run_findings_writer):
    """plan findings satisfy manifest traceability WITHOUT counting as a
    codex review — the stamp still requires a real codex-* pass."""
    _bootstrap(fake_repo, write_config)
    r = run_findings_writer(
        fake_repo, "add", "prd-x", "--source", "plan",
        stdin_text=json.dumps([{"severity": "major", "body": "planned work item"}]))
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["codex_reviewed_stamped"] is False
    spec = (fake_repo / ".prd-os" / "prds" / "prd-x.md").read_text()
    assert "codex_reviewed_at" not in spec


def test_covered_by_persists_on_disposition(fake_repo, write_config, run_findings_writer):
    _bootstrap(fake_repo, write_config)
    run_findings_writer(
        fake_repo, "add", "prd-x", "--source", "plan",
        stdin_text=json.dumps([{"severity": "major", "body": "x"}]))
    r = run_findings_writer(
        fake_repo, "set-disposition", "prd-x", "finding-1", "accepted",
        "--covered-by", "prd-phase-1-2026-06-12")
    assert r.returncode == 0, r.stderr
    recs = _read_jsonl(_findings_file(fake_repo, "prd-x"))
    assert recs[0]["covered_by"] == "prd-phase-1-2026-06-12"
