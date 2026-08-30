from __future__ import annotations

import json
from pathlib import Path


class RegistryManager:
    # Readers index these directly (list_instances/list_excluded/list_eliminated),
    # so a registry written before a key existed crashed every read. The live
    # file drifted to a shape without 'excluded' and took kipi://instances down
    # with it; found only once the test suite could COLLECT (sp-dcd84af1).
    _REQUIRED_KEYS = {"instances": [], "excluded": [], "eliminated": []}

    def __init__(self, registry_path: Path):
        self.registry_path = registry_path

    def load(self) -> dict:
        if not self.registry_path.exists():
            return dict(self._REQUIRED_KEYS)
        with open(self.registry_path) as f:
            data = json.load(f)
        # Persisted external input: tolerate schema drift on read instead of
        # crashing every consumer (fable-discipline: validating loader).
        for key, default in self._REQUIRED_KEYS.items():
            data.setdefault(key, default)
        return data

    def save(self, data: dict) -> None:
        with open(self.registry_path, "w") as f:
            json.dump(data, f, indent=2)

    def list_instances(self) -> list[dict]:
        return self.load()["instances"]

    def list_excluded(self) -> list[dict]:
        return self.load()["excluded"]

    def list_eliminated(self) -> list[dict]:
        return self.load()["eliminated"]

    def get_skeleton(self) -> dict:
        return self.load()["skeleton"]

    def find_instance(self, name: str) -> dict | None:
        for inst in self.list_instances():
            if inst["name"] == name:
                return inst
        return None

    def add_instance(
        self,
        name: str,
        path: str,
        prefix: str = "q-system",
        instance_q_dir: str | None = None,
        inst_type: str = "subtree",
    ) -> dict:
        data = self.load()
        for inst in data["instances"]:
            if inst["name"] == name:
                raise ValueError(f"Instance '{name}' already exists")
        entry = {
            "name": name,
            "path": path,
            "subtree_prefix": prefix,
            "instance_q_dir": instance_q_dir,
            "type": inst_type,
            "has_git": True,
        }
        data["instances"].append(entry)
        self.save(data)
        return entry

    def remove_instance(self, name: str) -> bool:
        data = self.load()
        original_len = len(data["instances"])
        data["instances"] = [i for i in data["instances"] if i["name"] != name]
        if len(data["instances"]) == original_len:
            return False
        self.save(data)
        return True
