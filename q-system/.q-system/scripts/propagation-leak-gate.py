#!/usr/bin/env python3
"""Fingerprint semantic leak findings so a baseline stays a real statement.

Pairs with q-system/.q-system/scripts/test/test-propagation-leak-gate.py and
q-system/.q-system/scripts/test/test-propagation-leak-sources.py.

A baseline is an allowlist over content that is already known and accepted. Two
properties make it honest, and both are easy to get wrong:

- Key on the offending line's CONTENT, not its line number. Reformatting a file
  must not churn the baseline, or the baseline gets regenerated so often that
  nobody reads the diff.
- Carry the OCCURRENCE COUNT. A bare set of fingerprints is a permanent replay
  permit: bless one `- Client: Northwind` and the same line can be pasted a
  second time, or deleted and reintroduced months later, without ever
  registering as new.

This module owns the fingerprint algebra and the source enumeration it runs
over. Reading the baseline file and wiring the gate into the propagation entry
points are separate issues (pff-baseline-provenance, pff-baseline-lifecycle,
pff-updater-preflight, pff-all-propagation-entrypoints).

The source half exists because the scan surface is NOT one snapshot.
`kipi-update.sh` propagates from two different places:

- `q-system/` from `git archive HEAD`, so a committed snapshot;
- `plugins/*/` (rsync) and `.claude/{agents,output-styles,rules}/*.md` (cp)
  from the LIVE WORKTREE, so untracked and unstaged content included.

Enumerating only the Git index would miss both halves of the real risk: an
untracked file dropped into a plugin, and the contents of a symlink. rsync
dereferences its transfer ROOT and `cp` (without -P) dereferences its argument,
so `plugins/memory-lifecycle -> <external repo>` reaches every instance while
never appearing in a tracked-path manifest at all.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import re
from collections.abc import Mapping
from pathlib import Path, PurePosixPath


def normalize_line(text: str) -> str:
    """The asserted text, with line endings and surrounding space removed."""
    return text.replace("\r\n", "\n").strip()


def indent_bucket(text: str) -> str:
    """"top" for an unindented line, "nested" for any indented one.

    Indentation cannot be discarded outright: an indented
    `- Client: Northwind` inside a fenced example is not the same thing as the
    same line asserted at top level, and hashing them together lets a baseline
    for the example bless the assertion. Nor can the exact width be kept, or
    re-indenting two spaces would churn the baseline. Bucketing keeps the
    distinction that carries meaning and drops the one that does not.
    """
    stripped = text.replace("\r\n", "\n").lstrip("\n")
    return "nested" if stripped[:1].isspace() else "top"


def fingerprint(finding: dict) -> tuple:
    """(path, fact_class, indent bucket, sha256 of the offending line).

    The finding must carry its own text. Re-reading the line from disk here
    would fingerprint whatever is at that line NOW, which is not necessarily
    the line the classifier judged.
    """
    text = finding.get("text")
    if not isinstance(text, str):
        raise ValueError(
            f"finding for {finding.get('path')!r} carries no text to fingerprint"
        )
    path = finding.get("path")
    fact_class = finding.get("fact_class")
    if not isinstance(path, str) or not path:
        raise ValueError("finding carries no path")
    if not isinstance(fact_class, str) or not fact_class:
        raise ValueError(f"finding for {path!r} carries no fact_class")
    digest = hashlib.sha256(normalize_line(text).encode("utf-8")).hexdigest()
    return (path, fact_class, indent_bucket(text), digest)


def fingerprint_findings(findings) -> dict:
    """{fingerprint: occurrence count}."""
    counts: dict = {}
    for finding in findings:
        key = fingerprint(finding)
        counts[key] = counts.get(key, 0) + 1
    return counts


def new_findings(baseline: dict, current: dict) -> list:
    """Everything in `current` the baseline does not already account for.

    An increased count is an addition too: one blessed occurrence does not
    bless the second one.
    """
    additions = []
    for key in sorted(current):
        allowed = baseline.get(key, 0)
        found = current[key]
        if found > allowed:
            path, fact_class, indent, digest = key
            additions.append(
                {
                    "path": path,
                    "fact_class": fact_class,
                    "indent": indent,
                    "line_sha256": digest,
                    "baseline_count": allowed,
                    "current_count": found,
                    "count_delta": found - allowed,
                }
            )
    return additions


def prune_baseline(baseline: dict, current: dict) -> dict:
    """Drop permits for content that is gone, and lower ones that shrank.

    Without this a retired fingerprint parks in the baseline forever and
    silently re-authorizes the same line when it comes back.
    """
    pruned = {}
    for key, allowed in baseline.items():
        found = current.get(key, 0)
        if found > 0:
            pruned[key] = min(allowed, found)
    return pruned


def baseline_delta(baseline: dict, current: dict) -> dict:
    """Adds and removals reported separately.

    One combined number lets an unrelated real leak ride along with expected
    classifier churn during a re-baseline.
    """
    return {
        "added": new_findings(baseline, current),
        "removed": [
            {
                "path": key[0],
                "fact_class": key[1],
                "indent": key[2],
                "line_sha256": key[3],
                "baseline_count": allowed,
                "current_count": current.get(key, 0),
            }
            for key, allowed in sorted(baseline.items())
            if current.get(key, 0) < allowed
        ],
    }


# --------------------------------------------------------------------------
# Sources: what propagation actually copies
# --------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
GATE_REPO_ROOT = SCRIPT_DIR.parents[2]

# The roots kipi-update.sh copies from the WORKTREE rather than from a commit:
# `for plugin_dir in "$SCRIPT_DIR"/plugins/*/` rsynced with a trailing slash,
# and `cp "$SCRIPT_DIR"/.claude/<kind>/*.md`. Both dereference symlinks (rsync
# at the transfer root, cp because it is not passed -P) and both copy untracked
# and unstaged content, so neither can be enumerated from the Git index.
WORKTREE_CONFIG_KINDS = ("agents", "output-styles", "rules")
WORKTREE_COPIED_PREFIXES = ("plugins",) + tuple(
    f".claude/{kind}" for kind in WORKTREE_CONFIG_KINDS
)

# Mirrors the updater's rsync filters, INCLUDING their type semantics. A
# trailing slash in an rsync exclude means DIRECTORY ONLY: `--exclude="/.git/"`
# does not exclude a regular file named `.git`, which is exactly the shape a
# submodule or a linked worktree uses, and `--exclude="__pycache__/"` likewise.
# `--exclude="*.pyc"` has no trailing slash, so it matches either kind.
# Excluding by name alone would hand a copied file a free pass.
RSYNC_EXCLUDED_ROOT_DIRS = (".git",)
RSYNC_EXCLUDED_DIRS = ("__pycache__",)
RSYNC_EXCLUDED_SUFFIXES = (".pyc",)

# Suffixes that cannot carry a `label: value` record, so an undecodable file
# with one of them is an asset rather than an unscanned source. This is a DENY
# list on purpose: an allowlist of text extensions fails open, because any
# unlisted extension (a UTF-16 `.rst` holding a client record) would be filed
# under "binary" and skipped. Anything not listed here that fails to decode is
# a source the gate cannot read, and refuses.
BINARY_ASSET_SUFFIXES = (
    ".a", ".bin", ".bz2", ".class", ".db", ".dll", ".dylib", ".eot", ".gif",
    ".gz", ".ico", ".icns", ".idx", ".jar", ".jpeg", ".jpg", ".mov", ".mp3",
    ".mp4", ".node", ".o", ".otf", ".pack", ".pdf", ".png", ".pyd", ".so",
    ".sqlite", ".sqlite3", ".tar", ".tgz", ".ttf", ".wasm", ".wav", ".webp",
    ".whl", ".woff", ".woff2", ".xz", ".zip",
)


class PropagationSourceRefused(RuntimeError):
    """Raised when a source propagation copies cannot be scanned.

    Silence is not evidence of cleanliness. A source that is copied into every
    instance and cannot be read has to stop the run, not pass it.
    """


def copied_from_worktree(relative_path: str) -> bool:
    """True for a path under a root the updater copies off disk."""
    path = PurePosixPath(relative_path)
    return any(
        relative_path == prefix or str(path).startswith(prefix + "/")
        for prefix in WORKTREE_COPIED_PREFIXES
    )


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise PropagationSourceRefused(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _containment_targets():
    return _load_module(
        "kipi_containment_targets", SCRIPT_DIR / "containment-targets.py"
    )


def _default_classifier():
    """This repo's classifier, not the scanned tree's.

    The baseline is a statement about what one classifier saw, so the gate
    always runs its own copy even when pointed at another checkout.
    """
    module = _load_module(
        "kipi_validate_separation", GATE_REPO_ROOT / "validate-separation.py"
    )
    return module.semantic_leakage_findings


def _read_source_or_refuse(real_path: Path, relative_path: str) -> str | None:
    """The source's text, or None when it is a non-text asset."""
    if not real_path.is_file():
        raise PropagationSourceRefused(
            f"propagation copies a source that is not a readable file: "
            f"{relative_path}"
        )
    try:
        content = real_path.read_bytes()
    except OSError as exc:
        raise PropagationSourceRefused(
            f"propagation copies a source the gate cannot read: {relative_path}"
        ) from exc
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as exc:
        if relative_path.endswith(BINARY_ASSET_SUFFIXES):
            return None
        raise PropagationSourceRefused(
            f"propagation copies a source the gate cannot decode: "
            f"{relative_path}"
        ) from exc


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _rsync_filter_reason(entry, at_transfer_root: bool) -> str | None:
    if entry.is_symlink():
        # `rsync -a` implies -l, so only the transfer ROOT is dereferenced. A
        # link inside the tree arrives as a link; its target never travels.
        return "nested-symlink-copied-as-link"
    is_directory = entry.is_dir(follow_symlinks=False)
    if is_directory and at_transfer_root and entry.name in RSYNC_EXCLUDED_ROOT_DIRS:
        return "excluded-by-rsync-filter"
    if is_directory and entry.name in RSYNC_EXCLUDED_DIRS:
        return "excluded-by-rsync-filter"
    if entry.name.endswith(RSYNC_EXCLUDED_SUFFIXES):
        return "excluded-by-rsync-filter"
    return None


