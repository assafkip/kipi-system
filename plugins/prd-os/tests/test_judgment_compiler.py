"""Tests for the Judgment Compiler (PRD prd-judgment-compiler-2026-08-04, ASK-363).

Test-first contract: written before judgment_compiler.py existed and run RED
against the pre-change tree to demonstrate the five capability gaps (G-1..G-5
in the PRD), then implementation proceeds until green.

Every test runs against an ephemeral tmp repo (fable-discipline test
isolation). Fixtures are producer-derived: findings are written by the real
findings_writer.py `add` path, PRD files mirror the exact frontmatter +
fenced-JSON `## Issues` manifest shape that prd_runner/prd_split produce
(fixtures-from-producers scar: an invented fixture tests my assumption).

Hash contract is pinned on BOTH ends: these tests recompute canonical hashes
independently of the implementation (cross-process handshake lesson).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PLUGIN_ROOT / "scripts"
JUDGMENT = SCRIPTS_DIR / "judgment_compiler.py"

REASON_CODES = (
    "valid-fix-now",
    "already-remediated",
    "duplicate",
    "owned-by-other-prd",
    "scope-removed",
    "out-of-scope",
    "superseded",
    "defer-dependency",
    "defer-ordering",
    "invalid-finding",
    "insufficient-context",
    "needs-human",
)


def canonical_hash(record: dict) -> str:
    """Independent recomputation of the ledger's canonical hash (pins the
    contract from the test side; the implementation must match byte-for-byte)."""
    payload = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def run_judgment(repo: Path, *args: str, stdin_text: str | None = None,
                 env_extra: dict | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(repo)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, str(JUDGMENT), *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        env=env,
        input=stdin_text,
    )


PRD_ID = "prd-fixture-2026-08-04"


def write_prd_spec(repo: Path, prd_id: str = PRD_ID, status: str = "in-review",
                   issues: list[dict] | None = None) -> Path:
    """Mirror the real PRD spec shape (frontmatter + fenced `## Issues` JSON)."""
    if issues is None:
        issues = [
            {"id": "fixture-issue-a", "title": "A", "allowed_files": ["a.py"]},
            {"id": "fixture-issue-b", "title": "B", "allowed_files": ["b.py"]},
        ]
    body = (
        "---\n"
        f"id: {prd_id}\n"
        "title: Fixture PRD\n"
        f"status: {status}\n"
        "created_at: 2026-08-04T00:00:00Z\n"
        "---\n\n"
        "# Fixture PRD\n\n"
        "## Problem\n\nFixture.\n\n"
        "## Scope\n\nIn scope: the fixture paths only.\n\n"
        "## Issues\n\n"
        "```json\n" + json.dumps(issues, indent=2) + "\n```\n"
    )
    path = repo / ".prd-os" / "prds" / f"{prd_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    return path


@pytest.fixture
def judgment_repo(fake_repo: Path, write_config, run_findings_writer) -> Path:
    """Repo with config, a PRD spec, and one real finding written by the
    producer (findings_writer add)."""
    write_config(fake_repo, {"config_schema_version": 1})
    write_prd_spec(fake_repo)
    proc = run_findings_writer(
        fake_repo, "add", PRD_ID, "--source", "codex-review",
        stdin_text=json.dumps(
            [{"severity": "major", "body": "the fixture gate can be bypassed"}]
        ),
    )
    assert proc.returncode == 0, proc.stderr
    return fake_repo


def assemble_packet(repo: Path, prd_id: str = PRD_ID,
                    finding_id: str = "finding-1") -> tuple[Path, dict]:
    out = repo / "packet.json"
    proc = run_judgment(repo, "assemble", "--prd", prd_id,
                        "--finding", finding_id, "--output", str(out))
    assert proc.returncode == 0, proc.stderr
    return out, json.loads(out.read_text())


def capture(repo: Path, packet_path: Path, *extra: str,
            disposition: str = "accepted",
            env_extra: dict | None = None) -> subprocess.CompletedProcess:
    return run_judgment(
        repo, "capture", "--prd", PRD_ID, "--finding", "finding-1",
        "--context", str(packet_path), "--disposition", disposition,
        "--actor", "founder", *extra, env_extra=env_extra,
    )


def read_ledger(repo: Path) -> list[dict]:
    path = repo / ".prd-os" / "judgments.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def make_judge_run(packet: dict, *, disposition: str = "fix-now",
                   reason_code: str = "valid-fix-now",
                   evidence: list[str] | None = None,
                   confidence: float = 0.7, extra_output: dict | None = None,
                   input_sha256: str | None = None) -> dict:
    output = {
        "technical_validity": "valid",
        "technical_reason": "the gate is bypassable as described",
        "workflow_disposition": disposition,
        "workflow_reason_code": reason_code,
        "evidence_refs": evidence or [],
        "missing_context": [],
        "confidence": confidence,
    }
    if extra_output:
        output.update(extra_output)
    return {
        "model": "test-model",
        "prompt_sha256": "0" * 64,
        "review_run_id": "run-1",
        "input_sha256": input_sha256 or packet["packet_sha256"],
        "output": output,
    }


# ---------------------------------------------------------------------------
# Gap repros (PRD section 6, run RED against the pre-change tree)
# ---------------------------------------------------------------------------


class TestGapRepros:
    def test_g1_decision_time_context_survives_prd_change(self, judgment_repo):
        """G-1: adjudicating freezes decision-time PRD state; editing the PRD
        afterwards does not invalidate or mutate the receipt."""
        packet_path, packet = assemble_packet(judgment_repo)
        proc = capture(judgment_repo, packet_path)
        assert proc.returncode == 0, proc.stderr
        before = read_ledger(judgment_repo)
        assert len(before) == 1
        frozen_sha = before[0]["prd_state"]["sha256"]
        assert frozen_sha not in ("", "unknown")

        write_prd_spec(judgment_repo, status="approved")  # PRD moves on
        after = read_ledger(judgment_repo)
        assert after == before  # receipt untouched
        proc = run_judgment(judgment_repo, "verify")
        assert proc.returncode == 0, proc.stderr

    def test_g2_technical_validity_and_workflow_disposition_are_separate(
            self, judgment_repo, run_findings_writer):
        """G-2: a technically valid finding recorded as a workflow duplicate.

        The cited duplicate is a REAL second finding, produced by
        findings_writer, so the packet actually contains the candidate. The
        original version cited finding-1 as its own duplicate against a
        zero-duplicate packet; `judge_view`'s citable set now (correctly)
        refuses that, and the test was only ever green because relevance went
        unchecked (ASK-363 judge_view refactor)."""
        assert run_findings_writer(
            judgment_repo, "add", PRD_ID, "--source", "codex-review",
            stdin_text=json.dumps([{"severity": "major",
                                    "body": "the fixture gate can be bypassed"}]),
        ).returncode == 0
        packet_path, packet = assemble_packet(judgment_repo)
        assert packet["duplicates"], "fixture must carry a duplicate candidate"
        dupe = packet["duplicates"][0]
        ref = f"finding:{dupe['prd_id']}/{dupe['finding_id']}"
        judge = make_judge_run(
            packet, disposition="duplicate", reason_code="duplicate",
            evidence=[ref],
        )
        judge_path = judgment_repo / "judge.json"
        judge_path.write_text(json.dumps(judge))
        proc = capture(
            judgment_repo, packet_path, "--judge-run", str(judge_path),
            "--reason-code", "duplicate",
            "--evidence", ref,
            disposition="rejected",
        )
        assert proc.returncode == 0, proc.stderr
        rec = read_ledger(judgment_repo)[-1]
        assert rec["judge"]["output"]["technical_validity"] == "valid"
        assert rec["judge"]["output"]["workflow_disposition"] == "duplicate"
        assert rec["human"]["disposition"] == "rejected"
        assert rec["human"]["reason_code"] == "duplicate"

    def test_g3_duplicate_without_reference_is_refused(self, judgment_repo):
        """G-3 / N-1 (human half): evidence-requiring disposition with no
        stable reference fails hard before anything is written."""
        packet_path, _ = assemble_packet(judgment_repo)
        proc = capture(judgment_repo, packet_path,
                       "--reason-code", "duplicate", disposition="rejected")
        assert proc.returncode == 2
        assert "duplicate" in proc.stderr
        assert read_ledger(judgment_repo) == []

    def test_g4_judge_run_reproducible_from_hashes(self, judgment_repo):
        """G-4: the stored packet re-hashes to the receipt's recorded basis;
        a corrupted packet is detected."""
        packet_path, packet = assemble_packet(judgment_repo)
        judge_path = judgment_repo / "judge.json"
        judge_path.write_text(json.dumps(make_judge_run(packet)))
        proc = capture(judgment_repo, packet_path, "--judge-run", str(judge_path))
        assert proc.returncode == 0, proc.stderr
        receipt_id = read_ledger(judgment_repo)[-1]["receipt_id"]

        proc = run_judgment(judgment_repo, "verify", "--packet", str(packet_path),
                            "--receipt-id", receipt_id)
        assert proc.returncode == 0, proc.stderr

        corrupted = json.loads(packet_path.read_text())
        corrupted["finding"]["body"] = "tampered"
        packet_path.write_text(json.dumps(corrupted))
        proc = run_judgment(judgment_repo, "verify", "--packet", str(packet_path),
                            "--receipt-id", receipt_id)
        assert proc.returncode == 2

    def test_g5_sampling_is_reproducible_across_processes(self, judgment_repo):
        """G-5: the same basis yields the same verdict in two separate
        processes, from the documented rule alone."""
        basis = hashlib.sha256(b"fixture-basis").hexdigest()
        first = run_judgment(judgment_repo, "sample-check", "--basis", basis)
        second = run_judgment(judgment_repo, "sample-check", "--basis", basis)
        assert first.returncode == 0 and second.returncode == 0
        a, b = json.loads(first.stdout), json.loads(second.stdout)
        assert a == b
        expected = int(hashlib.sha256(
            f"kipi-judgment-sample-v1:{basis}".encode()).hexdigest(), 16) % 10000 < 500
        assert a["sampled"] is expected
        assert a["rule"]  # the rule is recorded, not implied


# ---------------------------------------------------------------------------
# Assembler facts stay honest
# ---------------------------------------------------------------------------


class TestAssembler:
    def test_packet_hash_is_stable_across_assemblies(self, judgment_repo):
        _, p1 = assemble_packet(judgment_repo)
        _, p2 = assemble_packet(judgment_repo)
        assert p1["packet_sha256"] == p2["packet_sha256"]

    def test_packet_hash_matches_independent_recomputation(self, judgment_repo):
        _, packet = assemble_packet(judgment_repo)
        body = {k: v for k, v in packet.items()
                if k not in ("packet_sha256", "assembled_at")}
        assert canonical_hash(body) == packet["packet_sha256"]

    def test_n4_missing_context_is_unknown_not_false(self, judgment_repo):
        """N-4: no git in the fixture repo, so repo state must be `unknown`
        and listed in missing_context — never False/false."""
        _, packet = assemble_packet(judgment_repo)
        assert packet["repo_state"]["dirty"] == "unknown"
        assert packet["repo_state"]["commit_sha"] == "unknown"
        assert any(m.startswith("repo_state") for m in packet["missing_context"])
        assert False not in packet["repo_state"].values()

    def test_n4_fabricated_false_fails_packet_validation(self, judgment_repo):
        packet_path, packet = assemble_packet(judgment_repo)
        packet["repo_state"]["dirty"] = False  # fabricated boolean
        body = {k: v for k, v in packet.items()
                if k not in ("packet_sha256", "assembled_at")}
        packet["packet_sha256"] = canonical_hash(body)  # re-hash so only the
        # fabrication is on trial, not the hash mismatch
        packet_path.write_text(json.dumps(packet))
        proc = capture(judgment_repo, packet_path)
        assert proc.returncode == 2
        assert "dirty" in proc.stderr

    def test_duplicates_and_issue_order_carry_sources(self, judgment_repo):
        _, packet = assemble_packet(judgment_repo)
        assert packet["issue_state"]["issue_order"] == [
            "fixture-issue-a", "fixture-issue-b"]
        assert packet["issue_state"]["manifest_sha256"] not in ("", "unknown")
        assert packet["prd_state"]["status"] == "in-review"
        for dup in packet["duplicates"]:
            assert dup["source"]

    def test_git_repo_state_is_resolved_when_git_exists(self, tmp_path, monkeypatch,
                                                        write_config, run_findings_writer):
        repo = tmp_path / "gitrepo"
        repo.mkdir()
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-q", "--allow-empty", "-m", "seed"],
                       cwd=repo, check=True)
        write_config(repo, {"config_schema_version": 1})
        write_prd_spec(repo)
        proc = run_findings_writer(
            repo, "add", PRD_ID, "--source", "codex-review",
            stdin_text=json.dumps([{"severity": "major", "body": "b"}]))
        assert proc.returncode == 0, proc.stderr
        _, packet = assemble_packet(repo)
        assert len(packet["repo_state"]["commit_sha"]) == 40
        assert packet["repo_state"]["dirty"] in ("true", "false")


# ---------------------------------------------------------------------------
# Receipt chain integrity
# ---------------------------------------------------------------------------


def two_receipts(repo: Path) -> list[dict]:
    packet_path, _ = assemble_packet(repo)
    assert capture(repo, packet_path).returncode == 0
    proc = run_judgment(
        repo, "capture", "--prd", PRD_ID, "--finding", "finding-1",
        "--context", str(packet_path), "--disposition", "rejected",
        "--reason-code", "invalid-finding", "--rationale", "not real",
        "--actor", "founder",
    )
    assert proc.returncode == 0, proc.stderr
    return read_ledger(repo)


def reseal_ledger(repo: Path, records: list[dict]) -> None:
    """Rewrite the ledger as a FULLY self-consistent chain: recompute every
    prev-hash and receipt_id, then refresh the tip anchor to match.

    This simulates an attacker who repairs every invariant they know about. A
    test that reseals and then breaks exactly one thing isolates that one
    check — otherwise a redundant check masks it and the mutation survives.
    Added after a mutation run showed `sequence` and the prev-hash link could
    both be disabled with all 55 tests still green.
    """
    sealed = []
    prev = None
    for record in records:
        record = json.loads(json.dumps(record))
        record["prev_receipt_sha256"] = prev
        record.pop("receipt_id", None)
        record["receipt_id"] = "jr-" + canonical_hash(record)[:16]
        sealed.append(record)
        prev = canonical_hash(record)
    write_sealed(repo, sealed)


def write_sealed(repo: Path, sealed: list[dict]) -> None:
    path = repo / ".prd-os" / "judgments.jsonl"
    path.write_text("".join(
        json.dumps(r, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False) + "\n" for r in sealed))
    tip = {
        "count": len(sealed),
        "last_receipt_sha256": canonical_hash(sealed[-1]) if sealed else None,
        "last_receipt_id": sealed[-1]["receipt_id"] if sealed else None,
        "updated_at": "2026-08-04T00:00:00Z",
    }
    (repo / ".prd-os" / "judgments-tip.json").write_text(
        json.dumps(tip, indent=2, sort_keys=True) + "\n")


class TestInvariantIsolation:
    """One test per integrity check, with every OTHER check repaired first."""

    def test_sequence_gap_is_caught_when_everything_else_is_consistent(
            self, judgment_repo):
        recs = two_receipts(judgment_repo)
        recs[1]["sequence"] = 3  # contiguity broken, nothing else is
        reseal_ledger(judgment_repo, recs)
        proc = run_judgment(judgment_repo, "verify")
        assert proc.returncode == 2
        assert "sequence" in proc.stderr.lower()

    def test_broken_chain_link_is_caught_when_everything_else_is_consistent(
            self, judgment_repo):
        """An attacker who rewrites a receipt AND refreshes the tip anchor is
        still caught: the anchor is tamper-evident, the chain is the real check."""
        recs = two_receipts(judgment_repo)
        reseal_ledger(judgment_repo, recs)
        sealed = read_ledger(judgment_repo)
        sealed[1]["prev_receipt_sha256"] = "f" * 64  # point at nothing
        sealed[1].pop("receipt_id")
        sealed[1]["receipt_id"] = "jr-" + canonical_hash(sealed[1])[:16]
        write_sealed(judgment_repo, sealed)  # anchor refreshed to match
        proc = run_judgment(judgment_repo, "verify")
        assert proc.returncode == 2
        assert "chain" in proc.stderr.lower()

    def test_forged_sampling_verdict_is_caught_on_read(self, judgment_repo):
        """READ-path check. The suite exercised the write path, where the
        sampler computes its own verdict, so deleting the read-time
        reproducibility check survived every test (mutation run 2026-08-04)."""
        recs = two_receipts(judgment_repo)
        recs[1]["sampling"]["sampled"] = not recs[1]["sampling"]["sampled"]
        reseal_ledger(judgment_repo, recs)
        proc = run_judgment(judgment_repo, "verify")
        assert proc.returncode == 2
        assert "sampling" in proc.stderr.lower()

    def test_forged_evidence_free_disposition_is_caught_on_read(
            self, judgment_repo):
        """A hand-written ledger line claiming `duplicate` with no evidence
        must fail verify even though no writer would produce it."""
        recs = two_receipts(judgment_repo)
        recs[1]["human"]["reason_code"] = "duplicate"
        recs[1]["human"]["evidence_refs"] = []
        reseal_ledger(judgment_repo, recs)
        proc = run_judgment(judgment_repo, "verify")
        assert proc.returncode == 2
        assert "duplicate" in proc.stderr

    def test_forged_judge_output_hash_is_caught_on_read(self, judgment_repo):
        packet_path, packet = assemble_packet(judgment_repo)
        judge_path = judgment_repo / "judge.json"
        judge_path.write_text(json.dumps(make_judge_run(packet)))
        assert capture(judgment_repo, packet_path,
                       "--judge-run", str(judge_path)).returncode == 0
        recs = read_ledger(judgment_repo)
        recs[-1]["judge"]["output"]["confidence"] = 0.1  # hash now stale
        reseal_ledger(judgment_repo, recs)
        proc = run_judgment(judgment_repo, "verify")
        assert proc.returncode == 2
        assert "output_sha256" in proc.stderr

    def test_packet_whose_hash_does_not_match_its_body_is_refused(
            self, judgment_repo):
        """Distinct from the fabricated-false test, which re-hashes on purpose:
        here the body and its self-hash simply disagree."""
        packet_path, packet = assemble_packet(judgment_repo)
        packet["finding"]["body"] = "silently swapped"
        packet_path.write_text(json.dumps(packet))  # packet_sha256 untouched
        proc = capture(judgment_repo, packet_path)
        assert proc.returncode == 2
        assert "packet_sha256" in proc.stderr

    def test_reseal_helper_itself_produces_a_valid_ledger(self, judgment_repo):
        """Guard the guard: if reseal produced an invalid ledger, the two tests
        above would pass for the wrong reason."""
        recs = two_receipts(judgment_repo)
        reseal_ledger(judgment_repo, recs)
        proc = run_judgment(judgment_repo, "verify")
        assert proc.returncode == 0, proc.stderr


class TestChainIntegrity:
    def test_chain_links_and_verify_green(self, judgment_repo):
        recs = two_receipts(judgment_repo)
        assert len(recs) == 2
        assert recs[0]["prev_receipt_sha256"] is None
        first_line_hash = canonical_hash(recs[0])
        assert recs[1]["prev_receipt_sha256"] == first_line_hash
        assert run_judgment(judgment_repo, "verify").returncode == 0

    def test_second_receipt_supersedes_first_for_same_finding(self, judgment_repo):
        recs = two_receipts(judgment_repo)
        assert recs[1]["supersedes"] == recs[0]["receipt_id"]

    def test_n6_mutated_receipt_fails_verify(self, judgment_repo):
        two_receipts(judgment_repo)
        path = judgment_repo / ".prd-os" / "judgments.jsonl"
        lines = path.read_text().splitlines()
        rec = json.loads(lines[0])
        rec["human"]["disposition"] = "rejected"  # history rewrite
        lines[0] = json.dumps(rec, sort_keys=True, separators=(",", ":"),
                              ensure_ascii=False)
        path.write_text("\n".join(lines) + "\n")
        proc = run_judgment(judgment_repo, "verify")
        assert proc.returncode == 2
        assert "1" in proc.stderr  # names the line

    def test_n7_duplicate_receipt_id_fails_verify(self, judgment_repo):
        two_receipts(judgment_repo)
        path = judgment_repo / ".prd-os" / "judgments.jsonl"
        lines = path.read_text().splitlines()
        last = json.loads(lines[-1])
        forged = dict(last)
        forged["prev_receipt_sha256"] = canonical_hash(last)
        path.write_text("\n".join(lines + [json.dumps(
            forged, sort_keys=True, separators=(",", ":"), ensure_ascii=False)]) + "\n")
        proc = run_judgment(judgment_repo, "verify")
        assert proc.returncode == 2
        assert "duplicate" in proc.stderr.lower()

    def test_n8_broken_prev_hash_fails_verify(self, judgment_repo):
        two_receipts(judgment_repo)
        path = judgment_repo / ".prd-os" / "judgments.jsonl"
        lines = path.read_text().splitlines()
        rec = json.loads(lines[1])
        rec["prev_receipt_sha256"] = "f" * 64
        lines[1] = json.dumps(rec, sort_keys=True, separators=(",", ":"),
                              ensure_ascii=False)
        path.write_text("\n".join(lines) + "\n")
        assert run_judgment(judgment_repo, "verify").returncode == 2

    def test_truncating_the_tail_is_detected(self, judgment_repo):
        """Self-attack 2026-08-04: a prefix of a valid chain is a valid chain,
        so the prev-hash walk alone passed a truncated ledger. The tip anchor
        closes deletion — the one tamper class the chain cannot see."""
        two_receipts(judgment_repo)
        path = judgment_repo / ".prd-os" / "judgments.jsonl"
        lines = path.read_text().splitlines()
        path.write_text(lines[0] + "\n")  # drop the last receipt
        proc = run_judgment(judgment_repo, "verify")
        assert proc.returncode == 2
        assert "truncated" in proc.stderr.lower()

    def test_deleting_the_whole_ledger_is_detected(self, judgment_repo):
        two_receipts(judgment_repo)
        (judgment_repo / ".prd-os" / "judgments.jsonl").write_text("")
        proc = run_judgment(judgment_repo, "verify")
        assert proc.returncode == 2
        assert "truncated" in proc.stderr.lower()

    def test_deleting_a_middle_receipt_is_detected(self, judgment_repo):
        """Sequence contiguity catches a middle deletion even where a
        recomputed chain would look continuous."""
        packet_path, _ = assemble_packet(judgment_repo)
        for disposition, code, rationale in (
                ("accepted", None, None),
                ("rejected", "invalid-finding", "no"),
                ("deferred", "defer-ordering", "later")):
            args = ["capture", "--prd", PRD_ID, "--finding", "finding-1",
                    "--context", str(packet_path), "--disposition", disposition,
                    "--actor", "founder"]
            if code:
                args += ["--reason-code", code, "--rationale", rationale]
            assert run_judgment(judgment_repo, *args).returncode == 0
        path = judgment_repo / ".prd-os" / "judgments.jsonl"
        lines = path.read_text().splitlines()
        path.write_text(lines[0] + "\n" + lines[2] + "\n")  # drop the middle
        proc = run_judgment(judgment_repo, "verify")
        assert proc.returncode == 2

    def test_replacing_the_last_receipt_is_detected(self, judgment_repo):
        two_receipts(judgment_repo)
        path = judgment_repo / ".prd-os" / "judgments.jsonl"
        lines = path.read_text().splitlines()
        forged = json.loads(lines[1])
        forged["human"]["rationale"] = "rewritten"
        forged["receipt_id"] = "jr-" + hashlib.sha256(json.dumps(
            {k: v for k, v in forged.items() if k != "receipt_id"},
            sort_keys=True, separators=(",", ":"),
            ensure_ascii=False).encode()).hexdigest()[:16]
        path.write_text(lines[0] + "\n" + json.dumps(
            forged, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False) + "\n")
        proc = run_judgment(judgment_repo, "verify")
        assert proc.returncode == 2
        assert "tip anchor" in proc.stderr.lower()

    def test_deleting_the_tip_anchor_is_itself_detected(self, judgment_repo):
        """Treating a missing anchor as "legacy, pass" restored the whole
        truncation hole for one extra `rm` — deleting a file is cheaper than
        editing it. Every ledger this code writes has an anchor, so a
        non-empty ledger without one is missing evidence."""
        two_receipts(judgment_repo)
        (judgment_repo / ".prd-os" / "judgments-tip.json").unlink()
        proc = run_judgment(judgment_repo, "verify")
        assert proc.returncode == 2
        assert "missing" in proc.stderr.lower()

    def test_rm_anchor_then_truncate_is_still_caught(self, judgment_repo):
        """The exact two-command attack from the review."""
        two_receipts(judgment_repo)
        (judgment_repo / ".prd-os" / "judgments-tip.json").unlink()
        path = judgment_repo / ".prd-os" / "judgments.jsonl"
        path.write_text(path.read_text().splitlines()[0] + "\n")
        assert run_judgment(judgment_repo, "verify").returncode == 2

    def test_fresh_repo_with_no_ledger_and_no_anchor_verifies_clean(
            self, judgment_repo):
        """Absence of BOTH is a genuinely fresh repo, not tampering."""
        assert run_judgment(judgment_repo, "verify").returncode == 0

    def test_cross_check_flags_a_dispositioned_finding_with_no_receipt(
            self, judgment_repo, run_findings_writer):
        """Independent completeness source: findings_writer's own ledger.

        Contract change 2026-08-05: the cross-check now runs BY DEFAULT, so
        plain `verify` catches this too. This test previously asserted
        `plain.returncode == 0` -- the chain alone is fine, because an empty
        chain is a valid chain -- which is exactly the reassurance the default
        was changed to stop giving. The old behaviour is still reachable, and
        is asserted here so the opt-out cannot rot.
        """
        assert run_findings_writer(
            judgment_repo, "set-disposition", PRD_ID, "finding-1", "accepted",
            env_extra={"KIPI_JUDGMENT_CAPTURE": "0"}).returncode == 0
        assert read_ledger(judgment_repo) == []

        chain_only = run_judgment(judgment_repo, "verify", "--no-cross-check")
        assert chain_only.returncode == 0  # the chain itself is fine (empty)

        for flags in (("verify",), ("verify", "--cross-check")):
            crossed = run_judgment(judgment_repo, *flags)
            assert crossed.returncode == 2, f"{flags} missed the gap"
            assert "no judgment receipt" in crossed.stderr

    def test_cross_check_since_floor_excludes_legacy_findings(
            self, judgment_repo, run_findings_writer):
        assert run_findings_writer(
            judgment_repo, "set-disposition", PRD_ID, "finding-1", "accepted",
            env_extra={"KIPI_JUDGMENT_CAPTURE": "0"}).returncode == 0
        proc = run_judgment(judgment_repo, "verify", "--cross-check",
                            "--since", "2099-01-01T00:00:00Z")
        assert proc.returncode == 0

    def test_receipts_beyond_the_tip_anchor_are_reported(self, judgment_repo):
        """Codex review PR #97: an UNDER-counting anchor was treated as fine so
        a crashed anchor-write would not false-alarm — but that left the
        receipts past the anchor outside deletion detection, and verify still
        said 'chain intact'."""
        two_receipts(judgment_repo)
        tip_file = judgment_repo / ".prd-os" / "judgments-tip.json"
        tip = json.loads(tip_file.read_text())
        recs = read_ledger(judgment_repo)
        tip["count"] = 1  # simulate the crash: ledger moved on, anchor did not
        tip["last_receipt_sha256"] = canonical_hash(recs[0])
        tip["last_receipt_id"] = recs[0]["receipt_id"]
        tip_file.write_text(json.dumps(tip, indent=2, sort_keys=True))
        proc = run_judgment(judgment_repo, "verify")
        assert proc.returncode == 2
        assert "BEYOND" in proc.stderr
        assert "reanchor" in proc.stderr

    def test_reanchor_recovers_a_legitimate_unanchored_tail(self, judgment_repo):
        two_receipts(judgment_repo)
        tip_file = judgment_repo / ".prd-os" / "judgments-tip.json"
        recs = read_ledger(judgment_repo)
        tip_file.write_text(json.dumps(
            {"count": 1, "last_receipt_sha256": canonical_hash(recs[0]),
             "last_receipt_id": recs[0]["receipt_id"],
             "updated_at": "2026-08-04T00:00:00Z"}, indent=2, sort_keys=True))
        assert run_judgment(judgment_repo, "verify").returncode == 2
        proc = run_judgment(judgment_repo, "reanchor")
        assert proc.returncode == 0, proc.stderr
        assert json.loads(proc.stdout)["reanchored"] == 2
        assert run_judgment(judgment_repo, "verify").returncode == 0

    def test_reanchor_refuses_a_truncated_ledger(self, judgment_repo):
        """Reanchor must never double as a truncation eraser."""
        two_receipts(judgment_repo)
        path = judgment_repo / ".prd-os" / "judgments.jsonl"
        path.write_text(path.read_text().splitlines()[0] + "\n")
        proc = run_judgment(judgment_repo, "reanchor")
        assert proc.returncode == 2
        assert "TRUNCATED" in proc.stderr
        assert run_judgment(judgment_repo, "verify").returncode == 2

    def test_reanchor_refuses_when_the_anchor_is_missing_entirely(
            self, judgment_repo):
        """Codex round 3, executed repro: deleting the anchor AND truncating,
        then reanchoring, wrote a fresh anchor over the surviving prefix and
        made the deletion permanent. Without the old anchor there is no
        baseline, so this state is not repairable — it is refused."""
        two_receipts(judgment_repo)
        path = judgment_repo / ".prd-os" / "judgments.jsonl"
        path.write_text(path.read_text().splitlines()[0] + "\n")  # truncate
        (judgment_repo / ".prd-os" / "judgments-tip.json").unlink()  # and hide
        proc = run_judgment(judgment_repo, "reanchor")
        assert proc.returncode == 2
        assert "NO existing" in proc.stderr
        assert "cross-check" in proc.stderr
        # and the ledger is still reported as unverifiable, not blessed
        assert run_judgment(judgment_repo, "verify").returncode == 2

    def test_reanchor_on_a_fresh_empty_repo_is_a_no_op(self, judgment_repo):
        """An empty ledger with no anchor is a genuinely fresh repo: nothing to
        prove, so refusing here would be crying wolf."""
        proc = run_judgment(judgment_repo, "reanchor")
        assert proc.returncode == 0, proc.stderr
        assert json.loads(proc.stdout)["reanchored"] == 0

    def test_reanchor_refuses_a_broken_chain(self, judgment_repo):
        two_receipts(judgment_repo)
        path = judgment_repo / ".prd-os" / "judgments.jsonl"
        lines = path.read_text().splitlines()
        rec = json.loads(lines[1])
        rec["prev_receipt_sha256"] = "f" * 64
        lines[1] = json.dumps(rec, sort_keys=True, separators=(",", ":"),
                              ensure_ascii=False)
        path.write_text("\n".join(lines) + "\n")
        proc = run_judgment(judgment_repo, "reanchor")
        assert proc.returncode == 2
        assert "chain" in proc.stderr.lower()

    def test_supersedes_must_resolve(self, judgment_repo):
        packet_path, _ = assemble_packet(judgment_repo)
        proc = capture(judgment_repo, packet_path,
                       "--supersedes", "jr-doesnotexist0000")
        assert proc.returncode == 2


# ---------------------------------------------------------------------------
# Evidence gate (N-1..N-3) and judge conversion
# ---------------------------------------------------------------------------


class TestEvidenceGate:
    @pytest.mark.parametrize("code", ["duplicate", "already-remediated",
                                      "scope-removed", "out-of-scope",
                                      "owned-by-other-prd", "superseded"])
    def test_human_decision_without_evidence_fails(self, judgment_repo, code):
        packet_path, _ = assemble_packet(judgment_repo)
        proc = capture(judgment_repo, packet_path, "--reason-code", code,
                       disposition="rejected")
        assert proc.returncode == 2
        assert read_ledger(judgment_repo) == []

    def test_human_decision_with_evidence_passes(self, judgment_repo):
        packet_path, _ = assemble_packet(judgment_repo)
        proc = capture(judgment_repo, packet_path,
                       "--reason-code", "already-remediated",
                       "--evidence", "test:.prd-os/config.json",
                       disposition="rejected")
        assert proc.returncode == 0, proc.stderr

    def test_evidence_ref_that_points_at_nothing_is_refused(self, judgment_repo):
        """Grammar was not enough: a well-formed ref to a non-existent object
        used to be recorded as the evidence justifying a rejection."""
        packet_path, _ = assemble_packet(judgment_repo)
        for bad in (f"finding:{PRD_ID}/finding-999",
                    "finding:prd-does-not-exist/finding-1",
                    "commit:zzzz",
                    "prd:prd-not-here",
                    "judgment:jr-nope"):
            proc = capture(judgment_repo, packet_path,
                           "--reason-code", "duplicate" if bad.startswith("finding")
                           else "already-remediated" if bad.startswith("commit")
                           else "owned-by-other-prd" if bad.startswith("prd")
                           else "superseded",
                           "--evidence", bad, disposition="rejected")
            assert proc.returncode == 2, f"{bad} was accepted: {proc.stdout}"
        assert read_ledger(judgment_repo) == []

    def test_omitting_reason_code_is_a_known_bypass_that_is_counted(
            self, judgment_repo):
        """Omitting the code skips the evidence gate (requirements key off it).
        Requiring it changes the contract of a fleet-wide shipped command, so
        that is its own issue; here the bypass must at least be VISIBLE:
        recorded as missing context and counted by evaluate."""
        packet_path, _ = assemble_packet(judgment_repo)
        proc = run_judgment(
            judgment_repo, "capture", "--prd", PRD_ID,
            "--finding", "finding-1", "--context", str(packet_path),
            "--disposition", "rejected", "--actor", "founder",
            "--rationale", "nah, dupe of something else")
        assert proc.returncode == 0, proc.stderr
        rec = read_ledger(judgment_repo)[-1]
        assert rec["human"]["reason_code"] is None
        assert "human.reason_code" in rec["missing_context"]
        report = json.loads(run_judgment(judgment_repo, "evaluate").stdout)
        assert report["ungated_decision_rate"] == 1.0

    def test_ungated_rate_is_zero_when_codes_are_supplied(self, judgment_repo):
        packet_path, _ = assemble_packet(judgment_repo)
        assert capture(judgment_repo, packet_path, "--reason-code",
                       "invalid-finding", "--rationale", "no",
                       disposition="rejected").returncode == 0
        report = json.loads(run_judgment(judgment_repo, "evaluate").stdout)
        assert report["ungated_decision_rate"] == 0.0

    def test_omitting_reason_code_on_accepted_still_works(self, judgment_repo):
        """accepted/pending need no justification — being fixed is the reason."""
        packet_path, _ = assemble_packet(judgment_repo)
        assert capture(judgment_repo, packet_path).returncode == 0

    def test_judge_unsupported_disposition_converts_to_needs_human(self, judgment_repo):
        """N-1/N-2 judge half: unsupported judge recommendation degrades to
        needs-human and is flagged; it is never recorded as fact."""
        packet_path, packet = assemble_packet(judgment_repo)
        judge = make_judge_run(packet, disposition="already-remediated",
                               reason_code="already-remediated", evidence=[])
        judge_path = judgment_repo / "judge.json"
        judge_path.write_text(json.dumps(judge))
        proc = capture(judgment_repo, packet_path, "--judge-run", str(judge_path))
        assert proc.returncode == 0, proc.stderr
        rec = read_ledger(judgment_repo)[-1]
        assert rec["judge"]["output"]["workflow_disposition"] == "needs-human"
        assert rec["judge"]["converted_to_needs_human"] is True


# ---------------------------------------------------------------------------
# Judge output schema strictness (N-9..N-11) and stale context (N-5)
# ---------------------------------------------------------------------------


class TestJudgeContract:
    def write_judge(self, repo, judge) -> Path:
        path = repo / "judge.json"
        path.write_text(json.dumps(judge))
        return path

    def test_n9_unknown_reason_code_rejected(self, judgment_repo):
        packet_path, packet = assemble_packet(judgment_repo)
        judge = make_judge_run(packet, reason_code="sounds-fine")
        proc = capture(judgment_repo, packet_path,
                       "--judge-run", str(self.write_judge(judgment_repo, judge)))
        assert proc.returncode == 2

    @pytest.mark.parametrize("confidence", [1.5, -0.1, float("nan"), True])
    def test_n10_confidence_out_of_contract_rejected(self, judgment_repo, confidence):
        packet_path, packet = assemble_packet(judgment_repo)
        judge = make_judge_run(packet)
        judge["output"]["confidence"] = confidence
        path = judgment_repo / "judge.json"
        # json.dumps(allow_nan=True) emits a bare NaN literal; json.loads
        # accepts it back, so the validator must reject non-finite itself.
        path.write_text(json.dumps(judge))
        proc = capture(judgment_repo, packet_path, "--judge-run", str(path))
        assert proc.returncode == 2

    def test_n11_extra_fields_rejected(self, judgment_repo):
        packet_path, packet = assemble_packet(judgment_repo)
        judge = make_judge_run(packet, extra_output={"vibes": "good"})
        proc = capture(judgment_repo, packet_path,
                       "--judge-run", str(self.write_judge(judgment_repo, judge)))
        assert proc.returncode == 2
        assert "vibes" in proc.stderr

    def test_stale_input_hash_rejected(self, judgment_repo):
        packet_path, packet = assemble_packet(judgment_repo)
        judge = make_judge_run(packet, input_sha256="b" * 64)
        proc = capture(judgment_repo, packet_path,
                       "--judge-run", str(self.write_judge(judgment_repo, judge)))
        assert proc.returncode == 2

    def test_n5_capture_on_stale_packet_refused_but_old_receipts_stand(self, judgment_repo):
        packet_path, _ = assemble_packet(judgment_repo)
        assert capture(judgment_repo, packet_path).returncode == 0
        write_prd_spec(judgment_repo, status="approved")  # PRD changed
        proc = run_judgment(judgment_repo, "capture", "--prd", PRD_ID,
                            "--finding", "finding-1", "--context", str(packet_path),
                            "--disposition", "deferred", "--reason-code",
                            "defer-ordering", "--rationale", "later",
                            "--actor", "founder")
        assert proc.returncode == 2
        assert "stale" in proc.stderr.lower()
        assert run_judgment(judgment_repo, "verify").returncode == 0


# ---------------------------------------------------------------------------
# Evaluator (v2) and release gates
# ---------------------------------------------------------------------------


def seeded_ledger(repo: Path, n_agree: int, n_total: int) -> None:
    """Build a prospective ledger via the real capture path: n_total decisions,
    n_agree where the judge's mapped disposition matches the human one."""
    for index in range(n_total):
        finding_body = f"case {index}: distinct fixture objection"
        proc_add = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "findings_writer.py"), "add",
             PRD_ID, "--source", "codex-review"],
            cwd=str(repo), capture_output=True, text=True,
            env={**os.environ, "CLAUDE_PROJECT_DIR": str(repo)},
            input=json.dumps([{"severity": "major", "body": finding_body}]),
        )
        assert proc_add.returncode == 0, proc_add.stderr
        finding_id = json.loads(proc_add.stdout)["added"][0]
        out = repo / f"packet-{index}.json"
        proc = run_judgment(repo, "assemble", "--prd", PRD_ID,
                            "--finding", finding_id, "--output", str(out))
        assert proc.returncode == 0, proc.stderr
        packet = json.loads(out.read_text())
        judge = make_judge_run(packet)  # predicts fix-now -> accepted
        judge_path = repo / f"judge-{index}.json"
        judge_path.write_text(json.dumps(judge))
        human = "accepted" if index < n_agree else "rejected"
        args = ["capture", "--prd", PRD_ID, "--finding", finding_id,
                "--context", str(out), "--disposition", human,
                "--actor", "founder", "--judge-run", str(judge_path)]
        if human == "rejected":
            args += ["--reason-code", "invalid-finding", "--rationale", "wrong"]
        proc = run_judgment(repo, *args)
        assert proc.returncode == 0, proc.stderr


