#!/usr/bin/env python3
"""Surface a minor spillover finding at the moment someone edits its file (ASK-343).

why: 510 of 532 open findings are `minor`. They are real, but they are not a
queue -- nobody will ever sit down and work a 510-item list, and after ASK-341
they no longer block the gate. So they had no delivery mechanism at all, which
makes keeping them identical to deleting them.

This gives them one. A minor finding is a note left for THE NEXT PERSON TO TOUCH
THIS FILE. So it fires then, and only then.

Same shape as portability-lint.sh, which sp-db43af2f documents: wired as a
RATCHET on the file being edited, so pre-existing findings surface when a file
is next touched rather than turning a gate red on items nobody is working on
today.

Consequence, deliberately: a finding about a file nobody ever touches again
never fires. That is correct. If the file is dead, the finding was too.

PostToolUse on Edit/Write. Exits 2 ONCE per file per day, because the hook
contract is exit 2 = stderr fed to Claude, exit 0 = pass. An exit-0 hook writes
to a stderr nobody reads -- the first version of this file did exactly that and
was inert on arrival, which is the same defect the whole ledger suffered from.

The ask is NOT "fix this". Fixing an adjacent bug mid-task is scope creep and
the repo rules forbid it. The ask is "is this still true?" -- an agent with the
file already open is the cheapest verifier that will ever exist, and a confirm
or a void drains the pile one note at a time without a cleanup day.

Once per file per day, so a file with 17 notes interrupts once, not 17 times
and not on every edit. The marker is a date-stamped file; a new day re-asks,
which is correct for a note that was deferred rather than resolved.

Usage (hook): reads the tool payload on stdin.
Usage (manual): spillover-ratchet.py <path>
"""
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
SKELETON = HERE.parents[3]
MAX_SHOWN = 3
ACK_DIR = Path.home() / ".config" / "kipi" / "spillover-ratchet-ack"
PROMOTER = HERE.parent / "spillover-promote.py"


def ledger_root(root: Path) -> Path:
    """The ONE ledger directory, shared by every worktree in the set (ASK-457).

    why: measured before wiring, from a worktree off main -- `repo_root_for`
    returned the WORKTREE root, whose `.prd-os/spillover.jsonl` does not exist,
    because `*.jsonl` is gitignored and so the ledger never travels through git.
    Result: 0 rows and 0 findings on `linear-worker.sh`, a file carrying 57 real
    open notes. Agents do their work in worktrees, so arming the hook without
    this would have armed it exactly where it can never fire -- a switch that
    reports itself on while protecting nothing, which is the failure this whole
    ledger exists to stop.

    IMPORTED from spillover-promote.py, never reimplemented. That function in
    turn imports `prd_runner._ledger_root` (git-common-dir), so there is one
    derivation of "where does the ledger live" for the whole conveyor. Two
    private copies of that rule is literally how the ledger got split.

    Falls back to the passed-in root when the promoter is missing (an instance
    that has not synced yet). Degraded, not silent: the fallback reads a
    non-existent ledger and simply finds nothing, same as today.
    """
    if not PROMOTER.is_file():
        return root
    try:
        spec = importlib.util.spec_from_file_location("sp_ledger_root", PROMOTER)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return Path(m.ledger_root(root))
    except Exception:
        return root


def ledger_rows(root: Path) -> list:
    """Open MINOR findings only. Blocking ones go through the gate, not here."""
    p = root / ".prd-os" / "spillover.jsonl"
    if not p.is_file():
        return []
    rows = {}
    try:
        for line in p.read_text().splitlines():
            line = line.strip()
            if line:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if "id" in r:
                    rows[r["id"]] = r
    except OSError:
        return []
    return [r for r in rows.values()
            if r.get("status") == "open"
            and (r.get("severity") or "minor").lower() == "minor"]


