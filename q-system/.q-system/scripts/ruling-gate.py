#!/usr/bin/env python3
"""ruling-gate.py: every founder ruling names the code that enforces it.

ASK-4382, RULE-2026-11-10-RULING. Founder, 2026-11-10, verbatim: "What R that
represents a decision I made. Must be enforced in code. That's a Kippy level
decision". It extends RULE-2026-11-08-CODE (rule_gate.py, rule FILES) to the
other place founder decisions are written down: ruling lines in a case.

THE RECORD. A founder ruling is a line in a case's canonical/scope.md:

    RULING: R-NN | YYYY-MM-DD | <type> | "<verbatim>"

and, anywhere in the same file, keyed by the id, exactly one of:

    ENFORCED-BY: R-NN | <path>[, <path> ...]
    UNENFORCED: R-NN | <why it cannot be code today, 20+ characters>

WHY COMPANION LINES AND NOT A FIELD ON THE RULING LINE. The investigation
instance's ruling reader (case_gates.RULING_RE) is anchored on the closing
quote. A field appended after it makes the line malformed, and a malformed
ruling counts as ABSENT there: a collection ruling drops out of the tool-map
citation check and an exclusion citing it is refused. Measured 2026-11-10 by
running that parser on both shapes. A per-case sidecar would also parse, but it
is a second file and a second writer to keep in step with the line it backs.
A companion line starts with neither RULING: nor GATE-OVERRIDE:, so that reader
skips it, and it sits next to the decision.

THE ID AN ENFORCER MUST CONTAIN is case-qualified: <case dir>:R-NN (the case dir
is the folder that holds canonical/). Ruling ids restart at R-01 in every case,
so a bare "R-03" somewhere proves nothing about THIS case's R-03.

An enforcer resolves when it exists, is code (.py .sh .js .mjs .ts), contains
the case-qualified id, and is not a temp-space stub outside the case's repo. At
least one named enforcer must be WIRED: a git-tracked test file, a hook command
in the repo's or the user's .claude/settings.json, or a LaunchAgent plist.

Modes:
  PreToolUse Write|Edit|MultiEdit: refuses a scope.md edit that adds or changes
      a ruling (its RULING line or a companion line) that does not resolve, or
      that drops a ruling's declaration. Untouched rulings are not judged here:
      an enforcer that drifts later is the report's to raise, and blocking an
      unrelated scope edit on it would stall a case session without fixing it.
  PreToolUse Bash: snapshots the rulings of the scope files in the cwd's repo.
  PostToolUse Bash: diffs against that snapshot. A shell write that added or
      changed a ruling with no resolvable enforcer is reverted (prior lines put
      back, new lines removed), the removed text is saved under quarantine/,
      and the session is told. Judged by EFFECT, not by reading command text:
      rule_gate v1 matched shell text and a red-team pass beat it 15 ways.
  --report: the scheduled check. Lists every ruling as ENFORCED, UNENFORCED,
      DEBT (grandfathered, nothing declared) or FAIL, writes the listing, and
      files one alert through slack-notify.sh (Sana's Linear triage) when the
      set of open rulings changes.
  --check FILE: every ruling in one file; exit 1 on any FAIL.
  --init: writes the grandfather baseline once; refuses when it exists.

GRANDFATHERING. ../ruling-gate-baseline.json holds one hash per ruling line that
existed when this gate shipped: sha256 of the case dir plus the
whitespace-normalised line, nothing else, because this skeleton is public and
rulings are client work. A grandfathered ruling with nothing declared is DEBT.
Changing its text makes it new. Dropping a declaration is refused. The baseline
is never rewritten (test_ruling_gate.py pins its digest), so debt only shrinks.

LIMIT, stated: the gate proves LINKAGE (the ruling names wired code that names
the ruling). It does not prove the code enforces what the ruling says; review
does that. A session whose project carries no copy of this hook, and a shell
write to a scope file outside the cwd's repo, are seen only by --report. The
hook and baseline are user-writable files, like every repo hook; the root-owned
lock (lock-gate.sh) is what would close that, and it is the founder's sudo.
"""
import argparse
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
import time

