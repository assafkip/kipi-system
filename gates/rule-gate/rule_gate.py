#!/usr/bin/env python3
"""Rule gate v2: no rule may exist only in prose. RULE-2026-11-08-CODE.

Founder, 2026-11-08, verbatim: "There must be a standing rule that does not let
things that can and should be enforced in code just be enforced in prose - this
rule should itself be enforced in code and no prose can pass it." Then: "run an
adversarial test for this rule. it hqas failed on me too many time".

v1 matched shell command TEXT, and the red-team pass beat it 15 ways (relative
paths, variables, python, dd, ln, case, subdirectories, .MD, bad bytes, a reused
Rule-ID, a dummy enforcer, and edits to the gate's own files). v2 judges the
EFFECT: after every tool call it re-reads the rule files and repairs any rule
section that has no wired code enforcer, however it was written.

A rule section is a markdown section ('# ' or '## ' heading plus body) in a rule
file. Rule files, matched case-insensitively: any CLAUDE.md; any *.md at any
depth under a .claude/rules/ directory; *.md under ~/.claude/agents/; and every
file a rule file imports with @path. A section that is NEW or CHANGED (not in
the baseline taken at install) must carry:

    Rule-ID: <id>
    Enforced by: <path>[, <path> ...]

and each enforcer must exist, contain the Rule-ID, sit outside temp space, and be
code. At least one enforcer must be WIRED: a command in a settings.json hook, a
LaunchAgent plist, or a git-tracked test file in a repo. A Rule-ID belongs to one
section only.

Modes:
  PreToolUse (Write | Edit | MultiEdit | NotebookEdit | Bash):
    - refuses a rule-file write whose result has a failing section;
    - refuses writes to the gate's own files, the approvals store, the token
      minter and the destructive-op hook, and a settings.json edit that drops a
      protected hook entry;
    - refuses shell commands that mint approvals (kipi-approve, capability-token
      mint) or touch ~/.claude/approvals;
    - fails CLOSED on its own error for rule and protected paths.
  PostToolUse (every tool): scans the hot set (global rule files, the cwd and
    its ancestors, their imports). A failing section is repaired in place: a
    grandfathered section goes back to its baseline text, anything else is
    removed, and a symlinked rule file is unlinked. The removed text is saved
    under ~/.config/kipi/rule-gate/quarantine/. Missing protected hook entries
    are re-added to settings.json. Claude is told what was repaired.
  Stop / SubagentStop: the same scan, plus a report-only scan of ~/projects.
  --init writes the baseline (section texts) and the debt list. --scan reports.

Residual, stated: the gate, its baseline and the token minter are files this
user can write. Root-owning them (the founder's one-time sudo chown) is what
makes them tamper-proof against a same-user shell. Wiring proves the enforcer is
installed, not that it enforces the rule's meaning; review does that.
"""
import base64
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
import time

RULE_ID = "RULE-2026-11-08-CODE"
HOME = os.path.expanduser("~")
# Code and records live in LOCK (root-owned once the founder locks it); logs, quarantine
# and counters live in BASE, which stays writable.
GATE = os.path.realpath(__file__)
GATE_DIR = os.path.dirname(GATE)
# LOCK IS SELF-LOCATED (D33, lock-gate.sh). The root-owned copy at /opt/kipi-gate reads the
# records beside it, never the user-writable ones it was copied from. A copy with no
# records beside it (a test copy anywhere) keeps the legacy folder. No env override on
# purpose: a child `claude -p` an agent launches could set it and aim its gates at forged
# records.
_SELF_LOCK = os.path.dirname(GATE_DIR)
LOCK = (_SELF_LOCK if os.path.isfile(os.path.join(_SELF_LOCK, "baseline-v2.json"))
        else os.path.join(HOME, ".config", "kipi", "gate-locked"))
