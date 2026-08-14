#!/usr/bin/env python3
"""plugin-parity-check: does the code the SLASH COMMANDS run match the skeleton?

WHY THIS EXISTS (scar, ASK-721, measured 2026-08-13):

Every prd-os command invokes `"${CLAUDE_PLUGIN_ROOT}/scripts/prd_runner.py"` --
21 references across plugins/prd-os/commands/*.md. CLAUDE_PLUGIN_ROOT does NOT
resolve to this repo. It resolves to the MARKETPLACE CLONE under the user-level
claude plugins tree. On the day this was written the skeleton was at prd-os
0.27.0 and the clone was at 0.25.1, so a feature shipped that morning
(`spillover add --dor` auto-promoting a blocking finding into a Linear issue)
ran ONLY when an agent called the script by repo path. Every slash command ran
0.25.1, where the verb did not exist.

The clone was already at 0.25.1 while the skeleton was 0.26.5, so this is not a
regression from one release. It is drift with no detector, which is the actual
defect: `kipi update` fans the skeleton out to INSTANCE repos and never touches
the clone the runtime actually loads.

WHAT IT GATES, AND WHY ONLY THAT

Exit 1 on: a version MISMATCH, or a plugin present in the skeleton and MISSING
from the clone. That is the deployment question -- "is the running copy the copy
we built?" -- and it is answerable from two JSON files.

Content drift is REPORTED AND DOES NOT FAIL, on purpose. The clone is a working
git checkout: measured 2026-08-13 it carried six modified files and six
`*.pre-*.bak` files that exist nowhere in the skeleton. Nothing in this repo can
delete a file inside `.claude/` (apply_claude_changes.py is additive-only by
design), so gating on byte-equality would build a check that can NEVER go green.
A gate whose green state is unreachable gets switched off, and a gate that is off
protects nothing. So content drift is an advisory count next to the verdict --
information, never a blocker.

The honest residue: a plugin whose version was bumped WITHOUT its content being
copied passes this check. The advisory line is the only thing that shows it, and
nothing forces anyone to read an advisory line.

USAGE

    python3 q-system/.q-system/scripts/plugin-parity-check.py
    python3 q-system/.q-system/scripts/plugin-parity-check.py --json

    --skeleton DIR     repo holding plugins/ (default: this repo)
    --marketplace DIR  the clone the runtime loads
                       (default: $KIPI_MARKETPLACE_ROOT, else
                        ~/.claude/plugins/marketplaces/kipi)

Exit: 0 every plugin in parity, 1 any mismatch/missing, 2 the check itself could
not run (no plugins dir, unreadable manifest).
"""
import argparse
import hashlib
import json
import os
import sys

# Files that exist in a working checkout and never in a released tree. Excluded
# from the ADVISORY content hash only -- they cannot affect the verdict, which is
# version-only. Kept narrow: an unknown stray file SHOULD show up in the count.
NOISE_DIRS = {"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache"}
NOISE_SUFFIXES = (".pyc", ".pyo")


def default_marketplace():
    env = os.environ.get("KIPI_MARKETPLACE_ROOT")
    if env:
        return env
    return os.path.join(
        os.path.expanduser("~"), ".claude", "plugins", "marketplaces", "kipi"
    )


class ManifestUnreadable(Exception):
    """A manifest exists but could not be read as a versioned plugin manifest."""


def read_version(plugin_dir):
    """Return the plugin's declared version, or None if it has NO manifest.

    ABSENT AND MALFORMED ARE DIFFERENT ANSWERS (Codex review of #142, minor).
    This returned None for three unrelated situations: no manifest file, JSON
    that will not parse, and a manifest carrying no `version` key. The caller
    reads None as "not a plugin, skip it", which is right for the first and
    silently drops a real plugin for the other two.

    That is worse than it sounds because of how the exit code is derived: the
    verdict is `any(status != MATCH for row in rows)`, and `any([])` is False.
    So a skeleton whose manifests all failed to parse produced ZERO rows, exit
    0, and the sentence "PASS: all 0 plugins in version parity." A drift
    detector reporting PASS precisely when it could not read the thing it
    checks is the failure mode worth spending an exception on.

    So absence stays None (a directory under plugins/ that is genuinely not a
    plugin is not this check's business) and unreadable RAISES.
    """
    manifest = os.path.join(plugin_dir, ".claude-plugin", "plugin.json")
    if not os.path.isfile(manifest):
        return None
    try:
        with open(manifest, encoding="utf-8") as handle:
            data = json.load(handle)
    except (json.JSONDecodeError, OSError) as exc:
        raise ManifestUnreadable(f"{manifest}: {exc}") from exc
    version = data.get("version") if isinstance(data, dict) else None
    if version is None:
        raise ManifestUnreadable(f"{manifest}: no 'version' key")
    return version


def content_files(plugin_dir):
    """Relative paths of every non-noise file under a plugin dir."""
    found = []
    for root, dirs, files in os.walk(plugin_dir):
        dirs[:] = [d for d in dirs if d not in NOISE_DIRS]
        for name in files:
            if name.endswith(NOISE_SUFFIXES):
                continue
            full = os.path.join(root, name)
            found.append(os.path.relpath(full, plugin_dir))
    return sorted(found)


def file_digest(path):
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
    except OSError:
        return "UNREADABLE"
    return digest.hexdigest()


