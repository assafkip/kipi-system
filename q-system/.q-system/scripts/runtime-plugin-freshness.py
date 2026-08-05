#!/usr/bin/env python3
"""Fail when the RUNNING plugin copy is older than the merged one.

Scar (2026-08-05, ASK-363): the Judgment Compiler shipped through PRs #98-#104
and was unreachable from both runtime paths for a day. Refreshing the
marketplace clone was assumed to be the fix. It was not sufficient, and that is
the whole point of this checker.

There are TWO layers, and only the second decides what actually loads:

  layer 1  ~/.claude/plugins/marketplaces/<mp>   git clone of the repo
  layer 2  ~/.claude/plugins/cache/<mp>/<plugin>/<version>   what Claude loads

`claude plugin marketplace update` moves layer 1 ONLY. Measured that day: after
a successful marketplace update the clone served prd-os 0.16.5 while
installed_plugins.json still pinned prd-os@kipi to 0.1.0 from an April install.
A checker that compared only clone HEAD to origin/main would have gone GREEN on
a box still loading five months of stale code. So version parity per installed
plugin is the assertion; the git-distance check is a secondary signal.

Exit 0 = every installed kipi plugin matches the marketplace. Exit 1 = at least
one is behind (or the clone is behind origin/main). Exit 2 = malformed input.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

DEFAULT_PLUGIN_ROOT = Path.home() / ".claude" / "plugins"


def _load_json(path: Path, label: str) -> dict:
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} is not valid JSON ({path}): {exc}") from exc
    except OSError as exc:
        raise ValueError(f"{label} unreadable ({path}): {exc}") from exc


def marketplace_versions(marketplace: Path) -> dict[str, str]:
    """name -> version, read from each plugin's own manifest in the clone."""
    out: dict[str, str] = {}
    plugins_dir = marketplace / "plugins"
    if not plugins_dir.is_dir():
        return out
    for child in sorted(plugins_dir.iterdir()):
        manifest = child / ".claude-plugin" / "plugin.json"
        if not manifest.is_file():
            continue
        data = _load_json(manifest, f"plugin manifest for {child.name}")
        name = data.get("name") or child.name
        version = data.get("version")
        if version:
            out[name] = str(version)
    return out


def installed_versions(registry: Path, marketplace_name: str) -> list[tuple[str, str, str]]:
    """(plugin_name, scope, version) for every entry from this marketplace."""
    data = _load_json(registry, "installed_plugins.json")
    plugins = data.get("plugins")
    if not isinstance(plugins, dict):
        raise ValueError(f"installed_plugins.json has no 'plugins' object ({registry})")
    rows: list[tuple[str, str, str]] = []
    suffix = "@" + marketplace_name
    for key, entries in plugins.items():
        if not key.endswith(suffix):
            continue
        name = key[: -len(suffix)]
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            rows.append((name, str(entry.get("scope", "?")), str(entry.get("version", "?"))))
    return rows