def repo_root_for(path: Path) -> Path:
    try:
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                             cwd=str(path.parent if path.is_file() else path),
                             capture_output=True, text=True, timeout=10)
        if out.returncode == 0 and out.stdout.strip():
            return Path(out.stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        pass
    return SKELETON


def path_suffix_matches(token: str, target: str) -> bool:
    """Does `token` (a path fragment from a description) name `target`?

    Compared component-wise from the right, so `plugins/prd-os/hooks/hooks.json`
    names the file you are editing at `/w/ask-457/plugins/prd-os/hooks/hooks.json`
    while `.claude/hooks/hooks.json` does not. Suffix, never substring: a repo
    is full of same-named files in different directories and firing a note about
    one of them on all of them is the cry-wolf failure by another route.
    """
    want = [p for p in token.split("/") if p]
    have = [p for p in Path(target).as_posix().split("/") if p]
    return bool(want) and len(want) <= len(have) and have[-len(want):] == want


def basename_names_this_file(pat, description: str, target: str) -> bool:
    """A basename hit counts when it is bare, or when its path fits `target`."""
    for m in pat.finditer(description):
        if not m.group(1) or path_suffix_matches(m.group(0), target):
            return True
    return False


def findings_for(filename: str, rows: list) -> list:
    """Findings whose text names this file.

    Matches the BASENAME, not the full path: a finding written from another
    checkout names `capability-gate.py`, not the path you happen to be editing
    it through. Word-boundary anchored so `gate.py` does not match
    `capability-gate.py`.

    A PATHED mention counts too, and that is not cosmetic (Codex minor, ASK-457).
    Real producer descriptions cite `plugins/prd-os/hooks/hooks.json`, not a bare
    basename -- `spillover add --desc` is written by an agent that has the path in
    hand. The basename branch excluded a preceding `/`, and the stem branch only
    runs for stems carrying a separator, so every finding about an ORDINARY-stem
    file (`hooks.json`, `config.json`, `settings.json`) fell between the two and
    could never fire. Silent absence, which is the failure this whole ledger
    exists to stop.
    """
    base = os.path.basename(filename)
    if not base or len(base) < 4:
        return []
    stem, ext = os.path.splitext(base)
    # The SAME cry-wolf guard the stem path already carries, applied to the
    # basename path -- where the hole had simply relocated (ASK-457). Measured
    # against the live ledger before wiring: editing the repo-root `kipi` CLI
    # matched 148 findings, every sampled one a false positive, because the bare
    # word "kipi" appears in prose about `kipi update` in half the ledger. Same
    # for `claude` (72), `repo` (61), `main` (45), `config` (23), `HEAD` (17),
    # `python3`, `description`, `exclude` -- 395 bogus interruptions across 9
    # names, and `kipi` is a file people edit.
    #
    # A basename is a NAME only when something marks it as one: an extension
    # (`capability-gate.py`), a separator (`linear-worker`), or a leading dot
    # (`.gitignore`). A bare dictionary word is a word, and a ratchet that fires
    # 148 notes on the main CLI is a ratchet switched off by lunchtime -- the
    # exact fate this file's README guard was written to avoid.
    if not ext and "-" not in base and "_" not in base and not base.startswith("."):
        return []
    # `/` is no longer excluded by the lookbehind. It is CAPTURED instead, in
    # group 1, so the directory part is checked against the file being edited
    # rather than used to reject the mention outright. Excluding it was what made
    # a pathed mention invisible; accepting it blindly would fire every
    # `hooks.json` note on every hooks.json in the repo.
    pat = re.compile(r"(?<![\w.-])((?:[\w.-]+/)+)?" + re.escape(base) + r"(?![\w])")
    # Stem matching only for DISTINCTIVE stems, i.e. ones carrying a separator
    # ("capability-gate", "linear_dor_drafter"). Caught 2026-08-03: matching any
    # stem over 4 chars made README.md fire, because "README" appears in dozens
    # of unrelated descriptions. A ratchet that cries wolf on README is a ratchet
    # someone switches off, and then it protects nothing.
    distinctive = ("-" in stem or "_" in stem) and len(stem) > 4
    spat = re.compile(r"(?<![\w.-])" + re.escape(stem) + r"(?![\w-])") if distinctive else None
    hits = []
    for r in rows:
        d = r.get("description", "") or ""
        if basename_names_this_file(pat, d, filename) or (spat and spat.search(d)):
            hits.append(r)
    return hits


def main() -> int:
    if len(sys.argv) > 1:
        target = sys.argv[1]
    else:
        try:
            payload = json.load(sys.stdin)
        except (json.JSONDecodeError, ValueError):
            return 0
        target = (payload.get("tool_input") or {}).get("file_path") or ""
    if not target:
        return 0

    p = Path(target)
    rows = ledger_rows(ledger_root(repo_root_for(p)))
    hits = findings_for(target, rows)
    if not hits:
        return 0

    # One interruption per file per day. Without this, a file with 17 notes
    # would block every edit 17 times and the hook would be switched off within
    # the hour -- which is how a gate that protects nothing gets created.
    #
    # Keyed on the RESOLVED PATH, not the basename (Codex minor, ASK-457).
    # `<date>-hooks.json` made one acknowledgement silence every same-named file
    # in the repo for the day, and same-named files in different directories are
    # the ordinary case here: hooks.json, settings.json, config.json, README.md.
    # The pathed-mention fix above made findings able to address ONE of them
    # specifically; this key threw that distinction away one step later, so the
    # note about the other one went silently undelivered.
    #
    # The path is resolved first, so `a/./b/f.json` and `a/b/f.json` are one
    # acknowledgement rather than two -- keying on the raw argument would
    # re-interrupt on every spelling. Digested rather than sanitised inline
    # because a full path flattens to a name past the 255-byte filename limit.
    import datetime
    import hashlib
    stamp = os.environ.get("KIPI_RATCHET_DATE") or datetime.date.today().isoformat()
    try:
        resolved = str(p.resolve())
    except OSError:
        resolved = os.path.abspath(target)
    digest = hashlib.sha256(resolved.encode("utf-8", "surrogatepass")).hexdigest()[:16]
    key = re.sub(r"[^A-Za-z0-9_.-]", "_",
                 f"{stamp}-{os.path.basename(target)}-{digest}")
    ack = ACK_DIR / key
    if ack.exists():
        return 0
    try:
        ACK_DIR.mkdir(parents=True, exist_ok=True)
        ack.write_text("")
    except OSError:
        pass   # an unwritable marker must not turn one note into a loop

    print(f"\n[spillover] {len(hits)} open note(s) about {os.path.basename(target)}.",
          file=sys.stderr)
    print("These were left by whoever last worked here. You have the file open, "
          "so you are the cheapest person to check them.", file=sys.stderr)
    for r in hits[:MAX_SHOWN]:
        print(f"\n  {r['id']} (src {r.get('source')}):\n    "
              f"{(r.get('description') or '')[:260]}", file=sys.stderr)
    if len(hits) > MAX_SHOWN:
        print(f"\n  ...and {len(hits) - MAX_SHOWN} more "
              f"(`prd_runner.py spillover list --open`)", file=sys.stderr)
    # The promoter is named by RESOLVED PATH, not bare basename. It is not on
    # PATH, and the agent reading this is usually in a worktree where a relative
    # guess misses. An address the reader cannot dial is not an address, which is
    # the same defect as a finding with no address (ASK-457).
    print("\n  DO NOT fix them here -- that is scope creep. Decide, and give each "
          "an ADDRESS:\n"
          "    STALE     -> prd_runner.py spillover resolve <id> --void \"<reason>\"\n"
          f"    STILL TRUE-> {PROMOTER} <id> --title \"...\" --dor-file <f>\n"
          "                 makes a Linear issue the worker can pick up. It REFUSES\n"
          "                 without allowed-files + acceptance, because an issue\n"
          "                 nothing can work is the queue this all started from.\n"
          "  A confirmed note with no address is just the pile, re-read.\n"
          "  Then continue your task. This fires once per file per day.\n",
          file=sys.stderr)
    return 2     # the ONLY exit code whose stderr reaches the agent


if __name__ == "__main__":
    sys.exit(main())
