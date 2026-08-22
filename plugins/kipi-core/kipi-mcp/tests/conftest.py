import json
import pytest
from pathlib import Path

from kipi_mcp.paths import KipiPaths


@pytest.fixture
def tmp_kipi_paths(tmp_path):
    """Create a KipiPaths with all dirs rooted under tmp_path."""
    paths = KipiPaths(
        base_dir=tmp_path / "base",
        repo_dir=tmp_path / "repo",
        instance="test-instance",
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
    (q / "agent-pipeline" / "agents").mkdir(parents=True)
    (q / "agent-pipeline" / "templates").mkdir(parents=True)
    return q


@pytest.fixture
def tmp_harvest_store(tmp_path):
    """Create a HarvestStore backed by a temp DB."""
    from kipi_mcp.harvest_store import HarvestStore
    db = tmp_path / "metrics.db"
    store = HarvestStore(db_path=db)
    store.init_db()
    return store


@pytest.fixture
def tmp_sources_dir(tmp_path):
    """Create a temporary sources directory with sample YAML configs."""
    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "chrome").mkdir()
    return sources


@pytest.fixture
def registry_with_domain_dir(tmp_path):
    """A registry whose instance names a domain dir that is NOT q-system.

    Every pre-existing fixture set `instance_q_dir: None`, so the registry branch of the
    path contract had no test at all and would have shipped unexercised. Mirrors the real
    shape: a repo holding both `q-system/` (skeleton-synced code) and a named domain dir
    that actually owns `canonical/`.
    """
    repo = tmp_path / "domain-instance"
    (repo / "q-system").mkdir(parents=True)
    (repo / "q-domain" / "canonical").mkdir(parents=True)
    (repo / "q-domain" / "my-project").mkdir(parents=True)

    registry = {
        "skeleton": {"path": str(tmp_path / "skeleton"), "remote": "https://example.invalid/x.git"},
        "instances": [
            {
                "name": "domain-instance",
                "path": str(repo),
                "subtree_prefix": "q-system",
                "instance_q_dir": "q-domain",
                "type": "subtree",
                "has_git": True,
            }
        ],
        "excluded": [],
        "eliminated": [],
    }
    registry_path = tmp_path / "instance-registry.json"
    registry_path.write_text(json.dumps(registry, indent=2))
    return registry_path, repo
