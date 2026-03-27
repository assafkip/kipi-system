import json

import pytest

from kipi_mcp.registry import RegistryManager


class TestLoad:
    def test_load_reads_registry_from_disk(self, tmp_registry):
        mgr = RegistryManager(tmp_registry)
        data = mgr.load()
        assert "skeleton" in data
        assert "instances" in data
        assert "excluded" in data
        assert "eliminated" in data

    def test_load_reflects_external_changes(self, tmp_registry):
        mgr = RegistryManager(tmp_registry)
        data = mgr.load()
        data["instances"].append({"name": "injected", "path": "/tmp"})
        tmp_registry.write_text(json.dumps(data, indent=2))
        reloaded = mgr.load()
        assert len(reloaded["instances"]) == 1


class TestListInstances:
    def test_list_instances_empty(self, tmp_registry):
        mgr = RegistryManager(tmp_registry)
        assert mgr.list_instances() == []

    def test_list_instances_returns_entries(self, tmp_registry_with_instances):
        mgr = RegistryManager(tmp_registry_with_instances)
        instances = mgr.list_instances()
        assert len(instances) == 2
        assert instances[0]["name"] == "test-instance"
        assert instances[1]["name"] == "test-clone"


class TestListExcludedAndEliminated:
    def test_list_excluded(self, tmp_registry_with_instances):
        mgr = RegistryManager(tmp_registry_with_instances)
        excluded = mgr.list_excluded()
        assert len(excluded) == 1
        assert excluded[0]["name"] == "excluded-one"

    def test_list_eliminated(self, tmp_registry_with_instances):
        mgr = RegistryManager(tmp_registry_with_instances)
        eliminated = mgr.list_eliminated()
        assert len(eliminated) == 1
        assert eliminated[0]["name"] == "old-plugin"


class TestGetSkeleton:
    def test_get_skeleton_returns_config(self, tmp_registry):
        mgr = RegistryManager(tmp_registry)
        skel = mgr.get_skeleton()
        assert "path" in skel
        assert "remote" in skel
        assert skel["remote"] == "https://github.com/test/kipi-system.git"


class TestFindInstance:
    def test_find_instance_exists(self, tmp_registry_with_instances):
        mgr = RegistryManager(tmp_registry_with_instances)
        inst = mgr.find_instance("test-clone")
        assert inst is not None
        assert inst["type"] == "direct-clone"

    def test_find_instance_missing_returns_none(self, tmp_registry_with_instances):
        mgr = RegistryManager(tmp_registry_with_instances)
        assert mgr.find_instance("nonexistent") is None


class TestAddInstance:
    def test_add_instance_persists_to_disk(self, tmp_registry):
        mgr = RegistryManager(tmp_registry)
        entry = mgr.add_instance("new-proj", "/tmp/new-proj")
        assert entry["name"] == "new-proj"
        assert entry["subtree_prefix"] == "q-system"
        assert entry["type"] == "subtree"
        assert entry["has_git"] is True
        on_disk = json.loads(tmp_registry.read_text())
        assert len(on_disk["instances"]) == 1
        assert on_disk["instances"][0]["name"] == "new-proj"

    def test_add_instance_custom_params(self, tmp_registry):
        mgr = RegistryManager(tmp_registry)
        entry = mgr.add_instance(
            "custom", "/tmp/custom", prefix="alt", instance_q_dir="my-q", inst_type="direct-clone"
        )
        assert entry["subtree_prefix"] == "alt"
        assert entry["instance_q_dir"] == "my-q"
        assert entry["type"] == "direct-clone"

    def test_add_instance_duplicate_raises(self, tmp_registry_with_instances):
        mgr = RegistryManager(tmp_registry_with_instances)
        with pytest.raises(ValueError, match="already exists"):
            mgr.add_instance("test-instance", "/tmp/dup")


class TestRemoveInstance:
    def test_remove_instance_persists_to_disk(self, tmp_registry_with_instances):
        mgr = RegistryManager(tmp_registry_with_instances)
        result = mgr.remove_instance("test-instance")
        assert result is True
        on_disk = json.loads(tmp_registry_with_instances.read_text())
        assert len(on_disk["instances"]) == 1
        assert on_disk["instances"][0]["name"] == "test-clone"

    def test_remove_instance_missing_returns_false(self, tmp_registry):
        mgr = RegistryManager(tmp_registry)
        assert mgr.remove_instance("ghost") is False