class TestEvaluate:
    def test_metrics_and_gate_status(self, judgment_repo):
        seeded_ledger(judgment_repo, n_agree=3, n_total=4)
        proc = run_judgment(judgment_repo, "evaluate")
        assert proc.returncode == 0, proc.stderr
        report = json.loads(proc.stdout)
        assert report["cases"] == 4
        assert report["exact_agreement"] == 0.75
        assert "cohen_kappa" in report
        assert "per_class" in report and "accepted" in report["per_class"]
        assert "confusion_matrix" in report
        assert "ece_10_bin" in report
        assert "human_review_rate" in report
        assert "unsupported_disposition_rate" in report
        assert "missing_context_rate" in report
        assert "by_reason_code" in report
        assert "population_counts" in report
        gates = report["release_gates"]
        assert gates["passed"] is False  # 4 cases, 75% << thresholds
        assert gates["min_cases"]["required"] == 50

    def test_release_gates_fail_when_any_decision_bypassed_the_evidence_gate(self):
        """Codex review round 5, executed repro: 60 otherwise-perfect cases plus
        ONE reason-code-less rejection returned release_gates.passed == True
        with a nonzero ungated rate. `passed` is the field that would authorize
        automation, and the PRD lists zero bypasses as a release condition, so
        a caller could enable auto-decide on known-invalid calibration data.

        Built with the module's own in-memory fixtures (no repo, no tmp dir) so
        it runs anywhere the selftest does."""
        import importlib.util

        spec = importlib.util.spec_from_file_location("jc_gate", JUDGMENT)
        jc = importlib.util.module_from_spec(spec)
        sys.modules["jc_gate"] = jc
        spec.loader.exec_module(jc)

        shapes = [("accepted", "fix-now", "valid-fix-now"),
                  ("rejected", "invalid", "invalid-finding"),
                  ("deferred", "defer", "defer-ordering")]
        records = []
        for index in range(60):
            human, workflow, code = shapes[index % 3]
            packet = jc._fixture_packet(index)
            run = {"model": "m", "prompt_sha256": "0" * 64,
                   "review_run_id": str(index),
                   "input_sha256": packet["packet_sha256"],
                   "output": {"technical_validity": "valid",
                              "technical_reason": "ok",
                              "workflow_disposition": workflow,
                              "workflow_reason_code": code,
                              "evidence_refs": [], "missing_context": [],
                              "confidence": 1.0}}
            records.append(jc.build_receipt(
                packet, disposition=human, actor="human", reason_code=code,
                evidence_refs=[], rationale=None, judge_run=run,
                supersedes=None, existing=records))

        clean = jc.evaluate(records)
        assert clean["cases"] == 60
        assert clean["ungated_decision_rate"] == 0.0
        assert clean["release_gates"]["passed"] is True, (
            "a perfect 60-case set must be able to pass, or the gate is "
            "unpassable and this test proves nothing")

        # ...now one ungated decision, and nothing else changes.
        packet = jc._fixture_packet(999)
        records.append(jc.build_receipt(
            packet, disposition="rejected", actor="human", reason_code=None,
            evidence_refs=[], rationale="ungated", judge_run=None,
            supersedes=None, existing=records))
        dirty = jc.evaluate(records)
        assert dirty["ungated_decision_rate"] > 0
        assert dirty["release_gates"]["zero_gate_bypasses"]["passed"] is False
        assert dirty["release_gates"]["passed"] is False, (
            "release gates reported PASSED over a ledger containing a decision "
            "that skipped the evidence gate")

    def test_superseded_receipts_are_excluded(self, judgment_repo):
        recs = two_receipts(judgment_repo)  # second supersedes first
        proc = run_judgment(judgment_repo, "evaluate")
        assert proc.returncode == 0, proc.stderr
        report = json.loads(proc.stdout)
        # neither fixture receipt carries a judge run -> zero scorable cases,
        # and the superseded first receipt must not resurrect as a case
        assert report["cases"] == 0
        assert report["superseded_excluded"] == 1
        assert len(recs) == 2

    def test_n12_row_without_context_basis_fails_ledger_validation(self, judgment_repo):
        """N-12: a v1-style context-free row cannot be presented as a
        context-complete prospective case."""
        two_receipts(judgment_repo)
        path = judgment_repo / ".prd-os" / "judgments.jsonl"
        lines = path.read_text().splitlines()
        prev_hash = canonical_hash(json.loads(lines[-1]))
        forged = {"case_id": "fjc-v1-001", "severity": "major",
                  "finding": "history text", "founder_disposition": "accepted",
                  "prev_receipt_sha256": prev_hash}
        path.write_text("\n".join(lines + [json.dumps(
            forged, sort_keys=True, separators=(",", ":"), ensure_ascii=False)]) + "\n")
        assert run_judgment(judgment_repo, "verify").returncode == 2
        assert run_judgment(judgment_repo, "evaluate").returncode == 2