def _skipped_by_shell_glob(name: str) -> bool:
    """`plugins/*/` and `*.md` are shell globs, and `*` never matches a dot.

    Walking a dotdir the updater cannot reach turns unreadable content that
    never propagates into a refusal, which is how a gate gets switched off.
    """
    return name.startswith(".")


def _scandir_or_refuse(real_dir: Path, relative_dir: str):
    try:
        return sorted(os.scandir(real_dir), key=lambda entry: entry.name)
    except OSError as exc:
        raise PropagationSourceRefused(
            f"propagation copies a directory the gate cannot enumerate: "
            f"{relative_dir}"
        ) from exc


def _record_source(real_path: Path, relative_path: str, sources: dict) -> None:
    text = _read_source_or_refuse(real_path, relative_path)
    if text is None:
        sources["excluded"].append(
            {"path": relative_path, "reason": "generated-or-binary-asset"}
        )
        return
    sources["worktree"].append(
        {
            "path": relative_path,
            "real_path": str(real_path),
            "sha256": _digest(text),
        }
    )


def _collect_dir(real_dir: Path, relative_dir: str, at_root: bool,
                 stack: list, sources: dict) -> None:
    for entry in _scandir_or_refuse(real_dir, relative_dir):
        relative_path = f"{relative_dir}/{entry.name}"
        reason = _rsync_filter_reason(entry, at_root)
        if reason is not None:
            sources["excluded"].append({"path": relative_path, "reason": reason})
        elif entry.is_dir():
            stack.append((Path(entry.path), relative_path, False))
        else:
            _record_source(Path(entry.path), relative_path, sources)


