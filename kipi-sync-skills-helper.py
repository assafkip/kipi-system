#!/usr/bin/env python3
"""Sync skills from skeleton to subtree instances based on skill-manifest.json."""
import json
import os
import shutil
import sys


def sync(skeleton_dir, dry_run=False):
    registry_path = os.path.join(skeleton_dir, "instance-registry.json")
    manifest_path = os.path.join(skeleton_dir, "skill-manifest.json")
    skills_src = os.path.join(skeleton_dir, ".claude", "skills")

    registry = json.load(open(registry_path))
    manifest = json.load(open(manifest_path))

    print("=== Kipi Skill Sync ===")
    print(f"Source: {skills_src}")
    if dry_run:
        print("MODE: DRY RUN")
    print()

    # Show groups
    for group, info in manifest["skill_groups"].items():
        skills = ", ".join(info["skills"])
        print(f"  [{group}] {info['description']}")
        print(f"    {skills}")
    print()

    synced = 0
    skipped = 0

    for inst in registry["instances"]:
        if "merged_date" in inst:
            continue

        name = inst["name"]
        path = inst["path"]
        itype = inst.get("type", "subtree")

        print(f"--- {name} ---")

        if not os.path.isdir(path):
            print("  SKIP: path does not exist")
            skipped += 1
            print()
            continue

        if itype == "direct-clone":
            print("  SKIP: direct clone")
            skipped += 1
            print()
            continue

        groups = manifest["project_skills"].get(name, [])
        if not groups:
            print("  SKIP: no skill groups assigned")
            skipped += 1
            print()
            continue

        # Resolve skills for this project
        skills = []
        for g in groups:
            skills.extend(manifest["skill_groups"][g]["skills"])
        skills = sorted(set(skills))

        print(f"  Groups: {', '.join(groups)} ({len(skills)} skills)")
        target = os.path.join(path, ".claude", "skills")

        if dry_run:
            if os.path.isdir(target):
                existing = len(os.listdir(target))
                print(f"  Target has {existing} existing skills")
            for skill in skills:
                if os.path.isdir(os.path.join(target, skill)):
                    print(f"    UPDATE: {skill}")
                else:
                    print(f"    ADD: {skill}")
        else:
            os.makedirs(target, exist_ok=True)
            for skill in skills:
                src = os.path.join(skills_src, skill)
                dst = os.path.join(target, skill)
                if os.path.isdir(src):
                    if os.path.exists(dst) or os.path.islink(dst):
                        import subprocess
                        subprocess.run(["rm", "-rf", dst], check=True)
                    shutil.copytree(src, dst, symlinks=False)
                else:
                    print(f"  WARN: {skill} not found in skeleton")
            total = len(os.listdir(target))
            print(f"  OK: synced {len(skills)} skills ({total} total in target)")

        synced += 1
        print()

    print("=== Summary ===")
    print(f"  Synced:  {synced}")
    print(f"  Skipped: {skipped}")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "sync":
        skeleton_dir = sys.argv[2]
        dry_run = len(sys.argv) > 3 and sys.argv[3] == "--dry-run"
        sync(skeleton_dir, dry_run)
    elif cmd == "show-groups":
        manifest = json.load(open(sys.argv[2]))
        for group, info in manifest["skill_groups"].items():
            print(f"  [{group}] {', '.join(info['skills'])}")
    elif cmd == "plan":
        registry = json.load(open(sys.argv[2]))
        manifest = json.load(open(sys.argv[3]))
        for inst in registry["instances"]:
            if "merged_date" in inst:
                continue
            name = inst["name"]
            groups = manifest["project_skills"].get(name, [])
            skills = []
            for g in groups:
                skills.extend(manifest["skill_groups"][g]["skills"])
            csv = ",".join(sorted(set(skills))) or "NONE"
            print(f"{name}|{inst['path']}|{inst.get('type','subtree')}|{csv}")
