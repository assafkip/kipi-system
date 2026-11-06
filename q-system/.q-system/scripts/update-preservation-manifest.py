#!/usr/bin/env python3
"""Refuse a fleet sync that would delete recent instance work the skeleton never had.

WHY THIS EXISTS (ASK-3821, RULE-2026-11-06-A). The fleet sync deleted fixes that
had already landed, twice, with no error and no log line:

  * kipi-investigations f00ee9d7 (2026-06-14) added `_deferral_tracking_gate` to
    plugins/prd-os/scripts/prd_runner.py plus 5 tests. The next morning the
    plugin sync (1d2568c5) wrote the skeleton's older prd_runner.py back, byte
    for byte (blob 67fc9808, the parent's), and deleted the test file.
  * consulting 75014dc0 dropped the ASK-1040 guard and 7 tests the same way;
    kipi-system #333 restored them by hand on 2026-09-08.

Both have one shape: code an INSTANCE commit added, which the SKELETON never had,
overwritten by `rsync --delete` from the skeleton's copy. instance_ahead_scan in
kipi-update.sh already REPORTS a differing file, but only on overwrites (never a
deleted test file) and only refuses behind a flag, because "differs from the
skeleton" is true of hook churn on most of the fleet and a refusal red on its
whole population gets switched off.

So this asks a narrower question, and refuses on every run without a flag:

    Would this sync remove a def, a class or a test file that a commit in the
    instance's last 30 days added, at a path where the skeleton never had it?

"The skeleton never had it" is what keeps the guard quiet on a DELIBERATE
skeleton removal: if the skeleton ever defined that name at that path, the
skeleton owns its removal and its own PR review is the gate. Without that clause
one rename in the skeleton would refuse every instance for 30 days.

Its one override is an entry in kipi-update-preservation-overrides.json naming
the commit, the path, the symbol and the reason. That file is committed and
reviewed like code. There is no environment variable that skips this.

Subcommands:

  check   The guard. kipi-update.sh pipes a framed stream on stdin, one block
          per synced scope, each the itemized `rsync -ain --delete` preview the
          real run would execute, with the real run's flags:
              @@scope<TAB>src_dir<TAB>dest_dir<TAB>instance_rel<TAB>skeleton_rel
              @@restore<TAB>instance-relative path      (zero or more)
              <itemized rsync lines>
              ...
              @@end
          The candidate set therefore comes from rsync itself, so it cannot
          drift from what the sync would change. The @@restore lines are the
          list the real q-system sync snapshots and puts back after its rsync
          (q_system_restore_list in kipi-update.sh); a deletion on it loses
          nothing, so it is not judged.
          Exit 0: nothing protected would be removed (or every hit has an
                  override). Exit 2: refuse. Exit 1: the guard could not decide
                  (bad stream, bad override file, git failure). The caller treats
                  any non-zero as a refusal: a guard that cannot see must not pass.

  probe   The wiring check `kipi check` runs. Builds a throwaway skeleton from
          --kipi-home's updater and the real f00ee9d7 objects in
          test/fixtures/sync-guard-f00ee9d7, runs that home's kipi-update.sh on
          it, and reports whether the updater refused the 1d2568c5 replay. It
          runs the updater the fleet runs, so it proves the call site executes,
          which a grep for the call site cannot.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

WINDOW_DAYS = 30
OVERRIDES_NAME = "kipi-update-preservation-overrides.json"
FILE_SYMBOL = "<file>"
CODE_SUFFIXES = (".py", ".sh", ".bash")
# kipi-update.sh writes this on its two skeleton-sync commits and nowhere else,
# and those commits stage only the synced scopes of a tree the dirty guard just
# proved clean. So whatever such a commit added came FROM the skeleton, and the
# skeleton owns removing it even where it has no git history for the path:
# plugins/ syncs from the skeleton's working tree, so untracked or symlinked
# plugin content has none (review of #609, finding 2: the guard refused and
# named the updater's own commit as the work to keep). Pinned by
# test_the_updater_still_writes_the_sync_marker_the_guard_trusts.
SYNC_MARKER = "[no-issue: fleet updater skeleton sync]"


class GuardError(Exception):
    """The guard cannot decide. Exit 1, never 0."""


# --------------------------------------------------------------------- names

_PY_DEF_RE = re.compile(r"^[ \t]*(?:async[ \t]+)?(def|class)[ \t]+([A-Za-z_]\w*)", re.M)
# `name() {`, `function name {`, `function name() {`. A line that only CALLS a
# function never has `()` straight after the name, so calls do not match.
_SH_DEF_RE = re.compile(
    r"^[ \t]*(?:function[ \t]+([A-Za-z_][\w:.-]*)[ \t]*(?:\(\))?|([A-Za-z_][\w:.-]*)[ \t]*\(\))[ \t]*(?:\{|$)",
    re.M,
)


def _py_ast_names(text: str) -> dict[str, str]:
    tree = ast.parse(text)
    names: dict[str, str] = {}

    def walk(body: list, prefix: str) -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names[prefix + node.name] = "def"
            elif isinstance(node, ast.ClassDef):
                names[prefix + node.name] = "class"
                walk(node.body, prefix + node.name + ".")
            elif isinstance(node, (ast.If, ast.Try, ast.With)):
                # A def under `if TYPE_CHECKING:` or `try: ... except ImportError:`
                # is still a module-level def a sync can delete.
                for block in ("body", "orelse", "finalbody"):
                    walk(getattr(node, block, []) or [], prefix)
                for handler in getattr(node, "handlers", []) or []:
                    walk(handler.body, prefix)

    walk(tree.body, "")
    return names


def _regex_names(path: str, text: str) -> dict[str, str]:
    """Unqualified names by regex: the scheme for shell, and for Python that
    does not parse."""
    if path.endswith(".py"):
        return {m.group(2): m.group(1) for m in _PY_DEF_RE.finditer(text)}
    return {(m.group(1) or m.group(2)): "def" for m in _SH_DEF_RE.finditer(text)}


def code_names(path: str, old_text: str, new_text: str | None) -> tuple[dict, dict, bool]:
    """(names in old_text, names in new_text, qualified) in ONE naming scheme.

    Python is read with ast, so methods are qualified (`Cls.method`) and a
    method that moved between classes counts as removed. If EITHER side does
    not parse, both fall back to the regex, unqualified, and `qualified` says
    so: every history lookup for these names must use the same scheme, or a
    removal named `m` is looked up as `C.m` and never matches (review of #609,
    finding 1: "0 refusals" from a check that could not see)."""
    if path.endswith(".py"):
        try:
            old = _py_ast_names(old_text)
            new = _py_ast_names(new_text) if new_text is not None else {}
            return old, new, True
        except SyntaxError:
            pass
    new = _regex_names(path, new_text) if new_text is not None else {}
    return _regex_names(path, old_text), new, False


def is_code(path: str) -> bool:
    return path.endswith(CODE_SUFFIXES)


def is_test_file(path: str) -> bool:
    base = path.rsplit("/", 1)[-1]
    return base.startswith(("test_", "test-")) or re.search(r"_test\.[A-Za-z]+$", base) is not None


# ----------------------------------------------------------------------- git


def git(repo: str, *args: str, check: bool = True) -> str:
    proc = subprocess.run(["git", "-C", repo, *args], capture_output=True)
    if check and proc.returncode != 0:
        raise GuardError(
            f"git {' '.join(args)} failed in {repo}: "
            f"{proc.stderr.decode(errors='replace').strip()}"
        )
    return proc.stdout.decode("utf-8", errors="replace") if proc.returncode == 0 else ""


class History:
    """Reads one repo's history. Every blob is parsed at most once."""

    def __init__(self, repo: str):
        self.repo = repo
        self._names: dict[tuple[str, str], dict | None] = {}

    def _parsed(self, commit: str, path: str) -> tuple[dict | None, dict] | None:
        """(ast names, or None when the blob does not parse; regex names), or
        None when the path is absent at that commit."""
        key = (commit, path)
        if key not in self._names:
            # `./` makes the path relative to -C's directory. A bare `<rev>:path`
            # resolves from the REPO ROOT, so for an instance that is a subdir
            # of a larger repo every lookup came back "absent", which reads as
            # "never added" and the guard could never refuse (measured
            # 2026-11-06 with `git -C q-system show HEAD:.q-system/...`).
            proc = subprocess.run(
                ["git", "-C", self.repo, "show", f"{commit}:./{path}"], capture_output=True
            )
            if proc.returncode != 0:
                self._names[key] = None  # path absent at that commit
            else:
                text = proc.stdout.decode("utf-8", errors="replace")
                tree = None
                if path.endswith(".py"):
                    try:
                        tree = _py_ast_names(text)
                    except SyntaxError:
                        tree = None
                self._names[key] = (tree, _regex_names(path, text))
        return self._names[key]

    def has(self, commit: str, path: str, symbol: str, qualified: bool) -> bool:
        """Is `symbol` defined at `path` in `commit`, read in the removal's
        scheme. A qualified name at a blob that does not parse falls back to
        its leaf, so a broken historical blob cannot hide an add either."""
        got = self._parsed(commit, path)
        if got is None:
            return False
        tree, flat = got
        if qualified and tree is not None:
            return symbol in tree
        return symbol.rsplit(".", 1)[-1] in flat

    def has_parent(self, commit: str) -> bool:
        return bool(git(self.repo, "rev-parse", "--verify", "-q", f"{commit}^", check=False).strip())


