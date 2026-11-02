#!/usr/bin/env python3
"""instruction-chars-audit.py: fleet gate for Claude Code's instruction-file char limit (ASK-3689).

Pairs with no skill. Called by `kipi-update.sh` after a sync (--apply, reported,
never folded into its exit code). Check mode exits 2 and is runnable by hand; it
is wired into `kipi check` only once the fleet reads green (ASK-3692), because a
gate red on its own population gets switched off (PR 599 review, round 1).

THE LIMIT
Claude Code 2.1.316 prints "N instruction files add up to X chars, over the
150.0k-char total limit" when the CLAUDE.md files, rules files and the files they
import pass 150,000 characters for the session's model. Over the limit, the whole
set still rides every turn.

THE LOADER THIS REPLAYS
Calibrated 2026-11-02: the largest nested client instance measured 53 files /
209.8k against the warning's own 53 files / 209.9k.
  - <user dir>/CLAUDE.md and <user dir>/rules/**/*.md
  - EVERY ancestor of the launch folder, not only the git root: CLAUDE.md,
    .claude/CLAUDE.md, CLAUDE.local.md, .claude/rules/**/*.md
  - a rules file with `paths:` frontmatter is skipped: it loads on demand
  - @imports followed to depth 5, ignoring fenced and inline code
  - YAML frontmatter and HTML comments are not counted
  - claudeMdExcludes from user settings and the launch folder's project and local
    settings drop a matching file, and with it the files it imports

WHY --apply EXISTS (scar 2026-11-02, founder ruling "Option 2" on ASK-3689)
Client repos live inside the consulting instance. Because ancestors load past the
git root, a client session loaded consulting's rules AND its own byte-identical
copy of 41 of them, which put 8 client instances at or over the limit. --apply
writes into the user settings file one exclude per nested rules file that is
byte-identical to the same file in an ancestor's rules folder, so exactly one copy
loads. A copy that DIFFERS is never excluded: when a sync leaves the parent stale,
both load rather than the stale one alone. Entries under a registered instance's
.claude/rules/ are owned by this script and rewritten; every other entry is kept.

WHAT IT SEES / DOES NOT SEE
Sees: the always-on set at session start, for each registered instance root used
as the launch folder. Does not see: path-scoped rules a session triggers later; a
launch folder below an instance root (a .wt-* worktree inside an instance loads
its own copy as well); a different model's limit; managed-policy files. Exclude
globs are matched with fnmatch after brace expansion, an approximation of
Claude Code's picomatch; the entries --apply writes are plain absolute paths,
which both match exactly. Whether Claude Code drops project or local scope
excludes for an untrusted folder is not modelled; --apply writes user scope only.

Exit: 0 when every instance is under the limit and no owned exclude is stale,
2 otherwise (and 2 when --apply refuses to touch an unreadable settings file).

prompt-only-enforcement-skip: THIS FILE IS THE DETERMINISTIC BLOCKER (exit 2;
`kipi check` wiring tracked as ASK-3692), pinned by test_instruction_chars_audit.py. The guard matched the
words above that describe the gate this file already is.
"""
import argparse
import fnmatch
import json
import os
import re
import sys
import tempfile
from pathlib import Path

QROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
PROJECT_ROOT = os.path.normpath(os.path.join(QROOT, ".."))

LIMIT = 150_000      # Claude Code 2.1.316, current model: "150.0k-char total limit"
WARN_AT = 140_000    # printed as WARN, never fails
IMPORT_DEPTH = 5     # Claude Code follows imports five hops deep

IMPORT_RE = re.compile(r"(?:^|\s)@((?:~|\.{1,2}|/)?[\w./~-]+\.md)\b")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
INLINE_CODE_RE = re.compile(r"`[^`]*`")
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
PATHS_KEY_RE = re.compile(r"^paths\s*:", re.M)


def read(p):
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def frontmatter_split(text):
    """(frontmatter, body). There is frontmatter only when the file opens with ---."""
    if not text.startswith("---"):
        return "", text
    end = text.find("\n---", 3)
    if end < 0:
        return "", text
    nl = text.find("\n", end + 1)
    return text[3:end], (text[nl + 1:] if nl >= 0 else "")


def counted_chars(text):
    return len(HTML_COMMENT_RE.sub("", frontmatter_split(text)[1]))


def is_path_scoped(p):
    return bool(PATHS_KEY_RE.search(frontmatter_split(read(p))[0]))


def imports_of(p):
    out, in_fence = [], False
    for line in read(p).splitlines():
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for m in IMPORT_RE.finditer(INLINE_CODE_RE.sub("", line)):
            ref = m.group(1)
            if ref.startswith("~"):
                out.append(Path(os.path.expanduser(ref)))
            elif ref.startswith("/"):
                out.append(Path(ref))
            else:
                out.append(p.parent / ref)
    return out