BASE = os.path.join(HOME, ".config", "kipi", "rule-gate")
BASELINE = os.path.join(LOCK, "baseline-v2.json")
DEBT = os.path.join(BASE, "debt.md")
LOG = os.path.join(BASE, "rule-gate.jsonl")
QUAR = os.path.join(BASE, "quarantine")
SETTINGS = os.path.join(HOME, ".claude", "settings.json")
# MANAGED SETTINGS (D33). Once locked, the gate entries live in Claude Code's managed
# settings, which no user settings file can override or drop. The path is a record beside
# LOCK so a sandbox lock names its own; the default is the macOS system path.
try:
    MANAGED = open(os.path.join(LOCK, "managed-settings-path")).read().strip()
except OSError:
    MANAGED = ""
MANAGED = MANAGED or "/Library/Application Support/ClaudeCode/managed-settings.json"
# MOVED GATES (D33): old realpath -> locked copy, written by lock-gate.sh. A rule written
# before the lock still names the old path; it is judged as the locked copy, so its
# enforcer stays wired (the Q6 scar: an unwired-looking gate rule gets reverted) and the
# Rule-ID must be in the root-owned text, not in the user-writable original.
try:
    MOVED = json.load(open(os.path.join(LOCK, "moved-gates.json")))
except (OSError, ValueError):
    MOVED = {}
APPROVALS = os.path.join(HOME, ".claude", "approvals")
PROTECTED = [GATE, os.path.join(GATE_DIR, "rule_gate.py"), BASELINE,
             os.path.join(HOME, ".config", "kipi", "handoff-gate", "hooks", "rule_gate.py"),
             os.path.join(HOME, ".claude", "bin", "capability-token.sh"),
             "/opt/homebrew/bin/kipi-approve", "/opt/homebrew/bin/capability-token.sh",
             os.path.join(HOME, ".claude", "hooks", "destructive-op-deny.sh")]
PROTECTED.extend([os.path.join(LOCK, "protected-hooks.json"), os.path.join(LOCK, "protected-manifest.json")])
PROTECTED_DIRS = [APPROVALS, QUAR, LOCK]
HOOK_MARKERS = ("handoff-gate/hooks/", "gate-locked/", "destructive-op-deny", "worktree-disk-floor",
                "kipi-gate/bin/run-gate.sh")
MAX_BLOCKS = 2
CODE_EXT = (".py", ".sh", ".js", ".mjs", ".ts")
TEMP_PREFIXES = ("/tmp/", "/private/tmp/", "/var/folders/", "/private/var/folders/")
ID_RX = re.compile(r"^\s*(?:[-*]\s*)?\**Rule-ID\**\s*:\s*\**\s*`?([A-Za-z0-9._-]+)`?", re.M | re.I)
ENF_RX = re.compile(r"^\s*(?:[-*]\s*)?\**Enforced by\**\s*:\s*\**\s*(.+)$", re.M | re.I)
IMPORT_RX = re.compile(r"(?:^|\s)@((?:~|\.{1,2}|/)[^\s`'\"]+)")
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next"}


# ---------------------------------------------------------------- matching
def norm(p):
    return os.path.normpath(os.path.expanduser(p or ""))


def is_rule_path(path):
    p = norm(path)
    low = p.lower()
    name = os.path.basename(low)
    if name == "claude.md":
        return True
    if not name.endswith(".md"):
        return False
    parts = low.split(os.sep)
    for i in range(len(parts) - 1):
        if parts[i] == ".claude" and i + 1 < len(parts) and parts[i + 1] == "rules":
            return True
    return low.startswith(os.path.join(HOME, ".claude", "agents").lower() + os.sep)


def is_protected(path):
    p = os.path.realpath(norm(path))
    if p in [os.path.realpath(x) for x in PROTECTED]:
        return True
    return any(p == os.path.realpath(d) or p.startswith(os.path.realpath(d) + os.sep) for d in PROTECTED_DIRS)


def read_text(path):
    with open(path, "rb") as fh:
        return fh.read().decode("utf-8", errors="replace")


