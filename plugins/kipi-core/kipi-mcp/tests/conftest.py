import json
import sys
import pytest
from pathlib import Path

# Make this directory importable so helpers below can be reached as
# `from conftest import write_registry`. pytest loads conftest under its own
# private module name, so without this a test importing `conftest` gets
# ModuleNotFoundError. The plain-function helper is needed by _build_skeleton in
# test_validator.py, which is a helper, not a fixture, and so cannot receive one.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from kipi_mcp.paths import KipiPaths


def write_registry(base: Path, repo: Path, instance: str = "test",
                   instance_q_dir=None, subtree_prefix: str = "q-system") -> Path:
    """Register `repo` as `instance` so canonical_dir / my_project_dir resolve.

    Those two properties are repo-derived now and FAIL CLOSED on an unregistered
    instance, so any test constructing KipiPaths by hand needs this. Also creates
    the two repo-owned dirs, because ensure_dirs() deliberately no longer does:
    they are tracked git content, and this stands in for the git tree.
    """
    root = repo / (instance_q_dir or subtree_prefix)
    (root / "canonical").mkdir(parents=True, exist_ok=True)
    (root / "my-project").mkdir(parents=True, exist_ok=True)
    base.mkdir(parents=True, exist_ok=True)
    (base / "instance-registry.json").write_text(json.dumps({
        "skeleton": {"path": str(repo)},
        "instances": [{"name": instance, "path": str(repo),
                       "subtree_prefix": subtree_prefix,
                       "instance_q_dir": instance_q_dir}],
        "excluded": [], "eliminated": [],
    }), encoding="utf-8")
    return base / "instance-registry.json"


@pytest.fixture
def tmp_kipi_paths(tmp_path):
    """Create a KipiPaths with all dirs rooted under tmp_path.

    REGISTERED, and the repo-owned dirs are created here rather than by
    ensure_dirs(). canonical_dir and my_project_dir are now derived from the
    instance's own tree via the registry (they used to be plugin-data, which is
    why kipi_canonical_digest read an empty directory fleet-wide). Two consequences
    every consumer of this fixture depends on:

      1. An unregistered instance FAILS CLOSED, so the registry row below is not
         decoration -- without it every test touching canonical/ raises.
      2. ensure_dirs() no longer mkdirs those two, because they are tracked git
         content, not tool-created state. The fixture stands in for the git tree.
    """
    base = tmp_path / "base"
    repo = tmp_path / "repo"
    (repo / "q-system" / "canonical").mkdir(parents=True, exist_ok=True)
    (repo / "q-system" / "my-project").mkdir(parents=True, exist_ok=True)
    base.mkdir(parents=True, exist_ok=True)
    (base / "instance-registry.json").write_text(json.dumps({
        "skeleton": {"path": str(repo)},
        "instances": [{
            "name": "test-instance",
            "path": str(repo),
            "subtree_prefix": "q-system",
            "instance_q_dir": None,
        }],
        "excluded": [], "eliminated": [],
    }), encoding="utf-8")

    paths = KipiPaths(base_dir=base, repo_dir=repo, instance="test-instance")
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