def content_drift(skeleton_dir, clone_dir):
    """Count files that differ, are missing from the clone, or are clone-only.

    ADVISORY. Never feeds the exit code -- see the module docstring.
    """
    left = content_files(skeleton_dir)
    right = set(content_files(clone_dir)) if os.path.isdir(clone_dir) else set()
    differing = 0
    missing = 0
    for rel in left:
        if rel not in right:
            missing += 1
            continue
        a = file_digest(os.path.join(skeleton_dir, rel))
        b = file_digest(os.path.join(clone_dir, rel))
        if a != b:
            differing += 1
    extra = len(right - set(left))
    return {"differing": differing, "missing": missing, "clone_only": extra}


def compare(skeleton_root, marketplace_root):
    """One row per plugin in the skeleton. Rows are the whole result."""
    plugins_dir = os.path.join(skeleton_root, "plugins")
    if not os.path.isdir(plugins_dir):
        raise FileNotFoundError(f"no plugins/ directory under {skeleton_root}")

    rows = []
    for name in sorted(os.listdir(plugins_dir)):
        skel_dir = os.path.join(plugins_dir, name)
        if not os.path.isdir(skel_dir):
            continue
        skel_version = read_version(skel_dir)
        if skel_version is None:
            # Not a plugin (no manifest). Not this check's business.
            # A manifest that EXISTS and will not parse raises instead of
            # landing here -- see read_version.
            continue

        clone_dir = os.path.join(marketplace_root, "plugins", name)
        # The clone is the untrusted side, so its unreadable manifest is a ROW
        # (reported, non-MATCH, fails the run) rather than an exception that
        # would abandon the other plugins. The skeleton's own manifest is
        # different: if that will not parse the check has no baseline at all,
        # so read_version's raise propagates.
        try:
            clone_version = read_version(clone_dir)
        except ManifestUnreadable:
            clone_version = None
            status = "UNREADABLE"
            rows.append(
                {
                    "plugin": name,
                    "skeleton_version": skel_version,
                    "marketplace_version": None,
                    "status": status,
                    "advisory_content": {"differing": 0, "missing": 0, "clone_only": 0},
                }
            )
            continue

        if clone_version is None:
            status = "MISSING"
        elif clone_version == skel_version:
            status = "MATCH"
        else:
            status = "MISMATCH"

        rows.append(
            {
                "plugin": name,
                "skeleton_version": skel_version,
                "marketplace_version": clone_version,
                "status": status,
                "advisory_content": content_drift(skel_dir, clone_dir),
            }
        )
    return rows


def render(rows, skeleton_root, marketplace_root):
    lines = []
    lines.append(f"skeleton    : {skeleton_root}")
    lines.append(f"marketplace : {marketplace_root}")
    lines.append("")
    lines.append(f"{'PLUGIN':<18} {'SKELETON':<12} {'RUNTIME':<12} STATUS")
    for row in rows:
        runtime = row["marketplace_version"] or "-"
        lines.append(
            f"{row['plugin']:<18} {row['skeleton_version']:<12} "
            f"{runtime:<12} {row['status']}"
        )
    bad = [r for r in rows if r["status"] != "MATCH"]
    lines.append("")
    for row in bad:
        drift = row["advisory_content"]
        lines.append(
            f"OUT OF PARITY: {row['plugin']} "
            f"skeleton={row['skeleton_version']} "
            f"runtime={row['marketplace_version'] or 'absent'} "
            f"(advisory: {drift['differing']} files differ, "
            f"{drift['missing']} absent from runtime, "
            f"{drift['clone_only']} runtime-only)"
        )
    if bad:
        lines.append("")
        lines.append(
            f"FAIL: {len(bad)} of {len(rows)} plugins out of parity. "
            "Slash commands run the runtime column."
        )
    elif not rows:
        lines.append(
            "FAIL: no plugins were checked. The skeleton exposed no readable "
            "plugin manifest, so this run proves nothing about parity."
        )
    else:
        lines.append(f"PASS: all {len(rows)} plugins in version parity.")
        advisory = [r for r in rows if any(r["advisory_content"].values())]
        for row in advisory:
            drift = row["advisory_content"]
            lines.append(
                f"  advisory {row['plugin']}: {drift['differing']} differ, "
                f"{drift['missing']} absent, {drift['clone_only']} runtime-only"
            )
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    here = os.path.dirname(os.path.abspath(__file__))
    repo_default = os.path.abspath(os.path.join(here, "..", "..", ".."))
    parser.add_argument("--skeleton", default=repo_default)
    parser.add_argument("--marketplace", default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    marketplace = args.marketplace or default_marketplace()

    try:
        rows = compare(args.skeleton, marketplace)
    # ManifestUnreadable joins FileNotFoundError here because they are the same
    # answer to the operator: the check could not establish a baseline, so it is
    # reporting nothing rather than parity. Letting it escape as a traceback
    # still exits non-zero (the verdict was right), but a stack trace reads as
    # "the tool is broken" instead of "your skeleton manifest will not parse",
    # and the second one is the sentence that gets it fixed.
    except (FileNotFoundError, ManifestUnreadable) as exc:
        print(f"CHECK FAILED TO RUN: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(
            json.dumps(
                {
                    "skeleton": args.skeleton,
                    "marketplace": marketplace,
                    "plugins": rows,
                },
                indent=2,
            )
        )
    else:
        print(render(rows, args.skeleton, marketplace))

    # ZERO ROWS IS NOT PARITY (Codex review of #142, minor). `any([])` is False,
    # so an empty result set used to exit 0 -- the check reported success in the
    # one case where it had inspected nothing at all. Absence of a finding is
    # only good news when something was actually examined.
    if not rows:
        return 1
    return 1 if any(r["status"] != "MATCH" for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