# ---------------------------------------------------------------- sections
def sections(text):
    out, head, buf, in_code = [], "(preamble)", [], False
    for line in (text or "").splitlines():
        if line.strip().startswith(("```", "~~~")):
            in_code = not in_code
        if not in_code and re.match(r"^\s{0,3}#{1,2}(?!#)\s*\S", line):
            if buf or head != "(preamble)":
                out.append((head, "\n".join(buf)))
            head, buf = line.strip(), []
        else:
            buf.append(line)
    out.append((head, "\n".join(buf)))
    return [(h, b) for h, b in out if (h != "(preamble)" or b.strip())]


def shash(head, body):
    n = head.strip() + "\n" + "\n".join(l.rstrip() for l in body.strip().splitlines())
    return hashlib.sha256(n.encode()).hexdigest()[:16]


def load_baseline():
    try:
        return json.load(open(BASELINE)).get("sections", {})
    except (OSError, ValueError):
        return None


def baseline_text(path):
    """The file exactly as the baseline holds it, in section order, or "" if it was not there."""
    try:
        b = json.load(open(BASELINE))
    except (OSError, ValueError):
        return ""
    secs = b.get("sections", {})
    out = []
    for head, hx in b.get("files", {}).get(os.path.realpath(path), []):
        if hx not in secs:
            return ""
        h, body = secs[hx]
        out.append(((h + "\n") if h != "(preamble)" else "") + body)
    return ("\n".join(out).rstrip() + "\n") if out else ""


def baseline_file_sections(path):
    """{heading: body} this exact file held at install, for restoring a grandfathered edit."""
    try:
        b = json.load(open(BASELINE))
    except (OSError, ValueError):
        return {}
    secs = b.get("sections", {})
    out = {}
    for head, hx in b.get("files", {}).get(os.path.realpath(path), []):
        if hx in secs and head not in out:
            out[head] = secs[hx][1]
    return out


# ---------------------------------------------------------------- enforcers
def _settings_commands():
    cmds = []
    files = [SETTINGS, MANAGED] + glob.glob(os.path.join(HOME, "projects", "*", ".claude", "settings*.json"))
    for f in files:
        try:
            s = json.load(open(f))
        except (OSError, ValueError):
            continue
        for rows in (s.get("hooks") or {}).values():
            for r in rows or []:
                for hk in r.get("hooks", []) or []:
                    cmds.append(hk.get("command") or "")
    return cmds