def expand_braces(pat):
    m = re.search(r"\{([^{}]*,[^{}]*)\}", pat)
    if not m:
        return [pat]
    out = []
    for alt in m.group(1).split(","):
        out.extend(expand_braces(pat[:m.start()] + alt + pat[m.end():]))
    return out


def compile_patterns(patterns):
    out = []
    for pat in patterns:
        out.extend(expand_braces(os.path.expanduser(pat)))
    return out


def excluded(path, compiled):
    s = str(path)
    return any(s == e or fnmatch.fnmatchcase(s, e) for e in compiled)


def load_json_dict(p):
    try:
        with open(p, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def exclude_patterns(user_dir, launch):
    pats = []
    for f in (user_dir / "settings.json",
              launch / ".claude" / "settings.json",
              launch / ".claude" / "settings.local.json"):
        v = load_json_dict(f).get("claudeMdExcludes")
        if isinstance(v, list):
            pats.extend(x for x in v if isinstance(x, str))
    return pats


def rules_files(d):
    r = d / ".claude" / "rules"
    return sorted(r.rglob("*.md")) if r.is_dir() else []


def collect(launch, user_dir, compiled):
    """The files Claude Code loads at session start for this launch folder, in order."""
    seen, files = set(), []

    def add(p, depth=0):
        p = Path(os.path.abspath(p))
        if p in seen or not p.is_file() or excluded(p, compiled):
            return
        seen.add(p)
        files.append(p)
        if depth < IMPORT_DEPTH:
            for q in imports_of(p):
                add(q, depth + 1)

    def add_rules(d):
        if d.is_dir():
            for r in sorted(d.rglob("*.md")):
                if not is_path_scoped(r):
                    add(r)

    add(user_dir / "CLAUDE.md")
    add_rules(user_dir / "rules")
    chain, d = [], launch
    while d != d.parent:
        chain.append(d)
        d = d.parent
    for d in reversed(chain):
        for name in ("CLAUDE.md", ".claude/CLAUDE.md", "CLAUDE.local.md"):
            add(d / name)
        add_rules(d / ".claude" / "rules")
    return files


def duplicate_copies(inst, hand_excludes=()):
    """Always-on rules files in `inst` byte-identical to an ancestor copy that still loads.

    Path-scoped files are skipped: they cost nothing at session start, and excluding
    the nested copy can suppress its on-demand load, because the parent copy's globs
    need not match files in the nested repo (PR 599 review, round 2: 25 of 41 were
    path-scoped, security.md among them). An ancestor copy that a hand-written
    exclude already drops does not count as loading, or --apply would remove the
    last copy.
    """
    out = []
    base = inst / ".claude" / "rules"
    for f in rules_files(inst):
        if is_path_scoped(f):
            continue
        if loading_twin(inst, f.relative_to(base), f.read_bytes(), hand_excludes):
            out.append(f)
    return out


def loading_twin(inst, rel, data, hand_excludes):
    for a in inst.parents:
        twin = a / ".claude" / "rules" / rel
        if twin.is_file() and not excluded(twin, hand_excludes) and twin.read_bytes() == data:
            return twin
    return None


def hand_written(entries, roots):
    """Compiled user excludes this script does not own."""
    return compile_patterns([e for e in entries if isinstance(e, str) and not owned(e, roots)])


def load_registry(path):
    data = load_json_dict(path)
    insts = data.get("instances", [])
    out = []
    for i in insts if isinstance(insts, list) else []:
        if isinstance(i, dict) and i.get("path"):
            p = Path(os.path.abspath(os.path.expanduser(i["path"])))
            out.append((str(i.get("name") or i["path"]), p))
    return out


def owned(entry, roots):
    return any(entry.startswith(str(r) + "/.claude/rules/") for r in roots)


def nested_roots(roots):
    """Registered instances inside another registered instance: the only ones --apply writes for.

    Ownership is limited to these. Owning every registered instance's rules path
    would let --apply delete a hand-written exclude of a PARENT's rule (found by
    test_parent_copy_dropped_by_hand_keeps_the_child_copy, round 2).
    """
    return [r for r in roots if any(o != r and o in r.parents for o in roots)]


def measure(inst, user_dir):
    files = collect(inst, user_dir, compile_patterns(exclude_patterns(user_dir, inst)))
    return files, sum(counted_chars(read(f)) for f in files)


def do_check(registry, user_dir, limit, as_json):
    rc, rows = 0, []
    user_excl = load_json_dict(user_dir / "settings.json").get("claudeMdExcludes")
    user_excl = [e for e in user_excl if isinstance(e, str)] if isinstance(user_excl, list) else []
    nested = nested_roots([p for _, p in registry])
    hand = hand_written(user_excl, nested)
    for name, inst in registry:
        if not inst.is_dir():
            rows.append({"name": name, "status": "SKIP", "reason": "path missing", "path": str(inst)})
            continue
        files, total = measure(inst, user_dir)
        status = "OVER" if total > limit else ("WARN" if total > WARN_AT else "OK")
        is_nested = inst in nested
        dupes = {str(f) for f in duplicate_copies(inst, hand)} if is_nested else set()
        mine = [e for e in user_excl if is_nested and owned(e, [inst]) and Path(e).is_file()]
        stale = sorted(e for e in mine if e not in dupes)
        unexcluded = sorted(d for d in dupes if d not in set(mine))
        if status == "OVER" or stale:
            rc = 2
        rows.append({"name": name, "status": status, "chars": total, "files": len(files),
                     "stale_excludes": stale, "duplicates_not_excluded": len(unexcluded)})
    if as_json:
        print(json.dumps({"limit": limit, "rows": rows, "exit": rc}))
        return rc
    for r in rows:
        if r["status"] == "SKIP":
            print(f"SKIP  {'':>7} {'':>9}  {r['name']}  (path missing: {r['path']})")
            continue
        print(f"{r['status']:5} {r['chars'] / 1000:6.1f}k {r['files']:3d} files  {r['name']}")
        for e in r["stale_excludes"]:
            print(f"      STALE EXCLUDE: {e} has no identical, always-on parent copy that loads; "
                  "this rule may not load at all. Rerun --apply")
        if r["duplicates_not_excluded"]:
            print(f"      note: {r['duplicates_not_excluded']} rules file(s) also load from a parent folder")
    measured = [r for r in rows if r["status"] != "SKIP"]
    worst = max(measured, key=lambda r: r["chars"], default=None)
    if worst:
        print(f"instruction-chars-audit: {len(measured)} instance(s), worst {worst['chars'] / 1000:.1f}k "
              f"({worst['name']}), limit {limit / 1000:.1f}k")
    if rc:
        me = os.path.relpath(os.path.abspath(__file__), PROJECT_ROOT)
        print(f"RED: fix with `python3 {me} --apply`, then trim any instance still OVER", file=sys.stderr)
    return rc


def do_apply(registry, user_dir):
    settings = user_dir / "settings.json"
    if settings.exists():
        try:
            with open(settings, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError) as exc:
            print(f"REFUSED: {settings} did not parse ({exc}); left untouched", file=sys.stderr)
            return 2
        if not isinstance(data, dict):
            print(f"REFUSED: {settings} is not a JSON object; left untouched", file=sys.stderr)
            return 2
    else:
        data = {}
    current = data.get("claudeMdExcludes", [])
    if not isinstance(current, list):
        print(f"REFUSED: claudeMdExcludes in {settings} is not a list; left untouched", file=sys.stderr)
        return 2
    roots = nested_roots([p for _, p in registry])
    keep = [e for e in current if not (isinstance(e, str) and owned(e, roots))]
    hand = hand_written(keep, roots)
    want = sorted({str(f) for inst in roots if inst.is_dir() for f in duplicate_copies(inst, hand)})
    # Entries under a registered instance's .claude/rules/ are owned and rewritten,
    # so every one that goes is named: a hand-written one must not vanish silently.
    dropped = [e for e in current if isinstance(e, str) and owned(e, roots) and e not in want]
    for e in dropped:
        print(f"removed exclude: {e}")
    new = keep + want
    if new == current:
        print(f"claudeMdExcludes unchanged: {len(want)} nested duplicate(s) excluded")
        return 0
    data["claudeMdExcludes"] = new
    write_settings(settings, data)
    print(f"claudeMdExcludes updated: {len(want)} nested duplicate(s) excluded, {len(dropped)} removed")
    return 0


def write_settings(settings, data):
    """Atomic write that keeps a symlinked settings file a symlink (dotfiles repos)."""
    target = settings.resolve() if settings.is_symlink() else settings
    mode = target.stat().st_mode & 0o777 if target.exists() else 0o644
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), prefix=".settings.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        os.chmod(tmp, mode)
        os.replace(tmp, target)
    except OSError:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--registry", default=os.path.join(PROJECT_ROOT, "instance-registry.json"))
    ap.add_argument("--user-dir", default=os.path.expanduser("~/.claude"))
    ap.add_argument("--limit", type=int, default=LIMIT)
    ap.add_argument("--apply", action="store_true", help="write the nested-duplicate excludes to user settings")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if not os.path.isfile(a.registry):
        print(f"SKIP: no instance registry at {a.registry}; this gate runs from the skeleton")
        return 0
    registry = load_registry(a.registry)
    user_dir = Path(os.path.abspath(a.user_dir))
    if a.apply:
        return do_apply(registry, user_dir)
    return do_check(registry, user_dir, a.limit, a.json)


if __name__ == "__main__":
    sys.exit(main())
