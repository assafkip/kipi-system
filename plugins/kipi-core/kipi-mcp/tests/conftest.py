import importlib.util
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

# AND the package this plugin ships, which lives beside these tests at src/.
# Without it `kipi_mcp` only imports where someone has pip-installed the plugin,
# and a conftest that raises ImportError does not fail one test -- it aborts
# COLLECTION for the whole run. Measured 2026-08-29 on a fresh instance: this
# was one of exactly two errors standing between the fleet and an armed
# verify.sh floor (ASK-1129). An installed copy still wins: sys.path is only
# APPENDED to here, so a real install earlier on the path is used unchanged.
_SRC = Path(__file__).resolve().parents[1] / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.append(str(_SRC))

# ONE CHOKEPOINT FOR "IS THIS PLUGIN INSTALLED", not one guard per file.
#
# Codex major, PR #283. The first version put `pytest.importorskip` in the five
# files that import yaml or feedparser DIRECTLY. That is the wrong layer, and it
# was green here for the wrong reason: this machine has no pyyaml, so the guard
# fired before anything else could. On a machine WITH pyyaml the very same files
# reach `from pydantic import ...` (pulled in by mcp) and abort collection again.
# A guard that only works because of what happens to be missing locally is not a
# guard, it is a coincidence.
#
# The real question is not "is yaml importable" but "is this plugin installed",
# and that has ONE answer for the whole directory. The list is the plugin's own
# declared dependencies from pyproject.toml, by IMPORT name.
_REQUIRED = {
    "mcp": "mcp",
    "httpx": "httpx",
    "yaml": "pyyaml",
    "tenacity": "tenacity",
    "apify_client": "apify-client",
    "feedparser": "feedparser",
    "pytest_mock": "pytest-mock (dev extra)",
}
_MISSING = sorted(pkg for mod, pkg in _REQUIRED.items()
                  if importlib.util.find_spec(mod) is None)

if _MISSING:
    # Skip the directory rather than let an ImportError abort COLLECTION for the
    # whole run -- one uninstalled plugin is why `python3 -m pytest` at the root
    # of most of the fleet exited non-zero having executed nothing (ASK-1129).
    collect_ignore_glob = ["test_*.py"]


_SKIP_NOTE = ("kipi-mcp tests SKIPPED: the plugin is not installed here "
              "(missing %s). Install it to run them: "
              "pip install -e plugins/kipi-core/kipi-mcp[dev]" % ", ".join(_MISSING)
              if _MISSING else "")


def pytest_report_header(config):
    """Say it at the top of the run."""
    return _SKIP_NOTE or None


def pytest_configure(config):
    """AND as a warning, because the header is not always shown.

    collect_ignore_glob is silent by design, and a suite nobody can see skipping
    reads exactly like a suite that passes -- the failure this whole change
    exists to end. So it needs a channel that survives the floor's own flags:
    verify.sh runs pytest with `-q --no-header`, which SUPPRESSES the header.
    Measured, not assumed -- the first version used only the header and was
    invisible in exactly the run that matters. The warnings summary still prints
    under -q --no-header, so the warning is the load-bearing half and the header
    is the convenience.
    """
    if _SKIP_NOTE:
        config.issue_config_time_warning(UserWarning(_SKIP_NOTE), stacklevel=2)


if not _MISSING:
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
    # Each instance gets a REAL canonical tree. A registry row is not proof the
    # tree exists, and the resolver now refuses a root with no canonical/ (4 live
    # instances were resolving to directories that do not exist). A fixture that
    # describes an instance without one is describing something that cannot happen.
    inst_path = tmp_path / "test-instance"
    inst_path.mkdir()
    (inst_path / "q-system" / "canonical").mkdir(parents=True)
    (inst_path / "q-system" / "my-project").mkdir(parents=True)

    clone_path = tmp_path / "test-clone"
    clone_path.mkdir()
    (clone_path / "q-system" / "canonical").mkdir(parents=True)
    (clone_path / "q-system" / "my-project").mkdir(parents=True)

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