def wired(fp):
    forms = {fp, fp.replace(HOME, "~"), fp.replace(HOME, "$HOME")}
    for c in _settings_commands():
        if any(f in c for f in forms):
            return True
    for pl in glob.glob(os.path.join(HOME, "Library", "LaunchAgents", "*.plist")):
        try:
            if any(f in read_text(pl) for f in forms):
                return True
        except OSError:
            pass
    if fp.startswith(os.path.join(HOME, "projects") + os.sep):
        base = os.path.basename(fp).lower()
        if base.startswith("test") or "/test/" in fp or "/tests/" in fp:
            r = subprocess.run(["git", "-C", os.path.dirname(fp), "ls-files", "--error-unmatch", fp],
                               capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                return True
    return False


def check_section(head, body, id_owner, here):
    m = ID_RX.search(body)
    if not m:
        return "no 'Rule-ID:' line"
    rid = m.group(1)
    owner = id_owner.get(rid)
    if owner and owner != here:
        return f"{rid}: Rule-ID already belongs to {owner[0]} :: {owner[1][:50]}"
    e = ENF_RX.search(body)
    if not e:
        return f"{rid}: no 'Enforced by:' line"
    paths = [p.strip(" `'\"*") for p in re.split(r"[,;]", e.group(1)) if p.strip(" `'\"*")]
    if not paths:
        return f"{rid}: 'Enforced by:' names no file"
    any_wired = False
    for p in paths:
        fp = os.path.realpath(norm(p.split()[0]))
        fp = MOVED.get(fp, fp)  # a gate moved under lock is judged as its locked copy (D33)
        if fp.startswith(TEMP_PREFIXES):
            return f"{rid}: enforcer {p} is in temp space"
        if not os.path.isfile(fp):
            return f"{rid}: enforcer {p} does not exist"
        if not fp.endswith(CODE_EXT):
            return f"{rid}: enforcer {p} is not code ({', '.join(CODE_EXT)})"
        if rid not in read_text(fp):
            return f"{rid}: enforcer {p} does not mention {rid}"
        any_wired = any_wired or wired(fp)
    if not any_wired:
        return (f"{rid}: no enforcer is wired (a settings.json hook command, a LaunchAgent "
                f"plist, or a git-tracked test file in a repo)")
    return None


def failing(path, text, baseline, id_owner):
    bad, seen_ids = [], {}
    for head, body in sections(text):
        if baseline is not None and shash(head, body) in baseline:
            continue
        m = ID_RX.search(body)
        if m:
            if m.group(1) in seen_ids:
                bad.append((head, f"{m.group(1)}: Rule-ID used twice in this file"))
                continue
            seen_ids[m.group(1)] = head
        why = check_section(head, body, id_owner, (os.path.realpath(path), head))
        if why:
            bad.append((head, why))
    return bad


# ---------------------------------------------------------------- the hot set
def imports_of(path, text, depth, acc):
    if depth <= 0:
        return
    for m in IMPORT_RX.finditer(text or ""):
        raw = m.group(1)
        tgt = norm(raw) if raw.startswith(("~", "/")) else norm(os.path.join(os.path.dirname(path), raw))
        if tgt in acc or not os.path.isfile(tgt):
            continue
        acc.add(tgt)
        try:
            imports_of(tgt, read_text(tgt), depth - 1, acc)
        except OSError:
            pass


def walk_rules_dir(d, acc):
    for root, dirs, files in os.walk(d, followlinks=False):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
        for f in files:
            if f.lower().endswith(".md"):
                acc.add(os.path.join(root, f))


def hot_set(cwd):
    acc = set()
    c = os.path.join(HOME, ".claude")
    for name in os.listdir(c) if os.path.isdir(c) else []:
        low = name.lower()
        full = os.path.join(c, name)
        if low == "claude.md":
            acc.add(full)
        elif low == "rules" and os.path.isdir(full):
            walk_rules_dir(full, acc)
        elif low == "agents" and os.path.isdir(full):
            walk_rules_dir(full, acc)
    d = norm(cwd) if cwd else None
    while d and d.startswith(HOME) and d != os.path.dirname(HOME):
        try:
            for name in os.listdir(d):
                low = name.lower()
                full = os.path.join(d, name)
                if low == "claude.md":
                    acc.add(full)
                elif low == ".claude" and os.path.isdir(full):
                    for sub in os.listdir(full):
                        if sub.lower() == "rules":
                            walk_rules_dir(os.path.join(full, sub), acc)
        except OSError:
            pass
        if d == HOME:
            break
        d = os.path.dirname(d)
    for f in list(acc):
        try:
            imports_of(f, read_text(f), 5, acc)
        except OSError:
            pass
    return sorted(acc)


def id_index(files, exclude=None):
    idx = {}
    for f in files:
        if exclude and os.path.realpath(f) == os.path.realpath(exclude):
            continue
        try:
            text = read_text(f)
        except OSError:
            continue
        for head, body in sections(text):
            m = ID_RX.search(body)
            if m and m.group(1) not in idx:
                idx[m.group(1)] = (os.path.realpath(f), head)
    return idx


# ---------------------------------------------------------------- output
def log(row):
    try:
        os.makedirs(BASE, exist_ok=True)
        with open(LOG, "a") as fh:
            fh.write(json.dumps(row) + "\n")
    except OSError:
        pass


def deny(reason):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
          "permissionDecision": "deny", "permissionDecisionReason": "rule-gate: " + reason}}))


