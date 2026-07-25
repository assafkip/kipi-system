"""What the gate must scan is what propagation actually copies.

`containment-targets.py` enumerates the Git index and drops every tracked
symlink with reason "symlink". That is correct for a containment check over
repository-owned content, and wrong for a propagation gate: `kipi-update.sh`
rsyncs `plugins/<name>/` with a TRAILING SLASH, which dereferences the link and
copies the external repo's contents into all 23 instances. The one source that
reaches every instance without ever entering the target manifest is the one the
gate would never look at.

So these tests pin two properties:

- a fact behind a dereferenced symlink is FOUND, keyed on the repo-relative
  propagation path so the baseline is not machine-specific;
- a source that is copied but cannot be read REFUSES the propagation, rather
  than passing as clean by silence.

The inverse matters just as much: content that propagation does NOT copy (a
dangling link, a nested symlink rsync preserves as a link, an rsync-filtered
path) is EXCLUDED with a reason, never refused. A gate that refuses on things
that cannot leak is a gate someone switches off.
"""

import importlib.util
import os
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[4]
GATE = REPO_ROOT / "q-system" / ".q-system" / "scripts" / "propagation-leak-gate.py"

LEAKED_RECORD = "- Client: Northwind Trading\n"


def load_gate():
    spec = importlib.util.spec_from_file_location("propagation_leak_gate", GATE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(repo, *args):
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def make_repo(tmp_path):
    """A skeleton-shaped repo with an index, which is all the gate reads."""
    repo = tmp_path / "skeleton"
    (repo / "plugins").mkdir(parents=True)
    (repo / "q-system" / "marketing").mkdir(parents=True)
    git(repo, "init", "-q")
    return repo


def track_everything(repo):
    git(repo, "add", "-A", "-f", ".")


def link_plugin(repo, external, name="memory-lifecycle"):
    """The shape kipi-update.sh dereferences: plugins/<name> -> elsewhere."""
    (repo / "plugins" / name).symlink_to(external)
    track_everything(repo)


def recording_classifier(seen):
    """Records every source it is handed, flags any line containing LEAK."""

    def classify(text, source_path=None):
        seen.append(source_path)
        return [
            {"fact_class": "client_identity", "line": number}
            for number, line in enumerate(text.splitlines(), start=1)
            if "LEAK" in line
        ]

    return classify


def scanned_paths(findings):
    return {finding["path"] for finding in findings}


def excluded_reason(sources, path):
    for entry in sources["excluded"]:
        if entry["path"] == path:
            return entry["reason"]
    return None


def test_fact_behind_a_dereferenced_symlink_is_found(tmp_path):
    """The leak the target manifest cannot see, found through the real path."""
    gate = load_gate()
    external = tmp_path / "external-repo"
    external.mkdir()
    (external / "notes.md").write_text(LEAKED_RECORD, encoding="utf-8")
    repo = make_repo(tmp_path)
    link_plugin(repo, external)

    findings = gate.scan_propagation_sources(repo)

    leaks = [
        finding
        for finding in findings
        if finding["path"] == "plugins/memory-lifecycle/notes.md"
    ]
    assert leaks, "a fact rsync copies into every instance was not scanned"
    assert leaks[0]["fact_class"] == "client_identity"
    assert leaks[0]["text"].strip() == LEAKED_RECORD.strip()


def test_symlinked_source_fingerprint_is_repo_relative(tmp_path):
    """Two machines with the external repo checked out elsewhere agree.

    Keying on the resolved real path would make every developer's baseline a
    different file, and a baseline nobody can share is a baseline nobody reads.
    """
    gate = load_gate()
    fingerprints = []
    for index, place in enumerate(("one", "two")):
        external = tmp_path / place / "external-repo"
        external.mkdir(parents=True)
        (external / "notes.md").write_text(LEAKED_RECORD, encoding="utf-8")
        repo = make_repo(tmp_path / f"host-{index}")
        link_plugin(repo, external)
        fingerprints.append(
            gate.fingerprint_findings(gate.scan_propagation_sources(repo))
        )

    assert fingerprints[0] == fingerprints[1]


def test_special_file_behind_a_symlink_is_refused(tmp_path):
    """A FIFO is copied by `rsync -a` (-D) and can never be read.

    Opening it would block the updater forever, so the gate cannot clear it.
    Unscannable and copied is exactly the case that must stop the run.
    """
    gate = load_gate()
    external = tmp_path / "external-repo"
    external.mkdir()
    os.mkfifo(external / "channel")
    repo = make_repo(tmp_path)
    link_plugin(repo, external)

    with pytest.raises(gate.PropagationSourceRefused) as refusal:
        gate.scan_propagation_sources(repo)
    assert "plugins/memory-lifecycle/channel" in str(refusal.value)


@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root can read a mode-000 file, so the refusal cannot be provoked",
)
def test_unreadable_symlinked_source_is_refused(tmp_path):
    """Cannot read it, cannot clear it. Silence is not evidence."""
    gate = load_gate()
    external = tmp_path / "external-repo"
    external.mkdir()
    secret = external / "notes.md"
    secret.write_text(LEAKED_RECORD, encoding="utf-8")
    secret.chmod(0o000)
    repo = make_repo(tmp_path)
    link_plugin(repo, external)

    try:
        with pytest.raises(gate.PropagationSourceRefused):
            gate.scan_propagation_sources(repo)
    finally:
        secret.chmod(0o600)


