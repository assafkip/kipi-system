import json
import pytest
from pathlib import Path

from kipi_mcp.paths import KipiPaths


@pytest.fixture
def tmp_kipi_paths(tmp_path):
    """Create a KipiPaths with all dirs rooted under tmp_path."""
    paths = KipiPaths(
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
        state_dir=tmp_path / "state",
        repo_dir=tmp_path / "repo",
    )
    paths.ensure_dirs()
    return paths


@pytest.fixture
def tmp_registry(tmp_path):
    """Create a temporary instance registry for testing."""
    registry = {
        "skeleton": {
            "path": str(tmp_path / "skeleton"),
            "remote": "https://github.com/test/kipi-system.git"
        },
        "instances": [],
        "excluded": [],
        "eliminated": []
    }
    registry_path = tmp_path / "instance-registry.json"
    registry_path.write_text(json.dumps(registry, indent=2))
    return registry_path


@pytest.fixture
def tmp_registry_with_instances(tmp_path):
    """Create a registry with sample instances."""
    inst_path = tmp_path / "test-instance"
    inst_path.mkdir()
    (inst_path / "q-system").mkdir()

    clone_path = tmp_path / "test-clone"
    clone_path.mkdir()
    (clone_path / "q-system").mkdir()

    registry = {
        "skeleton": {
            "path": str(tmp_path / "skeleton"),
            "remote": "https://github.com/test/kipi-system.git"
        },
        "instances": [
            {
                "name": "test-instance",
                "path": str(inst_path),
                "subtree_prefix": "q-system",
                "instance_q_dir": None,
                "type": "subtree",
                "has_git": True
            },
            {
                "name": "test-clone",
                "path": str(clone_path),
                "subtree_prefix": "q-system",
                "instance_q_dir": None,
                "type": "direct-clone",
                "has_git": True
            }
        ],
        "excluded": [
            {"name": "excluded-one", "path": "/tmp/excluded", "reason": "Custom architecture"}
        ],
        "eliminated": [
            {"name": "old-plugin", "status": "already removed"}
        ]
    }
    registry_path = tmp_path / "instance-registry.json"
    registry_path.write_text(json.dumps(registry, indent=2))
    return registry_path


@pytest.fixture
def tmp_q_system(tmp_path):
    """Create a temporary q-system directory structure."""
    q = tmp_path / "q-system"
    q.mkdir()
    (q / "output").mkdir()
    (q / ".q-system").mkdir(parents=True)
    (q / ".q-system" / "steps").mkdir()
    (q / ".q-system" / "commands.md").write_text("")
    (q / ".q-system" / "agent-pipeline" / "templates").mkdir(parents=True)
    return q