# ---------------------------------------------------------------------------
# Policy candidates (N-13, N-14)
# ---------------------------------------------------------------------------


def seed_override_pattern(repo: Path, count: int) -> None:
    """Judge says fix-now; founder repeatedly rejects as duplicate with the
    same evidence-kind — the repeated pattern a policy candidate must catch."""
    for index in range(count):
        proc_add = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "findings_writer.py"), "add",
             PRD_ID, "--source", "codex-review"],
            cwd=str(repo), capture_output=True, text=True,
            env={**os.environ, "CLAUDE_PROJECT_DIR": str(repo)},
            input=json.dumps([{"severity": "major",
                               "body": f"override case {index}"}]),
        )
        assert proc_add.returncode == 0, proc_add.stderr
        finding_id = json.loads(proc_add.stdout)["added"][0]
        out = repo / f"op-{index}.json"
        assert run_judgment(repo, "assemble", "--prd", PRD_ID, "--finding",
                            finding_id, "--output", str(out)).returncode == 0
        packet = json.loads(out.read_text())
        judge_path = repo / f"oj-{index}.json"
        judge_path.write_text(json.dumps(make_judge_run(packet)))
        proc = run_judgment(
            repo, "capture", "--prd", PRD_ID, "--finding", finding_id,
            "--context", str(out), "--disposition", "rejected",
            "--reason-code", "duplicate",
            "--evidence", f"finding:{PRD_ID}/finding-1",
            "--rationale", "same defect as finding-1",
            "--actor", "founder", "--judge-run", str(judge_path),
        )
        assert proc.returncode == 0, proc.stderr


class TestPolicyCandidates:
    def test_repeated_override_produces_candidate_with_counterexample_search(self, judgment_repo):
        seed_override_pattern(judgment_repo, 3)
        proc = run_judgment(judgment_repo, "policy-candidates", "--min-cases", "3")
        assert proc.returncode == 0, proc.stderr
        path = judgment_repo / ".prd-os" / "judgment-policy-candidates.jsonl"
        rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
        assert rows, "no candidate emitted for a 3x repeated pattern"
        cand = rows[-1]
        assert cand["status"] == "proposed"
        assert cand["case_count"] >= 3
        assert len(cand["supporting_receipt_ids"]) >= 3
        assert "counterexamples" in cand
        assert cand["counterexample_search"]
        assert cand["proposed_rule"]
        assert cand["proposed_tests"]
        assert cand["false_positive_risk"]
        assert cand["integration_point"] == "before-llm-judge"

    def test_below_min_cases_emits_nothing(self, judgment_repo):
        seed_override_pattern(judgment_repo, 2)
        proc = run_judgment(judgment_repo, "policy-candidates", "--min-cases", "3")
        assert proc.returncode == 0, proc.stderr
        path = judgment_repo / ".prd-os" / "judgment-policy-candidates.jsonl"
        assert not path.is_file() or not path.read_text().strip()

    def test_n13_candidate_without_counterexample_search_fails_verify(self, judgment_repo):
        seed_override_pattern(judgment_repo, 3)
        assert run_judgment(judgment_repo, "policy-candidates",
                            "--min-cases", "3").returncode == 0
        path = judgment_repo / ".prd-os" / "judgment-policy-candidates.jsonl"
        rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
        rows[-1].pop("counterexample_search")
        path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        assert run_judgment(judgment_repo, "verify").returncode == 2

    def test_n14_no_self_install_path_exists(self, judgment_repo):
        """N-14: the module exposes no promote/install command and never
        touches the gate ledger or hook wiring (grep-the-source proof)."""
        proc = run_judgment(judgment_repo, "promote")
        assert proc.returncode != 0
        source = JUDGMENT.read_text()
        for forbidden in ("gates.jsonl", "gate_register", "hooks.json",
                          "settings.json", "settings-template.json"):
            assert forbidden not in source, (
                f"judgment_compiler.py must not reference {forbidden}: "
                "policy promotion is the human-reviewed path")


# ---------------------------------------------------------------------------
# findings_writer integration (the real caller)
# ---------------------------------------------------------------------------


class TestTriageIntegration:
    def test_legacy_set_disposition_captures_receipt_with_honest_nulls(
            self, judgment_repo, run_findings_writer):
        proc = run_findings_writer(judgment_repo, "set-disposition", PRD_ID,
                                   "finding-1", "accepted")
        assert proc.returncode == 0, proc.stderr
        recs = read_ledger(judgment_repo)
        assert len(recs) == 1
        assert recs[0]["human"]["disposition"] == "accepted"
        assert recs[0]["human"]["reason_code"] is None
        assert "human.reason_code" in recs[0]["missing_context"]

    def test_set_disposition_with_reason_code_and_evidence(
            self, judgment_repo, run_findings_writer):
        assert run_findings_writer(
            judgment_repo, "add", PRD_ID, "--source", "codex-review",
            stdin_text=json.dumps([{"severity": "minor",
                                    "body": "the owning defect"}]),
        ).returncode == 0  # finding-2, so the evidence ref resolves
        proc = run_findings_writer(
            judgment_repo, "set-disposition", PRD_ID, "finding-1", "rejected",
            "--rationale", "same as finding-9",
            "--reason-code", "duplicate",
            "--evidence", f"finding:{PRD_ID}/finding-2")
        assert proc.returncode == 0, proc.stderr
        rec = read_ledger(judgment_repo)[-1]
        assert rec["human"]["reason_code"] == "duplicate"
        assert rec["human"]["evidence_refs"] == [f"finding:{PRD_ID}/finding-2"]

    def test_set_disposition_evidence_gate_fails_fast(
            self, judgment_repo, run_findings_writer):
        """Gate failure leaves the findings file untouched (validated BEFORE
        the write, not after)."""
        findings_path = (judgment_repo / ".prd-os" / "findings" /
                         f"{PRD_ID}-findings.jsonl")
        before = findings_path.read_text()
        proc = run_findings_writer(
            judgment_repo, "set-disposition", PRD_ID, "finding-1", "rejected",
            "--rationale", "dup", "--reason-code", "duplicate")
        assert proc.returncode == 2
        assert findings_path.read_text() == before
        assert read_ledger(judgment_repo) == []

    def test_failed_capture_leaves_no_spillover_entry(
            self, judgment_repo, run_findings_writer):
        """Codex review PR #97: spillover fanned out BEFORE the receipt, so a
        refused receipt rolled the findings file back while the append-only
        spillover entry stood — the standing gate then saw permanent open work
        for a disposition the command reported as rolled back."""
        spill = judgment_repo / ".prd-os" / "spillover.jsonl"
        before = spill.read_text() if spill.is_file() else ""
        # An unresolvable evidence ref passes the fail-fast grammar check and
        # fails inside capture, which is exactly the late-failure window.
        proc = run_findings_writer(
            judgment_repo, "set-disposition", PRD_ID, "finding-1", "deferred",
            "--rationale", "later", "--reason-code", "defer-ordering",
            "--evidence", "judgment:jr-doesnotexist000")
        assert proc.returncode == 2
        after = spill.read_text() if spill.is_file() else ""
        assert after == before, "spillover mutated despite the rollback"
        assert read_ledger(judgment_repo) == []

    def test_successful_deferral_still_creates_the_spillover_entry(
            self, judgment_repo, run_findings_writer):
        """The reorder must not cost the fan-out on the success path."""
        proc = run_findings_writer(
            judgment_repo, "set-disposition", PRD_ID, "finding-1", "deferred",
            "--rationale", "next phase", "--reason-code", "defer-ordering")
        assert proc.returncode == 0, proc.stderr
        spill = judgment_repo / ".prd-os" / "spillover.jsonl"
        assert spill.is_file()
        assert f"defer-{PRD_ID}-finding-1" in spill.read_text()

    def test_kill_switch_restores_legacy_behavior(
            self, judgment_repo, run_findings_writer):
        proc = run_findings_writer(
            judgment_repo, "set-disposition", PRD_ID, "finding-1", "accepted",
            env_extra={"KIPI_JUDGMENT_CAPTURE": "0"})
        assert proc.returncode == 0, proc.stderr
        assert read_ledger(judgment_repo) == []
        payload = json.loads(proc.stdout)
        assert payload["disposition"] == "accepted"

    def test_deferred_still_syncs_spillover_and_captures(
            self, judgment_repo, run_findings_writer):
        proc = run_findings_writer(
            judgment_repo, "set-disposition", PRD_ID, "finding-1", "deferred",
            "--rationale", "belongs to the next phase",
            "--reason-code", "defer-ordering")
        assert proc.returncode == 0, proc.stderr
        spill = judgment_repo / ".prd-os" / "spillover.jsonl"
        assert spill.is_file() and f"defer-{PRD_ID}-finding-1" in spill.read_text()
        rec = read_ledger(judgment_repo)[-1]
        assert rec["human"]["disposition"] == "deferred"

    def test_redisposition_appends_superseding_receipt(
            self, judgment_repo, run_findings_writer):
        assert run_findings_writer(judgment_repo, "set-disposition", PRD_ID,
                                   "finding-1", "accepted").returncode == 0
        assert run_findings_writer(
            judgment_repo, "set-disposition", PRD_ID, "finding-1", "rejected",
            "--rationale", "reconsidered", "--reason-code",
            "invalid-finding").returncode == 0
        recs = read_ledger(judgment_repo)
        assert len(recs) == 2
        assert recs[1]["supersedes"] == recs[0]["receipt_id"]
        assert run_judgment(judgment_repo, "verify").returncode == 0