def test_dangling_plugin_symlink_is_excluded_not_refused(tmp_path):
    """`for d in plugins/*/` never matches a dangling link, so nothing copies.

    Refusing here would block every update over content that cannot leak.
    """
    gate = load_gate()
    repo = make_repo(tmp_path)
    link_plugin(repo, tmp_path / "was-deleted")

    sources = gate.enumerate_propagation_sources(repo)

    assert excluded_reason(sources, "plugins/memory-lifecycle") is not None
    assert gate.scan_propagation_sources(repo) == []


def test_nested_symlink_is_preserved_as_a_link_not_scanned(tmp_path):
    """`rsync -a` implies -l: only the transfer ROOT is dereferenced.

    A link inside the tree is copied as a link, so its target's content never
    reaches an instance and is out of the gate's scope.
    """
    gate = load_gate()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "private.md").write_text("- Client: LEAK Corp\n", encoding="utf-8")
    external = tmp_path / "external-repo"
    external.mkdir()
    (external / "private.md").symlink_to(outside / "private.md")
    repo = make_repo(tmp_path)
    link_plugin(repo, external)

    seen = []
    findings = gate.scan_propagation_sources(repo, classify=recording_classifier(seen))

    assert findings == []
    assert "plugins/memory-lifecycle/private.md" not in seen


def test_rsync_filtered_paths_are_not_scanned(tmp_path):
    """The updater excludes /.git/, __pycache__/ and *.pyc from the copy."""
    gate = load_gate()
    external = tmp_path / "external-repo"
    (external / ".git").mkdir(parents=True)
    (external / "__pycache__").mkdir(parents=True)
    (external / ".git" / "config").write_text("LEAK\n", encoding="utf-8")
    (external / "__pycache__" / "cached.md").write_text("LEAK\n", encoding="utf-8")
    (external / "module.pyc").write_text("LEAK\n", encoding="utf-8")
    (external / "kept.md").write_text("kept\n", encoding="utf-8")
    repo = make_repo(tmp_path)
    link_plugin(repo, external)

    seen = []
    findings = gate.scan_propagation_sources(repo, classify=recording_classifier(seen))

    assert findings == []
    assert seen == ["plugins/memory-lifecycle/kept.md"]