def _collect_tree(real_root: Path, relative_root: str, sources: dict) -> None:
    stack = [(real_root, relative_root, True)]
    while stack:
        real_dir, relative_dir, at_root = stack.pop()
        _collect_dir(real_dir, relative_dir, at_root, stack, sources)


def _collect_plugins(root: Path, sources: dict) -> None:
    """Mirror `for plugin_dir in plugins/*/`, which only matches directories."""
    plugins = root / "plugins"
    if not plugins.is_dir():
        return
    for entry in _scandir_or_refuse(plugins, "plugins"):
        relative_path = f"plugins/{entry.name}"
        if _skipped_by_shell_glob(entry.name):
            sources["excluded"].append(
                {"path": relative_path, "reason": "not-matched-by-shell-glob"}
            )
        elif entry.is_dir():
            _collect_tree(Path(entry.path), relative_path, sources)
        else:
            # A dangling link or a loose file never matches `plugins/*/`, so
            # the updater copies nothing. Refusing here would block every
            # update over content that cannot leak.
            sources["excluded"].append(
                {"path": relative_path, "reason": "not-a-directory-not-copied"}
            )


def _collect_config_kind(root: Path, kind: str, sources: dict) -> None:
    """Mirror `cp .claude/<kind>/*.md`: one flat glob, symlinks dereferenced."""
    config_dir = root / ".claude" / kind
    if not config_dir.is_dir():
        return
    for entry in _scandir_or_refuse(config_dir, f".claude/{kind}"):
        if not entry.name.endswith(".md") or _skipped_by_shell_glob(entry.name):
            continue
        relative_path = f".claude/{kind}/{entry.name}"
        if entry.is_file():
            _record_source(Path(entry.path), relative_path, sources)
        else:
            sources["excluded"].append(
                {"path": relative_path, "reason": "not-a-file-not-copied"}
            )


