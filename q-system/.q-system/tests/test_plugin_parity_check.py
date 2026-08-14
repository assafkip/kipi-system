"""Tests for plugin-parity-check.py (ASK-721, ASK-728).

The check's whole job is to go RED when the RUNNING plugin lags the skeleton.
A check that cannot go GREEN is useless, and a check that cannot go RED is a lie,
so both directions are pinned here against built fixtures -- never against the
live tree, which changes under the suite.

WHAT "RUNNING" MEANS, AND WHY THE FIXTURES LOOK LIKE THIS (Codex review of #152,
major). The first cut compared the marketplace CLONE. The clone is a git worktree
of the skeleton; the runtime executes a version-pinned directory under
plugins/cache/<marketplace>/<plugin>/<version> and picks it from
installed_plugins.json. Measured 2026-08-14: the clone read prd-os 0.27.2 while
the record pinned 0.16.5 and `claude plugin list` agreed with the record. Aimed at
the clone the checker compared 0.27.2 to 0.27.2 and printed MATCH while the plugin
actually loading was eleven minor versions behind.

So every fixture here builds a real installed_plugins.json plus the cache
directories it points at. A fixture that skipped the record would test the bug.

The mutation cases at the bottom are the point: each one makes ONE change to an
otherwise-green fixture and asserts the verdict flips.
"""
import json
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
CHECK = os.path.join(REPO, "q-system", ".q-system", "scripts", "plugin-parity-check.py")


def write_plugin(root, name, version, files=None):
    """Build a minimal plugin tree: a manifest plus optional content files."""
    plugin_dir = os.path.join(root, "plugins", name)
    os.makedirs(os.path.join(plugin_dir, ".claude-plugin"), exist_ok=True)
    manifest = os.path.join(plugin_dir, ".claude-plugin", "plugin.json")
    with open(manifest, "w", encoding="utf-8") as handle:
        json.dump({"name": name, "version": version}, handle)
    for rel, body in (files or {}).items():
        target = os.path.join(plugin_dir, rel)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as handle:
            handle.write(body)
    return plugin_dir


def write_raw_manifest(root, name, body):
    """A manifest written as literal bytes, so it can be malformed on purpose."""
    plugin_dir = os.path.join(root, "plugins", name, ".claude-plugin")
    os.makedirs(plugin_dir, exist_ok=True)
    with open(os.path.join(plugin_dir, "plugin.json"), "w", encoding="utf-8") as handle:
        handle.write(body)