# ---------------------------------------------------------------------------
# Read-only survival (R-5) and selftest
# ---------------------------------------------------------------------------


class TestConcurrency:
    def test_concurrent_captures_do_not_fork_the_chain(
            self, judgment_repo, run_findings_writer):
        """The ledger sits at the SHARED worktree root by design, so N
        worktrees write one file. Unlocked, capture was a read-modify-append:
        concurrent calls both derived sequence/prev_hash from a stale snapshot,
        the chain forked, and EVERY writer exited 0 — corruption surfaced only
        later, at a verify that append-only forbids repairing."""
        count = 6
        assert run_findings_writer(
            judgment_repo, "add", PRD_ID, "--source", "codex-review",
            stdin_text=json.dumps([
                {"severity": "major", "body": f"distinct objection {i}"}
                for i in range(count - 1)]),
        ).returncode == 0
        packets = []
        for index in range(1, count + 1):
            out = judgment_repo / f"cp{index}.json"
            assert run_judgment(judgment_repo, "assemble", "--prd", PRD_ID,
                                "--finding", f"finding-{index}",
                                "--output", str(out)).returncode == 0
            packets.append((f"finding-{index}", out))

        procs = [
            subprocess.Popen(
                [sys.executable, str(JUDGMENT), "capture", "--prd", PRD_ID,
                 "--finding", finding_id, "--context", str(out),
                 "--disposition", "accepted", "--actor", "founder"],
                cwd=str(judgment_repo), stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE, text=True,
                env={**os.environ, "CLAUDE_PROJECT_DIR": str(judgment_repo)})
            for finding_id, out in packets
        ]
        errors = [proc.communicate()[1] for proc in procs]
        assert all(proc.returncode == 0 for proc in procs), errors

        recs = read_ledger(judgment_repo)
        assert len(recs) == count, f"expected {count} receipts, got {len(recs)}"
        assert [r["sequence"] for r in recs] == list(range(1, count + 1))
        assert len({r["receipt_id"] for r in recs}) == count
        proc = run_judgment(judgment_repo, "verify")
        assert proc.returncode == 0, proc.stderr


class TestLedgerRoot:
    def test_ledger_follows_the_git_common_dir_not_the_config_root(
            self, judgment_repo, run_findings_writer):
        """The ledger is SHARED across a worktree set on purpose, so its
        location follows `git rev-parse --git-common-dir`, NOT the config's
        repo_root. Pinned because that is surprising in exactly the way that
        bites: during this PRD's own dogfood run a sandbox that had copied a
        `.git` directory wrote its receipts into the MAIN checkout's ledger.
        The behavior was correct; the harness was wrong. A test states which."""
        proc = run_judgment(judgment_repo, "assemble", "--prd", PRD_ID,
                            "--finding", "finding-1", "--output",
                            str(judgment_repo / "p.json"))
        assert proc.returncode == 0, proc.stderr
        assert capture(judgment_repo, judgment_repo / "p.json").returncode == 0
        # fake_repo's .git is a plain directory with no git metadata, so
        # rev-parse fails and _ledger_root falls back to repo_root.
        assert (judgment_repo / ".prd-os" / "judgments.jsonl").is_file()

    def test_ledger_path_is_reported_so_the_operator_can_see_it(
            self, judgment_repo):
        packet_path, _ = assemble_packet(judgment_repo)
        proc = capture(judgment_repo, packet_path)
        assert proc.returncode == 0, proc.stderr
        payload = json.loads(proc.stdout)
        assert payload["path"].endswith("judgments.jsonl")
        assert str(judgment_repo) in payload["path"]


class TestCliParity:
    """The Python subparsers and the `kipi judgment` bash allowlist are two
    lists of the same thing, edited by hand, in different files. Codex review
    round 2 caught the predictable result: `reanchor` shipped in Python and in
    the docs while the dispatcher rejected it, so the documented recovery for
    an interrupted anchor write did not exist. One test, both ends."""

    KIPI = PLUGIN_ROOT.parents[1] / "kipi"

    def _python_subcommands(self) -> set[str]:
        source = JUDGMENT.read_text()
        return set(re.findall(r'sub\.add_parser\("([a-z-]+)"\)', source))

    def _bash_subcommands(self) -> set[str]:
        block = self.KIPI.read_text().split("  judgment)", 1)[1]
        allowlist = re.search(r"^\s+([a-z|-]+)\)$", block, re.M).group(1)
        return set(allowlist.split("|")) | {"selftest"}

    def test_every_python_subcommand_is_reachable_through_kipi(self):
        missing = self._python_subcommands() - self._bash_subcommands()
        assert not missing, (
            f"judgment_compiler.py exposes {sorted(missing)} but `kipi "
            "judgment` rejects them: the CLI cannot reach a shipped command")

    def test_the_dispatcher_advertises_nothing_python_lacks(self):
        # selftest is a --flag, not a subparser, so it is exempt by name.
        phantom = self._bash_subcommands() - self._python_subcommands() - {"selftest"}
        assert not phantom, (
            f"`kipi judgment` advertises {sorted(phantom)} which "
            "judgment_compiler.py does not implement")

    def test_usage_text_lists_every_subcommand(self):
        usage_lines = [l for l in self.KIPI.read_text().splitlines()
                       if "usage: kipi judgment" in l]
        assert usage_lines, "the judgment dispatcher prints no usage line"
        for name in self._python_subcommands():
            assert name in usage_lines[0], (
                f"{name} is dispatchable but absent from the usage text")


class TestReadOnly:
    def test_selftest_passes(self, judgment_repo):
        proc = run_judgment(judgment_repo, "--selftest")
        assert proc.returncode == 0, proc.stderr
        assert "SELFTEST PASS" in proc.stdout

    def test_verify_evaluate_selftest_survive_read_only_repo(self, judgment_repo):
        two_receipts(judgment_repo)
        locked: list[Path] = []
        for root, dirs, _files in os.walk(judgment_repo):
            for d in dirs:
                locked.append(Path(root) / d)
        locked.append(judgment_repo)
        try:
            for path in locked:
                os.chmod(path, 0o555)
            assert run_judgment(judgment_repo, "verify").returncode == 0
            assert run_judgment(judgment_repo, "evaluate").returncode == 0
            proc = run_judgment(judgment_repo, "--selftest")
            assert proc.returncode == 0, proc.stderr
        finally:
            for path in locked:
                os.chmod(path, 0o755)


if __name__ == "__main__":
    # Self-executing under the capability gate's `python3` runner (the
    # test_prd_split_from_linear.py precedent): a manifest entry that cannot
    # run is exactly the silent absence the gate exists to catch.
    sys.exit(subprocess.run(
        [sys.executable, "-m", "pytest", str(Path(__file__).resolve()), "-q"],
        cwd=str(PLUGIN_ROOT.parent.parent),
    ).returncode)


class TestBakedIntoApproval:
    """The compiler must be REQUIRED by prd-os, not merely available to it.

    Shipped writing a receipt everywhere and requiring one nowhere, so
    KIPI_JUDGMENT_CAPTURE=0 or a hand-edited findings file left a hole no gate
    could see. These pin the gate that closes it.
    """

    def _prd_ready_for_approval(self, repo: Path, run_findings_writer):
        spec = repo / ".prd-os" / "prds" / f"{PRD_ID}.md"
        text = spec.read_text().replace(
            "status: in-review",
            "status: in-review\ncodex_reviewed_at: 2026-08-04T00:00:00Z\n"
            f"findings_path: .prd-os/findings/{PRD_ID}-findings.jsonl")
        spec.write_text(text)

    def test_receipt_gate_reports_a_missing_receipt(self, judgment_repo,
                                                    run_findings_writer):
        """Direct call: the gate's own predicate, without the PRD state machine."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "jc_gate2", SCRIPTS_DIR / "judgment_compiler.py")
        jc = importlib.util.module_from_spec(spec)
        sys.modules["jc_gate2"] = jc
        spec.loader.exec_module(jc)
        assert run_findings_writer(
            judgment_repo, "set-disposition", PRD_ID, "finding-1", "accepted",
            env_extra={"KIPI_JUDGMENT_CAPTURE": "0"}).returncode == 0
        cfg_spec = importlib.util.spec_from_file_location(
            "jc_cfg", SCRIPTS_DIR / "config.py")
        cfgmod = importlib.util.module_from_spec(cfg_spec)
        sys.modules["jc_cfg"] = cfgmod
        cfg_spec.loader.exec_module(cfgmod)
        cfg = cfgmod.load(judgment_repo)
        missing, _ = jc.cross_check_findings(cfg, [], "2026-01-01T00:00:00Z")
        assert any(PRD_ID in m for m in missing), missing
        assert any("no judgment receipt" in m for m in missing)

    def test_floor_exempts_pre_feature_dispositions(self, judgment_repo,
                                                    run_findings_writer):
        """A gate that cannot be satisfied gets switched off. Findings decided
        before the compiler existed must not block approval forever."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "jc_gate3", SCRIPTS_DIR / "judgment_compiler.py")
        jc = importlib.util.module_from_spec(spec)
        sys.modules["jc_gate3"] = jc
        spec.loader.exec_module(jc)
        cfg_spec = importlib.util.spec_from_file_location(
            "jc_cfg3", SCRIPTS_DIR / "config.py")
        cfgmod = importlib.util.module_from_spec(cfg_spec)
        sys.modules["jc_cfg3"] = cfgmod
        cfg_spec.loader.exec_module(cfgmod)
        assert run_findings_writer(
            judgment_repo, "set-disposition", PRD_ID, "finding-1", "accepted",
            env_extra={"KIPI_JUDGMENT_CAPTURE": "0"}).returncode == 0
        cfg = cfgmod.load(judgment_repo)
        far_future, _ = jc.cross_check_findings(cfg, [], "2099-01-01T00:00:00Z")
        assert far_future == [], "floor did not exempt an older disposition"


class TestReceiptGateFailsClosed:
    """A REQUIRED integrity gate must refuse on doubt, not wave work through.

    The first version caught every exception and returned 0, defended as 'a bug
    in the check must not cause an approval outage'. That conflated a buggy gate
    with a corrupt ledger -- and a corrupt ledger is exactly what this gate
    exists to catch (Codex, PR #101).
    """

    def _runner(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "pr_gate", SCRIPTS_DIR / "prd_runner.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules["pr_gate"] = mod
        spec.loader.exec_module(mod)
        return mod

    def test_unreadable_ledger_blocks_approval(self, monkeypatch):
        runner = self._runner()
        import judgment_compiler as jc

        monkeypatch.setattr(jc, "ledger_path", lambda cfg: Path("/dev/null"))
        import contextlib
        monkeypatch.setattr(jc, "ledger_lock",
                            lambda cfg: contextlib.nullcontext())
        def boom(_path):
            raise ValueError("line 7: invalid JSON")
        monkeypatch.setattr(jc, "read_ledger", boom)
        code, message = runner._judgment_receipt_gate(object(), "prd-alpha")
        assert code == 2, "a corrupt ledger must not let approval through"
        assert "could not be checked" in message

    def test_prefix_prd_id_does_not_cross_block(self, monkeypatch):
        """`prd-alpha` must not be blocked by a gap belonging to
        `prd-alpha-2`; substring matching did exactly that."""
        runner = self._runner()
        import judgment_compiler as jc

        monkeypatch.setattr(jc, "ledger_path", lambda cfg: Path("/dev/null"))
        monkeypatch.setattr(jc, "read_ledger", lambda p: [])
        monkeypatch.setattr(jc, "tip_path", lambda cfg: Path("/dev/null"))
        monkeypatch.setattr(jc, "read_tip", lambda p: None)
        monkeypatch.setattr(jc, "verify_ledger", lambda r, tip=None: [])
        # the gate now reads under the writer's lock; a stub cfg has no path
        import contextlib
        monkeypatch.setattr(jc, "ledger_lock",
                            lambda cfg: contextlib.nullcontext())
        monkeypatch.setattr(
            jc, "cross_check_findings",
            lambda c, r, s=None, *, prd_id=None: ([
                "prd-alpha-2/finding-1: dispositioned but no judgment receipt "
                "exists"], []))
        assert runner._judgment_receipt_gate(object(), "prd-alpha")[0] == 0
        assert runner._judgment_receipt_gate(object(), "prd-alpha-2")[0] == 2

    def test_missing_compiler_is_the_only_fail_open(self, monkeypatch):
        """An instance without the compiler has no contract to enforce."""
        runner = self._runner()
        real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) \
            else __builtins__.__import__

        def no_compiler(name, *args, **kwargs):
            if name == "judgment_compiler":
                raise ImportError("not installed")
            return real_import(name, *args, **kwargs)
        monkeypatch.setattr("builtins.__import__", no_compiler)
        assert runner._judgment_receipt_gate(object(), "prd-alpha") == (0, "")


class TestGateChecksTheDecisionNotJustTheFinding:
    def test_hand_edited_disposition_is_caught(self, judgment_repo,
                                               run_findings_writer):
        """Codex PR #101 r2: coverage was identity-only, so a receipt for an
        EARLIER decision satisfied the gate after the findings file was edited
        to a different one -- the decision actually recorded had none."""
        assert run_findings_writer(judgment_repo, "set-disposition", PRD_ID,
                                   "finding-1", "accepted").returncode == 0
        assert len(read_ledger(judgment_repo)) == 1
        path = (judgment_repo / ".prd-os" / "findings"
                / f"{PRD_ID}-findings.jsonl")
        rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
        rows[0]["disposition"] = "rejected"      # hand-edit, no capture
        rows[0]["rationale"] = "changed my mind offline"
        path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
        proc = run_judgment(judgment_repo, "verify", "--cross-check",
                            "--since", "2026-01-01T00:00:00Z")
        assert proc.returncode == 2
        assert "never captured" in proc.stderr

    def test_matching_disposition_passes(self, judgment_repo,
                                         run_findings_writer):
        assert run_findings_writer(judgment_repo, "set-disposition", PRD_ID,
                                   "finding-1", "accepted").returncode == 0
        proc = run_judgment(judgment_repo, "verify", "--cross-check",
                            "--since", "2026-01-01T00:00:00Z")
        assert proc.returncode == 0, proc.stderr

    def test_redisposition_through_the_writer_stays_covered(
            self, judgment_repo, run_findings_writer):
        """A legitimate change of mind captures a superseding receipt, so the
        latest receipt matches and the gate stays green."""
        assert run_findings_writer(judgment_repo, "set-disposition", PRD_ID,
                                   "finding-1", "accepted").returncode == 0
        assert run_findings_writer(
            judgment_repo, "set-disposition", PRD_ID, "finding-1", "rejected",
            "--rationale", "reconsidered", "--reason-code",
            "invalid-finding").returncode == 0
        proc = run_judgment(judgment_repo, "verify", "--cross-check",
                            "--since", "2026-01-01T00:00:00Z")
        assert proc.returncode == 0, proc.stderr


class TestGateVerifiesBeforeTrusting:
    def test_forged_receipt_does_not_authorize_approval(self, judgment_repo,
                                                        run_findings_writer):
        """Codex PR #101 r3: the gate parsed receipts but never verified the
        chain, so a hand-appended receipt with the right ids authorized
        approval. A hash chain no consumer checks is decoration."""
        assert run_findings_writer(judgment_repo, "set-disposition", PRD_ID,
                                   "finding-1", "accepted").returncode == 0
        path = judgment_repo / ".prd-os" / "judgments.jsonl"
        real = read_ledger(judgment_repo)[0]
        forged = json.loads(json.dumps(real))
        forged["finding"]["finding_id"] = "finding-2"
        forged["prev_receipt_sha256"] = "0" * 64          # chain broken
        path.write_text(path.read_text() + json.dumps(
            forged, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False) + "\n")
        assert run_judgment(judgment_repo, "verify").returncode == 2
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "pr_gate_v", SCRIPTS_DIR / "prd_runner.py")
        runner = importlib.util.module_from_spec(spec)
        sys.modules["pr_gate_v"] = runner
        spec.loader.exec_module(runner)
        import config as cfgmod
        cfg = cfgmod.load(judgment_repo)
        code, message = runner._judgment_receipt_gate(cfg, PRD_ID)
        assert code == 2, "a forged receipt authorized approval"
        assert "does not verify" in message


class TestDecisionFingerprint:
    """Rounds 2-5 of PR #101 each found a different unchecked field. One
    fingerprint, used on both sides, closes the class rather than the instance."""

    def test_hand_edited_rationale_is_caught(self, judgment_repo,
                                             run_findings_writer):
        assert run_findings_writer(
            judgment_repo, "set-disposition", PRD_ID, "finding-1", "rejected",
            "--rationale", "duplicate of finding-9",
            "--reason-code", "invalid-finding").returncode == 0
        path = (judgment_repo / ".prd-os" / "findings"
                / f"{PRD_ID}-findings.jsonl")
        rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
        rows[0]["rationale"] = "actually it was a security hole"  # rewritten
        path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
        proc = run_judgment(judgment_repo, "verify", "--cross-check",
                            "--since", "2026-01-01T00:00:00Z")
        assert proc.returncode == 2
        assert "never captured" in proc.stderr

    def test_empty_vs_absent_rationale_is_not_a_change(self, judgment_repo,
                                                       run_findings_writer):
        """The writer stores None for an empty rationale; a findings record may
        omit the key. That difference must not read as tampering."""
        assert run_findings_writer(judgment_repo, "set-disposition", PRD_ID,
                                   "finding-1", "accepted").returncode == 0
        path = (judgment_repo / ".prd-os" / "findings"
                / f"{PRD_ID}-findings.jsonl")
        rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
        rows[0].pop("rationale", None)
        rows[0]["rationale"] = ""
        path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
        proc = run_judgment(judgment_repo, "verify", "--cross-check",
                            "--since", "2026-01-01T00:00:00Z")
        assert proc.returncode == 0, proc.stderr


