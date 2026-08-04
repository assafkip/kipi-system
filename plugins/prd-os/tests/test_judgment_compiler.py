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

    def test_g2_technical_validity_and_workflow_disposition_are_separate(self, judgment_repo):
        """G-2: a technically valid finding recorded as a workflow duplicate."""
        packet_path, packet = assemble_packet(judgment_repo)
        judge = make_judge_run(
            packet, disposition="duplicate", reason_code="duplicate",
            evidence=[f"finding:{PRD_ID}/finding-1"],
        )
        judge_path = judgment_repo / "judge.json"
        judge_path.write_text(json.dumps(judge))
        proc = capture(
            judgment_repo, packet_path, "--judge-run", str(judge_path),
            "--reason-code", "duplicate",
            "--evidence", f"finding:{PRD_ID}/finding-1",
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
        """Independent completeness source: findings_writer's own ledger."""
        assert run_findings_writer(
            judgment_repo, "set-disposition", PRD_ID, "finding-1", "accepted",
            env_extra={"KIPI_JUDGMENT_CAPTURE": "0"}).returncode == 0
        assert read_ledger(judgment_repo) == []
        plain = run_judgment(judgment_repo, "verify")
        assert plain.returncode == 0  # chain itself is fine (it is empty)
        crossed = run_judgment(judgment_repo, "verify", "--cross-check")
        assert crossed.returncode == 2
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
