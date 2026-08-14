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
# `.in_use` is the loader's own bookkeeping, not plugin content (Codex review of
# #152 round 2, major). It lives INSIDE the installed cache directory and holds
# one PID-named lock file per live session, so it is guaranteed absent from the
# skeleton and guaranteed present at runtime. Measured 2026-08-14: 26 files,
# mtime moving while the check ran.
#
# Counting it meant a perfectly synchronized plugin still printed advisory drift,
# and the count changed between two runs of an unchanged tree. That is the same
# failure as the permanently-red test gate this branch also fixes: output that is
# noisy by construction teaches the reader to stop reading it, and then the one
# real finding goes past unnoticed.
NOISE_DIRS = {
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".in_use",
}
NOISE_SUFFIXES = (".pyc", ".pyo")


def default_marketplace():
    env = os.environ.get("KIPI_MARKETPLACE_ROOT")
    if env:
        return env
    return os.path.join(
        os.path.expanduser("~"), ".claude", "plugins", "marketplaces", "kipi"
    )


def default_installed_record():
    env = os.environ.get("KIPI_INSTALLED_PLUGINS")
    if env:
        return env
    return os.path.join(
        os.path.expanduser("~"), ".claude", "plugins", "installed_plugins.json"
    )


def read_installed(record_path):
    """Parse installed_plugins.json into {"<plugin>@<marketplace>": [entry, ...]}.

    THIS FILE, NOT THE MARKETPLACE CLONE, IS WHAT RUNS (Codex review of #152,
    major). The clone is a git worktree of the skeleton; the runtime executes a
    VERSION-PINNED directory under plugins/cache/<marketplace>/<plugin>/<version>
    and decides which one from this record. The two disagree freely: measured
    2026-08-14, the clone read prd-os 0.27.2 while this record pinned 0.16.5 and
    `claude plugin list` agreed with the record.

    That is why the first cut of this checker was worse than useless. Aimed at
    the clone it compared 0.27.2 against 0.27.2 and printed MATCH while the
    plugin actually loading was eleven minor versions behind. A parity checker
    that reports parity because it read the wrong artifact is the exact failure
    it exists to catch.
    """
    if not os.path.isfile(record_path):
        raise FileNotFoundError(f"no installed-plugins record at {record_path}")
    try:
        with open(record_path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (json.JSONDecodeError, OSError) as exc:
        raise ManifestUnreadable(f"{record_path}: {exc}") from exc
    plugins = data.get("plugins") if isinstance(data, dict) else None
    if not isinstance(plugins, dict):
        raise ManifestUnreadable(f"{record_path}: no 'plugins' object")
    return plugins


def resolve_live_entry(entries, project):
    """Pick the entry the LOADER would use, or None if the plugin is not installed.

    The value under "<plugin>@<marketplace>" is a LIST, and each entry carries a
    scope. A project-scoped install pins a version for one projectPath only; a
    user-scoped install is the fallback everywhere else. So "the version Claude
    executes" is a question that cannot be answered without naming a project,
    which is why --project exists rather than a default guess.

    Checking only the user entry (the simpler option considered and rejected)
    would rebuild the very hole this fix closes: it would report parity for a
    project that pins something older, one level further down.
    """
    project_entries = [e for e in entries if e.get("scope") == "project"]
    if project is not None:
        target = os.path.abspath(project)
        for entry in project_entries:
            recorded = entry.get("projectPath")
            if recorded and os.path.abspath(recorded) == target:
                return entry
    for entry in entries:
        if entry.get("scope") == "user":
            return entry
    return None


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


def compare(skeleton_root, installed, marketplace_name="kipi", project=None):
    """One row per plugin in the skeleton. Rows are the whole result.

    `installed` is the parsed plugins map from read_installed. Every row names
    the install_path it judged, because the defect this check exists to catch
    appeared three times in one day (2026-08-14) in three different places, and
    each time the tell was the same: a parity claim that did not say which
    artifact it read. Printing the path makes the next wrong answer obvious
    instead of ambient.
    """
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

        entries = installed.get(f"{name}@{marketplace_name}") or []
        entry = resolve_live_entry(entries, project) if entries else None

        if entry is None:
            rows.append(
                {
                    "plugin": name,
                    "skeleton_version": skel_version,
                    "installed_version": None,
                    "install_path": None,
                    "scope": None,
                    "status": "NOT_INSTALLED",
                    "advisory_content": {"differing": 0, "missing": 0, "clone_only": 0},
                }
            )
            continue

        live_version = entry.get("version")
        install_path = entry.get("installPath")

        # A record that names a directory which is not there is NOT parity, even
        # when the version string matches. The loader would have nothing to load.
        if not install_path or not os.path.isdir(install_path):
            status = "PATH_MISSING"
        elif live_version is None:
            status = "UNREADABLE"
        elif live_version == skel_version:
            status = "MATCH"
        else:
            status = "MISMATCH"

        drift = {"differing": 0, "missing": 0, "clone_only": 0}
        if install_path and os.path.isdir(install_path):
            drift = content_drift(skel_dir, install_path)

        rows.append(
            {
                "plugin": name,
                "skeleton_version": skel_version,
                "installed_version": live_version,
                "install_path": install_path,
                "scope": entry.get("scope"),
                "status": status,
                "advisory_content": drift,
            }
        )
    return rows


def render(rows, skeleton_root, record_path, project=None):
    lines = []
    lines.append(f"skeleton  : {skeleton_root}")
    lines.append(f"installed : {record_path}")
    lines.append(f"project   : {project or '(user scope)'}")
    lines.append("")
    lines.append(f"{'PLUGIN':<18} {'SKELETON':<12} {'RUNNING':<12} STATUS")
    for row in rows:
        runtime = row["installed_version"] or "-"
        lines.append(
            f"{row['plugin']:<18} {row['skeleton_version']:<12} "
            f"{runtime:<12} {row['status']}"
        )
    bad = [r for r in rows if r["status"] != "MATCH"]
    lines.append("")
    for row in bad:
        drift = row["advisory_content"]
        # THE PATH IS PART OF THE VERDICT, not decoration. Every wrong answer
        # this checker has given came from reading the wrong directory, and in
        # each case the output looked identical to a right answer.
        lines.append(
            f"OUT OF PARITY: {row['plugin']} "
            f"skeleton={row['skeleton_version']} "
            f"running={row['installed_version'] or 'absent'} "
            f"scope={row['scope'] or '-'} "
            f"read={row['install_path'] or 'no install path recorded'} "
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
    parser.add_argument(
        "--installed",
        default=None,
        help="path to installed_plugins.json (what the loader actually reads)",
    )
    parser.add_argument(
        "--project",
        default=None,
        help=(
            "resolve project-scoped installs for this project path. Omit to "
            "check the user-scoped install, which is what a session outside any "
            "project-pinned plugin loads."
        ),
    )
    parser.add_argument("--marketplace-name", default="kipi")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    record_path = args.installed or default_installed_record()

    try:
        installed = read_installed(record_path)
        rows = compare(
            args.skeleton, installed, args.marketplace_name, args.project
        )
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
                    "installed_record": record_path,
                    "project": args.project,
                    "plugins": rows,
                },
                indent=2,
            )
        )
    else:
        print(render(rows, args.skeleton, record_path, args.project))

    # ZERO ROWS IS NOT PARITY (Codex review of #142, minor). `any([])` is False,
    # so an empty result set used to exit 0 -- the check reported success in the
    # one case where it had inspected nothing at all. Absence of a finding is
    # only good news when something was actually examined.
    if not rows:
        return 1
    return 1 if any(r["status"] != "MATCH" for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