def _collect_tracked(manifest: dict, sources: dict) -> None:
    """The `git archive` half, minus anything the worktree walk already owns."""
    for relative_path in manifest["targets"]:
        if copied_from_worktree(relative_path):
            continue
        sources["tracked"].append(relative_path)
        sources["tracked_objects"][relative_path] = manifest["target_objects"][
            relative_path
        ]
    for entry in manifest["excluded"]:
        if not copied_from_worktree(entry["path"]):
            sources["excluded"].append(entry)


def _collect_worktree(root: Path) -> dict:
    """The disk half alone, so the same snapshot can be re-taken and compared."""
    collected: dict = {"worktree": [], "excluded": []}
    _collect_plugins(root, collected)
    for kind in WORKTREE_CONFIG_KINDS:
        _collect_config_kind(root, kind, collected)
    return collected


def _worktree_sha256(collected: dict) -> str:
    """A digest of the SOURCE SET, not of each source.

    Per-entry digests only prove that files already seen still say the same
    thing. A file ADDED to a copied root after enumeration is invisible to
    them, and the updater copies it regardless.
    """
    digest = hashlib.sha256()
    for entry in sorted(collected["worktree"], key=lambda item: item["path"]):
        digest.update(f"{entry['path']}\0{entry['sha256']}\0".encode("utf-8"))
    for entry in sorted(collected["excluded"], key=lambda item: item["path"]):
        digest.update(f"{entry['path']}\0{entry['reason']}\0".encode("utf-8"))
    return digest.hexdigest()


def enumerate_propagation_sources(repo_root: Path | str) -> dict:
    """Every source a propagation run copies, plus a reason for each exclusion."""
    root = Path(repo_root).resolve()
    manifest = _containment_targets().enumerate_containment_targets(root)
    sources = {
        "schema_version": 3,
        "index_sha256": manifest["index_sha256"],
        "tracked": [],
        "tracked_objects": {},
        "worktree": [],
        "excluded": [],
    }
    _collect_tracked(manifest, sources)
    collected = _collect_worktree(root)
    sources["worktree"] = collected["worktree"]
    sources["excluded"].extend(collected["excluded"])
    sources["worktree_sha256"] = _worktree_sha256(collected)
    return sources