def instance_adder(hist: History, path: str, symbol: str, qualified: bool,
                   since: str) -> str | None:
    """Newest instance commit since `since` that ADDED `symbol` to `path`.

    Commits that touched the path in the window, newest first; the adder is the
    one whose tree has the symbol and whose first parent's tree does not. Newest,
    because if a name was added, dropped and re-added, the re-add is the work a
    sync would undo."""
    if symbol == FILE_SYMBOL:
        out = git(hist.repo, "log", f"--since={since}", "--diff-filter=A",
                  "--format=%H", "HEAD", "--", path)
        commits = out.split()
        return commits[0] if commits else None
    out = git(hist.repo, "log", f"--since={since}", "--format=%H", "HEAD", "--", path)
    for commit in out.split():
        if not hist.has(commit, path, symbol, qualified):
            continue
        if not (hist.has_parent(commit) and hist.has(f"{commit}^", path, symbol, qualified)):
            return commit
    return None


def skeleton_ever_had(hist: History, ref: str, path: str, symbol: str,
                      qualified: bool) -> bool:
    """True when the skeleton defined `symbol` at `path` at any commit up to `ref`.

    Narrowed by pickaxe on the bare name, then confirmed by parsing the commit
    and its parent, so a skeleton `Foo.run` does not vouch for an instance
    `Bar.run`."""
    if symbol == FILE_SYMBOL:
        return bool(git(hist.repo, "log", "-1", "--format=%H", ref, "--", path, check=False).strip())
    leaf = symbol.rsplit(".", 1)[-1]
    out = git(hist.repo, "log", "--format=%H", f"-S{leaf}", ref, "--", path, check=False)
    for commit in out.split():
        if hist.has(commit, path, symbol, qualified):
            return True
        if hist.has_parent(commit) and hist.has(f"{commit}^", path, symbol, qualified):
            return True
    return False