class TestRedispositionWithoutNewRationale:
    def test_rejected_to_accepted_without_rationale_stays_covered(
            self, judgment_repo, run_findings_writer):
        """Codex PR #101 r6, a regression from my own round-5 fingerprint fix:
        findings_writer keeps the previous rationale on a re-disposition (only
        `pending` clears it), so capturing the FLAG instead of the RECORD froze
        None against a record that still had text, and the gate falsely blocked."""
        assert run_findings_writer(
            judgment_repo, "set-disposition", PRD_ID, "finding-1", "rejected",
            "--rationale", "not a real defect",
            "--reason-code", "invalid-finding").returncode == 0
        assert run_findings_writer(judgment_repo, "set-disposition", PRD_ID,
                                   "finding-1", "accepted").returncode == 0
        proc = run_judgment(judgment_repo, "verify", "--cross-check",
                            "--since", "2026-01-01T00:00:00Z")
        assert proc.returncode == 0, proc.stderr
        rec = read_ledger(judgment_repo)[-1]
        assert rec["human"]["disposition"] == "accepted"
        assert rec["human"]["rationale"] == "not a real defect", (
            "the receipt must freeze the rationale the finding actually carries")


class TestFloorDoesNotShieldAConflict:
    def test_finding_without_resolved_at_still_compared_when_a_receipt_exists(
            self, judgment_repo, run_findings_writer):
        """Codex PR #101 r7: '' sorts before every timestamp, so a dispositioned
        finding with no resolved_at was skipped by the floor even when its
        receipt disagreed. The floor exempts findings that CANNOT have a
        receipt; one that has a receipt is not in that category."""
        assert run_findings_writer(judgment_repo, "set-disposition", PRD_ID,
                                   "finding-1", "accepted").returncode == 0
        path = (judgment_repo / ".prd-os" / "findings"
                / f"{PRD_ID}-findings.jsonl")
        rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
        rows[0]["disposition"] = "rejected"     # conflicts with the receipt
        rows[0]["rationale"] = "changed offline"
        rows[0].pop("resolved_at", None)        # ...and is undateable
        path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
        proc = run_judgment(judgment_repo, "verify", "--cross-check",
                            "--since", "2099-01-01T00:00:00Z")
        assert proc.returncode == 2, "a far-future floor hid a real conflict"
        assert "never captured" in proc.stderr

    def test_undateable_and_unclaimed_finding_is_still_exempt(
            self, judgment_repo, run_findings_writer):
        """No receipt and no date: genuinely pre-feature. Must stay exempt, or
        every legacy PRD blocks forever and the gate gets switched off."""
        assert run_findings_writer(
            judgment_repo, "set-disposition", PRD_ID, "finding-1", "accepted",
            env_extra={"KIPI_JUDGMENT_CAPTURE": "0"}).returncode == 0
        path = (judgment_repo / ".prd-os" / "findings"
                / f"{PRD_ID}-findings.jsonl")
        rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
        rows[0].pop("resolved_at", None)
        path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
        proc = run_judgment(judgment_repo, "verify", "--cross-check",
                            "--since", "2099-01-01T00:00:00Z")
        assert proc.returncode == 0, proc.stderr


# ---------------------------------------------------------------------------
# PR #101 split: the gate keeps the integrity half (rounds 1-5) and demotes the
# field-agreement half (rounds 6-8). See CHANGELOG 0.14.0.
# ---------------------------------------------------------------------------


FINDINGS_REL = ".prd-os/findings"