def test_regular_files_named_like_excluded_dirs_are_scanned(tmp_path):
    """A trailing slash in an rsync exclude means DIRECTORY ONLY.

    `--exclude="/.git/"` does not exclude a regular FILE named .git, which is
    exactly the shape a submodule or a linked worktree uses, and rsync copies
    it. Excluding by name alone hands that file a free pass.
    """
    gate = load_gate()
    repo = make_repo(tmp_path)
    plugin = repo / "plugins" / "kipi-core"
    plugin.mkdir(parents=True)
    (plugin / ".git").write_text(LEAKED_RECORD, encoding="utf-8")
    (plugin / "__pycache__").write_text(LEAKED_RECORD, encoding="utf-8")

    scanned = scanned_paths(gate.scan_propagation_sources(repo))

    assert "plugins/kipi-core/.git" in scanned
    assert "plugins/kipi-core/__pycache__" in scanned


def test_dot_directory_the_updater_cannot_reach_is_not_refused(tmp_path):
    """`for d in plugins/*/` never matches a dotdir, so nothing there travels.

    Refusing on content the updater cannot copy is how a gate gets switched
    off, which protects nothing.
    """
    gate = load_gate()
    repo = make_repo(tmp_path)
    hidden = repo / "plugins" / ".hidden"
    hidden.mkdir(parents=True)
    os.mkfifo(hidden / "channel")

    sources = gate.enumerate_propagation_sources(repo)

    assert excluded_reason(sources, "plugins/.hidden") == "not-matched-by-shell-glob"
    assert gate.scan_propagation_sources(repo) == []


def test_undecodable_unlisted_extension_is_refused(tmp_path):
    """Binary detection is a deny list; an allowlist of text types fails open.

    A UTF-16 .rst carries a client record and rsync copies it. Filing every
    unlisted extension under "binary" lets a whole file type walk past.
    """
    gate = load_gate()
    repo = make_repo(tmp_path)
    plugin = repo / "plugins" / "kipi-core"
    plugin.mkdir(parents=True)
    (plugin / "facts.rst").write_bytes(LEAKED_RECORD.encode("utf-16"))

    with pytest.raises(gate.PropagationSourceRefused) as refusal:
        gate.scan_propagation_sources(repo)
    assert "plugins/kipi-core/facts.rst" in str(refusal.value)


def test_source_added_during_the_scan_is_refused(tmp_path):
    """Per-entry digests cannot see a file that was not there to digest.

    The updater copies whatever is on disk when it runs, so a source appearing
    after enumeration is a source the verdict never covered.
    """
    gate = load_gate()
    repo = make_repo(tmp_path)
    plugin = repo / "plugins" / "kipi-core"
    plugin.mkdir(parents=True)
    (plugin / "first.md").write_text("clean\n", encoding="utf-8")

    def add_then_classify(text, source_path=None):
        (plugin / "arrived-late.md").write_text(LEAKED_RECORD, encoding="utf-8")
        return []

    with pytest.raises(gate.PropagationSourceRefused) as refusal:
        gate.scan_propagation_sources(repo, classify=add_then_classify)
    assert "set of sources" in str(refusal.value)


def test_tracked_generic_sources_are_still_scanned(tmp_path):
    """The dereferenced half is an addition, not a replacement."""
    gate = load_gate()
    repo = make_repo(tmp_path)
    (repo / "q-system" / "marketing" / "outreach.md").write_text(
        LEAKED_RECORD, encoding="utf-8"
    )
    track_everything(repo)

    findings = gate.scan_propagation_sources(repo)

    assert "q-system/marketing/outreach.md" in scanned_paths(findings)


def test_untracked_plugin_file_is_scanned(tmp_path):
    """The updater rsyncs plugins/ off DISK, so tracking is not the surface.

    An index-derived manifest cannot see a file that was never added, yet
    `rsync -a plugins/<name>/` copies it into all 23 instances.
    """
    gate = load_gate()
    repo = make_repo(tmp_path)
    (repo / "plugins" / "kipi-core").mkdir(parents=True)
    (repo / "plugins" / "kipi-core" / "notes.md").write_text(
        LEAKED_RECORD, encoding="utf-8"
    )

    findings = gate.scan_propagation_sources(repo)

    assert "plugins/kipi-core/notes.md" in scanned_paths(findings)