RULE_ID = "RULE-2026-11-10-RULING"
HERE = os.path.dirname(os.path.realpath(__file__))
BASELINE = os.path.join(os.path.dirname(HERE), "ruling-gate-baseline.json")
NOTIFY = os.path.join(HERE, "slack-notify.sh")
CODE_EXT = (".py", ".sh", ".js", ".mjs", ".ts")
TEMP_PREFIXES = ("/tmp/", "/private/tmp/", "/var/folders/", "/private/var/folders/")
PRUNE = {".git", "node_modules", ".venv", "venv", "__pycache__", "evidence", "dist", "build", ".next"}
MAX_DEPTH = 8
MIN_REASON = 20
RULING_RX = re.compile(r"^\s*RULING:\s*(R-\d{2,})(?![0-9A-Za-z-])")
COMP_RX = re.compile(r"^\s*(ENFORCED-BY|UNENFORCED):\s*(R-\d{2,})\s*\|\s*(.*?)\s*$")
# What reads as an ATTEMPT at a ruling line, so a near miss is refused instead of
# silently skipped. RULING: is case-sensitive, as the instance reader is (a prose
# line "Ruling: ..." is not a ruling to it). The companions are matched loosely
# ("Enforced by: R-05 x.py") because that is the rule-file spelling people reach for.
LOOSE_RX = re.compile(r"^\s*(?:RULING\s*:|(?i:enforced[- ]by|unenforced)\s*:\s*R-\d)")
HOWTO = ("Under the ruling add 'ENFORCED-BY: R-NN | <code path>' naming wired code (a git-tracked "
         "test, a settings.json hook, or a LaunchAgent plist) that contains '<case dir>:R-NN', or "
         "'UNENFORCED: R-NN | <reason>' when it cannot be code today; that one is listed and alerted "
         f"as debt ({RULE_ID}, ASK-4382).")


def home():
    return os.path.expanduser("~")


def state_dir():
    return os.path.join(home(), ".local", "state", "kipi", "ruling-gate")


def read_text(path):
    with open(path, "rb") as fh:
        return fh.read().decode("utf-8", errors="replace")


def norm_line(s):
    return " ".join((s or "").split())


def is_scope_path(path):
    p = os.path.normpath(os.path.abspath(os.path.expanduser(path or "")))
    return os.path.basename(p) == "scope.md" and os.path.basename(os.path.dirname(p)) == "canonical"


def case_of(path):
    return os.path.basename(os.path.dirname(os.path.dirname(os.path.abspath(path))))


def repo_root(path):
    d = os.path.dirname(os.path.abspath(path)) if not os.path.isdir(path) else os.path.abspath(path)
    while d and d != os.path.dirname(d):
        if os.path.exists(os.path.join(d, ".git")):
            return d
        d = os.path.dirname(d)
    return ""


def line_hash(case, line):
    return hashlib.sha256((case + "\n" + norm_line(line)).encode()).hexdigest()[:16]


def load_baseline(path=None):
    try:
        return set(json.load(open(path or BASELINE)).get("hashes") or [])
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------- parsing
def parse(text):
    """({rid: entry}, [malformed lines]). An entry keeps normalised lines for
    comparison ('raw') and the original lines for a restore ('lines')."""
    out, bad = {}, []
    for line in (text or "").splitlines():
        m = RULING_RX.match(line)
        c = None if m else COMP_RX.match(line)
        if m or c:
            rid = m.group(1) if m else c.group(2)
            e = out.setdefault(rid, {"ruling": [], "ENFORCED-BY": [], "UNENFORCED": [], "raw": [], "lines": []})
            if m:
                e["ruling"].append(norm_line(line))
            else:
                e[c.group(1)].append(c.group(3))
            e["raw"].append(norm_line(line))
            e["lines"].append(line)
        elif LOOSE_RX.match(line):
            bad.append(norm_line(line))
    return out, bad


def line_rid(line):
    m = RULING_RX.match(line) or COMP_RX.match(line)
    if not m:
        return None
    return m.group(1) if m.re is RULING_RX else m.group(2)


# ---------------------------------------------------------------- resolving
def settings_commands(root):
    files = [os.path.join(home(), ".claude", "settings.json")]
    if root:
        files.insert(0, os.path.join(root, ".claude", "settings.json"))
    cmds = []
    for f in files:
        try:
            s = json.load(open(f))
        except (OSError, ValueError):
            continue
        for rows in (s.get("hooks") or {}).values():
            for r in rows or []:
                for hk in (r or {}).get("hooks", []) or []:
                    cmds.append(hk.get("command") or "")
    return cmds