HOWTO = ("A new or changed rule needs 'Rule-ID: <id>' (unique) and 'Enforced by: <path>' naming "
         "code that contains the id and is wired in (a settings.json hook, a LaunchAgent plist, "
         f"or a git-tracked test). Build and wire the enforcer first, then write the rule ({RULE_ID}). "
         "If it cannot be enforced in code, it does not go in a rule file.")


# ---------------------------------------------------------------- PreToolUse
def after_edit(tool, tin):
    path = tin.get("file_path") or tin.get("notebook_path") or ""
    try:
        cur = read_text(path)
    except OSError:
        cur = ""
    if tool == "Write":
        return path, tin.get("content") or ""
    if tool == "Edit":
        old, new = tin.get("old_string") or "", tin.get("new_string") or ""
        return path, (cur.replace(old, new) if tin.get("replace_all") else cur.replace(old, new, 1))
    if tool == "MultiEdit":
        for ed in tin.get("edits") or []:
            old, new = ed.get("old_string") or "", ed.get("new_string") or ""
            cur = cur.replace(old, new) if ed.get("replace_all") else cur.replace(old, new, 1)
        return path, cur
    return path, None


def protected_pairs(text):
    """{(event, command)} of protected hook entries, or None if the JSON does not parse.
    Per event: the same command sits on several events, so a set of commands alone
    cannot see one entry removed (red-team case P8a)."""
    try:
        s = json.loads(text)
    except ValueError:
        return None
    out = set()
    for ev, rows in (s.get("hooks") or {}).items():
        for r in rows or []:
            for hk in r.get("hooks", []) or []:
                c = hk.get("command") or ""
                if any(m in c for m in HOOK_MARKERS):
                    out.add((ev, c))
    return out


def protected_commands(text):
    try:
        s = json.loads(text)
    except ValueError:
        return None
    out = set()
    for rows in (s.get("hooks") or {}).values():
        for r in rows or []:
            for hk in r.get("hooks", []) or []:
                c = hk.get("command") or ""
                if any(m in c for m in HOOK_MARKERS):
                    out.add(c)
    return out


def managed_pairs():
    """(event, command) gate pairs that managed settings carry; empty with no managed file."""
    try:
        return protected_pairs(read_text(MANAGED)) or set()
    except OSError:
        return set()


MINT_RX = re.compile(r"kipi-approve|capability-token(?:\.sh)?\b[^\n;|&]*\bmint\b|/\.claude/approvals|\bapprovals/[0-9a-f]{8,}", re.I)


def mark_pre(data):
    try:
        os.makedirs(os.path.join(BASE, "state"), exist_ok=True)
        key = re.sub(r"[^A-Za-z0-9_-]", "_", str(data.get("session_id", "x")))
        open(os.path.join(BASE, "state", key + ".pre"), "w").write(str(time.time()))
    except OSError:
        pass


def agent_tokens(data):
    """Approval tokens created since this session's last PreToolUse were made inside a
    tool call, so by an agent; the founder mints them in their own shell."""
    key = re.sub(r"[^A-Za-z0-9_-]", "_", str(data.get("session_id", "x")))
    try:
        since = float(open(os.path.join(BASE, "state", key + ".pre")).read().strip())
    except (OSError, ValueError):
        return None
    removed = []
    for t in glob.glob(os.path.join(APPROVALS, "*")):
        try:
            if os.path.getmtime(t) >= since - 1:
                os.remove(t)
                removed.append(os.path.basename(t))
        except OSError:
            pass
    return ("an approval token created during this tool call was removed (only the founder "
            "mints approvals, in their own shell): " + ", ".join(removed)) if removed else None


