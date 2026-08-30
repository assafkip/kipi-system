#!/usr/bin/env python3
"""Ensure every registered kipi instance has its own local knowledge base.

Reads instance-registry.json and creates <memory>/graph.jsonl for each
instance that lacks one. Idempotent: existing files are never touched.

KB location:
  - instance_q_dir set: <path>/<instance_q_dir>/memory/graph.jsonl
  - else:               <path>/memory/graph.jsonl

Files stay untracked by design (fleet lefthook bans *.jsonl commits).
"""

import json
import sys
from pathlib import Path

REGISTRY = Path("/Users/assafkipnis/projects/kipi-system/instance-registry.json")


def kb_path(instance: dict) -> Path | None:
    root = Path(instance["path"])
    if not root.is_dir():
        return None
    q_dir = instance.get("instance_q_dir")
    base = root / q_dir if q_dir else root
    return base / "memory" / "graph.jsonl"


def main() -> int:
    registry = json.loads(REGISTRY.read_text())
    created, present, missing = [], [], []
    for inst in registry["instances"]:
        path = kb_path(inst)
        if path is None:
            missing.append((inst["name"], "path does not exist"))
            continue
        if path.exists():
            present.append(inst["name"])
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
        created.append(inst["name"])
        print(f"created: {inst['name']} -> {path}")

    print(f"\ntotal={len(registry['instances'])} "
          f"created={len(created)} present={len(present)} missing={len(missing)}")
    for name, why in missing:
        print(f"missing: {name} ({why})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