def is_wired(fp, root):
    base = os.path.basename(fp).lower()
    if base.startswith("test") or "/test/" in fp or "/tests/" in fp:
        r = subprocess.run(["git", "-C", os.path.dirname(fp), "ls-files", "--error-unmatch", fp],
                           capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            return True
    h = home()
    forms = {fp}
    if len(h) > 1 and fp.startswith(h + os.sep):
        forms |= {"~" + fp[len(h):], "$HOME" + fp[len(h):]}
    if root:
        rel = os.path.relpath(fp, os.path.realpath(root))
        if not rel.startswith(".."):
            forms |= {"$CLAUDE_PROJECT_DIR/" + rel, "${CLAUDE_PROJECT_DIR}/" + rel}
    if any(f in c for c in settings_commands(root) for f in forms):
        return True
    for pl in glob.glob(os.path.join(h, "Library", "LaunchAgents", "*.plist")):
        try:
            if any(f in read_text(pl) for f in forms):
                return True
        except OSError:
            pass
    return False


def resolve(key, raw, root):
    paths = [p.strip(" `'\"") for p in re.split(r"[,;]", raw or "")]
    paths = [p for p in paths if p]
    if not paths:
        return f"{key}: ENFORCED-BY names no file"
    root_r = os.path.realpath(root) if root else ""
    id_rx = re.compile(r"(?<![A-Za-z0-9_-])" + re.escape(key) + r"(?![0-9])")
    any_wired = False
    for p in paths:
        fp = os.path.expanduser(p.split()[0])
        if not os.path.isabs(fp):
            if not root:
                return f"{key}: enforcer {p} is relative and the scope file is in no git repo"
            fp = os.path.join(root, fp)
        fp = os.path.realpath(fp)
        inside = bool(root_r) and fp.startswith(root_r + os.sep)
        if fp.startswith(TEMP_PREFIXES) and not inside:
            return f"{key}: enforcer {p} is a temp-space file outside the case's repo"
        if not os.path.isfile(fp):
            return f"{key}: enforcer {p} does not exist"
        if not fp.endswith(CODE_EXT):
            return f"{key}: enforcer {p} is not code ({', '.join(CODE_EXT)})"
        if not id_rx.search(read_text(fp)):
            return f"{key}: enforcer {p} does not contain {key}"
        any_wired = any_wired or is_wired(fp, root)
    if not any_wired:
        return (f"{key}: no named enforcer is wired (a git-tracked test file, a hook command in "
                f".claude/settings.json, or a LaunchAgent plist)")
    return None


def classify(case, rid, e, baseline, root, before=None):
    """(status, detail): ENFORCED | UNENFORCED | DEBT | FAIL."""
    key = f"{case}:{rid}"
    if len(e["ruling"]) > 1:
        return "FAIL", f"{key}: {len(e['ruling'])} RULING lines share this id"
    enf, une = e["ENFORCED-BY"], e["UNENFORCED"]
    if enf and une:
        return "FAIL", f"{key}: has both ENFORCED-BY and UNENFORCED; keep one"
    if len(enf) > 1 or len(une) > 1:
        return "FAIL", f"{key}: more than one ENFORCED-BY or UNENFORCED line"
    if enf:
        why = resolve(key, enf[0], root)
        return ("FAIL", why) if why else ("ENFORCED", enf[0])
    if une:
        if len(une[0].strip()) < MIN_REASON:
            return "FAIL", f"{key}: UNENFORCED needs a reason of at least {MIN_REASON} characters"
        return "UNENFORCED", une[0]
    # Debt only shrinks: a ruling that had a declaration may not lose it.
    if before and (before.get("ENFORCED-BY") or before.get("UNENFORCED")):
        return "FAIL", f"{key}: this edit drops the ruling's ENFORCED-BY/UNENFORCED line"
    if line_hash(case, e["ruling"][0]) in (baseline or set()):
        return "DEBT", "grandfathered, nothing declared"
    return "FAIL", f"{key}: no ENFORCED-BY line (and it is not a grandfathered ruling)"


def touched(before, after):
    (b, bbad), (a, abad) = before, after
    rids = sorted(r for r in a if a[r]["ruling"] and a[r]["raw"] != (b.get(r) or {}).get("raw"))
    return rids, [x for x in abad if x not in bbad]


def judge_change(path, before_text, after_text, baseline):
    """Reasons the edit is refused, or []."""
    before, after = parse(before_text), parse(after_text)
    rids, new_bad = touched(before, after)
    case, root = case_of(path), repo_root(path)
    out = [f"{case}: a malformed ruling line: {b[:80]}" for b in new_bad]
    for rid in rids:
        st, why = classify(case, rid, after[0][rid], baseline, root, before[0].get(rid))
        if st == "FAIL":
            out.append(why)
    return out


# ---------------------------------------------------------------- scope files
def scope_files(roots):
    found, seen = {}, set()
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        base_depth = root.rstrip(os.sep).count(os.sep)
        for d, dirs, files in os.walk(root, followlinks=True):
            rd = os.path.realpath(d)
            if rd in seen:
                dirs[:] = []
                continue
            seen.add(rd)
            depth = d.rstrip(os.sep).count(os.sep) - base_depth
            # A folder holding its own .git is a SEPARATE repo (in the fleet, another
            # registered instance): never descend. The consulting root holds about ten,
            # and this walk runs on every Bash call.
            dirs[:] = [x for x in dirs if x not in PRUNE and depth < MAX_DEPTH
                       and not os.path.exists(os.path.join(d, x, ".git"))]
            if os.path.basename(d) == "canonical" and "scope.md" in files:
                f = os.path.join(d, "scope.md")
                found.setdefault(os.path.realpath(f), f)
    return sorted(found.values())


# ---------------------------------------------------------------- hook output
def deny(reason):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
          "permissionDecision": "deny", "permissionDecisionReason": "ruling-gate: " + reason}}))