def _findings_with_text(text: str, relative_path: str, classify) -> list:
    """Attach the offending line, which is what the fingerprint hashes."""
    lines = text.splitlines()
    located = []
    for finding in classify(text, source_path=relative_path):
        line_number = finding["line"]
        if not 1 <= line_number <= len(lines):
            raise PropagationSourceRefused(
                f"classifier reported line {line_number} outside {relative_path}"
            )
        located.append(
            {**finding, "path": relative_path, "text": lines[line_number - 1]}
        )
    return located


def _scan_tracked(root: Path, sources: dict, targets, classify) -> list:
    findings = []
    for relative_path in sources["tracked"]:
        text = targets.read_indexed_target(
            root, relative_path, sources["tracked_objects"][relative_path]
        )
        findings.extend(_findings_with_text(text, relative_path, classify))
    return findings


def _read_recorded_source(entry: dict) -> str:
    """Re-read one enumerated worktree source, refusing if it moved under us."""
    text = _read_source_or_refuse(Path(entry["real_path"]), entry["path"])
    if text is None or _digest(text) != entry["sha256"]:
        raise PropagationSourceRefused(
            f"propagation source changed during the scan: {entry['path']}"
        )
    return text


def _scan_worktree(sources: dict, classify) -> list:
    findings = []
    for entry in sources["worktree"]:
        findings.extend(
            _findings_with_text(_read_recorded_source(entry), entry["path"], classify)
        )
    return findings


def assert_worktree_unchanged(repo_root: Path | str, sources: dict) -> None:
    """The disk-half twin of containment's assert_index_unchanged.

    A verdict is only about the bytes that were read. If a worktree source
    changed, appeared, or vanished while the scan ran, the verdict describes
    content the updater will not copy, so it is not a verdict at all.
    """
    root = Path(repo_root).resolve()
    if _worktree_sha256(_collect_worktree(root)) != sources["worktree_sha256"]:
        raise PropagationSourceRefused(
            "the set of sources propagation copies changed during the scan"
        )


def scan_propagation_sources(repo_root: Path | str, classify=None) -> list:
    """Classify every propagated source, with the offending line attached.

    Tracked content is read from the same Git index snapshot the manifest was
    built from; worktree-copied content has no index entry and is read from
    disk, then re-verified against the digest taken at enumeration.
    """
    root = Path(repo_root).resolve()
    classify = classify or _default_classifier()
    targets = _containment_targets()
    sources = enumerate_propagation_sources(root)
    findings = _scan_tracked(root, sources, targets, classify)
    findings.extend(_scan_worktree(sources, classify))
    targets.assert_index_unchanged(root, sources["index_sha256"])
    assert_worktree_unchanged(root, sources)
    return findings


# --------------------------------------------------------------------------
# Baseline: what is blessed, and who said why
# --------------------------------------------------------------------------

# The classes worth blocking on. Measured on this repo: 784 findings across 450
# files, against 63k `unclassified_populated_record` hits that are mostly YAML
# frontmatter (`name:` in an agent file) read as client identity. A 784-entry
# file can be read by a human; a 64k one cannot, and a baseline nobody can read
# is an unaudited allowlist, not a review.
BLOCKING_FACT_CLASSES = (
    "case_proof_gap",
    "client_identity",
    "dated_interaction",
    "pricing",
    "source_identity",
    "sourced_interaction",
)

BASELINE_SCHEMA_VERSION = 1
BASELINE_INDENT_VALUES = ("nested", "top")
LINE_SHA256_RE = re.compile(r"[0-9a-f]{64}")


class BaselineRefused(RuntimeError):
    """Raised when a baseline would bless something nobody stood behind."""


def _fact_class(finding) -> str:
    """The finding's class, normalized, refusing malformed classifier output.

    Exact string matching fails OPEN here: a `fact_class` of `"pricing "` or a
    missing one would quietly land in the warning bucket, and a warning never
    stops a run. Anything the classifier emits that this cannot read is a
    refusal, not a warning.
    """
    if not isinstance(finding, Mapping):
        raise BaselineRefused(f"finding is not a record: {finding!r}")
    fact_class = finding.get("fact_class")
    if not isinstance(fact_class, str) or not fact_class.strip():
        raise BaselineRefused(
            f"finding for {finding.get('path')!r} carries no fact_class"
        )
    return " ".join(fact_class.lower().split())


