import json

import pytest
from pathlib import Path

from kipi_mcp.paths import KipiPaths
from kipi_mcp.validator import Validator
from kipi_mcp.registry import RegistryManager


def _make_agent_file(agents_dir: Path, name: str, numbered: bool = True):
    """Create a valid agent .md file with frontmatter and Reads section."""
    content = "---\ntitle: Agent\n---\n\n## Reads\n- bus/data.json\n"
    (agents_dir / name).write_text(content)


def _build_skeleton(tmp_path: Path) -> tuple[KipiPaths, Path]:
    """Build a minimal valid skeleton for all validation phases.

    Returns (paths, repo_dir) where paths is a KipiPaths with user data
    dirs under tmp_path, and repo_dir is the repo root.
    """
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    paths = KipiPaths(
        base_dir=tmp_path / "base",
        repo_dir=repo_dir,
        instance="test",
    )
    paths.ensure_dirs()

    # q-system core (repo code)
    q = repo_dir / "q-system"
    q.mkdir()
    qsys = q / ".q-system"
    qsys.mkdir()
    agents_dir = qsys / "agent-pipeline" / "agents"
    agents_dir.mkdir(parents=True)

    # 36 numbered agent files
    for i in range(1, 37):
        _make_agent_file(agents_dir, f"{i:02d}-agent-{i}.md")

    # Special agent files
    (agents_dir / "step-orchestrator.md").write_text("# Orchestrator\n")
    (agents_dir / "_cadence-config.yaml").write_text("cadence: daily\n")
    (agents_dir / "_auto-fail-checklist.md").write_text("# Checklist\n")

    # Scripts (only hook scripts remain in q-system/)
    (qsys / "token-guard.py").write_text("# script\n")

    # Canonical files (user data -> config_dir)
    for fname in [
        "discovery.md",
        "objections.md",
        "talk-tracks.md",
        "decisions.md",
        "engagement-playbook.md",
        "lead-lifecycle-rules.md",
        "market-intelligence.md",
        "pricing-framework.md",
        "verticals.md",
    ]:
        (paths.canonical_dir / fname).write_text(f"# {fname}\n")

    # founder-profile.md (user data -> config_dir)
    paths.founder_profile.write_text("{{SETUP_NEEDED}}\n")

    # Voice skill (repo code)
    voice = repo_dir / ".claude" / "skills" / "founder-voice"
    voice.mkdir(parents=True)
    (voice / "SKILL.md").write_text("# Voice Skill\n")
    refs = voice / "references"
    refs.mkdir()
    (refs / "voice-dna.md").write_text("# Voice DNA\n")
    (refs / "writing-samples.md").write_text("# Samples\n")

    # CLAUDE.md files (repo code)
    (repo_dir / "CLAUDE.md").write_text("# Root\n@q-system\n")
    (q / "CLAUDE.md").write_text("# Q System\n")

    # Documentation files (repo code, phase 5)
    for fname in ["SETUP.md", "UPDATE.md", "CONTRIBUTE.md", "ARCHITECTURE.md"]:
        (repo_dir / fname).write_text(f"# {fname}\n")

    return paths, repo_dir


def _make_registry(
    tmp_path: Path,
    repo_dir: Path,
    instances: list[dict] | None = None,
    eliminated: list[dict] | None = None,
) -> RegistryManager:
    registry_data = {
        "skeleton": {"path": str(repo_dir), "remote": "git@example.com:test.git"},
        "instances": instances or [],
        "excluded": [],
        "eliminated": eliminated or [],
    }
    reg_path = repo_dir / "instance-registry.json"
    reg_path.write_text(json.dumps(registry_data, indent=2))
    return RegistryManager(reg_path)


def _make_instance(
    tmp_path: Path,
    name: str,
    inst_type: str = "subtree",
    agent_count: int = 36,
) -> dict:
    """Create an instance directory with proper structure and return registry entry."""
    inst_path = tmp_path / name
    inst_path.mkdir(parents=True, exist_ok=True)

    prefix = "q-system"

    if inst_type == "subtree":
        agents_dir = inst_path / prefix / ".q-system" / "agent-pipeline" / "agents"
    else:
        agents_dir = inst_path / ".q-system" / "agent-pipeline" / "agents"

    agents_dir.mkdir(parents=True, exist_ok=True)
    (inst_path / prefix).mkdir(exist_ok=True)

    for i in range(1, agent_count + 1):
        _make_agent_file(agents_dir, f"{i:02d}-agent.md")

    (inst_path / "CLAUDE.md").write_text("# Instance\n@q-system import\n")

    return {
        "name": name,
        "path": str(inst_path),
        "subtree_prefix": prefix,
        "instance_q_dir": None,
        "type": inst_type,
        "has_git": True,
    }


@pytest.fixture
def skeleton(tmp_path):
    paths, repo_dir = _build_skeleton(tmp_path)
    registry = _make_registry(tmp_path, repo_dir)
    return paths, registry