# ----------------------------------------------------------------- overrides


def load_overrides(path: str) -> list[dict]:
    """Missing file = no overrides (fewer exemptions is the safe direction).
    A file that exists but is malformed is an error: a typo must not silently
    widen or narrow what the guard lets through."""
    p = Path(path)
    if not p.is_file():
        return []
    try:
        data = json.loads(p.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise GuardError(f"override file {path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != 1 \
            or not isinstance(data.get("overrides"), list):
        raise GuardError(f"override file {path} needs schema_version 1 and an overrides list")
    entries = []
    for i, entry in enumerate(data["overrides"]):
        if not isinstance(entry, dict):
            raise GuardError(f"override #{i} in {path} is not an object")
        commit = str(entry.get("commit", ""))
        missing = [k for k in ("path", "symbol", "reason") if not str(entry.get(k, "")).strip()]
        if not re.fullmatch(r"[0-9a-f]{7,40}", commit):
            missing.append("commit (7 to 40 hex chars)")
        if missing:
            raise GuardError(f"override #{i} in {path} is missing: {', '.join(missing)}")
        entries.append(entry)
    return entries


def override_for(entries: list[dict], commit: str, path: str, symbol: str) -> dict | None:
    for entry in entries:
        if commit.startswith(entry["commit"]) and entry["path"] == path and entry["symbol"] == symbol:
            return entry
    return None


# ------------------------------------------------------------------- the scan

_ITEM_RE = re.compile(r"^(\S+) +(.+)$")


def parse_stream(stream: str) -> list[dict]:
    scopes: list[dict] = []
    ended = False
    for raw in stream.splitlines():
        if raw.startswith("@@scope\t"):
            parts = raw.split("\t")
            if len(parts) != 5:
                raise GuardError(f"malformed scope header: {raw!r}")
            scopes.append({"src": parts[1], "dest": parts[2], "inst_rel": parts[3],
                           "skel_rel": parts[4], "items": [], "restore": set()})
            continue
        if raw.startswith("@@restore\t"):
            if ended or not scopes:
                raise GuardError(f"restore line outside a scope block: {raw!r}")
            scopes[-1]["restore"].add(raw[len("@@restore\t"):])
            continue
        if raw == "@@end":
            ended = True
            continue
        if not raw.strip():
            continue
        if ended or not scopes:
            raise GuardError(f"rsync line outside a scope block: {raw!r}")
        m = _ITEM_RE.match(raw.rstrip())
        if not m:
            continue
        code, rel = m.group(1), m.group(2)
        if code == "*deleting" or code == "deleting":
            if not rel.endswith("/"):
                scopes[-1]["items"].append(("delete", rel))
        elif code.startswith(">f") and "+" not in code:
            scopes[-1]["items"].append(("overwrite", rel))
    # The sentinel is what makes a producer that died halfway an error instead
    # of a short, clean-looking list.
    if not ended:
        raise GuardError("stream has no @@end: the rsync preview did not finish")
    # A deletion on the updater's own restore list comes back after the rsync,
    # file and defs, so it is not lost work. An overwrite never does: the sync
    # restores only a path the rsync left missing. #609 review round 2: judging
    # the raw preview without this list refused a whole instance over a test
    # file the sync puts back.
    for scope in scopes:
        scope["items"] = [
            ("restored" if action == "delete" and _join(scope["inst_rel"], rel) in scope["restore"]
             else action, rel)
            for action, rel in scope["items"]
        ]
    return scopes


def _join(prefix: str, rel: str) -> str:
    return f"{prefix}/{rel}" if prefix else rel


def removals(scope: dict) -> list[tuple[str, str, str, str, bool]]:
    """(instance_path, skeleton_path, symbol, kind, qualified) for everything
    this scope would remove and not put back. A deleted test file is one item;
    its defs are checked too, so a test added to an OLD file is still caught."""
    out = []
    for action, rel in scope["items"]:
        if action == "restored":
            continue
        inst_path = _join(scope["inst_rel"], rel)
        skel_path = _join(scope["skel_rel"], rel)
        dest_file = Path(scope["dest"]) / rel
        if action == "delete" and is_test_file(rel):
            out.append((inst_path, skel_path, FILE_SYMBOL, "test file", True))
        if not is_code(rel) or not dest_file.is_file():
            continue
        old_text = dest_file.read_text(errors="replace")
        new_text = None
        if action == "overwrite":
            src_file = Path(scope["src"]) / rel
            new_text = src_file.read_text(errors="replace") if src_file.is_file() else ""
            # rsync lists a file whose only difference is its mtime (most of
            # the 50 lines in the real 1d2568c5 preview). Same bytes, same defs.
            if new_text == old_text:
                continue
        old, new, qualified = code_names(rel, old_text, new_text)
        for symbol in sorted(set(old) - set(new)):
            out.append((inst_path, skel_path, symbol, old[symbol], qualified))
    return out


def cmd_check(args: argparse.Namespace) -> int:
    now = datetime.fromisoformat(args.now) if args.now else datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    since = (now - timedelta(days=args.window_days)).strftime("%Y-%m-%dT%H:%M:%S%z")
    overrides = load_overrides(args.overrides)
    scopes = parse_stream(sys.stdin.read())
    inst = History(args.instance_root)
    skel = History(args.skeleton_root)
    git(args.instance_root, "rev-parse", "--verify", "HEAD")
    git(args.skeleton_root, "rev-parse", "--verify", args.skeleton_ref)

    refused, allowed, checked = [], [], 0
    restored = sum(action == "restored" for scope in scopes for action, _ in scope["items"])
    settled_files: set[str] = set()
    for scope in scopes:
        for inst_path, skel_path, symbol, kind, qualified in removals(scope):
            # A test file already refused, or let through by its own override,
            # settles every def in it. Judging the defs again turned one finding
            # into ten lines (first measured run), and made a `<file>` override
            # useless because each test in the file still refused.
            if inst_path in settled_files:
                continue
            checked += 1
            commit = instance_adder(inst, inst_path, symbol, qualified, since)
            if commit is None:
                continue
            if SYNC_MARKER in git(args.instance_root, "log", "-1", "--format=%B", commit):
                continue
            if skeleton_ever_had(skel, args.skeleton_ref, skel_path, symbol, qualified):
                continue
            entry = override_for(overrides, commit, inst_path, symbol)
            if entry is not None:
                allowed.append((inst_path, symbol, commit, entry["reason"]))
            else:
                refused.append((inst_path, symbol, kind, commit))
            if symbol == FILE_SYMBOL:
                settled_files.add(inst_path)

    for inst_path, symbol, commit, reason in allowed:
        print(f"  sync guard: removal allowed by override: {inst_path} {symbol} "
              f"(added by {commit[:12]}): {reason}")
    if not refused:
        print(f"  sync guard: 0 refusals ({checked} removal(s) checked against the last "
              f"{args.window_days} days of instance commits"
              + (f"; {restored} deletion(s) skipped, the sync restores them" if restored else "")
              + ")")
        return 0

    print(f"  REFUSING SYNC: it would remove {len(refused)} item(s) that an instance commit "
          f"in the last {args.window_days} days added and the skeleton never had (ASK-3821):")
    for inst_path, symbol, kind, commit in refused[:20]:
        what = "test file" if symbol == FILE_SYMBOL else f"{kind} {symbol}"
        meta = git(args.instance_root, "log", "-1", "--format=%cs %s", commit, check=False).strip()
        print(f"    {inst_path}: {what}")
        print(f"      added by {commit[:12]} {meta}")
        print(f"      this sync would undo {commit[:12]}")
    if len(refused) > 20:
        print(f"    ... and {len(refused) - 20} more")
    first = refused[0]
    print("  To keep the work: port it to the skeleton (kipi push, or a PR), then sync again.")
    print(f"  To let a removal through on purpose, add an entry like this to {OVERRIDES_NAME}")
    print("  in the skeleton, in a reviewed commit:")
    print("    " + json.dumps({"commit": first[3], "path": first[0], "symbol": first[1],
                               "reason": "<why removing this is intended>"}))
    return 2


# ---------------------------------------------------------------------- probe

FIXTURE_REL = "q-system/.q-system/scripts/test/fixtures/sync-guard-f00ee9d7"
# Blob ids of the REAL objects in kipi-investigations. Checked on every probe so
# the fixture cannot drift into a hand-edited stand-in.
BEFORE_BLOB = "67fc9808fa64edecf86341b1b7456c74f1f41a29"  # f00ee9d7^ and 1d2568c5
AFTER_BLOB = "ee64a404d1adfe7a68bbcd85e7312c98a91ee1c3"   # f00ee9d7
TEST_BLOB = "6a91b9520969fedde4156bc531f1005622f7d5be"    # its test file
# RELOCATED one directory, on purpose. At its literal path prd_runner.py is one
# of the 3 files fleet-replica-divergence.py hashes, and that preflight aborts the
# WHOLE run before the per-instance loop when a copy is ahead (measured
# 2026-11-06: "ABORT: a replica has drifted ahead", no commit named). The literal
# replay therefore never reaches a per-instance guard. Under a path that gate
# does not list, the same bytes, message, author and timing show what every
# OTHER synced file gets today: the sync deletes the work.
REPLAY_PLUGIN = "plugins/prd-os-replay"
RUNNER = f"{REPLAY_PLUGIN}/scripts/prd_runner.py"
TESTFILE = f"{REPLAY_PLUGIN}/tests/test_archive_deferral_gate.py"
SYMBOL = "_deferral_tracking_gate"

# The files a fixture skeleton needs for kipi-update.sh to reach the per-instance
# preflights. Same set the other kipi-update fixtures copy
# (test-kipi-update-instance-ahead.sh); the optional ones are copied when present.
UPDATER_FILES = ("kipi-update.sh", "kipi-update-preserve-scan.py",
                 "kipi-update-deletion-guard.py", "kipi-update-instance-ahead.py",
                 "validate-separation.py", "q-system/hooks/auto-commit.py")
OPTIONAL_FILES = ("q-system/.q-system/scripts/propagation-leak-gate.py",
                  "q-system/.q-system/scripts/containment-targets.py",
                  "q-system/.q-system/scripts/fleet-replica-divergence.py",
                  "q-system/.q-system/scripts/update-preservation-manifest.py",
                  OVERRIDES_NAME)
LEAK_BASELINE = {
    "schema_version": 1,
    "blocking_classes": ["case_proof_gap", "client_identity", "dated_interaction", "pricing",
                         "relationship", "source_identity", "sourced_interaction"],
    "classifier_sha256": None,
    "entries": [],
}


def _g(repo: Path, *args: str, env: dict | None = None) -> str:
    proc = subprocess.run(
        ["git", "-c", "user.email=probe@kipi.local", "-c", "user.name=probe",
         "-c", "commit.gpgsign=false", "-C", str(repo), *args],
        capture_output=True, text=True, env=env,
    )
    if proc.returncode != 0:
        raise GuardError(f"probe fixture: git {' '.join(args)}: {proc.stderr.strip()}")
    return proc.stdout.strip()


def build_replay(kipi_home: Path, work: Path) -> dict:
    """Skeleton = kipi_home's updater + prd_runner.py as 1d2568c5 wrote it.
    Instance = that same file 40 days old, then the real f00ee9d7 patch applied
    a day before the sync, as it was."""
    fixture = kipi_home / FIXTURE_REL
    before = fixture / "prd_runner.py.at-1d2568c5"
    patch = fixture / "f00ee9d7.patch"
    if not before.is_file() or not patch.is_file():
        raise GuardError(f"probe fixture missing under {fixture}")
    sk, inst = work / "skel", work / "inst"
    for rel in UPDATER_FILES:
        src = kipi_home / rel
        if not src.is_file():
            raise GuardError(f"probe: {rel} missing from {kipi_home}")
        (sk / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, sk / rel)
    for rel in OPTIONAL_FILES:
        if (kipi_home / rel).is_file():
            (sk / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(kipi_home / rel, sk / rel)
    state = sk / "q-system/.q-system/state"
    state.mkdir(parents=True, exist_ok=True)
    (state / "propagation-leak-baseline.json").write_text(json.dumps(LEAK_BASELINE, indent=2))
    (sk / "q-system/tracked.md").write_text("skeleton\n")
    (sk / ".claude/rules").mkdir(parents=True, exist_ok=True)
    (sk / ".claude/rules/demo.md").write_text("# demo rule\n")
    (sk / RUNNER).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(before, sk / RUNNER)
    _g(sk, "init", "-q", "-b", "main")
    _g(sk, "add", "-A", "-f")
    _g(sk, "commit", "-qm", "skeleton: prd_runner.py as 1d2568c5 wrote it")
    (sk / "instance-registry.json").write_text(json.dumps({"instances": [{
        "name": "replay", "path": str(inst), "subtree_prefix": "q-system", "type": "subtree"}]}))

    (inst / "q-system").mkdir(parents=True)
    (inst / "q-system/tracked.md").write_text("skeleton\n")
    (inst / ".claude/rules").mkdir(parents=True)
    (inst / ".claude/rules/demo.md").write_text("# demo rule\n")
    (inst / RUNNER).parent.mkdir(parents=True)
    shutil.copy2(before, inst / RUNNER)
    now = datetime.now(timezone.utc)
    old = (now - timedelta(days=40)).strftime("%Y-%m-%dT%H:%M:%S+0000")
    env = {**os.environ, "GIT_AUTHOR_DATE": old, "GIT_COMMITTER_DATE": old}
    _g(inst, "init", "-q", "-b", "main")
    _g(inst, "add", "-A", "-f", env=env)
    _g(inst, "commit", "-qm", "instance base", env=env)
    recent = (now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S+0000")
    # -p3 strips a/plugins/prd-os/, --directory re-roots it under REPLAY_PLUGIN.
    _g(inst, "am", "-q", "-p3", f"--directory={REPLAY_PLUGIN}", str(patch),
       env={**os.environ, "GIT_COMMITTER_DATE": recent})
    got = (_g(inst, "rev-parse", "HEAD~1:" + RUNNER), _g(inst, "rev-parse", "HEAD:" + RUNNER),
           _g(inst, "rev-parse", "HEAD:" + TESTFILE))
    if got != (BEFORE_BLOB, AFTER_BLOB, TEST_BLOB):
        raise GuardError(f"probe fixture is not the real f00ee9d7 objects: {got}")
    return {"skel": sk, "inst": inst, "replay": _g(inst, "rev-parse", "HEAD")}


def run_replay(kipi_home: Path, work: Path, real: bool) -> dict:
    fx = build_replay(kipi_home, work)
    home = work / "home"
    home.mkdir()
    env = {**os.environ, "HOME": str(home),
           "KIPI_FLEET_SWEEP_HISTORY": str(work / "sweep-history.jsonl")}
    cmd = ["bash", str(fx["skel"] / "kipi-update.sh")] + ([] if real else ["--dry-run"])
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(work), env=env)
    out = proc.stdout + proc.stderr
    runner_text = (fx["inst"] / RUNNER).read_text(errors="replace")
    short = fx["replay"][:12]
    return {
        "output": out,
        "replay": fx["replay"],
        "refused": "REFUSING SYNC" in out and f"undo {short}" in out and SYMBOL in out,
        "function_kept": f"def {SYMBOL}(" in runner_text,
        "tests_kept": (fx["inst"] / TESTFILE).is_file(),
        "head_kept": _g(fx["inst"], "rev-parse", "HEAD") == fx["replay"],
    }


def cmd_probe(args: argparse.Namespace) -> int:
    kipi_home = Path(args.kipi_home).resolve()
    work = Path(tempfile.mkdtemp(prefix="kipi-sync-guard-probe-"))
    try:
        res = run_replay(kipi_home, work, args.real)
    except GuardError as exc:
        print(f"update sync guard: PROBE BROKEN ({exc})")
        return 1
    finally:
        if not args.keep:
            shutil.rmtree(work, ignore_errors=True)
    mode = "real" if args.real else "dry"
    kept = res["function_kept"] and res["tests_kept"] and res["head_kept"]
    if res["refused"] and kept:
        print(f"update sync guard: WIRED ({mode} replay of 1d2568c5 through {kipi_home}/kipi-update.sh "
              f"was refused and named {res['replay'][:12]}, the replay of f00ee9d7; "
              f"{SYMBOL} and its tests kept)")
        return 0
    lost = []
    if not res["function_kept"]:
        lost.append(f"{SYMBOL} removed from {RUNNER}")
    if not res["tests_kept"]:
        lost.append(f"{TESTFILE} deleted")
    print(f"update sync guard: NOT WIRED ({mode} replay of 1d2568c5 through {kipi_home}/kipi-update.sh "
          f"{'refused' if res['refused'] else 'was not refused'}; "
          f"{'; '.join(lost) if lost else 'instance work kept'})")
    for line in res["output"].strip().splitlines()[-12:]:
        print(f"    {line}")
    return 1


# ----------------------------------------------------------------------- main


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="the guard; framed rsync previews on stdin")
    c.add_argument("--instance-root", required=True)
    c.add_argument("--skeleton-root", required=True)
    c.add_argument("--skeleton-ref", default="HEAD")
    c.add_argument("--overrides", required=True)
    c.add_argument("--window-days", type=int, default=WINDOW_DAYS)
    c.add_argument("--now", help="ISO time to measure the window from (tests only; default now)")
    p = sub.add_parser("probe", help="replay 1d2568c5 through an updater; WIRED or NOT WIRED")
    p.add_argument("--kipi-home", required=True)
    p.add_argument("--real", action="store_true",
                   help="run the fixture sync for real (inside the temp fixture) instead of --dry-run")
    p.add_argument("--keep", action="store_true", help="keep the temp fixture for inspection")
    args = parser.parse_args(argv)
    try:
        return cmd_check(args) if args.cmd == "check" else cmd_probe(args)
    except GuardError as exc:
        print(f"  sync guard ERROR (treated as a refusal): {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
