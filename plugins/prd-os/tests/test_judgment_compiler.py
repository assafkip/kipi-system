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
                       "--evidence", "commit:" + "a" * 40,
                       disposition="rejected")
        assert proc.returncode == 0, proc.stderr

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
        proc = run_findings_writer(
            judgment_repo, "set-disposition", PRD_ID, "finding-1", "rejected",
            "--rationale", "same as finding-9",
            "--reason-code", "duplicate",
            "--evidence", f"finding:{PRD_ID}/finding-9")
        assert proc.returncode == 0, proc.stderr
        rec = read_ledger(judgment_repo)[-1]
        assert rec["human"]["reason_code"] == "duplicate"
        assert rec["human"]["evidence_refs"] == [f"finding:{PRD_ID}/finding-9"]

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