def pre_tool(data):
    mark_pre(data)
    tool = data.get("tool_name") or ""
    tin = data.get("tool_input") or {}
    if tool == "Bash":
        cmd = tin.get("command") or ""
        if MINT_RX.search(cmd):
            log({"ts": time.time(), "mode": "pre", "verdict": "deny-mint", "cmd": cmd[:200]})
            deny("approvals are minted by the founder in their own shell (kipi-approve), never by an "
                 "agent, and the approvals store is not an agent's to touch.")
        return 0
    if tool not in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        return 0
    path = tin.get("file_path") or tin.get("notebook_path") or ""
    if is_protected(path):
        log({"ts": time.time(), "mode": "pre", "verdict": "deny-protected", "path": path})
        deny(f"{path} is part of the rule gate or the approval chain; it changes only with the "
             f"founder's own hand, outside an agent session.")
        return 0
    if os.path.realpath(norm(path)) == os.path.realpath(SETTINGS):
        _, text = after_edit(tool, tin)
        after = protected_pairs(text or "")
        try:
            want = {(r["event"], r["command"]) for r in json.load(open(os.path.join(LOCK, "protected-hooks.json")))}
        except (OSError, ValueError):
            want = protected_pairs(read_text(SETTINGS)) or set()
        # An entry managed settings already carries is not this file's to keep (D33).
        want -= managed_pairs()
        if after is None or not want <= after:
            log({"ts": time.time(), "mode": "pre", "verdict": "deny-settings", "path": path})
            deny("this settings.json edit removes or breaks a protected hook entry (the rule gate, "
                 "the handoff and resource gates, or the destructive-op hook).")
        return 0
    if not is_rule_path(path) and os.path.realpath(norm(path)) not in [
            os.path.realpath(x) for x in hot_set(data.get("cwd"))]:
        return 0
    _, text = after_edit(tool, tin)
    if text is None:
        deny(f"{path}: cannot compute the edited rule file; refused (fails closed).")
        return 0
    bad = failing(path, text, load_baseline(), id_index(hot_set(data.get("cwd")), exclude=path))
    log({"ts": time.time(), "mode": "pre", "tool": tool, "path": path,
         "verdict": "deny" if bad else "allow", "failing": [b[1] for b in bad]})
    if bad:
        deny(f"{path}: {len(bad)} rule section(s) with no wired code enforcer: "
             + " | ".join(f"{h[:50]}: {w}" for h, w in bad[:4]) + ". " + HOWTO)
    return 0


# ---------------------------------------------------------------- repair
def quarantine(path, removed):
    os.makedirs(QUAR, exist_ok=True)
    q = os.path.join(QUAR, "%s-%s.md" % (time.strftime("%Y%m%dT%H%M%S"), re.sub(r"[^A-Za-z0-9._-]", "_", path)[-80:]))
    with open(q, "w") as fh:
        fh.write(f"<!-- removed by rule_gate from {path} at {time.ctime()} -->\n" + removed)
    return q


def repair_file(path, baseline, id_owner):
    """Returns a one-line report if the file was repaired, else None."""
    if os.path.islink(path):
        try:
            text = read_text(path)
        except OSError:
            text = ""
        # A symlinked rule file is judged by its target's content. Failing, the LINK is
        # removed and the target is never written: it may live in a repo or elsewhere.
        if failing(path, text, baseline, id_owner):
            q = quarantine(path, f"symlink -> {os.readlink(path)}\n\n{text}")
            os.unlink(path)
            return f"{path}: a symlinked rule file with no wired enforcer was removed (saved: {q})"
        return None
    try:
        text = read_text(path)
    except OSError:
        return None
    bad = failing(path, text, baseline, id_owner)
    if not bad:
        return None
    by_heading = baseline_file_sections(path)
    bad_heads = {h for h, _ in bad}
    out, removed = [], []
    for head, body in sections(text):
        if head in bad_heads and not (baseline is not None and shash(head, body) in baseline):
            removed.append((head + "\n" + body) if head != "(preamble)" else body)
            if head in by_heading:
                out.append((head, by_heading[head]))
            continue
        out.append((head, body))
    new = "\n".join(((h + "\n") if h != "(preamble)" else "") + b for h, b in out).rstrip() + "\n"
    q = quarantine(path, "\n\n".join(removed))
    if not new.strip():
        restored = baseline_text(path)
        if restored:
            with open(path, "w") as fh:
                fh.write(restored)
            return (f"{path}: every section failed, so the file was restored to its baseline "
                    f"text, never deleted (the replaced text is saved: {q})")
        os.remove(path)
        return f"{path}: a new rule file with no enforced section was removed (saved: {q})"
    with open(path, "w") as fh:
        fh.write(new)
    return (f"{path}: {len(removed)} section(s) with no wired enforcer were reverted or removed "
            f"({'; '.join(w for _, w in bad[:3])}) (saved: {q})")