def make_cache_dir(cache_root, marketplace, name, version, files=None):
    """The version-pinned directory the loader actually executes."""
    target = os.path.join(cache_root, marketplace, name, version)
    os.makedirs(os.path.join(target, ".claude-plugin"), exist_ok=True)
    with open(
        os.path.join(target, ".claude-plugin", "plugin.json"), "w", encoding="utf-8"
    ) as handle:
        json.dump({"name": name, "version": version}, handle)
    for rel, body in (files or {}).items():
        full = os.path.join(target, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as handle:
            handle.write(body)
    return target


def write_record(path, plugins):
    """installed_plugins.json in the real shape: a LIST of scoped entries."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"version": 2, "plugins": plugins}, handle, indent=2)
    return path


def entry(install_path, version, scope="user", project_path=None):
    row = {"scope": scope, "installPath": install_path, "version": version}
    if project_path is not None:
        row["projectPath"] = project_path
    return row


def run_check(skeleton, record, project=None, extra=None):
    argv = [sys.executable, CHECK, "--skeleton", skeleton, "--installed", record, "--json"]
    if project is not None:
        argv += ["--project", project]
    argv += extra or []
    proc = subprocess.run(argv, capture_output=True, text=True)
    payload = json.loads(proc.stdout) if proc.stdout.strip() else {}
    return proc.returncode, payload, proc.stderr


@pytest.fixture
def in_parity(tmp_path):
    """Skeleton and the RUNNING install agree on every version."""
    skeleton = tmp_path / "skeleton"
    cache = tmp_path / "cache"
    write_plugin(str(skeleton), "prd-os", "0.27.0", {"scripts/runner.py": "ok\n"})
    write_plugin(str(skeleton), "kipi-core", "1.6.0", {"skills/a/SKILL.md": "a\n"})
    a = make_cache_dir(str(cache), "kipi", "prd-os", "0.27.0", {"scripts/runner.py": "ok\n"})
    b = make_cache_dir(str(cache), "kipi", "kipi-core", "1.6.0", {"skills/a/SKILL.md": "a\n"})
    record = write_record(
        str(tmp_path / "installed_plugins.json"),
        {"prd-os@kipi": [entry(a, "0.27.0")], "kipi-core@kipi": [entry(b, "1.6.0")]},
    )
    return str(skeleton), record


def test_green_when_versions_agree(in_parity):
    """The control. Without this passing, every RED below proves nothing."""
    skeleton, record = in_parity
    code, payload, _ = run_check(skeleton, record)
    assert code == 0
    assert [r["status"] for r in payload["plugins"]] == ["MATCH", "MATCH"]


def test_red_when_running_version_lags(tmp_path):
    """The whole point: the skeleton moved and the installed copy did not."""
    skeleton = tmp_path / "skeleton"
    cache = tmp_path / "cache"
    write_plugin(str(skeleton), "prd-os", "0.27.2")
    old = make_cache_dir(str(cache), "kipi", "prd-os", "0.16.5")
    record = write_record(
        str(tmp_path / "rec.json"), {"prd-os@kipi": [entry(old, "0.16.5")]}
    )
    code, payload, _ = run_check(str(skeleton), record)
    assert code == 1
    assert payload["plugins"][0]["status"] == "MISMATCH"
    assert payload["plugins"][0]["installed_version"] == "0.16.5"


def test_every_verdict_names_the_path_it_read(tmp_path):
    """The fix for the pattern that produced this bug three times in one day: a
    parity claim that does not say which artifact it read looks identical whether
    it is right or wrong."""
    skeleton = tmp_path / "skeleton"
    cache = tmp_path / "cache"
    write_plugin(str(skeleton), "prd-os", "0.27.2")
    old = make_cache_dir(str(cache), "kipi", "prd-os", "0.16.5")
    record = write_record(
        str(tmp_path / "rec.json"), {"prd-os@kipi": [entry(old, "0.16.5")]}
    )
    _, payload, _ = run_check(str(skeleton), record)
    assert payload["plugins"][0]["install_path"] == old
    proc = subprocess.run(
        [sys.executable, CHECK, "--skeleton", str(skeleton), "--installed", record],
        capture_output=True,
        text=True,
    )
    assert old in proc.stdout


def test_project_scoped_entry_wins_for_its_own_project(tmp_path):
    """Option 3, the property that made it worth the extra argument.

    A project pinning an older build must be reported against THAT build. The
    rejected alternative -- always read the user entry -- would print MATCH here
    and rebuild, one level down, the exact wrong-artifact bug this check exists
    to catch.
    """
    skeleton = tmp_path / "skeleton"
    cache = tmp_path / "cache"
    proj = str(tmp_path / "someproject")
    write_plugin(str(skeleton), "prd-os", "0.27.2")
    user_dir = make_cache_dir(str(cache), "kipi", "prd-os", "0.27.2")
    proj_dir = make_cache_dir(str(cache), "kipi", "prd-os", "0.16.5")
    record = write_record(
        str(tmp_path / "rec.json"),
        {
            "prd-os@kipi": [
                entry(user_dir, "0.27.2"),
                entry(proj_dir, "0.16.5", scope="project", project_path=proj),
            ]
        },
    )
    code, payload, _ = run_check(str(skeleton), record, project=proj)
    assert code == 1
    assert payload["plugins"][0]["installed_version"] == "0.16.5"
    assert payload["plugins"][0]["scope"] == "project"

    # Same record, a DIFFERENT project: the user entry is what loads.
    code2, payload2, _ = run_check(str(skeleton), record, project=str(tmp_path / "other"))
    assert code2 == 0
    assert payload2["plugins"][0]["scope"] == "user"


def test_not_installed_is_not_parity(tmp_path):
    """A skeleton plugin with no install record is not MATCH by default."""
    skeleton = tmp_path / "skeleton"
    write_plugin(str(skeleton), "prd-os", "0.27.2")
    record = write_record(str(tmp_path / "rec.json"), {})
    code, payload, _ = run_check(str(skeleton), record)
    assert code == 1
    assert payload["plugins"][0]["status"] == "NOT_INSTALLED"


def test_recorded_path_that_does_not_exist_is_not_parity(tmp_path):
    """Matching version strings are not enough when the directory is gone: the
    loader would have nothing to load. Seen live -- kipi-ops pinned a projectPath
    under a home directory that no longer exists."""
    skeleton = tmp_path / "skeleton"
    write_plugin(str(skeleton), "prd-os", "0.27.2")
    record = write_record(
        str(tmp_path / "rec.json"),
        {"prd-os@kipi": [entry(str(tmp_path / "gone" / "0.27.2"), "0.27.2")]},
    )
    code, payload, _ = run_check(str(skeleton), record)
    assert code == 1
    assert payload["plugins"][0]["status"] == "PATH_MISSING"


def test_content_drift_is_advisory_and_does_not_fail(tmp_path):
    """Versions agree, bytes differ. Reported, never fatal: the cache legitimately
    carries build artifacts the skeleton does not."""
    skeleton = tmp_path / "skeleton"
    cache = tmp_path / "cache"
    write_plugin(str(skeleton), "prd-os", "0.27.0", {"scripts/r.py": "one\n"})
    live = make_cache_dir(str(cache), "kipi", "prd-os", "0.27.0", {"scripts/r.py": "two\n"})
    record = write_record(
        str(tmp_path / "rec.json"), {"prd-os@kipi": [entry(live, "0.27.0")]}
    )
    code, payload, _ = run_check(str(skeleton), record)
    assert code == 0
    assert payload["plugins"][0]["advisory_content"]["differing"] == 1


def test_in_use_bookkeeping_is_not_counted_as_drift(tmp_path):
    """Codex review of #152 round 2, major.

    `.in_use` is the loader's own lock directory, living INSIDE the installed
    cache dir with one PID-named file per live session. It is absent from the
    skeleton by construction and present at runtime by construction, so counting
    it made a perfectly synchronized plugin print advisory drift -- and the count
    moved between two runs of an unchanged tree. Noise by construction teaches
    the reader to stop reading, which is how the one real finding gets missed.
    """
    skeleton = tmp_path / "skeleton"
    cache = tmp_path / "cache"
    write_plugin(str(skeleton), "prd-os", "0.27.0", {"scripts/r.py": "same\n"})
    live = make_cache_dir(
        str(cache), "kipi", "prd-os", "0.27.0",
        {
            "scripts/r.py": "same\n",
            ".in_use/25941": "pid lock\n",
            ".in_use/2414.tmp.6cad4abf": "stale lock\n",
        },
    )
    record = write_record(
        str(tmp_path / "rec.json"), {"prd-os@kipi": [entry(live, "0.27.0")]}
    )
    code, payload, _ = run_check(str(skeleton), record)
    assert code == 0
    assert payload["plugins"][0]["advisory_content"] == {
        "differing": 0,
        "missing": 0,
        "clone_only": 0,
    }


def test_record_version_is_not_trusted_over_the_directory(tmp_path):
    """Codex review of #152 round 3, minor.

    The record is a CLAIM about the directory; the directory is what loads. This
    trusted entry["version"] and never opened the manifest it pointed at, so a
    record saying 0.27.2 over a tree whose manifest says 0.16.5 reported MATCH --
    repeating one level in the exact mistake that produced this branch: believing
    a claim instead of reading the artifact.
    """
    skeleton = tmp_path / "skeleton"
    cache = tmp_path / "cache"
    write_plugin(str(skeleton), "prd-os", "0.27.2")
    stale = make_cache_dir(str(cache), "kipi", "prd-os", "0.16.5")
    record = write_record(
        str(tmp_path / "rec.json"),
        {"prd-os@kipi": [entry(stale, "0.27.2")]},  # record LIES about the tree
    )
    code, payload, _ = run_check(str(skeleton), record)
    assert code == 1
    row = payload["plugins"][0]
    assert row["status"] == "RECORD_DRIFT"
    assert row["installed_version"] == "0.27.2"
    assert row["runtime_manifest_version"] == "0.16.5"


def test_removed_marketplace_flag_is_an_error_not_a_prefix_match(tmp_path):
    """Codex review of #152 round 3, major.

    argparse accepts any unambiguous PREFIX, so the removed `--marketplace DIR`
    was silently folded into `--marketplace-name=DIR`. Every lookup key became
    `<plugin>@DIR`, so the run reported EVERY plugin NOT_INSTALLED and exited 1 --
    a confident false alarm from a spelling the docs still carried. An unknown
    flag must fail loudly rather than be guessed into a neighbour.
    """
    skeleton = tmp_path / "skeleton"
    cache = tmp_path / "cache"
    write_plugin(str(skeleton), "prd-os", "0.27.0")
    live = make_cache_dir(str(cache), "kipi", "prd-os", "0.27.0")
    record = write_record(
        str(tmp_path / "rec.json"), {"prd-os@kipi": [entry(live, "0.27.0")]}
    )
    proc = subprocess.run(
        [
            sys.executable, CHECK, "--skeleton", str(skeleton),
            "--installed", record, "--marketplace", "/some/clone",
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    assert "NOT_INSTALLED" not in proc.stdout
    assert "unrecognized arguments" in proc.stderr


def test_non_plugin_directory_is_skipped(tmp_path):
    """A directory under plugins/ with no manifest is not a plugin."""
    skeleton = tmp_path / "skeleton"
    cache = tmp_path / "cache"
    write_plugin(str(skeleton), "prd-os", "0.27.0")
    live = make_cache_dir(str(cache), "kipi", "prd-os", "0.27.0")
    os.makedirs(os.path.join(str(skeleton), "plugins", "scratch"), exist_ok=True)
    record = write_record(
        str(tmp_path / "rec.json"), {"prd-os@kipi": [entry(live, "0.27.0")]}
    )
    code, payload, _ = run_check(str(skeleton), record)
    assert code == 0
    assert [r["plugin"] for r in payload["plugins"]] == ["prd-os"]


def test_missing_plugins_dir_exits_2_not_0(tmp_path):
    """"Nothing to compare" must never read as "everything is in parity"."""
    skeleton = tmp_path / "empty"
    skeleton.mkdir()
    record = write_record(str(tmp_path / "rec.json"), {})
    proc = subprocess.run(
        [sys.executable, CHECK, "--skeleton", str(skeleton), "--installed", record],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    assert "CHECK FAILED TO RUN" in proc.stderr


def test_absent_installed_record_exits_2(tmp_path):
    """No record means the check cannot know what runs. That is a failed run, not
    a pass."""
    skeleton = tmp_path / "skeleton"
    write_plugin(str(skeleton), "prd-os", "0.27.0")
    proc = subprocess.run(
        [
            sys.executable, CHECK, "--skeleton", str(skeleton),
            "--installed", str(tmp_path / "nope.json"),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    assert "CHECK FAILED TO RUN" in proc.stderr


def test_malformed_installed_record_exits_2(tmp_path):
    """Same reasoning as a malformed manifest: unreadable is not parity."""
    skeleton = tmp_path / "skeleton"
    write_plugin(str(skeleton), "prd-os", "0.27.0")
    bad = tmp_path / "rec.json"
    bad.write_text("{ not json", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, CHECK, "--skeleton", str(skeleton), "--installed", str(bad)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    assert "CHECK FAILED TO RUN" in proc.stderr


def test_malformed_skeleton_manifest_never_reports_pass(tmp_path):
    """The round-5 minor on PR #142, pinned.

    `read_version` used to answer None for three unrelated situations: no
    manifest, JSON that will not parse, and a manifest with no version key. The
    caller reads None as "not a plugin, skip", so a broken manifest silently
    dropped a real plugin -- and with one plugin in the tree that emptied the
    result set, where the verdict `any(status != MATCH)` is False for an empty
    list. Measured against the pre-fix file: exit 0, "PASS: all 0 plugins".
    """
    skeleton = tmp_path / "skeleton"
    write_raw_manifest(str(skeleton), "prd-os", "{ this is not json")
    record = write_record(str(tmp_path / "rec.json"), {})
    proc = subprocess.run(
        [sys.executable, CHECK, "--skeleton", str(skeleton), "--installed", record],
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert "PASS" not in proc.stdout
    assert "CHECK FAILED TO RUN" in proc.stderr


def test_manifest_without_version_key_never_reports_pass(tmp_path):
    """Parses fine, carries no version. The likelier one in practice: a
    hand-edited manifest keeps valid JSON more often than it keeps every key."""
    skeleton = tmp_path / "skeleton"
    write_raw_manifest(str(skeleton), "prd-os", '{"name": "prd-os"}')
    record = write_record(str(tmp_path / "rec.json"), {})
    proc = subprocess.run(
        [sys.executable, CHECK, "--skeleton", str(skeleton), "--installed", record],
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert "PASS" not in proc.stdout


def test_zero_readable_plugins_is_not_pass(tmp_path):
    """`any([])` is False. An empty result set must not inherit that as success."""
    skeleton = tmp_path / "skeleton"
    os.makedirs(os.path.join(str(skeleton), "plugins", "scratch"), exist_ok=True)
    record = write_record(str(tmp_path / "rec.json"), {})
    proc = subprocess.run(
        [sys.executable, CHECK, "--skeleton", str(skeleton), "--installed", record],
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert "PASS" not in proc.stdout
