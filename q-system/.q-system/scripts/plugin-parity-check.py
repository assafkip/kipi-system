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

    --skeleton DIR          repo holding plugins/ (default: this repo)
    --installed FILE        installed_plugins.json, the record the LOADER reads
                            (default: $KIPI_INSTALLED_PLUGINS, else
                             ~/.claude/plugins/installed_plugins.json)
    --marketplace-name NAME marketplace key in the record (default: kipi)

Every RECORDED INSTALL is checked, not just the one believed to be live. A plugin
installed under several scopes produces several rows and the run fails if any of
them lags. There is no --project or --user-scope: picking "the live one" needs the
loader's real resolution rule, which is not knowable from these files.
There is deliberately no --marketplace option. It was removed when this check
stopped reading the clone, and argparse's prefix matching then silently folded a
leftover `--marketplace DIR` into `--marketplace-name=DIR` -- which made every
lookup key `<plugin>@DIR`, so the run reported EVERY plugin NOT_INSTALLED and
exited 1. A confident false alarm from a documented flag (Codex review of #152
round 3, major). The parser now runs with allow_abbrev=False so that spelling is
a hard error instead of a wrong answer.

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


# THERE IS DELIBERATELY NO resolve_live_entry() HERE.
#
# It used to pick "the entry the loader would use" and it was removed after four
# consecutive review rounds found a new way that guess was wrong: exact-path
# matching only (round 3), a default that resolved user scope and undid its own
# argument (round 4), and descendant directories falling back to the user install
# while the session there loads the project one (round 5).
#
# The pattern is not a series of missed edge cases. It is that the VERSION half of
# this check is grounded and the RESOLUTION half never was. The cache key was
# verified against two independent sources -- installed_plugins.json and
# `claude plugin list` agreeing -- which is why it has been stable. How the loader
# chooses among several scoped entries was inferred from the shape of a JSON file.
# The loader is closed-source, so there is no oracle to converge on, and each
# round was one guess meeting a different guess.
#
# So this file no longer claims to know which install is live. It enumerates EVERY
# install and fails if ANY of them lags. "An install of prd-os at <path>
# (scope=project, projectPath=X) is stale" is true whatever the resolution rule
# turns out to be, and it still answers the question this check exists for: is the
# fleet silently split.
#
# What is lost is the sentence "the plugin YOU are running right now is stale."
# That sentence needs the loader's real behaviour, established by experiment
# (install two versions, launch from different directories, observe which loads),
# not by reading a manifest. That is a separate piece of work.


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


def row_for_entry(name, skel_dir, skel_version, entry, scopes=None, project_paths=None):
    """Judge ONE distinct install TARGET of one plugin.

    Every row names the install_path it judged. The defect this check exists to
    catch showed up repeatedly on 2026-08-14, and each time the tell was the
    same: a parity claim that did not say which artifact it read.
    """
    live_version = entry.get("version")
    install_path = entry.get("installPath")

    runtime_version = None
    if not install_path or not os.path.isdir(install_path):
        # A record naming a directory that is not there is NOT parity, even when
        # the version string matches. There would be nothing to load.
        status = "PATH_MISSING"
    else:
        # THE DIRECTORY IS THE TRUTH; THE RECORD IS A CLAIM ABOUT IT. Trusting
        # entry["version"] without opening the manifest it points at repeats, one
        # level in, the mistake that produced this branch: believing a claim
        # instead of reading the artifact.
        try:
            runtime_version = read_version(install_path)
        except ManifestUnreadable:
            runtime_version = None

        if runtime_version is None:
            status = "UNREADABLE"
        elif live_version is not None and runtime_version != live_version:
            # Its own state, not folded into MISMATCH: the two mean different
            # repairs. MISMATCH is "update the plugin", RECORD_DRIFT is "the
            # bookkeeping disagrees with the disk".
            status = "RECORD_DRIFT"
        elif runtime_version == skel_version:
            status = "MATCH"
        else:
            status = "MISMATCH"

    drift = {"differing": 0, "missing": 0, "clone_only": 0}
    if install_path and os.path.isdir(install_path):
        drift = content_drift(skel_dir, install_path)

    return {
        "plugin": name,
        "skeleton_version": skel_version,
        "installed_version": live_version,
        "runtime_manifest_version": runtime_version,
        "install_path": install_path,
        "scopes": sorted(scopes) if scopes else [entry.get("scope")],
        "project_paths": sorted(pp for pp in (project_paths or []) if pp),
        "status": status,
        "advisory_content": drift,
    }