def test_symlinked_config_directory_is_dereferenced(tmp_path):
    """`cp .claude/rules/*.md` globs THROUGH a symlinked rules/ directory."""
    gate = load_gate()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "house-rule.md").write_text(LEAKED_RECORD, encoding="utf-8")
    repo = make_repo(tmp_path)
    (repo / ".claude").mkdir()
    (repo / ".claude" / "rules").symlink_to(outside)
    track_everything(repo)

    findings = gate.scan_propagation_sources(repo)

    assert ".claude/rules/house-rule.md" in scanned_paths(findings)


def test_undecodable_markdown_source_is_refused(tmp_path):
    """A .md the gate cannot decode is unscannable, not a binary asset.

    UTF-16 Markdown still carries `label: value` records. Filing it under
    "binary" would let a whole encoding walk past the gate.
    """
    gate = load_gate()
    repo = make_repo(tmp_path)
    (repo / "plugins" / "kipi-core").mkdir(parents=True)
    (repo / "plugins" / "kipi-core" / "notes.md").write_bytes(
        LEAKED_RECORD.encode("utf-16")
    )

    with pytest.raises(gate.PropagationSourceRefused) as refusal:
        gate.scan_propagation_sources(repo)
    assert "plugins/kipi-core/notes.md" in str(refusal.value)


def test_source_changed_during_the_scan_is_refused(tmp_path):
    """A verdict is only about the bytes that were read.

    The indexed half has assert_index_unchanged; the disk half needs the same
    guarantee or the gate clears content the updater will never copy.
    """
    gate = load_gate()
    repo = make_repo(tmp_path)
    plugin = repo / "plugins" / "kipi-core"
    plugin.mkdir(parents=True)
    (plugin / "first.md").write_text("clean\n", encoding="utf-8")
    (plugin / "second.md").write_text("clean\n", encoding="utf-8")

    def mutate_then_classify(text, source_path=None):
        (plugin / "second.md").write_text(LEAKED_RECORD, encoding="utf-8")
        return []

    with pytest.raises(gate.PropagationSourceRefused) as refusal:
        gate.scan_propagation_sources(repo, classify=mutate_then_classify)
    assert "changed during the scan" in str(refusal.value)


def test_symlinked_config_file_is_dereferenced_by_cp(tmp_path):
    """`cp` without -P dereferences too, so .claude/<kind>/*.md is in scope.

    The updater copies agents, output-styles and rules with a plain `cp`. A
    symlinked rule file lands in every instance as the target's CONTENT.
    """
    gate = load_gate()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "house-rule.md").write_text(LEAKED_RECORD, encoding="utf-8")
    repo = make_repo(tmp_path)
    (repo / ".claude" / "rules").mkdir(parents=True)
    (repo / ".claude" / "rules" / "house-rule.md").symlink_to(
        outside / "house-rule.md"
    )
    track_everything(repo)

    findings = gate.scan_propagation_sources(repo)

    assert ".claude/rules/house-rule.md" in scanned_paths(findings)


def test_binary_behind_a_symlink_is_excluded_not_refused(tmp_path):
    """Mirrors containment-targets: a non-text asset carries no record line."""
    gate = load_gate()
    external = tmp_path / "external-repo"
    external.mkdir()
    (external / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\xff\xfe")
    repo = make_repo(tmp_path)
    link_plugin(repo, external)

    sources = gate.enumerate_propagation_sources(repo)

    assert (
        excluded_reason(sources, "plugins/memory-lifecycle/logo.png")
        == "generated-or-binary-asset"
    )
    assert gate.scan_propagation_sources(repo) == []