def blocking_findings(findings) -> list:
    """The findings that can stop a propagation run, with the class canonical.

    The normalized class is substituted so the fingerprint keys on the canonical
    form; otherwise `"pricing "` and `"pricing"` would be two different permits.
    """
    return [
        {**finding, "fact_class": _fact_class(finding)}
        for finding in findings
        if _fact_class(finding) in BLOCKING_FACT_CLASSES
    ]


def warning_findings(findings) -> list:
    """Reported, never blocking. Mostly `unclassified_populated_record`."""
    return [
        finding
        for finding in findings
        if _fact_class(finding) not in BLOCKING_FACT_CLASSES
    ]


def blocking_fingerprints(findings) -> dict:
    """{fingerprint: count} over the blocking classes only."""
    return fingerprint_findings(blocking_findings(findings))


def _describe(key) -> str:
    path, fact_class, indent, digest = key
    return f"{path} [{fact_class}/{indent}] {digest[:12]}"


def _materialize_justifications(justifications) -> dict:
    """A real dict built from real items, never from the caller's `get`.

    A Mapping subclass whose `get` returns a constant reason and whose
    `__iter__` is empty would otherwise satisfy every per-entry check while
    being precisely the bulk accept this refuses.
    """
    if not isinstance(justifications, Mapping):
        raise BaselineRefused(
            "a baseline is built per-entry: pass one justification per "
            "fingerprint, not a single reason for the whole set"
        )
    materialized = {}
    for key in list(justifications.keys()):
        if (
            type(key) is not tuple
            or len(key) != 4
            or not all(type(part) is str for part in key)
        ):
            # A key object with a hostile __eq__/__hash__ compares equal to a
            # real fingerprint, so `key not in counts` passes and the entry is
            # written with a reason that was never attached to that fact.
            raise BaselineRefused(
                f"justification key is not a fingerprint: {key!r}"
            )
        materialized[key] = justifications[key]
    return materialized


def _assert_every_entry_is_justified(counts: dict, justifications: dict) -> None:
    missing = [key for key in counts if not str(justifications.get(key) or "").strip()]
    if missing:
        raise BaselineRefused(
            "every baselined high-confidence fact needs its own written "
            "justification; missing for:\n  "
            + "\n  ".join(_describe(key) for key in sorted(missing))
        )
    unknown = [key for key in justifications if key not in counts]
    if unknown:
        # A permit written before the fact exists is a pre-authorized leak: the
        # line can be introduced later and the delta gate will already allow it.
        raise BaselineRefused(
            "justification given for a fact that is not present:\n  "
            + "\n  ".join(_describe(key) for key in sorted(unknown))
        )


def build_baseline_document(findings, justifications,
                            classifier_sha256: str | None = None) -> dict:
    """The committed baseline, one reviewed entry at a time.

    `justifications` is a mapping from fingerprint to the reason that specific
    line is known and accepted. A single reason covering the set is refused:
    bulk acceptance is exactly how a fact that leaked before this gate shipped
    gets blessed forever without anyone reading it.
    """
    justifications = _materialize_justifications(justifications)
    counts = blocking_fingerprints(findings)
    _assert_every_entry_is_justified(counts, justifications)
    entries = [
        {
            "path": key[0],
            "fact_class": key[1],
            "indent": key[2],
            "line_sha256": key[3],
            "count": counts[key],
            "justification": str(justifications[key]).strip(),
        }
        for key in sorted(counts)
    ]
    return {
        "schema_version": BASELINE_SCHEMA_VERSION,
        "blocking_classes": list(BLOCKING_FACT_CLASSES),
        "classifier_sha256": classifier_sha256,
        "entries": entries,
    }