def heal_settings():
    try:
        cur = json.load(open(SETTINGS))
    except (OSError, ValueError):
        return None
    try:
        want = json.load(open(os.path.join(LOCK, "protected-hooks.json")))
    except (OSError, ValueError):
        return None
    hooks = cur.setdefault("hooks", {})
    have = {(ev, hk.get("command")) for ev, rows in hooks.items() for r in rows or [] for hk in r.get("hooks", []) or []}
    # Managed settings already run these (D33); a second copy here would run each gate
    # twice, and two repair passes on one file is two writers.
    have |= managed_pairs()
    added = 0
    for row in want:
        if (row["event"], row["command"]) in have:
            continue
        entry = {"hooks": [{"type": "command", "command": row["command"], "timeout": row.get("timeout", 30)}]}
        if row.get("matcher"):
            entry["matcher"] = row["matcher"]
        hooks.setdefault(row["event"], []).append(entry)
        added += 1
    if not added:
        return None
    tmp = SETTINGS + ".rulegate.tmp"
    json.dump(cur, open(tmp, "w"), indent=2)
    os.replace(tmp, SETTINGS)
    return f"{SETTINGS}: {added} protected hook entr{'y' if added == 1 else 'ies'} restored"


def tamper_report():
    """Protected files are compared with the manifest taken at install. A same-user shell
    can still rewrite them, so this reports (it cannot restore); root ownership closes it."""
    try:
        man = json.load(open(os.path.join(LOCK, "protected-manifest.json")))
    except (OSError, ValueError):
        return None
    changed = []
    for path, digest in man.items():
        try:
            cur = hashlib.sha256(open(path, "rb").read()).hexdigest()
        except OSError:
            cur = "missing"
        if cur != digest:
            changed.append(path)
    if not changed:
        return None
    return ("TAMPER: protected file(s) changed since install with no founder approval: "
            + ", ".join(changed))


def post_tool(data):
    baseline = load_baseline()
    if baseline is None:
        # NO BASELINE, NO REPAIR (2026-11-08 13:22 scar): without it every grandfathered
        # section looks new, and a repair pass removed 18 real rule files. Judge nothing.
        log({"ts": time.time(), "mode": "post", "verdict": "no-baseline-no-repair", "baseline": BASELINE})
        return 0
    files = hot_set(data.get("cwd"))
    reports = []
    # SETTINGS FIRST (2026-11-08 attack-suite case Q6): with the gate's hook entries
    # stripped, every enforcer looked unwired, so the repair pass reverted the gate's
    # own rule before settings were healed. Restore the wiring, then judge rules.
    s = heal_settings()
    if s:
        reports.append(s)
    for f in files:
        r = repair_file(f, baseline, id_index(files, exclude=f))
        if r:
            reports.append(r)
    t = tamper_report()
    if t:
        reports.append(t)
    a = agent_tokens(data)
    if a:
        reports.append(a)
    if not reports:
        return 0
    log({"ts": time.time(), "mode": "post", "tool": data.get("tool_name"), "repaired": reports})
    print(json.dumps({"decision": "block", "reason": "rule-gate repaired rule files after this tool call: "
                      + " || ".join(reports) + ". " + HOWTO}))
    return 0


# ---------------------------------------------------------------- Stop
def projects_files():
    acc = set()
    root = os.path.join(HOME, "projects")
    for d, dirs, files in os.walk(root):
        depth = d[len(root):].count(os.sep)
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS and depth < 4]
        for f in files:
            full = os.path.join(d, f)
            if is_rule_path(full):
                acc.add(full)
    return sorted(acc)