class TestPhase0:
    def test_phase_0_all_pass(self, skeleton):
        paths, registry = skeleton
        v = Validator(paths, registry)
        result = v.run(phase=0)
        assert result["failed"] == 0
        assert result["passed"] >= 2

    def test_phase_0_missing_registry(self, tmp_path):
        repo_dir = tmp_path / "empty"
        repo_dir.mkdir()
        (repo_dir / "q-system").mkdir()
        paths = KipiPaths(
            base_dir=tmp_path / "base2",
            repo_dir=repo_dir,
            instance="test",
        )
        reg_path = repo_dir / "instance-registry.json"
        reg_path.write_text(json.dumps({
            "skeleton": {"path": str(repo_dir)},
            "instances": [],
            "excluded": [],
            "eliminated": [],
        }))
        registry = RegistryManager(reg_path)
        reg_path.unlink()
        v = Validator(paths, registry)
        result = v.run(phase=0)
        failed = [c for c in result["checks"] if c["result"] == "fail"]
        assert any("Registry" in c["description"] for c in failed)


class TestPhase1:
    def test_phase_1_skeleton_integrity(self, skeleton):
        paths, registry = skeleton
        v = Validator(paths, registry)
        result = v.run(phase=1)
        assert result["failed"] == 0
        assert result["passed"] > 10

    def test_phase_1_detects_ktlyst(self, tmp_path):
        paths, repo_dir = _build_skeleton(tmp_path)
        registry = _make_registry(tmp_path, repo_dir)
        agents_dir = (
            repo_dir / "q-system" / ".q-system" / "agent-pipeline" / "agents"
        )
        (agents_dir / "01-agent-1.md").write_text(
            "---\ntitle: Agent\n---\n\n## Reads\n- KTLYST data\n"
        )
        v = Validator(paths, registry)
        result = v.run(phase=1)
        ktlyst_checks = [
            c
            for c in result["checks"]
            if "KTLYST" in c["description"] and "agents" in c["description"]
        ]
        assert any(c["result"] == "fail" for c in ktlyst_checks)

    def test_phase_1_detects_hardcoded_paths(self, tmp_path):
        paths, repo_dir = _build_skeleton(tmp_path)
        registry = _make_registry(tmp_path, repo_dir)
        agents_dir = (
            repo_dir / "q-system" / ".q-system" / "agent-pipeline" / "agents"
        )
        (agents_dir / "02-agent-2.md").write_text(
            "---\ntitle: Agent\n---\n\n## Reads\n- /Users/assafkip/code\n"
        )
        v = Validator(paths, registry)
        result = v.run(phase=1)
        path_checks = [
            c
            for c in result["checks"]
            if "hardcoded" in c["description"].lower()
            and "agents" in c["description"].lower()
        ]
        assert any(c["result"] == "fail" for c in path_checks)


class TestPhase2:
    def test_phase_2_parameterized(self, tmp_path):
        paths, repo_dir = _build_skeleton(tmp_path)
        inst1 = _make_instance(tmp_path, "project-a", "subtree", 36)
        inst2 = _make_instance(tmp_path, "project-b", "direct-clone", 20)
        registry = _make_registry(
            tmp_path, repo_dir, instances=[inst1, inst2]
        )
        v = Validator(paths, registry)
        result = v.run(phase=2)
        inst_checks = [
            c for c in result["checks"] if c["description"].startswith("[")
        ]
        assert len(inst_checks) > 0
        a_checks = [c for c in inst_checks if "[project-a]" in c["description"]]
        b_checks = [c for c in inst_checks if "[project-b]" in c["description"]]
        assert len(a_checks) > 0
        assert len(b_checks) > 0


class TestPhase5:
    def test_phase_5_docs(self, skeleton):
        paths, registry = skeleton
        v = Validator(paths, registry)
        result = v.run(phase=5)
        doc_checks = [
            c for c in result["checks"] if "Documentation" in c["description"]
        ]
        assert all(c["result"] == "pass" for c in doc_checks)
        assert len(doc_checks) == 4

    def test_phase_5_missing_docs_fail(self, tmp_path):
        paths, repo_dir = _build_skeleton(tmp_path)
        (repo_dir / "SETUP.md").unlink()
        (repo_dir / "UPDATE.md").unlink()
        registry = _make_registry(tmp_path, repo_dir)
        v = Validator(paths, registry)
        result = v.run(phase=5)
        doc_fails = [
            c
            for c in result["checks"]
            if "Documentation" in c["description"] and c["result"] == "fail"
        ]
        assert len(doc_fails) == 2


class TestRun:
    def test_run_returns_structured_result(self, skeleton):
        paths, registry = skeleton
        v = Validator(paths, registry)
        result = v.run(phase=5)
        assert "phase" in result
        assert "passed" in result
        assert "failed" in result
        assert "warned" in result
        assert "checks" in result
        assert "errors" in result
        assert result["phase"] == 5
        assert isinstance(result["checks"], list)
        assert isinstance(result["errors"], list)
        for check in result["checks"]:
            assert "description" in check
            assert "result" in check
            assert check["result"] in ("pass", "fail", "warn")
            assert "detail" in check

    def test_verbose_flag(self, skeleton):
        paths, registry = skeleton
        v = Validator(paths, registry)
        result_normal = v.run(phase=1, verbose=False)
        result_verbose = v.run(phase=1, verbose=True)
        assert result_normal["passed"] == result_verbose["passed"]
        assert result_normal["failed"] == result_verbose["failed"]