def log(row):
    try:
        os.makedirs(state_dir(), exist_ok=True)
        with open(os.path.join(state_dir(), "ruling-gate.jsonl"), "a") as fh:
            fh.write(json.dumps(dict(row, ts=time.time())) + "\n")
    except OSError:
        pass


def after_edit(tool, tin, cur):
    if tool == "Write":
        return tin.get("content") or ""
    if tool == "Edit":
        old, new = tin.get("old_string") or "", tin.get("new_string") or ""
        return cur.replace(old, new) if tin.get("replace_all") else cur.replace(old, new, 1)
    if tool == "MultiEdit":
        for ed in tin.get("edits") or []:
            old, new = ed.get("old_string") or "", ed.get("new_string") or ""
            cur = cur.replace(old, new) if ed.get("replace_all") else cur.replace(old, new, 1)
        return cur
    return None


def snap_path(data):
    key = "%s-%s" % (data.get("session_id", "x"), data.get("tool_use_id", "x"))
    return os.path.join(state_dir(), "snap", re.sub(r"[^A-Za-z0-9_-]", "_", key) + ".json")


def hook_roots(data):
    roots = set()
    for c in (data.get("cwd"), os.environ.get("CLAUDE_PROJECT_DIR")):
        r = repo_root(c) if c and os.path.isdir(c) else ""
        if r:
            roots.add(r)
    return sorted(roots)


def pre_tool(data):
    tool = data.get("tool_name") or ""
    tin = data.get("tool_input") or {}
    if tool == "Bash":
        snap = {}
        for f in scope_files(hook_roots(data)):
            ents, bad = parse(read_text(f))
            snap[f] = {"entries": {r: {"raw": e["raw"], "lines": e["lines"], "ENFORCED-BY": e["ENFORCED-BY"],
                                       "UNENFORCED": e["UNENFORCED"], "ruling": e["ruling"]} for r, e in ents.items()},
                       "bad": bad}
        p = snap_path(data)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        # A Bash call another hook denies never reaches PostToolUse, so its snapshot
        # is never consumed. Drop any older than a day so the folder stays bounded.
        for old in glob.glob(os.path.join(os.path.dirname(p), "*.json")):
            try:
                if os.path.getmtime(old) < time.time() - 86400:
                    os.remove(old)
            except OSError:
                pass
        json.dump(snap, open(p, "w"))
        return 0
    if tool not in ("Write", "Edit", "MultiEdit"):
        return 0
    path = tin.get("file_path") or ""
    try:
        cur = read_text(path)
    except OSError:
        cur = ""
    if os.path.basename(path) == os.path.basename(BASELINE):
        if after_edit(tool, tin, cur) != cur:
            deny(f"{path} is the grandfather baseline; it never changes, so debt can only shrink.")
        return 0
    if not is_scope_path(path):
        return 0
    reasons = judge_change(path, cur, after_edit(tool, tin, cur), load_baseline() or set())
    log({"mode": "pre", "tool": tool, "path": path, "verdict": "deny" if reasons else "allow", "why": reasons})
    if reasons:
        deny(f"{path}: " + " | ".join(reasons[:4]) + ". " + HOWTO)
    return 0