def compare(skeleton_root, installed, marketplace_name="kipi"):
    """One row per RECORDED INSTALL -- not one per plugin.

    A plugin can be installed several times under different scopes. This used to
    pick the one it believed the loader would run, which is a question it could
    not answer (see the note where resolve_live_entry used to be). So it no
    longer picks: every recorded install is judged, and the run fails if ANY of
    them lags the skeleton.

    That claim survives whatever the loader's resolution rule turns out to be,
    and it is strictly more sensitive for the thing this check exists for -- it
    catches a stale project-scoped install even from outside that project, which
    the resolving version could not.
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
            # Not a plugin (no manifest). Not this check's business. A manifest
            # that EXISTS and will not parse raises instead -- see read_version.
            continue

        entries = installed.get(f"{name}@{marketplace_name}") or []
        if not entries:
            rows.append(
                {
                    "plugin": name,
                    "skeleton_version": skel_version,
                    "installed_version": None,
                    "runtime_manifest_version": None,
                    "install_path": None,
                    "scope": None,
                    "project_path": None,
                    "status": "NOT_INSTALLED",
                    "advisory_content": {"differing": 0, "missing": 0, "clone_only": 0},
                }
            )
            continue

        # COLLAPSE ENTRIES THAT NAME THE SAME TARGET. kipi-core is recorded once
        # per project it was installed into -- 9 identical rows on this box, same
        # installPath, same version, same verdict. Printing all of them is noise
        # by construction, which is the failure this branch has fixed twice
        # already (.in_use drift, permanently-red tests): a reader who learns to
        # skim the output stops seeing the one row that matters.
        #
        # Collapsing is safe precisely BECAUSE resolution was dropped: identical
        # target plus identical version is one fact however many scopes point at
        # it. The scopes and project paths are kept on the row so nothing about
        # WHO references it is lost.
        groups = {}
        for entry in entries:
            key = (entry.get("installPath"), entry.get("version"))
            groups.setdefault(key, []).append(entry)
        for group in groups.values():
            rows.append(
                row_for_entry(
                    name, skel_dir, skel_version, group[0],
                    scopes={e.get("scope") for e in group},
                    project_paths=[e.get("projectPath") for e in group],
                )
            )
    return rows


def render(rows, skeleton_root, record_path):
    lines = []
    lines.append(f"skeleton  : {skeleton_root}")
    lines.append(f"installed : {record_path}")
    lines.append(f"installs  : {len(rows)} recorded")
    lines.append("")
    lines.append(f"{'PLUGIN':<18} {'SKELETON':<12} {'RUNNING':<12} STATUS")
    for row in rows:
        # THE ON-DISK MANIFEST IS THE RUNNING VERSION (Codex review of #152
        # round 4, minor). This printed the RECORD's version under a column
        # headed RUNNING, so in the one case where the two provably disagree --
        # RECORD_DRIFT, which the previous round added detection for -- the
        # human-readable output named the wrong number. Detecting the drift and
        # then displaying the value it disproved is worse than not detecting it.
        runtime = row.get("runtime_manifest_version") or row["installed_version"] or "-"
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
            f"running={row.get('runtime_manifest_version') or 'absent'} "
            f"record={row['installed_version'] or 'absent'} "
            f"scopes={','.join(row['scopes']) or '-'} "
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
    # allow_abbrev=False: argparse otherwise accepts any unambiguous PREFIX, so
    # the removed `--marketplace DIR` was silently absorbed by
    # `--marketplace-name` and produced a confident all-NOT_INSTALLED run. An
    # unknown flag must fail loudly, never be guessed into a neighbour.
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n")[0], allow_abbrev=False
    )
    here = os.path.dirname(os.path.abspath(__file__))
    repo_default = os.path.abspath(os.path.join(here, "..", "..", ".."))
    parser.add_argument("--skeleton", default=repo_default)
    parser.add_argument(
        "--installed",
        default=None,
        help="path to installed_plugins.json (what the loader actually reads)",
    )
    parser.add_argument("--marketplace-name", default="kipi")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    record_path = args.installed or default_installed_record()

    try:
        installed = read_installed(record_path)
        rows = compare(
            args.skeleton, installed, args.marketplace_name
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
                    "plugins": rows,
                },
                indent=2,
            )
        )
    else:
        print(render(rows, args.skeleton, record_path))

    # ZERO ROWS IS NOT PARITY (Codex review of #142, minor). `any([])` is False,
    # so an empty result set used to exit 0 -- the check reported success in the
    # one case where it had inspected nothing at all. Absence of a finding is
    # only good news when something was actually examined.
    if not rows:
        return 1
    return 1 if any(r["status"] != "MATCH" for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