def _load_module(name: str, filename: str):
    """Load a scripts/ module under a private name (the file's own convention)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, SCRIPTS_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _cfg_for(repo: Path):
    return _load_module(f"cfg_{repo.name}_{id(repo)}", "config.py").load(repo)


def _findings_rows(repo: Path, prd_id: str = PRD_ID) -> tuple[Path, list[dict]]:
    path = repo / FINDINGS_REL / f"{prd_id}-findings.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()
            if line.strip()]
    return path, rows


def _rewrite_findings(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(
        json.dumps(r, sort_keys=True) + "\n" for r in rows))


class TestGateUsesAPrdLevelFloor:
    """Rounds 2, 7 and 8 were ONE defect class: inferring "was this decided
    after the floor" from `resolved_at`, a mutable strippable field on a
    hand-editable file. The round-8 code admitted the inference was undecidable
    ("undateable AND unclaimed: cannot judge, do not guess") and left a
    documented hole: capture off, strip the date, invisible. The gate runs for
    ONE named PRD whose id carries its creation date, so the floor is read from
    the id instead and no `resolved_at` is parsed at all.
    """

    def test_stripping_resolved_at_no_longer_hides_a_missing_receipt(
            self, judgment_repo, run_findings_writer):
        """THE round-8 hole, executed: the documented invisible case."""
        assert run_findings_writer(
            judgment_repo, "set-disposition", PRD_ID, "finding-1", "accepted",
            env_extra={"KIPI_JUDGMENT_CAPTURE": "0"}).returncode == 0
        path, rows = _findings_rows(judgment_repo)
        for row in rows:
            row.pop("resolved_at", None)
        _rewrite_findings(path, rows)
        runner = _load_module("pr_floor_a", "prd_runner.py")
        code, message = runner._judgment_receipt_gate(
            _cfg_for(judgment_repo), PRD_ID)
        assert code == 2, (
            "a dispositioned finding with the date stripped and no receipt was "
            "waved through: the kill-switch-plus-strip hole")
        assert "no judgment receipt" in message

    def test_an_old_prd_does_not_exempt_a_decision_made_today(
            self, fake_repo, write_config, run_findings_writer):
        """Codex BLOCKER on PR #102: a PRD-creation-date floor exempted every
        FUTURE decision on a pre-floor PRD. 35 of 36 real PRDs predate the
        floor, so the gate was a near-permanent no-op -- the opposite of
        "receipts are required from here on".

        Measured before removing the exemption: of the 36 real PRDs, 21 are
        archived and 13 approved, so they can never reach this gate again. ONE
        (in-review, 13 dispositioned findings) can, and its remedy is one
        `set-disposition` re-run per finding, which mints the receipt. So the
        exemption bought almost nothing and cost the entire guarantee."""
        legacy = "prd-legacy-2026-07-01"
        write_config(fake_repo, {"config_schema_version": 1})
        write_prd_spec(fake_repo, legacy)
        assert run_findings_writer(
            fake_repo, "add", legacy, "--source", "codex-review",
            stdin_text=json.dumps(
                [{"severity": "major", "body": "a legacy finding"}])
        ).returncode == 0
        assert run_findings_writer(
            fake_repo, "set-disposition", legacy, "finding-1", "accepted",
            env_extra={"KIPI_JUDGMENT_CAPTURE": "0"}).returncode == 0
        runner = _load_module("pr_floor_b", "prd_runner.py")
        code, message = runner._judgment_receipt_gate(_cfg_for(fake_repo), legacy)
        assert code == 2, (
            "an old PRD id must not buy an exemption for a decision being "
            "approved today")
        assert "no judgment receipt" in message

    def test_an_undateable_prd_id_fails_closed(
            self, fake_repo, write_config, run_findings_writer):
        """No code enforces a prd_id format, so an id whose date cannot be
        parsed must be treated as post-floor, never exempted."""
        weird = "prd-no-date-at-all"
        write_config(fake_repo, {"config_schema_version": 1})
        write_prd_spec(fake_repo, weird)
        assert run_findings_writer(
            fake_repo, "add", weird, "--source", "codex-review",
            stdin_text=json.dumps(
                [{"severity": "major", "body": "an undateable finding"}])
        ).returncode == 0
        assert run_findings_writer(
            fake_repo, "set-disposition", weird, "finding-1", "accepted",
            env_extra={"KIPI_JUDGMENT_CAPTURE": "0"}).returncode == 0
        runner = _load_module("pr_floor_c", "prd_runner.py")
        code, message = runner._judgment_receipt_gate(_cfg_for(fake_repo), weird)
        assert code == 2, "an unparseable prd_id must fail CLOSED, not exempt"
        assert "no judgment receipt" in message

    def test_a_post_floor_prd_with_its_receipt_passes(self, judgment_repo,
                                                      run_findings_writer):
        """Negative self-test: the gate is not simply always-blocking."""
        assert run_findings_writer(judgment_repo, "set-disposition", PRD_ID,
                                   "finding-1", "accepted").returncode == 0
        runner = _load_module("pr_floor_d", "prd_runner.py")
        code, message = runner._judgment_receipt_gate(
            _cfg_for(judgment_repo), PRD_ID)
        assert code == 0, message


class TestDecisionDisagreementWarnsAndDoesNotBlock:
    """Rounds 6-8 compared the MUTABLE findings file against the IMMUTABLE
    receipt and caused two of their own regressions. `cmd_evaluate` (which
    feeds the release gates) reads ONLY the ledger, so the ledger is the
    calibration set and the findings file is operational state. When they
    disagree the receipt is still the honest record, so this reports rather
    than blocks -- and false-blocking is the failure mode that gets a gate
    switched off.
    """

    def _diverge(self, repo, run_findings_writer):
        assert run_findings_writer(repo, "set-disposition", PRD_ID,
                                   "finding-1", "accepted").returncode == 0
        path, rows = _findings_rows(repo)
        rows[0]["rationale"] = "rewritten after the receipt was frozen"
        _rewrite_findings(path, rows)

    def test_a_fingerprint_mismatch_exits_zero_with_a_warning(
            self, judgment_repo, run_findings_writer):
        self._diverge(judgment_repo, run_findings_writer)
        runner = _load_module("pr_warn_a", "prd_runner.py")
        code, message = runner._judgment_receipt_gate(
            _cfg_for(judgment_repo), PRD_ID)
        assert code == 0, (
            "a disagreement between the mutable findings copy and the receipt "
            f"must not block approval: {message}")
        assert "warning" in message.lower()
        assert "finding-1" in message

    def test_evaluate_reports_the_disagreement_count(self, judgment_repo,
                                                     run_findings_writer):
        """Precedent: 41c0876 made the release gates read the evidence-gate
        bypass rate rather than leaving a documented condition unenforced."""
        self._diverge(judgment_repo, run_findings_writer)
        proc = run_judgment(judgment_repo, "evaluate")
        assert proc.returncode == 0, proc.stderr
        report = json.loads(proc.stdout)
        assert report["decision_disagreement_count"] == 1, report
        gate = report["release_gates"]["zero_decision_disagreements"]
        assert gate["passed"] is False, gate
        assert report["release_gates"]["passed"] is False

    def test_evaluate_reports_zero_when_the_copy_agrees(
            self, judgment_repo, run_findings_writer):
        """Negative self-test for the counter itself."""
        assert run_findings_writer(judgment_repo, "set-disposition", PRD_ID,
                                   "finding-1", "accepted").returncode == 0
        proc = run_judgment(judgment_repo, "evaluate")
        assert proc.returncode == 0, proc.stderr
        report = json.loads(proc.stdout)
        assert report["decision_disagreement_count"] == 0
        assert report["release_gates"][
            "zero_decision_disagreements"]["passed"] is True


# An out-of-process observer: the ONLY way to probe the lock from a test, since
# flock re-entry on a second fd blocks in the SAME process (measured: a second
# LOCK_EX in one process hangs). It reports whether the persist path left a
# window in which a gate could see a disposition whose receipt is not yet there.
_LOCK_OBSERVER = '''
import fcntl, json, sys
from pathlib import Path

repo, prd = Path(sys.argv[1]), sys.argv[2]
handle = open(repo / ".prd-os" / ".judgments.lock", "a+")
try:
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
except OSError:
    print("LOCK_HELD")
    raise SystemExit(0)
rows = [json.loads(l) for l
        in (repo / ".prd-os" / "findings" / (prd + "-findings.jsonl")
            ).read_text().splitlines() if l.strip()]
done = [r for r in rows if r.get("disposition") not in (None, "pending")]
ledger = repo / ".prd-os" / "judgments.jsonl"
receipts = len([l for l in ledger.read_text().splitlines() if l.strip()]) \\
    if ledger.is_file() else 0
print("WINDOW_OPEN dispositioned=%d receipts=%d" % (len(done), receipts))
'''


class TestPersistPathIsOneCriticalSection:
    """sp-0c725cde, a defect in MERGED code. `_write_all` published the
    disposition and only afterwards did `capture_from_triage` take
    `ledger_lock` internally. A gate reading under that lock (the round-4 fix)
    could land in the gap, see a dispositioned finding with no receipt, and
    false-block work that was completing normally.
    """

    def test_no_reader_can_observe_a_disposition_without_its_receipt(
            self, judgment_repo, tmp_path, monkeypatch):
        import argparse

        writer = _load_module("fw_window", "findings_writer.py")
        observer = tmp_path / "lock_observer.py"
        observer.write_text(_LOCK_OBSERVER)
        seen: list[str] = []
        real_write_all = writer._write_all

        def watched_write_all(path, records):
            real_write_all(path, records)
            proc = subprocess.run(
                [sys.executable, str(observer), str(judgment_repo), PRD_ID],
                capture_output=True, text=True)
            seen.append((proc.stdout + proc.stderr).strip())

        monkeypatch.setattr(writer, "_write_all", watched_write_all)
        args = argparse.Namespace(
            prd_id=PRD_ID, finding_id="finding-1", disposition="accepted",
            rationale="", covered_by="", reason_code=None, evidence=[],
            actor="founder", judge_run=None)
        assert writer.cmd_set_disposition(_cfg_for(judgment_repo), args) == 0
        assert seen, "the persist path never wrote the findings file"
        assert seen[0] == "LOCK_HELD", (
            "an outside reader observed the findings file mid-persist: "
            f"{seen[0]}")


# The date-shape table that used to live here is gone with the mechanism it
# guarded. `_prd_predates_floor` parsed a date out of the prd_id; Codex's
# blocker showed the whole date-based exemption was wrong, so the function was
# deleted rather than hardened a third time. A class dies best by deleting the
# mechanism, not by adding a guard to it.


def test_no_date_parsing_survives_in_the_receipt_gate():
    """Executable proof the class is gone, not merely unused."""
    source = (SCRIPTS_DIR / "prd_runner.py").read_text()
    for dead in ("_prd_predates_floor", "_PRD_ID_DATE", "_PRD_DATE_EARLIEST"):
        assert dead not in source, (
            f"{dead} is back: the receipt gate must not infer eligibility "
            "from any date")


def test_the_cross_check_runs_under_the_writer_lock(judgment_repo, monkeypatch):
    """Codex MAJOR on PR #102: the gate read the ledger under `ledger_lock`,
    RELEASED it, and only then cross-checked the findings files. A concurrent,
    perfectly valid triage landing in that gap writes a disposition the gate's
    stale ledger snapshot cannot see, so approval false-blocks on a missing
    receipt that does exist. The lock has to span the comparison, not just the
    read that feeds it.

    `ledger_lock` is re-entrant per thread, so depth > 0 is exactly the
    assertion "a lock is held right now" without deadlocking the prober.
    """
    runner = _load_module("pr_lockspan", "prd_runner.py")
    import judgment_compiler as jc

    seen = []
    real = jc.cross_check_findings
    monkeypatch.setattr(jc, "cross_check_findings",
                        lambda *a, **k: (seen.append(
                            getattr(jc._LOCK_DEPTH, "value", 0)) or real(*a, **k)))
    runner._judgment_receipt_gate(_cfg_for(judgment_repo), PRD_ID)
    assert seen, "the cross-check never ran"
    assert seen[0] >= 1, (
        "cross_check_findings ran with the writer lock released; a concurrent "
        "triage in that window false-blocks approval")


# ---------------------------------------------------------------------------
# The judge runner: the producer that never existed (ASK-363, sp-320d30e3)
# ---------------------------------------------------------------------------

# Stand-in for the LLM. The judge shells out, so the seam is the COMMAND, set
# via KIPI_JUDGE_CMD. A test must never make a real model call: it would be
# slow, nondeterministic, and billed.
_JUDGE_STUB = '''
import json, os, sys
sys.stdin.read()
n = int(os.environ.get("STUB_CALL_COUNT_FILE_BUMP", "0"))
counter = os.environ.get("STUB_COUNTER")
if counter:
    prior = 0
    if os.path.exists(counter):
        prior = int(open(counter).read() or "0")
    open(counter, "w").write(str(prior + 1))
    n = prior + 1
bad = os.environ.get("STUB_BAD_UNTIL")
if bad and n <= int(bad):
    sys.stdout.write("not json at all")
    raise SystemExit(0)
sys.stdout.write(os.environ.get("STUB_JUDGE_OUTPUT") or json.dumps({
    "technical_validity": "valid",
    "technical_reason": "the fixture gate can be bypassed as described",
    "workflow_disposition": "fix-now",
    "workflow_reason_code": "valid-fix-now",
    "evidence_refs": [],
    "missing_context": [],
    "confidence": 0.82,
}))
'''


@pytest.fixture
def judge_stub(tmp_path):
    path = tmp_path / "judge_stub.py"
    path.write_text(_JUDGE_STUB)
    return f"{sys.executable} {path}"


class TestJudgeRunnerClosesTheProductionGap:
    """No judge-run PRODUCER existed in production code.

    `/prd-triage` never passed `--judge-run`, and `evaluate` counts a
    calibration case only when a receipt carries BOTH `judge` and `human`. So
    every triage wrote a human-only receipt, `judged` stayed empty forever, and
    all four release gates were unreachable by construction. ~90 tests passed on
    that path because every one of them hand-built the judge run -- the
    "a gate's input needs a production producer, not just a test" class,
    recurring.
    """

    def test_production_triage_yields_a_judged_case(
            self, judgment_repo, tmp_path, run_findings_writer, judge_stub):
        """THE reproducer: drive the real production path end to end and ask
        `evaluate` whether it scored anything. Zero before the producer."""
        run = tmp_path / "judge-run.json"
        proc = run_judgment(
            judgment_repo, "judge", "--prd", PRD_ID, "--finding", "finding-1",
            "--output", str(run), env_extra={"KIPI_JUDGE_CMD": judge_stub})
        assert proc.returncode == 0, proc.stderr
        disp = run_findings_writer(
            judgment_repo, "set-disposition", PRD_ID, "finding-1", "accepted",
            "--judge-run", str(run))
        assert disp.returncode == 0, disp.stderr
        report = json.loads(run_judgment(judgment_repo, "evaluate").stdout)
        assert report["judged_receipts"] == 1, (
            "a full production-path triage still scored zero calibration "
            f"cases: {report['judged_receipts']}")
        assert report["cases"] == 1

    def test_judge_run_binds_to_an_independently_assembled_packet(
            self, judgment_repo, tmp_path, judge_stub):
        """The hard design question: the judge assembles its own packet and
        `capture` assembles another. They bind because `packet_hash` excludes
        `assembled_at` and `packet_sha256`, so two assemblies of unchanged
        state hash identically. If that ever stops being true, no judged
        receipt can be written at all."""
        run = tmp_path / "judge-run.json"
        assert run_judgment(
            judgment_repo, "judge", "--prd", PRD_ID, "--finding", "finding-1",
            "--output", str(run),
            env_extra={"KIPI_JUDGE_CMD": judge_stub}).returncode == 0
        emitted = json.loads(run.read_text())
        _, packet = assemble_packet(judgment_repo)  # a SEPARATE assembly
        assert emitted["input_sha256"] == packet["packet_sha256"]

    def test_the_judge_is_invoked_with_tools_disabled(self):
        """`duplicates[].source` is a filesystem path to a findings file and
        `prior_receipts` lists receipt ids. A judge that can open files reads
        prior HUMAN dispositions straight out of both, and the calibration set
        becomes a measure of its own leakage."""
        jc = _load_module("jc_judge_argv", "judgment_compiler.py")
        argv = jc._judge_argv("claude-opus-5")
        # `--tools ""` is the AVAILABILITY control -- `claude --help`: "Use ""
        # to disable all tools". `--allowedTools` is a permission ALLOWLIST and
        # does not remove availability, so the first version of this test
        # asserted the wrong flag and encoded the very bug it was meant to
        # prevent (Codex, PR #103 round 1).
        assert "--tools" in argv, argv
        assert argv[argv.index("--tools") + 1] == "", (
            f"tools must be disabled: {argv}")

    def test_malformed_output_retries_then_fails_loudly(
            self, judgment_repo, tmp_path, judge_stub):
        """Bounded retry (3, per the self-healing-retry contract) and then a
        LOUD failure. No silent fallback to a default disposition: a fabricated
        prediction poisons the calibration set worse than a missing one."""
        counter = tmp_path / "calls.txt"
        run = tmp_path / "judge-run.json"
        proc = run_judgment(
            judgment_repo, "judge", "--prd", PRD_ID, "--finding", "finding-1",
            "--output", str(run),
            env_extra={"KIPI_JUDGE_CMD": judge_stub,
                       "STUB_COUNTER": str(counter),
                       "STUB_BAD_UNTIL": "99"})
        assert proc.returncode == 2, proc.stdout
        assert int(counter.read_text()) == 3, "retry must be bounded at 3"
        assert not run.exists(), "a failed judge must not write a run file"

    def test_a_transient_malformed_reply_recovers_within_the_cap(
            self, judgment_repo, tmp_path, judge_stub):
        """Negative self-test for the retry: the cap must not be a hard fail."""
        counter = tmp_path / "calls.txt"
        run = tmp_path / "judge-run.json"
        proc = run_judgment(
            judgment_repo, "judge", "--prd", PRD_ID, "--finding", "finding-1",
            "--output", str(run),
            env_extra={"KIPI_JUDGE_CMD": judge_stub,
                       "STUB_COUNTER": str(counter),
                       "STUB_BAD_UNTIL": "2"})
        assert proc.returncode == 0, proc.stderr
        assert int(counter.read_text()) == 3
        assert json.loads(run.read_text())["output"]["confidence"] == 0.82

    def test_the_prompt_is_pinned_by_hash(self):
        """A judge whose prompt is tuned after seeing disagreements stops being
        an independent predictor. `prompt_sha256` is required on every run, so a
        changed prompt is a visible discontinuity in the ledger: cases either
        side of it are different experiments and must not be pooled."""
        jc = _load_module("jc_judge_prompt", "judgment_compiler.py")
        assert jc.JUDGE_PROMPT_SHA256 == hashlib.sha256(
            jc.JUDGE_PROMPT.encode("utf-8")).hexdigest()
        assert jc._prompt_hash("a different prompt") != jc.JUDGE_PROMPT_SHA256

    def test_the_packet_handed_to_the_judge_carries_no_label(
            self, judgment_repo, run_findings_writer):
        """Blindness is the dataset. Assert on the REAL packet text the judge
        receives, after a disposition exists to leak."""
        assert run_findings_writer(
            judgment_repo, "set-disposition", PRD_ID, "finding-1", "rejected",
            "--rationale", "a distinctive rationale string",
            env_extra={"KIPI_JUDGMENT_CAPTURE": "0"}).returncode == 0
        jc = _load_module("jc_judge_blind", "judgment_compiler.py")
        cfg = _cfg_for(judgment_repo)
        text = jc._judge_prompt_text(jc.assemble_packet(cfg, PRD_ID, "finding-1"))
        assert "a distinctive rationale string" not in text
        assert "rejected" not in text


# Flags whose ABSENCE leaves a receipt field permanently null. Each maps to the
# receipt field it is the only production input for.
RECEIPT_POPULATING_FLAGS = {
    "--judge-run": "receipt.judge — the calibration half of every scored case",
    "--reason-code": "receipt.human.reason_code — keys the evidence gate",
    "--evidence": "receipt.human.evidence_refs",
}


def test_every_receipt_populating_flag_has_a_production_caller():
    """MECHANICAL detector for a class that has now produced a defect twice.

    "A consumer without a production producer is dead wiring, and tests that
    supply the consumer's input verify the consumer's logic while hiding that
    the wiring is dead." `--judge-run` was defined on two argparse parsers,
    consumed by `_load_judge_run`, scored by `evaluate`, and covered by ~90
    tests that each hand-built the judge run -- while NO production caller ever
    passed it. `judged` was therefore empty forever and all four release gates
    were unreachable.

    Definition sites are deliberately NOT the corpus: an `add_argument` call
    proves a flag exists, which is exactly the thing that was never in doubt.
    The corpus is the set of places production actually INVOKES these scripts —
    the slash commands and the `kipi` dispatcher. This test fails on a flag
    nothing calls, which is the shape the class always takes.
    """
    corpus = "\n".join(
        [p.read_text() for p in sorted((PLUGIN_ROOT / "commands").glob("*.md"))]
        + [(PLUGIN_ROOT.parents[1] / "kipi").read_text()])
    orphaned = {flag: field for flag, field in RECEIPT_POPULATING_FLAGS.items()
                if flag not in corpus}
    assert not orphaned, (
        "these flags are defined and consumed but no production caller passes "
        "them, so the field each one feeds can never be populated outside "
        f"tests: {orphaned}")


class TestFailSoftJudgeStaysCountable:
    """`/prd-triage` continues without `--judge-run` when the judge call fails,
    so a model outage never blocks an author from closing findings. That is the
    right trade, but silent fail-soft would recreate the exact hole this issue
    exists to close: a judge erroring on every triage for a month would be
    indistinguishable from "not enough triage volume yet" -- both show `cases`
    short of 50 and a red gate, with no way to tell which. Same argument as
    41c0876, where a documented release condition was computed but never read.
    """

    def test_a_triage_with_no_judge_is_counted_and_gated(
            self, judgment_repo, run_findings_writer):
        assert run_findings_writer(
            judgment_repo, "set-disposition", PRD_ID, "finding-1",
            "accepted").returncode == 0
        report = json.loads(run_judgment(judgment_repo, "evaluate").stdout)
        assert report["unjudged_decision_rate"] == 1.0, report
        gate = report["release_gates"]["zero_unjudged_decisions"]
        assert gate["passed"] is False, gate
        assert report["release_gates"]["passed"] is False

    def test_a_judged_triage_leaves_the_rate_at_zero(
            self, judgment_repo, tmp_path, run_findings_writer, judge_stub):
        """Negative self-test: the counter must be able to read zero, or it is
        just a constant that happens to look like a metric."""
        run = tmp_path / "judge-run.json"
        assert run_judgment(
            judgment_repo, "judge", "--prd", PRD_ID, "--finding", "finding-1",
            "--output", str(run),
            env_extra={"KIPI_JUDGE_CMD": judge_stub}).returncode == 0
        assert run_findings_writer(
            judgment_repo, "set-disposition", PRD_ID, "finding-1", "accepted",
            "--judge-run", str(run)).returncode == 0
        report = json.loads(run_judgment(judgment_repo, "evaluate").stdout)
        assert report["unjudged_decision_rate"] == 0.0, report
        assert report["release_gates"][
            "zero_unjudged_decisions"]["passed"] is True


    def test_a_fabricated_judge_evidence_ref_is_dropped_and_downgraded(
            self, judgment_repo, tmp_path, run_findings_writer, judge_stub):
        """Codex MAJOR, PR #103 round 1. Judge refs were checked for SYNTAX and
        never RESOLVED, so an invented-but-well-formed citation satisfied the
        evidence gate and was stored as a supported decision that release gates
        then counted.

        Worse than a missed check: the judge prompt TOLD the model its refs
        would be resolved by `resolve_evidence_refs`, and that sentence was also
        what I used to satisfy the prompt-only-enforcement guard. A gate cleared
        with an untrue claim about my own code.
        """
        run = tmp_path / "judge-run.json"
        fabricated = json.dumps({
            "technical_validity": "valid",
            "technical_reason": "looks like a duplicate of something",
            "workflow_disposition": "duplicate",
            "workflow_reason_code": "duplicate",
            "evidence_refs": ["finding:prd-does-not-exist/finding-999"],
            "missing_context": [],
            "confidence": 0.9,
        })
        assert run_judgment(
            judgment_repo, "judge", "--prd", PRD_ID, "--finding", "finding-1",
            "--output", str(run),
            env_extra={"KIPI_JUDGE_CMD": judge_stub,
                       "STUB_JUDGE_OUTPUT": fabricated}).returncode == 0
        emitted = json.loads(run.read_text())
        assert emitted["output"]["evidence_refs"] == [], (
            "an unresolvable citation must not survive into the run: "
            f"{emitted['output']['evidence_refs']}")
        assert run_findings_writer(
            judgment_repo, "set-disposition", PRD_ID, "finding-1", "rejected",
            "--rationale", "dupe", "--judge-run", str(run)).returncode == 0
        receipt = read_ledger(judgment_repo)[-1]
        assert receipt["judge"]["converted_to_needs_human"] is True, (
            "a disposition left unsupported after dropping a fabricated ref "
            "must degrade to needs-human, not stand as supported")


class TestTheJudgeSummaryWithholdsThePrediction:
    """Codex MAJOR, PR #103 round 2. `cmd_judge` printed
    `workflow_disposition` in its stdout summary. `/prd-triage` runs that
    command in the founder's interactive session, so the prediction landed in
    the transcript BEFORE they set a disposition -- the precise contamination
    the blindness rule exists to stop. A founder who sees the prediction and
    agrees inflates measured agreement, and the calibration set stops measuring
    anything.

    The original code shipped the leak and a `note` field telling the reader
    not to show it. Prose was doing a job that belongs to code: the fix is to
    not emit the value at all.
    """

    def test_stdout_does_not_carry_the_predicted_disposition(
            self, judgment_repo, tmp_path, judge_stub):
        run = tmp_path / "judge-run.json"
        proc = run_judgment(
            judgment_repo, "judge", "--prd", PRD_ID, "--finding", "finding-1",
            "--output", str(run), env_extra={"KIPI_JUDGE_CMD": judge_stub})
        assert proc.returncode == 0, proc.stderr
        # The stub predicts fix-now / valid-fix-now.
        for leak in ("fix-now", "valid-fix-now", "technical_validity"):
            assert leak not in proc.stdout, (
                f"the judge summary leaked {leak!r} into the transcript the "
                f"founder reads before deciding:\n{proc.stdout}")

    def test_the_run_file_still_records_the_prediction(
            self, judgment_repo, tmp_path, judge_stub):
        """Negative self-test: withheld from the TRANSCRIPT, not discarded.
        A judge whose prediction never reaches the ledger scores nothing."""
        run = tmp_path / "judge-run.json"
        assert run_judgment(
            judgment_repo, "judge", "--prd", PRD_ID, "--finding", "finding-1",
            "--output", str(run),
            env_extra={"KIPI_JUDGE_CMD": judge_stub}).returncode == 0
        emitted = json.loads(run.read_text())
        assert emitted["output"]["workflow_disposition"] == "fix-now"


class TestDuplicateClaimsMustComeFromThePacket:
    """Codex MAJOR, PR #103 round 3. `EVIDENCE_REQUIREMENTS["duplicate"]`
    accepts any ref with a `finding:`/`issue:`/`spillover:` prefix, and
    `issue:` resolves by checking that a spec file exists. So the judge could
    cite ANY real issue in the repo as proof that this finding is a duplicate,
    even when the packet it saw contained no duplicate candidate at all -- and
    that unsupported decision was scored as supported.

    Prefix + existence are both necessary and neither is sufficient. The
    missing property is RELEVANCE: a claim must be checkable against the view
    the judge was actually given. The packet's `duplicates` list is that view,
    so a duplicate claim may only cite a candidate from it.
    """

    def _issue(self, repo, name="ASK-999"):
        issues = _cfg_for(repo).issues_dir
        issues.mkdir(parents=True, exist_ok=True)
        (issues / f"{name}.md").write_text("# an unrelated real issue\n")
        return f"issue:{name}"

    def test_an_unrelated_real_issue_cannot_prove_a_duplicate(
            self, judgment_repo, tmp_path, run_findings_writer, judge_stub):
        ref = self._issue(judgment_repo)
        payload = json.dumps({
            "technical_validity": "valid",
            "technical_reason": "this looks like something we already have",
            "workflow_disposition": "duplicate",
            "workflow_reason_code": "duplicate",
            "evidence_refs": [ref],
            "missing_context": [],
            "confidence": 0.91,
        })
        run = tmp_path / "judge-run.json"
        assert run_judgment(
            judgment_repo, "judge", "--prd", PRD_ID, "--finding", "finding-1",
            "--output", str(run),
            env_extra={"KIPI_JUDGE_CMD": judge_stub,
                       "STUB_JUDGE_OUTPUT": payload}).returncode == 0
        emitted = json.loads(run.read_text())
        assert emitted["output"]["evidence_refs"] == [], (
            "an issue that is not a duplicate candidate in the packet was "
            f"accepted as proof of duplication: {emitted['output']['evidence_refs']}")
        assert run_findings_writer(
            judgment_repo, "set-disposition", PRD_ID, "finding-1", "rejected",
            "--rationale", "dupe", "--judge-run", str(run)).returncode == 0
        receipt = read_ledger(judgment_repo)[-1]
        assert receipt["judge"]["converted_to_needs_human"] is True

    def test_a_real_packet_duplicate_candidate_is_still_accepted(
            self, judgment_repo, tmp_path, run_findings_writer, judge_stub):
        """Negative self-test. Over-restricting would convert every duplicate
        to needs-human and score nothing, which fails the same way in the
        opposite direction."""
        jc = _load_module("jc_dupe_ok", "judgment_compiler.py")
        packet = jc.assemble_packet(_cfg_for(judgment_repo), PRD_ID, "finding-1")
        assert packet["duplicates"] == [], "fixture unexpectedly has duplicates"
        # `_packet_duplicate_refs` is subsumed by `judge_view`, which derives
        # the citable set for ALL nine prefixes from one view (ASK-363).
        packet["duplicates"] = [{"prd_id": "prd-x-2026-01-01",
                                 "finding_id": "finding-7", "similarity": 0.9,
                                 "source": "some/ledger.jsonl"}]
        _, citable = jc.judge_view(packet)
        assert "finding:prd-x-2026-01-01/finding-7" in citable


class TestBindingSurvivesTheDispositionWrite:
    """Codex MAJOR, PR #103 round 4. The plan's load-bearing design claim was
    "packet_hash excludes assembled_at and packet_sha256, so the judge can
    assemble independently and still bind". The exclusion is real; the
    conclusion did not follow.

    `findings_xref.cross_reference` computes candidates ONLY for findings whose
    disposition is currently `pending` (findings_xref.py:186-188). So the judge
    assembles while the finding is pending and sees cross-PRD duplicates;
    `_write_all` then sets the disposition; `capture_from_triage` reassembles,
    the candidates are gone, the hash moves, and `_load_judge_run` refuses the
    run as stale. Every finding with a cross-PRD duplicate candidate is
    therefore un-capturable with a judge run.

    The earlier binding test passed because the fixture had NO duplicates -- it
    asserted the property on the one input that could not exercise it.
    """

    def _prior_prd_with_a_matching_finding(self, repo, body):
        prior = "prd-prior-2026-07-01"
        path = repo / FINDINGS_REL / f"{prior}-findings.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "id": "finding-1", "prd_id": prior, "source": "codex-review",
            "severity": "major", "body": body, "disposition": "rejected",
            "rationale": "we decided against this before",
            "created_at": "2026-07-01T00:00:00Z",
            "resolved_at": "2026-07-02T00:00:00Z",
        }) + "\n")
        return prior

    def test_a_cross_prd_duplicate_candidate_does_not_break_capture(
            self, judgment_repo, tmp_path, run_findings_writer, judge_stub):
        _, rows = _findings_rows(judgment_repo)
        self._prior_prd_with_a_matching_finding(judgment_repo, rows[0]["body"])

        jc = _load_module("jc_bind", "judgment_compiler.py")
        packet = jc.assemble_packet(_cfg_for(judgment_repo), PRD_ID, "finding-1")
        assert packet["duplicates"], (
            "fixture failed to produce a cross-PRD duplicate candidate, so "
            "this test cannot exercise the defect")

        run = tmp_path / "judge-run.json"
        assert run_judgment(
            judgment_repo, "judge", "--prd", PRD_ID, "--finding", "finding-1",
            "--output", str(run),
            env_extra={"KIPI_JUDGE_CMD": judge_stub}).returncode == 0
        disp = run_findings_writer(
            judgment_repo, "set-disposition", PRD_ID, "finding-1", "accepted",
            "--judge-run", str(run))
        assert disp.returncode == 0, (
            "a finding with a cross-PRD duplicate candidate could not be "
            f"captured with its judge run:\n{disp.stderr}")
        assert len(read_ledger(judgment_repo)) == 1


# ---------------------------------------------------------------------------
# judge_view: ONE constructor for the judge's view + its citable set
# (ASK-363 / PR #103 refactor, replacing four independent seams)
# ---------------------------------------------------------------------------

# Field names that carry a triage LABEL, or point at a file that carries one.
# Table-driven so reintroducing any of them is caught by name, wherever it is
# spliced into the packet.
LABEL_BEARING_FIELDS = (
    "disposition", "rationale", "resolved_at", "triaged_at", "triaged_by",
    "human", "judge", "workflow_disposition",
)
# (block, key) pairs where a `source` value is a filesystem PATH into a ledger
# that carries other findings' dispositions. `review.source` ("codex-review")
# and `scope.source` ("<prd>.md#Scope") are NOT paths into a label store and
# are deliberately kept: `scope.source` is the only citable proof of scope.
LABEL_POINTER_ROWS = ("duplicates", "remediation")

# The verified nine-prefix classification. `closed` names the view field the
# refs come from; the two refused kinds have no source in the packet at all.
CITABLE_TABLE = {
    "finding:": "duplicates",
    "judgment:": "prior_receipts",
    "prd:": "related_prds",
    "receipt:": "remediation[].issue_id",
    "commit:": "remediation[].commit_sha",
    "scope:": "scope.source",
}
# `issue:` MOVED here from CITABLE_TABLE (Codex round 9). Its only source is
# `issue_state.issue_id`, the globally ACTIVE issue -- ambient, identical for
# every finding in the run -- and `duplicate` is a relational code. See
# CITABLE_REF_PROVENANCE in judgment_compiler.py. This edit is the point of the
# table: the survival criterion below still holds every remaining kind to
# proving it is citable, so removing one kind cannot quietly become "refuse
# everything".
REFUSED_PREFIXES = ("spillover:", "test:", "issue:")


def _rich_packet(repo):
    """A packet with EVERY citable source populated.

    Rows use the exact shapes `_assemble_duplicates` / `_assemble_remediation`
    emit (read from the assemblers, not invented). A zero-duplicate fixture is
    how an earlier hash-binding test passed while testing nothing.
    """
    jc = _load_module(f"jc_rich_{id(repo)}", "judgment_compiler.py")
    packet = jc.assemble_packet(_cfg_for(repo), PRD_ID, "finding-1")
    packet["duplicates"] = [{
        "prd_id": "prd-other-2026-01-01", "finding_id": "finding-9",
        "similarity": 0.91,
        "source": "POINTER-DUPES-LEDGER.jsonl"}]
    packet["related_prds"] = ["prd-other-2026-01-01"]
    packet["prior_receipts"] = ["jr-00000001"]
    packet["issue_state"]["issue_id"] = "ASK-555"
    packet["remediation"] = [{
        "issue_id": "ASK-556", "finding_id": "finding-1",
        "closed_at": "2026-01-01T00:00:00Z", "commit_sha": "a" * 40,
        "source": "POINTER-RECEIPTS-LEDGER.jsonl:7"}]
    packet["repo_state"]["commit_sha"] = "b" * 40   # HEAD, must NOT be citable
    packet["scope"] = {"source": ".prd-os/prds/x.md#Scope", "sha256": "c" * 64}
    return jc, packet


def _expected_ref(prefix, packet):
    return {
        "finding:": "finding:prd-other-2026-01-01/finding-9",
        "judgment:": "judgment:jr-00000001",
        "prd:": "prd:prd-other-2026-01-01",
        "issue:": "issue:ASK-555",
        "receipt:": "receipt:ASK-556",
        "commit:": "commit:" + "a" * 40,
        "scope:": "scope:.prd-os/prds/x.md#Scope",
    }[prefix]


class TestJudgeViewIsTheOnlyConstructorOfTheJudgesWorld:
    """PR #103 rounds 1-4 found five majors, every one in the same dimension:
    the judge's blindness and citation integrity. Blindness was enforced at
    four independent seams (tool availability, prompt content, stdout, evidence
    refs) and three failed. A property enforced at N sites is not a chokepoint,
    so a fifth review round would only have told us the reviewer had not yet
    found the next insufficient guard. `judge_view` is the single writer.
    """

    # --- Property 1: the perceivable view ---------------------------------

    @pytest.mark.parametrize("field", LABEL_BEARING_FIELDS)
    def test_no_label_bearing_field_survives_into_the_view(
            self, judgment_repo, field):
        """Splice the label into every block and prove the ALLOWLIST drops it.

        Red at 85d4a46: the old builder deep-copied the packet and popped one
        known pointer, so `packet["finding"]["rationale"]` reached the prompt
        verbatim. A findings ledger record really does carry that field."""
        jc, packet = _rich_packet(judgment_repo)
        marker = f"LEAKED-{field.upper()}"
        for block in ("finding", "review", "repo_state", "prd_state",
                      "issue_state", "scope"):
            packet[block][field] = marker
        for block in ("duplicates", "remediation"):
            for row in packet[block]:
                row[field] = marker
        view, _ = jc.judge_view(packet)
        rendered = json.dumps(view, sort_keys=True)
        assert marker not in rendered, f"{field!r} reached the judge"
        assert f'"{field}"' not in rendered, f"key {field!r} reached the judge"

    @pytest.mark.parametrize("block", LABEL_POINTER_ROWS)
    def test_no_row_source_pointer_survives_into_the_view(
            self, judgment_repo, block):
        """`duplicates[].source` and `remediation[].source` are paths into
        ledgers that carry OTHER findings' human dispositions. A judge that
        could open one reads the labels straight out."""
        jc, packet = _rich_packet(judgment_repo)
        view, _ = jc.judge_view(packet)
        rendered = json.dumps(view, sort_keys=True)
        assert "POINTER-" not in rendered, rendered
        assert all("source" not in row for row in view[block]), view[block]

    def test_the_view_spec_covers_every_field_the_assembler_emits(
            self, judgment_repo):
        """Self-enumerating guard. An allowlist silently drops a NEW packet
        field, which is the safe direction, but it must be a decision someone
        made rather than an omission nobody noticed."""
        jc, packet = _rich_packet(judgment_repo)
        assert set(jc.JUDGE_VIEW_SPEC) == set(packet), (
            "packet fields and JUDGE_VIEW_SPEC have diverged: "
            f"{set(packet) ^ set(jc.JUDGE_VIEW_SPEC)}")

    # --- Property 2: the citable set --------------------------------------

    @pytest.mark.parametrize("prefix", sorted(CITABLE_TABLE))
    def test_a_ref_outside_the_citable_set_is_refused(
            self, judgment_repo, prefix):
        """One case per CLOSED prefix: a well-formed ref of the right kind that
        the view does not contain. Red at 85d4a46 for every prefix whose
        resolver merely checked existence -- any real PRD, issue, path or
        commit in the repo satisfied the gate."""
        jc, packet = _rich_packet(judgment_repo)
        _, citable = jc.judge_view(packet)
        outsider = prefix + "not-in-the-view-at-all"
        assert outsider not in citable
        assert jc.evidence_gate_errors(None, None, [outsider], citable) == \
            jc.evidence_gate_errors(None, None, [], citable)

    @pytest.mark.parametrize("prefix", REFUSED_PREFIXES)
    def test_the_refused_kinds_are_never_citable(
            self, judgment_repo, prefix):
        """Principled, not a default. `spillover:` has no block in the packet
        and nothing enumerates test paths, so the judge cannot honestly cite
        either; `issue:` has a source but an AMBIENT one, which cannot evidence
        a relational claim. `duplicate` keeps `finding:` and
        `already-remediated` keeps `receipt:`/`commit:`, all finding-dependent.
        `owned-by-other-prd` is now unsatisfiable on the judge path and
        converts to needs-human -- named in TestCitationProvenance, not
        silent."""
        jc, packet = _rich_packet(judgment_repo)
        _, citable = jc.judge_view(packet)
        assert not any(r.startswith(prefix) for r in citable), citable

    def test_head_is_not_citable_but_a_remediation_commit_is(
            self, judgment_repo):
        """`repo_state.commit_sha` is the CURRENT commit and always exists, so
        an existence check let a judge cite HEAD as proof of the very
        remediation under review. Only `remediation[].commit_sha` counts."""
        jc, packet = _rich_packet(judgment_repo)
        _, citable = jc.judge_view(packet)
        assert "commit:" + "a" * 40 in citable, "remediation commit must count"
        assert "commit:" + "b" * 40 not in citable, "HEAD must not be citable"

    # --- The negative self-test (acceptance criterion) --------------------

    @pytest.mark.parametrize("prefix", sorted(CITABLE_TABLE))
    def test_every_closed_kind_survives(self, judgment_repo, prefix):
        """THE acceptance criterion, table-driven over all nine prefixes (seven
        here, two in the refused test above).

        With the carve-out empty, "refuse everything" would pass every
        membership test trivially while converting every disposition to
        needs-human and scoring ZERO calibration cases -- the same failure in
        the opposite direction. Each closed kind must be proven to SURVIVE."""
        jc, packet = _rich_packet(judgment_repo)
        _, citable = jc.judge_view(packet)
        assert _expected_ref(prefix, packet) in citable, (
            f"{prefix} was derivable from the view but is not citable; "
            "over-refusal scores zero cases")

    def test_the_survival_check_can_actually_fail(self, judgment_repo):
        """Negative self-test OF the negative self-test. An empty citable set
        is exactly what "refuse everything" produces; prove the survival
        assertion above goes red against it rather than passing vacuously."""
        _, packet = _rich_packet(judgment_repo)
        empty: frozenset = frozenset()
        for prefix in CITABLE_TABLE:
            assert _expected_ref(prefix, packet) not in empty
        # and the same mutant must be caught by the gate, not silently allowed
        jc = _load_module("jc_mutant_gate", "judgment_compiler.py")
        assert jc.evidence_gate_errors(
            "duplicate", None, ["finding:prd-other-2026-01-01/finding-9"],
            empty), "an empty citable set must fail the duplicate gate"


class TestDispositionTransactionIsOneCriticalSection:
    """Codex MAJOR, PR #103 round 5. The lock started AFTER `_load_findings`,
    so it serialised stale snapshots rather than the transaction.

    Two concurrent dispositions each loaded the same snapshot, each mutated its
    own finding in its own copy, and each wrote the WHOLE list back. The second
    silently reverted the first while both processes exited 0 and both receipts
    recorded success -- lost disposition state, invisible to both writers.

    This reproducer drives the REAL `set-disposition` CLI in two concurrent
    processes against a real findings file. The review's own repro stubbed
    seven seams (`_load_findings`, `ledger_lock`, `assemble_packet`,
    `capture_from_triage`, `_write_all`, `_validate_record`,
    `validate_triage_decision`), which cannot distinguish a real race from one
    manufactured by its own harness. Measured before the fix: 6/6 runs lost an
    update. After: 6/6 clean.
    """

    def test_concurrent_dispositions_do_not_lose_an_update(
            self, fake_repo, write_config):
        import concurrent.futures
        prd = "prd-race-2026-08-04"
        write_config(fake_repo, {"config_schema_version": 1})
        findings_dir = fake_repo / ".prd-os" / "findings"
        findings_dir.mkdir(parents=True, exist_ok=True)
        rows = [{"id": f"finding-{i}", "prd_id": prd, "source": "manual",
                 "severity": "minor", "disposition": "pending",
                 "body": f"body {i}", "created_at": "2026-08-04T00:00:00Z"}
                for i in (1, 2)]
        path = findings_dir / f"{prd}-findings.jsonl"
        path.write_text("".join(json.dumps(r, sort_keys=True) + "\n"
                                for r in rows))
        writer = SCRIPTS_DIR / "findings_writer.py"
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(fake_repo),
                   # KIPI_JUDGMENT_CAPTURE=0 on purpose: the pre-fix code used
                   # a nullcontext on this branch, so it had NO serialisation
                   # at all. The race is a property of the read-modify-write,
                   # not of receipt capture.
                   KIPI_JUDGMENT_CAPTURE="0")

        def run(finding_id):
            return subprocess.run(
                [sys.executable, str(writer), "set-disposition", prd,
                 finding_id, "accepted", "--rationale", f"r-{finding_id}"],
                cwd=str(fake_repo), env=env, capture_output=True, text=True)

        # ITERATED, because a lost update is a RACE: one attempt wins or
        # loses on timing alone. A single-shot version of this test passed
        # against the unfixed file on its first run and failed on the next --
        # flaky in BOTH directions, and therefore worthless as a regression
        # guard. Eight rounds makes the red reliable (each round independently
        # loses an update roughly half the time on the unfixed code) while the
        # green stays deterministic: the fix admits no losing interleaving.
        for round_index in range(8):
            path.write_text("".join(json.dumps(r, sort_keys=True) + "\n"
                                    for r in rows))
            with concurrent.futures.ThreadPoolExecutor(2) as pool:
                results = list(pool.map(run, ["finding-1", "finding-2"]))
            assert all(r.returncode == 0 for r in results), \
                [r.stderr for r in results]
            final = {json.loads(line)["id"]: json.loads(line)["disposition"]
                     for line in path.read_text().splitlines() if line.strip()}
            assert final == {"finding-1": "accepted",
                             "finding-2": "accepted"}, (
                "a concurrent disposition was silently reverted while both "
                f"writers reported success (round {round_index}): {final}")


class TestNoPhantomReceiptWhenTheAnchorWriteFails:
    """Codex MAJOR, PR #103 round 6 — the THIRD distinct defect in this one
    transaction (after the write-to-receipt gap and the lost update).

    Root cause is not the anchor write. An APPEND-ONLY ledger cannot
    participate in a ROLLBACK-based transaction: the sequence was mutate
    findings -> append receipt -> write anchor, with rollback-of-findings as
    the failure path, and rollback cannot undo an append. So every failure
    after the append left the two artifacts disagreeing and the command
    reporting refusal for a decision that had already taken effect.

    The fix is to recover FORWARD past the append. The anchor is a pure
    function of the ledger, so an anchor failure is a stale derived artifact,
    not a lost transaction. The failure is INDUCED here (a directory occupying
    the tip path makes the write raise OSError), not asserted about.
    """

    def _break_the_anchor_path(self, repo):
        jc = _load_module("jc_anchor", "judgment_compiler.py")
        tip = jc.tip_path(_cfg_for(repo))
        tip.parent.mkdir(parents=True, exist_ok=True)
        tip.mkdir()          # a directory here makes write_tip raise OSError
        return jc

    def test_a_failed_anchor_write_does_not_refuse_or_orphan_the_decision(
            self, judgment_repo, run_findings_writer):
        jc = self._break_the_anchor_path(judgment_repo)
        proc = run_findings_writer(
            judgment_repo, "set-disposition", PRD_ID, "finding-1", "accepted",
            "--rationale", "the decision stands")
        assert proc.returncode == 0, (
            "a stale ANCHOR is not a failed decision; the receipt is durable "
            f"and must not be reported as a refusal:\n{proc.stderr}")
        assert "verify" in proc.stderr and "reanchor" in proc.stderr, (
            "the warning must name the inspection and repair path: "
            + proc.stderr)
        # The findings file kept the decision (no rollback past the append).
        path, rows = _findings_rows(judgment_repo)
        target = next(r for r in rows if r["id"] == "finding-1")
        assert target["disposition"] == "accepted", (
            f"the decision was rolled back despite being durable: {target}")
        # And the receipt is present, so the two artifacts AGREE.
        ledger = read_ledger(judgment_repo)
        assert len(ledger) == 1, f"expected exactly one receipt, got {ledger}"
        assert ledger[0]["finding"]["finding_id"] == "finding-1"

    def test_verify_reports_the_stale_anchor_so_it_is_not_silent(
            self, judgment_repo, run_findings_writer):
        """Exit 0 plus a stderr warning is only complete if something detects
        the stale anchor LATER -- a warning in an unattended run is lost."""
        self._break_the_anchor_path(judgment_repo)
        assert run_findings_writer(
            judgment_repo, "set-disposition", PRD_ID, "finding-1", "accepted",
            "--rationale", "the decision stands").returncode == 0
        verify = run_judgment(judgment_repo, "verify")
        assert verify.returncode != 0, "a stale anchor must not verify clean"
        combined = verify.stdout + verify.stderr
        # Assert the PROPERTY (the anchor problem is reported and named), not
        # one message. Which message fires depends on whether an anchor
        # already existed: a first-receipt failure leaves the anchor MISSING,
        # a later one leaves it UNDER-COUNTING. Both must be loud; only the
        # second is repairable by `reanchor`, which refuses a missing anchor
        # because it cannot tell a crashed write from a truncation.
        assert "anchor" in combined, combined
        assert ("MISSING" in combined or "BEYOND the tip anchor" in combined), \
            combined


# ---------------------------------------------------------------------------
# Judge output: disposition / reason-code pair consistency
# ---------------------------------------------------------------------------


def _load_jc(name: str = "jc_pairs"):
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, JUDGMENT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _judge_output(code: str, disposition: str) -> dict:
    return {"technical_validity": "valid", "technical_reason": "ok",
            "workflow_disposition": disposition, "workflow_reason_code": code,
            "evidence_refs": [], "missing_context": [], "confidence": 1.0}


class TestJudgeOutputPairConsistency:
    """`validate_judge_output` used to accept any code with any disposition.

    Severity is MINOR and the record says so: the escalation to major named
    "allows unsupported predictions into release-gate scoring", and that
    consequence does not hold -- `evidence_gate_errors` keys off BOTH fields,
    so a contradictory pair whose either half requires evidence is refused,
    degraded to needs-human, and dropped by `JUDGE_TO_LEGACY[...] is None`
    before any metric sees it. What DOES survive is narrower: a pair whose
    halves both happen to require no evidence reaches `_override_pattern_key`,
    where an agreeing disposition with a mismatched code reads as an override
    and can manufacture a policy candidate out of an agreement.
    """

    def test_a_contradictory_twin_pair_is_rejected(self):
        """The bad case, watched failing before the check existed."""
        jc = _load_jc()
        with pytest.raises(jc.ValidationError) as excinfo:
            jc.validate_judge_output(_judge_output("duplicate", "fix-now"),
                                     "judge run")
        assert "duplicate" in str(excinfo.value)
        assert "fix-now" in str(excinfo.value)

    @pytest.mark.parametrize(
        "code", [c for c in _load_jc("jc_pairs_ids").REASON_CODES
                 if c in _load_jc("jc_pairs_ids").WORKFLOW_DISPOSITIONS])
    def test_every_twin_code_rejects_every_other_disposition(self, code):
        """The rule has to bite for each twin, not just the one Codex named."""
        jc = _load_jc()
        for disposition in jc.WORKFLOW_DISPOSITIONS:
            if disposition == code or jc.JUDGE_TO_LEGACY[disposition] is None:
                continue
            with pytest.raises(jc.ValidationError):
                jc.validate_judge_output(_judge_output(code, disposition),
                                         "judge run")

    def test_every_legitimate_pair_still_passes(self):
        """THE half that matters. An over-strict contradiction check would
        convert real judge output into errors and score nothing, which is a
        worse failure than the one being fixed. The legitimate space is
        table-driven off the module's own enums so it cannot drift:

        - a twin code (one whose name is also a disposition) pairs with its
          own disposition, plus the needs-human sink;
        - a non-twin code is UNCONSTRAINED, because neither REASON_CODES nor
          WORKFLOW_DISPOSITIONS states what it refines and inventing that
          mapping today would be a second hand-maintained table.
        """
        jc = _load_jc()
        twins = set(jc.REASON_CODES) & set(jc.WORKFLOW_DISPOSITIONS)
        checked = 0
        for code in jc.REASON_CODES:
            for disposition in jc.WORKFLOW_DISPOSITIONS:
                if code in twins and disposition != code \
                        and jc.JUDGE_TO_LEGACY[disposition] is not None:
                    continue
                jc.validate_judge_output(_judge_output(code, disposition),
                                         "judge run")
                checked += 1
        assert checked >= len(jc.REASON_CODES), checked

    def test_the_gate_conversion_output_still_validates(self):
        """The conversion path is the pair check's real over-strictness trap.

        `_judge_block_from_run` rewrites workflow_disposition to needs-human
        and deliberately LEAVES the original reason code, so every converted
        receipt carries a non-matching pair. It is legitimate by construction:
        needs-human maps to None in JUDGE_TO_LEGACY, so it is excluded from
        scoring, and `converted_from` records what it was.
        """
        jc = _load_jc()
        packet = jc._fixture_packet(0)
        run = {"model": "m", "prompt_sha256": "0" * 64, "review_run_id": "r",
               "input_sha256": packet["packet_sha256"],
               "output": _judge_output("duplicate", "duplicate")}
        block = jc._judge_block_from_run(run, frozenset())
        assert block["converted_to_needs_human"] is True
        assert block["converted_from"] == "duplicate"
        assert block["output"]["workflow_reason_code"] == "duplicate"
        assert block["output"]["workflow_disposition"] == "needs-human"
        jc._validate_judge_block(block, "receipt")

    def test_the_enums_stay_in_sync(self):
        """The anti-drift device: the pair rule is derived from the two
        existing enums plus JUDGE_TO_LEGACY, so those three must agree."""
        jc = _load_jc()
        assert set(jc.WORKFLOW_DISPOSITIONS) == set(jc.JUDGE_TO_LEGACY)
        assert set(jc.REASON_CODES) & set(jc.WORKFLOW_DISPOSITIONS), \
            "no twin codes left: the pair rule would be a no-op"


# ---------------------------------------------------------------------------
# Citation provenance: the CLASS behind rounds 3-9, enumerated
# ---------------------------------------------------------------------------


def _maximal_packet(jc):
    """Every citable source populated at once, so one call to `_citable_refs`
    exercises all nine grammar prefixes instead of one per test."""
    packet = jc._fixture_packet(0)
    packet["issue_state"]["issue_id"] = "ASK-ACTIVE-UNRELATED"
    packet["duplicates"] = [{"prd_id": "prd-other", "finding_id": "finding-9",
                             "similarity": 0.9}]
    packet["related_prds"] = ["prd-other"]
    packet["prior_receipts"] = ["jr-0000000000000001"]
    packet["remediation"] = [{"issue_id": "ASK-111", "finding_id": "finding-1",
                              "closed_at": "2026-01-01T00:00:00Z",
                              "commit_sha": "a" * 40}]
    packet["scope"] = {"source": "docs/scope.md#s1", "sha256": "b" * 64}
    packet["packet_sha256"] = jc.packet_hash(packet)
    return packet


class TestCitationProvenance:
    """Rounds 3-9 each killed ONE guard of one class; the class kept moving one
    field over. `commit:<HEAD>` for `already-remediated` (round 3), then
    `issue:<active issue>` for `duplicate` (round 9, reintroduced by 83e3877).

    The rule is relational-vs-documentary, not always-exists: a code asserting
    a relationship to a specific other entity needs a finding-dependent source;
    a code invoking a document may cite an ambient one, which is why `scope:`
    is legitimate and must keep working.
    """

    def test_every_grammar_prefix_is_classified(self):
        """No unclassified prefix, or the enumeration has a blind spot."""
        jc = _load_jc("jc_prov")
        grammar = set(jc.EVIDENCE_REF_RE.pattern.split("(")[1]
                      .split(")")[0].split("|"))
        assert grammar == {p.rstrip(":") for p in jc.CITABLE_REF_PROVENANCE}
        assert set(jc.RELATIONAL_REASON_CODES) | \
            set(jc.DOCUMENTARY_REASON_CODES) == set(jc.EVIDENCE_REQUIREMENTS)

    def test_the_derived_forbidden_set_is_what_we_think(self):
        """The check ON the classification: a rule derived to catch `issue:`
        must also reproduce the two holes already closed by hand. If it did
        not, the axis would be wrong."""
        jc = _load_jc("jc_prov")
        assert set(jc.FORBIDDEN_CITABLE_PREFIXES) == {
            "issue:", "spillover:", "test:"}

    # getattr, not attribute access: the parametrize runs at COLLECTION, so a
    # hard reference makes this whole FILE uncollectable against a pre-fix
    # checkout -- which is exactly when you need to watch the case fail.
    @pytest.mark.parametrize("prefix", sorted(
        getattr(_load_jc("jc_prov_ids"), "CITABLE_REF_PROVENANCE", None)
        or {"finding:", "judgment:", "prd:", "issue:", "receipt:", "commit:",
            "scope:", "spillover:", "test:"}))
    def test_no_ambient_source_reaches_the_citable_set(self, prefix):
        """Table-driven over all nine prefixes against a MAXIMAL packet: every
        source populated, so a prefix that leaks has nowhere to hide."""
        jc = _load_jc("jc_prov")
        _view, citable = jc.judge_view(_maximal_packet(jc))
        emitted = [r for r in citable if r.startswith(prefix)]
        if prefix in jc.FORBIDDEN_CITABLE_PREFIXES:
            assert emitted == [], f"{prefix} leaked into the citable set"
        else:
            assert jc.CITABLE_REF_PROVENANCE[prefix] == "finding-dependent" \
                or prefix == "scope:"

    def test_documentary_codes_keep_their_ambient_source(self):
        """THE over-strictness half. `scope:` is ambient and legitimate: the
        claim is 'this falls outside that documented scope', not 'this is the
        same thing as that entity'. A rule keyed on always-exists would have
        broken `scope-removed` / `out-of-scope` and scored nothing."""
        jc = _load_jc("jc_prov")
        _view, citable = jc.judge_view(_maximal_packet(jc))
        assert "scope:docs/scope.md#s1" in citable
        for code in jc.DOCUMENTARY_REASON_CODES:
            assert jc.evidence_gate_errors(
                code, None, ["scope:docs/scope.md#s1"], citable) == []

    def test_relational_codes_keep_a_finding_dependent_route(self):
        """Refusing everything would pass a membership test trivially while
        scoring zero cases. Each relational code that still HAS a source must
        still be satisfiable from the maximal packet."""
        jc = _load_jc("jc_prov")
        _view, citable = jc.judge_view(_maximal_packet(jc))
        for code, refs in (("duplicate", ["finding:prd-other/finding-9"]),
                           ("already-remediated", ["receipt:ASK-111"]),
                           ("superseded", ["judgment:jr-0000000000000001"])):
            assert jc.evidence_gate_errors(code, None, refs, citable) == [], code

    def test_owned_by_other_prd_is_unsatisfiable_on_the_judge_path(self):
        """Named, not silent. Its `issue:` group has no finding-dependent
        source left, so it always converts to needs-human. Inventing a source
        (reusing a remediation row's issue_id) would rebuild the hole."""
        jc = _load_jc("jc_prov")
        _view, citable = jc.judge_view(_maximal_packet(jc))
        errors = jc.evidence_gate_errors(
            "owned-by-other-prd", None,
            ["prd:prd-other", "issue:ASK-111"], citable)
        assert errors and "issue:" in errors[0]

    def test_the_round_9_reproducer_no_longer_scores(self):
        """Codex round 9, executed: a zero-duplicate packet cited the globally
        active issue and entered scoring as a supported duplicate
        (converted=False, scored_cases=1, exact_agreement=1.0)."""
        jc = _load_jc("jc_prov")
        packet = jc._fixture_packet(0)
        packet["issue_state"]["issue_id"] = "ASK-ACTIVE-UNRELATED"
        packet["duplicates"] = []
        packet["related_prds"] = []
        packet["packet_sha256"] = jc.packet_hash(packet)
        output = {"technical_validity": "valid", "technical_reason": "dupe",
                  "workflow_disposition": "duplicate",
                  "workflow_reason_code": "duplicate",
                  "evidence_refs": ["issue:ASK-ACTIVE-UNRELATED"],
                  "missing_context": [], "confidence": 1.0}
        run = {"model": "stub", "prompt_sha256": "0" * 64,
               "input_sha256": packet["packet_sha256"], "output": output}
        receipt = jc.build_receipt(
            packet, disposition="rejected", actor="founder",
            reason_code="duplicate",
            evidence_refs=["issue:ASK-ACTIVE-UNRELATED"], rationale="dupe",
            judge_run=run, supersedes=None, existing=[])
        assert receipt["judge"]["converted_to_needs_human"] is True
        assert receipt["judge"]["output"]["workflow_disposition"] == "needs-human"
        assert receipt["judge"]["output"]["evidence_refs"] == []
        scored = jc.evaluate([receipt])
        assert scored["cases"] == 0
        assert scored["exact_agreement"] == 0.0

    def test_the_class_guard_can_actually_fire(self):
        """Negative self-test. A guard that has never been watched refusing is
        not a guard. Widen the forbidden set and confirm a ref the builder DOES
        emit trips it."""
        jc = _load_jc("jc_prov")
        packet = _maximal_packet(jc)
        jc.FORBIDDEN_CITABLE_PREFIXES = frozenset({"finding:"})
        with pytest.raises(jc.ValidationError) as excinfo:
            jc.judge_view(packet)
        assert "ambient refs for a relational reason code" in str(excinfo.value)
        assert "finding:prd-other/finding-9" in str(excinfo.value)


# --- helpers for TestCrossCheckRunsByDefault -------------------------------

def _run_verify(repo: Path, *flags: str):
    r = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "judgment_compiler.py"), "verify", *flags],
        cwd=repo, capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def _prd(repo: Path, *args: str, stdin: str | None = None):
    script = "findings_writer.py" if args[0] in ("add", "set-disposition") else "prd_runner.py"
    r = subprocess.run([sys.executable, str(SCRIPTS_DIR / script), *args],
                       cwd=repo, capture_output=True, text=True, input=stdin)
    assert r.returncode == 0, f"{args}: {r.stderr}"
    return r