def repair(path, before_entries, fails, bad_new):
    """Put back each failing ruling's prior lines (or drop them if it is new) and
    drop new malformed lines. Returns the removed text."""
    lines = read_text(path).splitlines(keepends=True)
    out, removed, done = [], [], set()
    for ln in lines:
        rid = line_rid(ln)
        if rid in fails:
            removed.append(ln)
            if rid not in done:
                done.add(rid)
                out.extend(x + "\n" for x in (before_entries.get(rid) or {}).get("lines", []))
            continue
        if LOOSE_RX.match(ln) and not rid and norm_line(ln) in bad_new:
            removed.append(ln)
            continue
        out.append(ln)
    tmp = path + ".ruling-gate.tmp"
    with open(tmp, "w") as fh:
        fh.write("".join(out))
    os.chmod(tmp, os.stat(path).st_mode & 0o7777)
    os.replace(tmp, path)
    return "".join(removed)


def quarantine(path, text):
    q = os.path.join(state_dir(), "quarantine")
    os.makedirs(q, exist_ok=True)
    f = os.path.join(q, "%s-%s.md" % (time.strftime("%Y%m%dT%H%M%S"), re.sub(r"[^A-Za-z0-9._-]", "_", path)[-80:]))
    with open(f, "w") as fh:
        fh.write(f"<!-- removed by ruling-gate from {path} at {time.ctime()} -->\n{text}")
    return f


def post_tool(data):
    if (data.get("tool_name") or "") != "Bash":
        return 0
    p = snap_path(data)
    try:
        snap = json.load(open(p))
    except (OSError, ValueError):
        return 0  # no before-state, no diff: the scheduled report sees it instead
    try:
        os.remove(p)
    except OSError:
        pass
    baseline = load_baseline() or set()
    reports = []
    for f in sorted(set(scope_files(hook_roots(data))) | set(snap)):
        if not os.path.isfile(f):
            continue
        prior = snap.get(f) or {"entries": {}, "bad": []}
        before = (prior["entries"], prior["bad"])
        after = parse(read_text(f))
        rids, bad_new = touched(before, after)
        case, root = case_of(f), repo_root(f)
        fails, why = set(), []
        for rid in rids:
            st, w = classify(case, rid, after[0][rid], baseline, root, prior["entries"].get(rid))
            if st == "FAIL":
                fails.add(rid)
                why.append(w)
        if not fails and not bad_new:
            continue
        removed = repair(f, prior["entries"], fails, set(bad_new))
        q = quarantine(f, removed)
        reports.append(f"{f}: reverted {len(fails)} ruling(s) and {len(bad_new)} malformed line(s) "
                       f"({'; '.join(why[:3]) or 'malformed'}) (saved: {q})")
    if reports:
        log({"mode": "post", "repaired": reports})
        print(json.dumps({"decision": "block", "reason": "ruling-gate reverted a shell write: "
                          + " || ".join(reports) + ". " + HOWTO}))
    return 0


# ---------------------------------------------------------------- CLI
def registry_roots(path):
    try:
        reg = json.load(open(path))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"ruling-gate: cannot read registry {path}: {exc}")
    items = reg.get("instances", reg) if isinstance(reg, dict) else reg
    items = items.values() if isinstance(items, dict) else items
    return [os.path.expanduser(i["path"]) for i in items if isinstance(i, dict) and i.get("path")]


def rows_for(files, baseline):
    rows = []
    for f in files:
        case, root = case_of(f), repo_root(f)
        ents, bad = parse(read_text(f))
        for rid in sorted(ents):
            if ents[rid]["ruling"]:
                st, why = classify(case, rid, ents[rid], baseline, root)
                rows.append((st, f"{case}:{rid}", f, why))
        rows.extend(("FAIL", f"{case}:?", f, "malformed ruling line: " + b[:80]) for b in bad)
    return rows