def stop(data):
    post_tool(data)  # repairs and reports the hot set on its own channel
    baseline = load_baseline()
    if baseline is None:
        return 0
    files = projects_files()
    bad = []
    for f in files:
        try:
            fl = failing(f, read_text(f), baseline, {})
        except OSError:
            continue
        if fl:
            bad.append(f"{f}: {fl[0][1]}")
    if not bad:
        return 0
    key = re.sub(r"[^A-Za-z0-9_-]", "_", "%s-%s" % (data.get("session_id", "x"), data.get("agent_id", "main")))
    counter = os.path.join(BASE, "state", key + ".count")
    os.makedirs(os.path.dirname(counter), exist_ok=True)
    try:
        n = int(open(counter).read().strip())
    except (OSError, ValueError):
        n = 0
    log({"ts": time.time(), "mode": "stop", "failing": bad[:20], "blocks_before": n})
    if n >= MAX_BLOCKS:
        return 0
    open(counter, "w").write(str(n + 1))
    print(json.dumps({"decision": "block", "reason": f"rule-gate: {len(bad)} project rule file(s) hold rule text "
                      f"with no wired enforcer, first: {bad[0]}. " + HOWTO}))
    return 0


# ---------------------------------------------------------------- init / scan
def init():
    os.makedirs(BASE, exist_ok=True)
    files = set(hot_set(HOME)) | set(projects_files())
    secs, seen, per_file = {}, {}, {}
    for f in sorted(files):
        try:
            text = read_text(f)
        except OSError:
            continue
        for head, body in sections(text):
            hx = shash(head, body)
            secs.setdefault(hx, (head, body))
            per_file.setdefault(os.path.realpath(f), []).append([head, hx])
            if hx in seen:
                seen[hx][1] += 1
            else:
                seen[hx] = [f"{f} :: {head[:90]}", 1]
    json.dump({"created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "rule": RULE_ID,
               "sections": secs, "files": per_file}, open(BASELINE, "w"))
    debt = sorted((f"- {v[0]} (copies: {v[1]})" for hx, v in seen.items()
                   if not ID_RX.search(secs[hx][1])), key=lambda s: (HOME + "/.claude/" not in s, s))
    with open(DEBT, "w") as fh:
        fh.write(f"# Rule debt: rule sections with no code enforcer ({RULE_ID})\n\n"
                 f"Taken {time.strftime('%Y-%m-%d %H:%M')} by rule_gate v2. Grandfathered prose. Editing one "
                 f"makes it new, so it then needs a Rule-ID and a wired enforcer. The list only shrinks.\n\n"
                 f"{len(debt)} sections:\n\n" + "\n".join(debt) + "\n")
    print(f"baseline {len(secs)} sections across {len(files)} files; debt {len(debt)}")
    return 0


def main():
    if "--init" in sys.argv:
        return init()
    if "--scan" in sys.argv:
        base = load_baseline()
        files = hot_set(os.getcwd())
        rc = 0
        for f in files:
            for h, w in failing(f, read_text(f), base, id_index(files, exclude=f)):
                print(f"FAIL {f}: {h[:60]}: {w}")
                rc = 1
        return rc
    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except ValueError:
        return 0
    ev = data.get("hook_event_name") or ""
    try:
        if ev in ("Stop", "SubagentStop"):
            return stop(data)
        if ev == "PostToolUse":
            return post_tool(data)
        return pre_tool(data)
    except Exception as exc:
        log({"ts": time.time(), "mode": ev, "error": repr(exc)})
        tin = data.get("tool_input") or {}
        path = tin.get("file_path") or tin.get("notebook_path") or ""
        if ev == "PreToolUse" and (is_rule_path(path) or is_protected(path)):
            deny(f"internal error on a rule or protected path ({exc!r}); refused (fails closed).")
        return 0


if __name__ == "__main__":
    sys.exit(main())