def _baseline_key(entry, position: int) -> tuple:
    """The fingerprint an entry grants, or a refusal.

    Fields are required to BE strings, not merely to stringify into something
    non-empty: a key built from a non-string never compares equal to a freshly
    computed fingerprint, so the permit would silently grant nothing while
    reading as reviewed.
    """
    if not isinstance(entry, Mapping):
        raise BaselineRefused(f"baseline entry {position} is not a record")
    for field in ("path", "fact_class", "indent", "line_sha256", "justification"):
        value = entry.get(field)
        if type(value) is not str or not value.strip():
            raise BaselineRefused(f"baseline entry {position} has no {field}")
    if entry["fact_class"] not in BLOCKING_FACT_CLASSES:
        raise BaselineRefused(
            f"baseline entry {position} is class {entry['fact_class']!r}, which "
            "cannot block, so a permit for it grants nothing and hides review"
        )
    if entry["indent"] not in BASELINE_INDENT_VALUES:
        raise BaselineRefused(
            f"baseline entry {position} has indent {entry['indent']!r}"
        )
    if LINE_SHA256_RE.fullmatch(entry["line_sha256"]) is None:
        raise BaselineRefused(
            f"baseline entry {position} has no line digest"
        )
    return (
        entry["path"],
        entry["fact_class"],
        entry["indent"],
        entry["line_sha256"],
    )


def _assert_document_shape(document) -> None:
    if not isinstance(document, Mapping):
        raise BaselineRefused("baseline is not a JSON object")
    if document.get("schema_version") != BASELINE_SCHEMA_VERSION:
        raise BaselineRefused(
            f"baseline schema_version is {document.get('schema_version')!r}, "
            f"expected {BASELINE_SCHEMA_VERSION}"
        )
    if document.get("blocking_classes") != list(BLOCKING_FACT_CLASSES):
        raise BaselineRefused(
            "baseline declares a different blocking scope than the gate enforces"
        )
    if not isinstance(document.get("entries"), list):
        raise BaselineRefused("baseline has no entries list")


def load_baseline_document(document, classifier_sha256: str | None = None,
                           current: dict | None = None) -> dict:
    """{fingerprint: count}, refusing a file that lost its provenance.

    The checks run on LOAD as well as on build, because the file is committed
    and a hand-edit is the cheapest way to slip an unjustified permit in.

    Pass `current` (the fingerprint counts actually found) to bound each permit.
    A count is how many copies of a line one written justification covers, so
    an unbounded count is a bulk accept with one reason attached: `count: 999`
    on a line found twice pre-authorizes 997 copies nobody reviewed.
    """
    _assert_document_shape(document)
    if classifier_sha256 is not None:
        recorded = document.get("classifier_sha256")
        if recorded != classifier_sha256:
            raise BaselineRefused(
                f"baseline was built by classifier {recorded!r}, running "
                f"{classifier_sha256!r}"
            )
    entries = document["entries"]
    if entries and current is None:
        # Without the current counts there is nothing to bound a permit
        # against, so `count: 999` on a line found twice loads as 999.
        raise BaselineRefused(
            "a baseline that grants permits cannot be loaded unbounded; pass "
            "current=blocking_fingerprints(findings)"
        )
    counts: dict = {}
    for position, entry in enumerate(entries):
        key = _baseline_key(entry, position)
        if key in counts:
            # Two entries for one fingerprint split an inflated permit across
            # two innocuous-looking rows.
            raise BaselineRefused(
                f"baseline entry {position} repeats {_describe(key)}"
            )
        counts[key] = _baseline_count(entry, position, key, current)
    return counts


def _baseline_count(entry: dict, position: int, key: tuple,
                    current: dict | None) -> int:
    count = entry.get("count")
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        raise BaselineRefused(f"baseline entry {position} has no count")
    if current is not None and count > current.get(key, 0):
        raise BaselineRefused(
            f"baseline permits {count} of {_describe(key)} but only "
            f"{current.get(key, 0)} exist; a permit cannot exceed what was reviewed"
        )
    return count