def _repo_with_two_receipts(tmp_path: Path) -> Path:
    """Two receipts written through the real triage chokepoint.

    Not hand-built: a hand-built ledger tests my idea of the format, and the
    forgery below has to be indistinguishable from a real ledger to mean
    anything.
    """
    repo = tmp_path / "jrepo"
    repo.mkdir()
    for cmd in (["init", "-q"], ["config", "user.email", "t@t.co"],
                ["config", "user.name", "t"]):
        subprocess.run(["git", *cmd], cwd=repo, capture_output=True)
    (repo / "README.md").write_text("x\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "i"], cwd=repo, capture_output=True)
    subprocess.run([sys.executable, str(SCRIPTS_DIR / "prd_os_init.py")],
                   cwd=repo, capture_output=True)
    out = _prd(repo, "new", "probe", "--title", "T").stdout
    prd_id = json.loads(out)["created"]
    _prd(repo, "advance", "draft")
    _prd(repo, "add", prd_id, "--source", "claude-review",
         stdin='[{"severity":"major","body":"f1"},{"severity":"minor","body":"f2"}]')
    for fid in ("finding-1", "finding-2"):
        _prd(repo, "set-disposition", prd_id, fid, "accepted",
             "--reason-code", "valid-fix-now", "--actor", "t")
    return repo


def _forge_truncation(repo: Path) -> None:
    """Drop the last receipt AND rewrite the tip anchor so it agrees.

    The only attack that survives the hash chain, because any prefix of a valid
    chain is itself a valid chain and the anchor shares a writer with the
    ledger.
    """
    ledger = repo / ".prd-os/judgments.jsonl"
    tip = repo / ".prd-os/judgments-tip.json"
    lines = ledger.read_text().splitlines()
    assert len(lines) >= 2, "fixture needs 2 receipts to truncate one"
    ledger.write_text(lines[0] + "\n")
    t = json.loads(tip.read_text())
    t["count"] = 1
    t["last_receipt_sha256"] = hashlib.sha256(lines[0].encode()).hexdigest()
    t["last_receipt_id"] = json.loads(lines[0])["receipt_id"]
    tip.write_text(json.dumps(t))


# ---------------------------------------------------------------------------
# The independent check must run by DEFAULT, and say so when it cannot
# ---------------------------------------------------------------------------
#
# Measured by attack 2026-08-05 in a virgin repo: five tamper attempts (tail
# truncation, whole-ledger deletion, field mutation, receipt reorder, anchor
# deletion) are all caught by plain `verify`. The sixth -- truncate the tail
# AND rewrite the tip anchor so it agrees -- passes plain `verify` at rc=0
# printing "chain intact", and is caught ONLY by `--cross-check`.
#
# That boundary is honestly documented ("tamper-EVIDENT, not tamper-proof; only
# --cross-check is independent"). The defect is INVOCATION: the one attack that
# survives is the one the default command does not look for, so the command a
# person naturally runs is the command that reassures them wrongly.

class TestCrossCheckRunsByDefault:
    def test_forged_truncation_is_caught_without_passing_the_flag(self, tmp_path):
        repo = _repo_with_two_receipts(tmp_path)
        _forge_truncation(repo)
        rc, out, err = _run_verify(repo)
        assert rc == 2, (
            "plain `verify` reported the forged ledger as intact; the only "
            f"attack that survives the hash chain is invisible by default. {out}"
        )

    def test_explicit_flag_still_works(self, tmp_path):
        repo = _repo_with_two_receipts(tmp_path)
        _forge_truncation(repo)
        assert _run_verify(repo, "--cross-check")[0] == 2

    def test_opt_out_restores_the_old_behaviour(self, tmp_path):
        """An escape hatch is required: a repo mid-migration, or one whose
        findings ledger is unreadable, must still be able to check the chain
        alone rather than being blocked with no path forward."""
        repo = _repo_with_two_receipts(tmp_path)
        _forge_truncation(repo)
        rc, out, _ = _run_verify(repo, "--no-cross-check")
        assert rc == 0 and "chain intact" in out

    def test_clean_ledger_still_passes_by_default(self, tmp_path):
        """Negative-fire. Without this, a verify that always exits 2 would
        satisfy every assertion above."""
        repo = _repo_with_two_receipts(tmp_path)
        rc, out, err = _run_verify(repo)
        assert rc == 0, f"default cross-check broke the honest path: {err}"
        assert "2 receipt(s)" in out

    def test_pass_line_states_whether_the_independent_check_ran(self, tmp_path):
        """A PASS that does not say what it checked is the same reassurance
        problem one level up."""
        repo = _repo_with_two_receipts(tmp_path)
        assert "cross-checked" in _run_verify(repo)[1]
        assert "cross-check skipped" in _run_verify(repo, "--no-cross-check")[1]
