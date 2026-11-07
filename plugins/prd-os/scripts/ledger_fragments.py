"""One file per row for the append-only `.prd-os` ledgers (ASK-3829).

WHY THIS SHAPE. `.prd-os/receipts.jsonl` and `.prd-os/gates.jsonl` were single files that every
close appended a line to. Two branches that each close an issue append at the same offset, and
GitHub reports the second PR CONFLICTING: it does not run the `merge=union` driver that
`.gitattributes` sets (measured on 37 PRs, see capability_manifest.py). October 2026: 20 approved
kipi-system PRs, all CONFLICTING, 19 of them on receipts.jsonl, 0 merged
(prd-receipts-fragments-2026-10-01.md). chief, 2026-09-15 to 2026-11-06: 96 merged PRs touched
receipts.jsonl and 93 touched gates.jsonl, and each conflict cost a 6-minute floor plus CI
(sp-f9ea5447). Two branches that each ADD a different file merge as two adds, on GitHub too.
Same fix #263 shipped for capability-manifest.json.

LAYOUT
  <name>.jsonl                          legacy rows. Read here, never rewritten, moved or deleted.
  <name>.d/<ts>-<kind>-<sha>.jsonl      one row, one file.
<ts> is UTC to the microsecond, so name order is write order. <sha> is the first 16 hex of the
row's own sha256, so two writers never pick one name, and a same-microsecond tie sorts the same
way on every machine.

THE FOLD (`iter_lines`) is the one reader: legacy rows in file order, then every fragment in name
order. No reader learns the layout, and the order is a pure function of the files, so a merge in
any order folds to the same rows.

THE ONE WRITE PATH (`append_line`). It writes a fragment, except in one case: git tracks the
legacy file and the repo's .gitignore would ignore a fragment beside it. Then the row goes to the
legacy file, as before, and a line on stderr says how to switch. Measured 2026-11-06 over the
instance registry: `investigations` and `accountant` track receipts.jsonl under a .gitignore
that ignores every other .jsonl. A fragment there would never be committed, and the fleet worker
deletes its worktree after a run, so the receipt would be gone. A conflict can be resolved; a
lost receipt cannot.

TWO BYTE-IDENTICAL COPIES, plugins/prd-os/scripts and plugins/kipi-dsse/scripts. A plugin cannot
import another plugin's file at a path that holds in every install, and the receipt writer must
not depend on finding prd-os. When issue_runner imports prd_runner, prd_runner gets whichever copy
loaded first, so drift would be two writers with one name.
test_ledger_fragments_close.py pins them.
"""

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

FRAGMENT_SUFFIX = ".jsonl"
KIND_RE = re.compile(r"^[a-z]+$")
# What `append_line` names a fragment. The fold reads any non-hidden *.jsonl in the directory so
# nothing is silently dropped; the receipts content gate holds names to this pattern.
FRAGMENT_NAME_RE = re.compile(r"^\d{8}T\d{12}Z-[a-z]+-[0-9a-f]{16}\.jsonl$")


def fragment_dir(ledger) -> Path:
    """`.prd-os/receipts.jsonl` -> `.prd-os/receipts.d`. Derived from the ledger path in one
    place, so a `receipts_path` override moves the writer and every reader together."""
    ledger = Path(ledger)
    return ledger.with_name(ledger.stem + ".d")


def fragment_files(ledger) -> list:
    """The fragments beside `ledger`, in fold order. Hidden names are a write in flight."""
    d = fragment_dir(ledger)
    if not d.is_dir():
        return []
    return sorted((p for p in d.iterdir()
                   if p.name.endswith(FRAGMENT_SUFFIX) and not p.name.startswith(".")
                   and p.is_file()), key=lambda p: p.name)


def iter_lines(ledger):
    """Yield (source_path, line_number, raw_line) for every line of the ledger: the legacy file
    first, in file order, then each fragment, in name order. Blank and malformed lines are
    yielded as they are; what to do with them stays each reader's call, as it was."""
    ledger = Path(ledger)
    if ledger.is_file():
        for number, raw in enumerate(ledger.read_text(encoding="utf-8").splitlines(), 1):
            yield ledger, number, raw
    for frag in fragment_files(ledger):
        for number, raw in enumerate(frag.read_text(encoding="utf-8").splitlines(), 1):
            yield frag, number, raw


def has_rows(ledger) -> bool:
    return Path(ledger).is_file() or bool(fragment_files(ledger))


def _git(cwd: Path, *args) -> int:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True,
                          timeout=20).returncode


def fragments_untracked(ledger) -> bool:
    """True only when git tracks the legacy ledger and would ignore a fragment beside it."""
    ledger = Path(ledger)
    parent = ledger.parent
    if not parent.is_dir():
        return False
    probe = f"{fragment_dir(ledger).name}/00000000T000000000000Z-probe-{'0' * 16}{FRAGMENT_SUFFIX}"
    try:
        if _git(parent, "ls-files", "--error-unmatch", "--", ledger.name) != 0:
            return False
        return _git(parent, "check-ignore", "-q", "--", probe) == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _now_stamp(now=None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%S%fZ")


def append_line(ledger, line: str, *, kind: str, now=None) -> Path:
    """Write one ledger row and return the file it landed in.

    `line` is the caller's own serialization of one JSON object, without a newline, so each call
    site keeps its exact bytes (issue_runner sorts keys, gate_register does not). Raises on I/O
    failure so the caller's own error path (close refusing) still runs."""
    ledger = Path(ledger)
    if not KIND_RE.match(kind or ""):
        raise ValueError(f"ledger row kind must be lowercase letters, got {kind!r}")
    if "\n" in line or "\r" in line:
        raise ValueError("a ledger row is one line; got a line break inside it")
    try:
        parsed = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ValueError(f"a ledger row must be JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("a ledger row must be a JSON object")
    data = (line + "\n").encode("utf-8")

    if fragments_untracked(ledger):
        rel = fragment_dir(ledger).name
        sys.stderr.write(
            f"ledger_fragments: git tracks {ledger.name} and this repo's .gitignore ignores "
            f"{rel}/*.jsonl, so this row went to {ledger.name} and parallel merges still "
            f"conflict on it. Add `!.prd-os/{rel}/*.jsonl` to .gitignore to switch.\n")
        ledger.parent.mkdir(parents=True, exist_ok=True)
        with ledger.open("ab") as fh:
            fh.write(data)
            fh.flush()
        return ledger

    d = fragment_dir(ledger)
    d.mkdir(parents=True, exist_ok=True)
    final = d / f"{_now_stamp(now)}-{kind}-{hashlib.sha256(data).hexdigest()[:16]}{FRAGMENT_SUFFIX}"
    # Written whole under a hidden name, then linked into place. A reader never sees half a row
    # (`gates run` exits 2 on one bad line), and link() refuses an existing name, which open('w')
    # would silently overwrite.
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", suffix=".part", dir=str(d))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        try:
            os.link(tmp, final)
        except FileExistsError:
            if final.read_bytes() != data:
                raise
        except OSError:
            # A filesystem with no hard links: exclusive create keeps the no-overwrite rule.
            with final.open("xb") as fh:
                fh.write(data)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
    return final
