import json

import pytest
from pathlib import Path

from kipi_mcp.validator import Validator
from kipi_mcp.registry import RegistryManager


def _make_agent_file(agents_dir: Path, name: str, numbered: bool = True):
    """Create a valid agent .md file with frontmatter and Reads section."""
    content = "---\ntitle: Agent\n---\n\n## Reads\n- bus/data.json\n"
    (agents_dir / name).write_text(content)


def _build_skeleton(tmp_path: Path) -> Path:
    """Build a minimal valid skeleton for all validation phases."""
    kipi_home = tmp_path / "kipi"
    kipi_home.mkdir()

    # q-system core
    q = kipi_home / "q-system"
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

    # Scripts
    for script in [
        "audit-morning.py",
        "verify-schedule.py",
        "token-guard.py",
        "verify-bus.py",
        "verify-orchestrator.py",
    ]:
        (qsys / script).write_text("# script\n")
    scripts_dir = qsys / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "scan-draft.py").write_text("# script\n")

    # Canonical
    canonical = q / "canonical"
    canonical.mkdir()
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
        (canonical / fname).write_text(f"# {fname}\n")

    # my-project
    my_proj = q / "my-project"
    my_proj.mkdir()
    (my_proj / "founder-profile.md").write_text("{{SETUP_NEEDED}}\n")

    # Voice skill
    voice = kipi_home / ".claude" / "skills" / "founder-voice"
    voice.mkdir(parents=True)
    (voice / "SKILL.md").write_text("# Voice Skill\n")
    refs = voice / "references"
    refs.mkdir()
    (refs / "voice-dna.md").write_text("# Voice DNA\n")
    (refs / "writing-samples.md").write_text("# Samples\n")

    # CLAUDE.md files
    (kipi_home / "CLAUDE.md").write_text("# Root\n@q-system\n")
    (q / "CLAUDE.md").write_text("# Q System\n")

    # Documentation files (phase 5)
    for fname in ["SETUP.md", "UPDATE.md", "CONTRIBUTE.md", "ARCHITECTURE.md"]:
        (kipi_home / fname).write_text(f"# {fname}\n")

    return kipi_home


def _make_registry(
    tmp_path: Path,
    kipi_home: Path,
    instances: list[dict] | None = None,
    eliminated: list[dict] | None = None,
) -> RegistryManager:
    registry_data = {
        "skeleton": {"path": str(kipi_home), "remote": "git@example.com:test.git"},
        "instances": instances or [],
        "excluded": [],
        "eliminated": eliminated or [],
    }
    reg_path = kipi_home / "instance-registry.json"
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
    kipi_home = _build_skeleton(tmp_path)
    registry = _make_registry(tmp_path, kipi_home)
    return kipi_home, registry


class TestPhase0:
    def test_phase_0_all_pass(self, skeleton):
        kipi_home, registry = skeleton
        v = Validator(kipi_home, registry)
        result = v.run(phase=0)
        assert result["failed"] == 0
        assert result["passed"] >= 2

    def test_phase_0_missing_registry(self, tmp_path):
        kipi_home = tmp_path / "empty"
        kipi_home.mkdir()
        (kipi_home / "q-system").mkdir()
        reg_path = kipi_home / "instance-registry.json"
        reg_path.write_text(json.dumps({
            "skeleton": {"path": str(kipi_home)},
            "instances": [],
            "excluded": [],
            "eliminated": [],
        }))
        registry = RegistryManager(reg_path)
        # Now delete the registry file
        reg_path.unlink()
        v = Validator(kipi_home, registry)
        result = v.run(phase=0)
        failed = [c for c in result["checks"] if c["result"] == "fail"]
        assert any("Registry" in c["description"] for c in failed)


class TestPhase1:
    def test_phase_1_skeleton_integrity(self, skeleton):
        kipi_home, registry = skeleton
        v = Validator(kipi_home, registry)
        result = v.run(phase=1)
        assert result["failed"] == 0
        assert result["passed"] > 10

    def test_phase_1_detects_ktlyst(self, tmp_path):
        kipi_home = _build_skeleton(tmp_path)
        registry = _make_registry(tmp_path, kipi_home)
        agents_dir = (
            kipi_home / "q-system" / ".q-system" / "agent-pipeline" / "agents"
        )
        # Inject KTLYST into an agent file
        (agents_dir / "01-agent-1.md").write_text(
            "---\ntitle: Agent\n---\n\n## Reads\n- KTLYST data\n"
        )
        v = Validator(kipi_home, registry)
        result = v.run(phase=1)
        ktlyst_checks = [
            c
            for c in result["checks"]
            if "KTLYST" in c["description"] and "agents" in c["description"]
        ]
        assert any(c["result"] == "fail" for c in ktlyst_checks)

    def test_phase_1_detects_hardcoded_paths(self, tmp_path):
        kipi_home = _build_skeleton(tmp_path)
        registry = _make_registry(tmp_path, kipi_home)
        agents_dir = (
            kipi_home / "q-system" / ".q-system" / "agent-pipeline" / "agents"
        )
        (agents_dir / "02-agent-2.md").write_text(
            "---\ntitle: Agent\n---\n\n## Reads\n- /Users/assafkip/code\n"
        )
        v = Validator(kipi_home, registry)
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
        kipi_home = _build_skeleton(tmp_path)
        inst1 = _make_instance(tmp_path, "project-a", "subtree", 36)
        inst2 = _make_instance(tmp_path, "project-b", "direct-clone", 20)
        registry = _make_registry(
            tmp_path, kipi_home, instances=[inst1, inst2]
        )
        v = Validator(kipi_home, registry)
        result = v.run(phase=2)
        inst_checks = [
            c for c in result["checks"] if c["description"].startswith("[")
        ]
        assert len(inst_checks) > 0
        # Both instances should have checks
        a_checks = [c for c in inst_checks if "[project-a]" in c["description"]]
        b_checks = [c for c in inst_checks if "[project-b]" in c["description"]]
        assert len(a_checks) > 0
        assert len(b_checks) > 0


class TestPhase5:
    def test_phase_5_docs(self, skeleton):
        kipi_home, registry = skeleton
        v = Validator(kipi_home, registry)
        result = v.run(phase=5)
        doc_checks = [
            c for c in result["checks"] if "Documentation" in c["description"]
        ]
        assert all(c["result"] == "pass" for c in doc_checks)
        assert len(doc_checks) == 4

    def test_phase_5_missing_docs_fail(self, tmp_path):
        kipi_home = _build_skeleton(tmp_path)
        (kipi_home / "SETUP.md").unlink()
        (kipi_home / "UPDATE.md").unlink()
        registry = _make_registry(tmp_path, kipi_home)
        v = Validator(kipi_home, registry)
        result = v.run(phase=5)
        doc_fails = [
            c
            for c in result["checks"]
            if "Documentation" in c["description"] and c["result"] == "fail"
        ]
        assert len(doc_fails) == 2


class TestRun:
    def test_run_returns_structured_result(self, skeleton):
        kipi_home, registry = skeleton
        v = Validator(kipi_home, registry)
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
        kipi_home, registry = skeleton
        v = Validator(kipi_home, registry)
        result_normal = v.run(phase=1, verbose=False)
        result_verbose = v.run(phase=1, verbose=True)
        # Verbose should not break anything; same check count
        assert result_normal["passed"] == result_verbose["passed"]
        assert result_normal["failed"] == result_verbose["failed"]