def report(args):
    baseline = load_baseline(args.baseline)
    if baseline is None:
        print(f"ruling-gate: baseline {args.baseline or BASELINE} is missing or unreadable", file=sys.stderr)
        return 1
    roots = list(args.roots) + (registry_roots(args.registry) if args.registry else [])
    rows = rows_for(scope_files(roots), baseline)
    count = {s: sum(1 for r in rows if r[0] == s) for s in ("ENFORCED", "UNENFORCED", "DEBT", "FAIL")}
    open_rows = sorted(r for r in rows if r[0] != "ENFORCED")
    lines = [f"# Ruling debt ({RULE_ID}, ASK-4382)", "",
             f"Taken {time.strftime('%Y-%m-%d %H:%M')} over {len(roots)} root(s). "
             + ", ".join(f"{k} {v}" for k, v in count.items()), ""]
    lines += [f"- {st} {key}: {why} ({f})" for st, key, f, why in open_rows]
    text = "\n".join(lines) + "\n"
    sys.stdout.write(text)
    out = args.out or os.path.join(state_dir(), "debt.md")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as fh:
        fh.write(text)
    if args.no_alert or not open_rows:
        return 0
    fp = hashlib.sha256("\n".join(f"{s} {k}" for s, k, _, _ in open_rows).encode()).hexdigest()
    stamp = os.path.join(state_dir(), "last-alert")
    try:
        if open(stamp).read().strip() == fp:
            return 0  # same open set as the last alert: state change only
    except OSError:
        pass
    msg = (f"ruling-gate: {len(open_rows)} founder ruling(s) have no resolvable code enforcer "
           f"({count['FAIL']} FAIL, {count['UNENFORCED']} UNENFORCED, {count['DEBT']} grandfathered DEBT). "
           f"First: {', '.join(k for _, k, _, _ in open_rows[:6])}. Listing: {out}. {HOWTO}")
    rc = subprocess.run(["bash", args.notify or NOTIFY, msg], capture_output=True, text=True, timeout=60).returncode
    if rc != 0:
        print(f"ruling-gate: the alert was not filed (notify exit {rc})", file=sys.stderr)
        return 1
    os.makedirs(state_dir(), exist_ok=True)
    with open(stamp, "w") as fh:
        fh.write(fp)
    return 0


def check(args):
    rows = rows_for([args.check], load_baseline(args.baseline) or set())
    for st, key, _, why in rows:
        print(f"{st} {key}: {why}")
    return 1 if any(r[0] == "FAIL" for r in rows) else 0


def init(args):
    out = args.out or BASELINE
    if os.path.exists(out):
        print(f"ruling-gate: {out} exists; the baseline is written once and never grows", file=sys.stderr)
        return 3
    roots = list(args.roots) + (registry_roots(args.registry) if args.registry else [])
    hashes = set()
    for f in scope_files(roots):
        case = case_of(f)
        for e in parse(read_text(f))[0].values():
            hashes.update(line_hash(case, ln) for ln in e["ruling"])
    with open(out, "w") as fh:
        json.dump({"rule": RULE_ID, "issue": "ASK-4382", "created": time.strftime("%Y-%m-%d"),
                   "note": "sha256(case dir + normalised RULING line)[:16]; hashes only, never text",
                   "count": len(hashes), "hashes": sorted(hashes)}, fh, indent=1)
        fh.write("\n")
    print(f"ruling-gate: baseline {len(hashes)} ruling(s) -> {out}")
    return 0


def main():
    if len(sys.argv) > 1:
        ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
        mode = ap.add_mutually_exclusive_group(required=True)
        mode.add_argument("--report", action="store_true")
        mode.add_argument("--check")
        mode.add_argument("--init", action="store_true")
        ap.add_argument("--registry")
        ap.add_argument("--baseline")
        ap.add_argument("--notify")
        ap.add_argument("--out")
        ap.add_argument("--no-alert", action="store_true")
        ap.add_argument("roots", nargs="*")
        args = ap.parse_args()
        return report(args) if args.report else check(args) if args.check else init(args)
    try:
        data = json.loads(sys.stdin.read())
    except ValueError:
        return 0
    ev = data.get("hook_event_name") or ""
    try:
        return post_tool(data) if ev == "PostToolUse" else pre_tool(data)
    except Exception as exc:
        log({"mode": ev, "error": repr(exc)})
        path = (data.get("tool_input") or {}).get("file_path") or ""
        if ev == "PreToolUse" and is_scope_path(path):
            deny(f"internal error on a scope file ({exc!r}); refused (fails closed).")
        return 0


if __name__ == "__main__":
    sys.exit(main())