def clone_commits_behind(marketplace: Path) -> int | None:
    """How many commits origin/main is ahead of the clone. None if unknowable.

    Deliberately does NOT fetch. A gate that reaches the network is a gate that
    fails on a plane and then gets switched off. This reads the already-fetched
    remote ref, so the number is a FLOOR, never an overstatement.

    COUNTS ONLY COMMITS THAT TOUCH `plugins/`. It used to count every commit on
    origin/main, which made a docs-only merge -- the most common commit in this
    repo -- report the RUNNING PLUGINS as stale. That is a permanent false alarm
    on a detector that files a Linear issue, and a gate that cries wolf is a gate
    someone switches off.

    This is the resolution of a real disagreement across two review rounds, not a
    revert of either. Round 2 said dropping the behind-signal entirely was wrong,
    because a plugin commit can change runtime code WITHOUT bumping a manifest
    version and version-parity alone would miss it. Round 3 said the signal as
    built fires on changes that cannot affect a plugin. Both are true of a
    whole-repo count and neither is true once the count is scoped to the only
    subtree whose contents become the runtime.
    """
    if not (marketplace / ".git").exists():
        return None
    try:
        proc = subprocess.run(
            ["git", "-C", str(marketplace), "rev-list", "--count",
             "HEAD..origin/main", "--", "plugins/"],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    try:
        return int(proc.stdout.strip())
    except ValueError:
        return None


def clone_dirty_tracked(marketplace: Path) -> list[str]:
    """Tracked files with uncommitted edits in the clone. [] if unknowable.

    Tracked only, on purpose: untracked .bak files are the debris of in-place
    editing and are noise, while a modified TRACKED file is content that exists
    in the runtime and nowhere else.
    """
    if not (marketplace / ".git").exists():
        return []
    try:
        proc = subprocess.run(
            ["git", "-C", str(marketplace), "diff", "--name-only", "HEAD"],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if proc.returncode != 0:
        return []
    return [l for l in proc.stdout.splitlines() if l.strip()]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Fail when a running plugin is older than the merged one.")
    ap.add_argument("--plugin-root", default=str(DEFAULT_PLUGIN_ROOT),
                    help="Claude Code plugin root (default: ~/.claude/plugins)")
    ap.add_argument("--marketplace-name", default="kipi")
    args = ap.parse_args(argv)

    root = Path(args.plugin_root).expanduser()
    registry = root / "installed_plugins.json"
    marketplace = root / "marketplaces" / args.marketplace_name

    # The ONLY sanctioned quiet path. Absence of a plugin registry means this box
    # does not run Claude Code plugins at all (CI container, fresh clone). It is
    # printed, never silent: a check that goes quiet because its dependency
    # vanished is indistinguishable from a check that passed, and that shape has
    # bitten this fleet before.
    if not registry.is_file():
        print(f"SKIP: no plugin registry at {registry} (box does not run Claude Code plugins)")
        return 0
    if not marketplace.is_dir():
        print(f"SKIP: marketplace '{args.marketplace_name}' not installed at {marketplace}")
        return 0

    try:
        live = marketplace_versions(marketplace)
        installed = installed_versions(registry, args.marketplace_name)
    except ValueError as exc:
        sys.stderr.write(f"ERROR: {exc}\n")
        return 2

    stale: list[str] = []
    for name, scope, version in sorted(installed):
        want = live.get(name)
        if want is None:
            # Installed from a marketplace that no longer ships this plugin.
            # Not a staleness failure; report it so it is not invisible.
            print(f"  note   {name:22} scope={scope:8} installed={version:10} (not in marketplace)")
            continue
        if version != want:
            stale.append(f"  STALE  {name:22} scope={scope:8} installed={version:10} marketplace={want}")
        else:
            print(f"  ok     {name:22} scope={scope:8} {version}")

    behind = clone_commits_behind(marketplace)
    problems = list(stale)

    # Direct edits to the live runtime. Third recurrence on 2026-08-05: a
    # `Least-code bias` rule was hand-added to fable-discipline's SKILL.md in the
    # clone and existed nowhere on main, and two older drift stashes (2026-06-21,
    # 2026-07-01) sit behind it in the same clone. Patching the running copy
    # works, which is exactly why people do it, and the next refresh silently
    # discards it. A stash is a place to put the loss, not a mechanism that
    # prevents it -- so the detector goes here.
    dirty = clone_dirty_tracked(marketplace)
    if dirty:
        problems.append(
            f"  EDITED marketplace clone has uncommitted edits to {len(dirty)} tracked file(s); "
            "they will be discarded on the next refresh:"
        )
        problems.extend(f"           {f}" for f in dirty[:10])
    if behind:
        problems.append(
            f"  BEHIND marketplace clone is {behind} commit(s) behind origin/main "
            f"(floor: computed without fetching)"
        )

    if problems:
        sys.stderr.write(
            f"FAIL: the running '{args.marketplace_name}' plugins are not the merged ones.\n"
        )
        for line in problems:
            sys.stderr.write(line + "\n")
        sys.stderr.write(
            "\nFix (both layers, in this order):\n"
            f"  claude plugin marketplace update {args.marketplace_name}\n"
            f"  claude plugin update <plugin>@{args.marketplace_name} --scope <scope>\n"
            "The second is not optional: the marketplace update moves the clone,\n"
            "but Claude loads the version-keyed cache the registry pins.\n"
        )
        return 1

    print(f"PASS: every installed '{args.marketplace_name}' plugin matches the marketplace")
    return 0


if __name__ == "__main__":
    sys.exit(main())
