#!/usr/bin/env python3
"""Audit every hook that injects additionalContext for the envelope that DELIVERS.

Scar (measured 2026-08-30, probe_hook_envelope.py, three headless `claude -p`
runs with a positive control): Claude Code silently DISCARDS a hook's
additionalContext unless it is nested as

    {"hookSpecificOutput": {"hookEventName": "<Event>", "additionalContext": "..."}}

Both other shapes were measured ABSENT:
  - nested WITHOUT hookEventName   -> discarded
  - top-level additionalContext    -> discarded (the scar already in token-guard.py)

The published docs say hookEventName is optional. The docs are wrong. Nothing
downstream can see the failure: every gate measures the OUTPUT, none check that
the INPUT arrived. So the only defence is a static audit of the emitters, and
this is it.

Classification per emission site:
  OK             hookSpecificOutput dict carrying BOTH hookEventName and
                 additionalContext as literal keys.
  NO_EVENT_NAME  hookSpecificOutput.additionalContext with no hookEventName. The
                 payload never reaches the model.
  TOP_LEVEL      additionalContext at the top level of the emitted object.
                 Same outcome.
  UNKNOWN        the envelope is not a literal dict at the emission site, so
                 this tool cannot tell. Reported, never passed: a check that
                 cannot see must not report green.

Exit 0 when every site is OK, 1 when any site is NO_EVENT_NAME/TOP_LEVEL/UNKNOWN,
2 when the self-test fails (the tool is not measuring what it claims).

Usage:
    hook_envelope_audit.py --self-test
    hook_envelope_audit.py <path-or-dir> [<path-or-dir> ...]
    hook_envelope_audit.py --json <path-or-dir> ...
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
import tempfile

KEY_CONTEXT = "additionalContext"
KEY_ENVELOPE = "hookSpecificOutput"
KEY_EVENT = "hookEventName"

OK = "OK"
NO_EVENT_NAME = "NO_EVENT_NAME"
TOP_LEVEL = "TOP_LEVEL"
UNKNOWN = "UNKNOWN"

SKIP_DIR_PARTS = {".git", "node_modules", "__pycache__", ".venv", "venv",
                  "review-trees", ".mypy_cache", ".pytest_cache"}


class Site:
    __slots__ = ("path", "line", "verdict", "event", "detail")

    def __init__(self, path, line, verdict, event=None, detail=""):
        self.path = path
        self.line = line
        self.verdict = verdict
        self.event = event
        self.detail = detail

    def as_dict(self):
        return {"path": self.path, "line": self.line, "verdict": self.verdict,
                "event": self.event, "detail": self.detail}

    def __repr__(self):  # pragma: no cover - debugging aid
        return "Site(%s:%s %s)" % (self.path, self.line, self.verdict)


def _literal_keys(node):
    """String keys of an ast.Dict, or None if any key is not a literal string."""
    keys = []
    for k in node.keys:
        if k is None:  # {**other}
            return None
        if isinstance(k, ast.Constant) and isinstance(k.value, str):
            keys.append(k.value)
        else:
            return None
    return keys


def _value_for(node, key):
    for k, v in zip(node.keys, node.values):
        if isinstance(k, ast.Constant) and k.value == key:
            return v
    return None


def _event_name(envelope):
    v = _value_for(envelope, KEY_EVENT)
    if isinstance(v, ast.Constant) and isinstance(v.value, str):
        return v.value
    return "<non-literal>" if v is not None else None


def audit_python(path, source=None):
    """Every additionalContext emission site in a Python file, classified."""
    if source is None:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            source = fh.read()
    if KEY_CONTEXT not in source:
        return []
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [Site(path, getattr(exc, "lineno", 0) or 0, UNKNOWN,
                     detail="unparseable: %s" % exc)]

    sites = []
    # Dicts that ARE the envelope: {"hookEventName": ..., "additionalContext": ...}
    envelopes = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        keys = _literal_keys(node)
        if keys is None:
            # A dict with a computed or **-unpacked key cannot be judged
            # statically. It is UNKNOWN, never absent: emitting no site at all
            # let `k = "additionalContext"` inside an otherwise literal envelope
            # walk straight through the blocking gate (Codex minor, PR #285
            # round 3). Two ways to recognise it as an envelope worth reporting:
            # it names the context key literally somewhere among its keys, or it
            # is envelope-shaped because it carries a literal hookEventName.
            named = any(isinstance(k, ast.Constant) and k.value == KEY_CONTEXT
                        for k in node.keys if k is not None)
            shaped = any(isinstance(k, ast.Constant) and k.value == KEY_EVENT
                         for k in node.keys if k is not None)
            if named or shaped:
                sites.append(Site(path, node.lineno, UNKNOWN,
                                  detail="dict has non-literal or **-unpacked keys"))
                envelopes.add(id(node))
            continue
        if KEY_CONTEXT not in keys:
            continue
        envelopes.add(id(node))
        if KEY_EVENT in keys:
            sites.append(Site(path, node.lineno, OK, event=_event_name(node)))
        else:
            sites.append(Site(path, node.lineno, NO_EVENT_NAME))

    # `hso = {...}` then `out = {"hookSpecificOutput": hso}` is a perfectly
    # ordinary way to write the delivering shape, and calling it TOP_LEVEL was a
    # false BLOCK on correct code (Codex minor, PR #285 round 4). One level of
    # simple-name aliasing is resolved; anything deeper stays unreadable and is
    # reported as such rather than guessed at.
    aliases = {}
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Dict)):
            aliases[node.targets[0].id] = node.value

    def _resolve(v):
        if isinstance(v, ast.Name):
            return aliases.get(v.id)
        return v

    # An envelope nested under "hookSpecificOutput" is the delivering shape; one
    # that is NOT nested there is top-level and is discarded too. Re-classify.
    nested = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            v = _resolve(_value_for(node, KEY_ENVELOPE))
            if isinstance(v, ast.Dict) and id(v) in envelopes:
                nested.add(id(v))
        # out["hookSpecificOutput"] = {...}
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if (isinstance(tgt, ast.Subscript)
                        and isinstance(tgt.slice, ast.Constant)
                        and tgt.slice.value == KEY_ENVELOPE
                        and isinstance(_resolve(node.value), ast.Dict)
                        and id(_resolve(node.value)) in envelopes):
                    nested.add(id(_resolve(node.value)))

    # dict(additionalContext=...) and dict(**{...}) are two more ways to build
    # the payload that a walk over Dict LITERALS never sees (Codex minor, PR #285
    # round 5). Same rule as everywhere else here: a shape this cannot read is
    # UNKNOWN, never absent.
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "dict"):
            continue
        named = any(kw.arg == KEY_CONTEXT for kw in node.keywords)
        starred = any(kw.arg is None for kw in node.keywords)
        if named or (starred and KEY_CONTEXT in ast.dump(node)):
            sites.append(Site(path, node.lineno, UNKNOWN,
                              detail="envelope built with dict(), which this "
                                     "cannot read as a literal"))

    # `out["hookSpecificOutput"]["additionalContext"] = x` builds the payload by
    # ASSIGNMENT, so a walk over dict literals sees nothing at all and the gate
    # passed the file at exit 0 (Codex minor, PR #285 round 4). Absent read as
    # approved -- the exact confusion this tool exists to end. A subscript in a
    # TARGET position is a write; the same subscript in a value position is a
    # read and is left alone, the same discrimination the text scanner makes.
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for tgt in targets:
            if (isinstance(tgt, ast.Subscript)
                    and isinstance(tgt.slice, ast.Constant)
                    and tgt.slice.value == KEY_CONTEXT):
                sites.append(Site(path, node.lineno, UNKNOWN,
                                  detail="additionalContext is written by "
                                         "assignment, so the envelope around it "
                                         "cannot be read statically"))

    # A .py hook can PRINT the envelope as a raw JSON string -- no dict node
    # exists, so everything above is blind to it (Opus fallback minor, PR #285
    # round 6).
    #
    # The first attempt ran the whole text scanner as a second pass and reported
    # 28 broken sites across this repo, nearly all of them fixture strings inside
    # this tool's OWN test file. A .py file is full of JSON-shaped strings that
    # are inputs, not outputs. So the match is narrowed to the one construct that
    # actually emits: a literal string handed straight to print() or
    # sys.stdout.write(). A fixture bound to a name, or passed to write_text, is
    # not an emission and stays invisible.
    emitted = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        is_print = isinstance(fn, ast.Name) and fn.id == "print"
        is_write = (isinstance(fn, ast.Attribute) and fn.attr == "write"
                    and isinstance(fn.value, ast.Attribute)
                    and fn.value.attr in ("stdout",))
        if not (is_print or is_write):
            continue
        for arg in node.args:
            if (isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                    and EMIT_KEY_RE.search(arg.value)):
                emitted[node.lineno] = arg.value
    seen_lines = {s.line for s in sites}
    for line, text in sorted(emitted.items()):
        if line in seen_lines:
            continue
        # Judge the STRING'S OWN CONTENT with the text scanner, not the source
        # line the call starts on. Reading one line verdicted a CORRECT
        # multi-line envelope as TOP_LEVEL and blocked it fleet-wide with a false
        # "Claude Code DISCARDS" claim (round 9 major) -- a false block on
        # correct code, which is how a gate gets switched off.
        for inner in audit_text(path, source=text):
            sites.append(Site(path, line, inner.verdict, event=inner.event,
                              detail="envelope emitted as a raw JSON string"))

    by_line = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict) and id(node) in envelopes:
            by_line.setdefault(node.lineno, []).append(node)

    out = []
    for site in sites:
        node = None
        for cand in by_line.get(site.line, []):
            node = cand
            break
        if site.verdict == UNKNOWN:
            out.append(site)
            continue
        if node is not None and id(node) not in nested:
            out.append(Site(path, site.line, TOP_LEVEL, event=site.event,
                            detail="additionalContext is not inside a literal "
                                   "hookSpecificOutput dict"))
        else:
            out.append(site)
    return out


TEXT_ENVELOPE_RE = re.compile(r'["\']?%s["\']?\s*[:=]' % KEY_ENVELOPE)

# In shell/JS the same token appears three ways and only one of them is an
# emission. Distinguishing them is the whole job: an audit that shouts on the
# ~700 correct assertion lines in this repo's own hook tests is an audit the
# fleet switches off, and then it protects nothing.
#   emission :  {"additionalContext": "..."}        <- key of an object literal
#   read     :  out["hookSpecificOutput"]["additionalContext"]
#   assertion:  assert "additionalContext" not in out
# So: the key must be FOLLOWED by a colon (it is a key, not an index or an
# operand) and must NOT be immediately PRECEDED by '[' (that is a subscript).
EMIT_KEY_RE = re.compile(r'(?<!\[)["\']%s["\']\s*:' % KEY_CONTEXT)
# `#` for shell and python, `//` for js/ts. A scar comment quoting the broken
# envelope verbatim -- which is exactly how this repo documents a scar -- was
# being read as an emission in a .js or .ts hook (round 8 minor).
COMMENT_LINE_RE = re.compile(r'^\s*(#|//)')


def _strip_comment_lines(source):
    """Blank out whole-line # comments, preserving line numbers.

    The token-guard hook test opens with a six-line scar comment that quotes the
    BROKEN envelope verbatim. Auditing prose as if it were code reported a defect
    in the file whose entire purpose is asserting that defect is gone.
    """
    return "\n".join("" if COMMENT_LINE_RE.match(l) else l
                      for l in source.split("\n"))


def audit_text(path, source=None):
    """Shell/JS fallback: brace-balanced read around each emitted context key."""
    if source is None:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            source = fh.read()
    scan = _strip_comment_lines(source)
    sites = []
    for m in EMIT_KEY_RE.finditer(scan):
        line = scan.count("\n", 0, m.start()) + 1
        start = scan.rfind("{", 0, m.start())
        if start < 0:
            sites.append(Site(path, line, TOP_LEVEL, detail="no enclosing object"))
            continue
        depth, end = 0, len(scan)
        for i in range(start, len(scan)):
            if scan[i] == "{":
                depth += 1
            elif scan[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        blob = scan[start:end]
        before = scan[max(0, start - 120):start]
        # Order matters: ask "is it nested at all" BEFORE "does it name the
        # event". Asking the other way round labelled a bare top-level
        # {"additionalContext": ...} as NO_EVENT_NAME, which blocks correctly but
        # tells the reader the wrong thing about their own code.
        if not TEXT_ENVELOPE_RE.search(before) and KEY_ENVELOPE not in blob:
            sites.append(Site(path, line, TOP_LEVEL))
        elif KEY_EVENT not in blob:
            sites.append(Site(path, line, NO_EVENT_NAME))
        else:
            ev = re.search(r'["\']%s["\']\s*:\s*["\']([A-Za-z]+)["\']' % KEY_EVENT, blob)
            sites.append(Site(path, line, OK, event=ev.group(1) if ev else "<non-literal>"))
    return sites


def audit_file(path):
    if path.endswith(".py"):
        return audit_python(path)
    return audit_text(path)


def walk(roots):
    for root in roots:
        if os.path.isfile(root):
            yield root
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIR_PARTS]
            for name in filenames:
                if name.endswith((".py", ".sh", ".js", ".ts")):
                    yield os.path.join(dirpath, name)


# --------------------------------------------------------------------------
# Self-test. The three arms are the three shapes probe_hook_envelope.py measured
# against a live model; this asserts the AUDIT agrees with the MEASUREMENT.
# Without the two negative arms the audit could return OK unconditionally and
# still look green, which is the exact failure this repo keeps hitting.
# --------------------------------------------------------------------------
SELF_TEST_CASES = [
    ("good_nested", OK,
     'import json,sys\n'
     'sys.stdout.write(json.dumps({"hookSpecificOutput": '
     '{"hookEventName": "UserPromptSubmit", "additionalContext": "x"}}))\n'),
    ("nested_no_event_name", NO_EVENT_NAME,
     'import json,sys\n'
     'sys.stdout.write(json.dumps({"hookSpecificOutput": '
     '{"additionalContext": "x"}}))\n'),
    ("top_level", TOP_LEVEL,
     'import json,sys\n'
     'sys.stdout.write(json.dumps({"additionalContext": "x"}))\n'),
    ("assigned_envelope", OK,
     'import json,sys\n'
     'out = {}\n'
     'out["hookSpecificOutput"] = {"hookEventName": "SessionStart", '
     '"additionalContext": "x"}\n'
     'sys.stdout.write(json.dumps(out))\n'),
    ("docstring_mention_only", None,
     '"""Injects hookSpecificOutput.additionalContext somewhere else."""\n'
     '# additionalContext is discussed here, never emitted\n'
     'x = 1\n'),
    ("computed_envelope", UNKNOWN,
     'import json,sys\n'
     'k = "additional" + "Context"\n'
     'sys.stdout.write(json.dumps({"hookSpecificOutput": {k: "x"}, '
     '"additionalContext": "y", **{}}))\n'),
]

SELF_TEST_SHELL = [
    ("shell_good", OK,
     'echo \'{"hookSpecificOutput": {"hookEventName": "SessionStart", '
     '"additionalContext": "x"}}\'\n'),
    ("shell_no_event_name", NO_EVENT_NAME,
     'echo \'{"hookSpecificOutput": {"additionalContext": "x"}}\'\n'),
    # The three shapes that are NOT emissions. Each of these was a live false
    # positive against this repo's own hook tests before the text scanner learned
    # to tell them apart; without these cases the scanner can regress to shouting
    # on ~700 correct lines and nothing goes red.
    ("shell_subscript_read", None,
     'python3 -c "import sys,json; a=json.load(sys.stdin)'
     "['hookSpecificOutput']['additionalContext']\"\n"),
    ("shell_negative_assertion", None,
     'python3 - <<EOF\n'
     'assert "additionalContext" not in out, "must not be top-level"\n'
     'EOF\n'),
    ("shell_scar_comment", None,
     '#!/usr/bin/env bash\n'
     '# Scar: warn() printed top-level {"additionalContext": ...}, which is\n'
     '#   ignored. Contract: nested hookSpecificOutput with hookEventName.\n'
     'echo ok\n'),
]


def self_test(verbose=True):
    failures = []
    for name, expected, src in SELF_TEST_CASES:
        got = audit_python("<%s>" % name, source=src)
        verdicts = [s.verdict for s in got]
        if expected is None:
            ok = verdicts == []
        else:
            ok = verdicts == [expected]
        if verbose:
            print("  %-24s expected=%-14s got=%s" % (name, expected, verdicts))
        if not ok:
            failures.append((name, expected, verdicts))
    for name, expected, src in SELF_TEST_SHELL:
        verdicts = [s.verdict for s in audit_text("<%s>" % name, source=src)]
        if verbose:
            print("  %-24s expected=%-14s got=%s" % (name, expected, verdicts))
        if verdicts != ([] if expected is None else [expected]):
            failures.append((name, expected, verdicts))
    return failures


# --------------------------------------------------------------------------
# Repair. Deliberately narrow: it only ever ADDS the missing hookEventName to a
# hookSpecificOutput dict that already carries additionalContext, and it refuses
# every other verdict. TOP_LEVEL needs a human to decide which event the payload
# belongs to and where the envelope should live; UNKNOWN is by definition
# unreadable. A repair that guessed at those would be the same class of defect
# as the bug: a tool reporting success on work it could not see.
# --------------------------------------------------------------------------
def fix_no_event_name(path, event, source=None, dry_run=False):
    """Insert hookEventName into every NO_EVENT_NAME site. Returns (n, text)."""
    if source is None:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            source = fh.read()
    sites = [s for s in (audit_python(path, source=source) if path.endswith(".py")
                         else audit_text(path, source=source))
             if s.verdict == NO_EVENT_NAME]
    if not sites:
        return 0, source
    out = source
    n = 0
    # Rewrite right-to-left so earlier offsets stay valid.
    for m in sorted(re.finditer(r'(["\'])%s\1(\s*):' % KEY_CONTEXT, out),
                    key=lambda m: -m.start()):
        line = out.count("\n", 0, m.start()) + 1
        # Only touch a line the audit actually flagged.
        if not any(abs(s.line - line) <= 6 for s in sites):
            continue
        head = out.rfind("{", 0, m.start())
        if head < 0:
            continue
        seg = out[head:m.start()]
        if KEY_EVENT in seg or KEY_EVENT in out[m.start():m.start() + 400]:
            continue
        q = m.group(1)
        indent = ""
        ls = out.rfind("\n", 0, m.start()) + 1
        if out[ls:m.start()].strip() == "":
            indent = out[ls:m.start()]
            insert = "%s%s%s%s: %s%s%s,\n" % (q, KEY_EVENT, q, "", q, event, q)
            insert = "%s%s%s: %s%s%s,\n%s" % (q + KEY_EVENT + q, "", "",
                                               q, event, q, indent)
        else:
            insert = "%s%s%s: %s%s%s, " % (q, KEY_EVENT, q, q, event, q)
        out = out[:m.start()] + insert + out[m.start():]
        n += 1
    if n and not dry_run:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(out)
    return n, out


# A dict key named additionalContext is not proof of a hook. `payload =
# {"additionalContext": "ordinary API field"}` in unrelated code is a perfectly
# ordinary line, and a BLOCKING gate that stops that edit is a gate the fleet
# switches off -- the same reasoning that made the text scanner learn to skip
# reads and assertions (Codex minor, PR #285 round 2).
#
# So the blocking path additionally demands evidence that the file IS a hook.
# These markers are taken from the files that actually carried the defect, not
# invented: every stale token-guard fork mentions hook_event_name and tool_input,
# and the leanest one (focus-kit's echo-of-prompt.py) still reads its payload
# with json.load(sys.stdin). The REPORTING path does not apply this filter -- a
# human reading a full audit wants to see everything, and only a block needs to
# be sure.
HOOK_MARKERS = (
    "hookSpecificOutput",
    "hookEventName",
    "hook_event_name",
    "tool_input",
    "tool_name",
    "CLAUDE_PROJECT_DIR",
    # Reading a JSON object off stdin, not merely touching stdin. Bare
    # `sys.stdin` caught any filter program that happens to carry an
    # additionalContext field (Codex minor, PR #285 round 3); this still catches
    # the leanest real offender, focus-kit's echo-of-prompt.py, whose only hook
    # tell is exactly this call.
    "json.load(sys.stdin)",
    "json.loads(sys.stdin",
    # The scar shape the probe itself generates drains stdin and emits, without
    # ever parsing it (Opus fallback minor, PR #285 round 6). `for line in
    # sys.stdin` still does not match, which is what keeps an ordinary filter out.
    "sys.stdin.read()",
)


def looks_like_a_hook(source):
    """True when the file carries any marker only a Claude Code hook would."""
    return any(marker in source for marker in HOOK_MARKERS)


# How recently a file must have been written for a Bash PostToolUse to own it.
# Wide enough to cover a slow command, narrow enough that a file broken last week
# does not wedge every Bash call in the session -- a gate that blocks unrelated
# work is a gate that gets switched off.
# The per-file bypass every blocking hook in this repo is required to have
# (skill-hook-pairing.md, "Override"). This one shipped without it, which left no
# way past a false block except switching the gate off (round 7 minor).
SKIP_MARKER = "hook-envelope-skip"

RECENT_WRITE_SECONDS = 120
# Cost ceiling for the Bash path: this runs after EVERY Bash call, so it reads a
# bounded number of recently-written files and no more (token discipline).
MAX_RECENT_FILES = 40


def _recently_written(root, now=None):
    """Hook-shaped files in `root`'s working tree written in the last window."""
    import subprocess
    import time
    now = time.time() if now is None else now
    # `git status --porcelain` prints paths relative to the GIT ROOT, not to the
    # directory passed with -C. Joining them onto a project dir that sits below
    # the root produces paths that do not exist, and every one is skipped -- the
    # gate goes silently inert exactly where it looks busiest (round 7 minor).
    try:
        top = subprocess.run(["git", "-C", root, "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=10)
        r = subprocess.run(["git", "-C", root, "status", "--porcelain",
                            "--untracked-files=all"],
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return []
    if r.returncode != 0 or top.returncode != 0:
        return []
    root = top.stdout.strip() or root
    candidates = []
    for line in r.stdout.splitlines():
        rel = line[3:].strip()
        if " -> " in rel:                       # a rename: take the destination
            rel = rel.split(" -> ", 1)[1]
        rel = rel.strip('"')
        if not rel.endswith((".py", ".sh", ".js", ".ts")):
            continue
        full = os.path.join(root, rel)
        try:
            mtime = os.path.getmtime(full)
        except OSError:
            continue
        if now - mtime > RECENT_WRITE_SECONDS:
            continue
        candidates.append((mtime, full))
    # The cap used to break out of the loop in GIT PATH ORDER, so a broken hook
    # whose path sorted late was never read at all and the gate exited 0 -- the
    # silent-blindness class this tool exists to end, reintroduced by its own
    # cost bound (round 8 major). Most-recently-written first, so the files the
    # command just wrote are the ones that survive the cap, and truncation is
    # reported rather than assumed harmless.
    candidates.sort(reverse=True)
    kept = [full for _, full in candidates[:MAX_RECENT_FILES]]
    dropped = len(candidates) - len(kept)
    if dropped:
        sys.stderr.write(
            "hook_envelope_audit: %d recently-written file(s) beyond the %d-file "
            "cap were NOT examined; this pass is partial.\n"
            % (dropped, MAX_RECENT_FILES))
    return kept


def _audit_recent_writes(payload):
    """The Bash leg: judge what was written, not what the command said."""
    root = (os.environ.get("CLAUDE_PROJECT_DIR")
            or (payload.get("cwd") if isinstance(payload.get("cwd"), str) else None)
            or os.getcwd())
    if self_test(verbose=False):
        return 0                      # a broken audit blocks nothing
    bad = []
    for full in _recently_written(root):
        try:
            with open(full, "r", encoding="utf-8", errors="replace") as fh:
                source = fh.read()
        except OSError:
            continue
        if (KEY_CONTEXT not in source or SKIP_MARKER in source
                or not looks_like_a_hook(source)):
            continue                  # the same bypass the block message names;
                                      # this leg ignored it (round 8 major)
        sites = (audit_python(full, source=source) if full.endswith(".py")
                 else audit_text(full, source=source))
        # DEFINITE verdicts only. UNKNOWN means "this shape is unreadable", and a
        # correct hook built with dict() kwargs is UNKNOWN -- blocking every Bash
        # call for 120s because some other recently-written file is unreadable is
        # how a gate gets switched off (Opus fallback major, PR #285 round 6).
        # The file_path leg still blocks on UNKNOWN: there it knows exactly which
        # file you just edited and the feedback is actionable. This leg is
        # inferring which file the command touched, so it only acts on certainty.
        bad.extend(s for s in sites if s.verdict in (NO_EVENT_NAME, TOP_LEVEL))
    if not bad:
        return 0
    _emit_block(bad)
    return 2


def hook_mode():
    """PostToolUse gate: block an edit that ships a discarded envelope.

    Self-scoped by tool_input.file_path (token discipline: this must not walk a
    tree on every Edit). Exit 2 = block with stderr fed back to Claude, exit 0 =
    pass. Anything unreadable or unparseable passes -- a gate that cannot run
    must not block the session, and the pytest layer catches what this misses.
    """
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    path = (payload.get("tool_input") or {}).get("file_path") or ""
    if not path:
        # A Bash write has no file_path, and this session wrote every one of its
        # own hook fixes through Bash heredocs and python drivers -- so wired on
        # Edit|Write alone the gate would never have fired on the very edits it
        # was built for (Codex major, PR #285 round 5).
        #
        # Parsing the COMMAND for a path is the wrong layer and this repo already
        # has the lesson: a guard that reads command text cannot see a computed
        # path, and the careless wide rewrite is exactly the one that computes
        # its targets. So look at the EFFECT instead: which hook-bearing files
        # in the working tree were just written.
        return _audit_recent_writes(payload)
    if not path.endswith((".py", ".sh", ".js", ".ts")):
        return 0
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            source = fh.read()
    except OSError:
        return 0
    if KEY_CONTEXT not in source:
        return 0                      # the fast exit for every other edit
    if SKIP_MARKER in source:
        return 0                      # explicit per-file bypass
    if not looks_like_a_hook(source):
        return 0                      # an ordinary dict key, not a hook payload
    if self_test(verbose=False):
        return 0                      # broken audit blocks nothing
    sites = (audit_python(path, source=source) if path.endswith(".py")
             else audit_text(path, source=source))
    bad = [s for s in sites if s.verdict != OK]
    if not bad:
        return 0
    _emit_block(bad)
    return 2


def _emit_block(bad):
    certain = [s for s in bad if s.verdict in (NO_EVENT_NAME, TOP_LEVEL)]
    headline = ("BLOCKED by hook_envelope_audit: this hook emits an envelope that "
                "Claude Code DISCARDS." if certain else
                "BLOCKED by hook_envelope_audit: this hook builds its envelope in "
                "a shape this audit CANNOT READ, so it cannot confirm the payload "
                "is delivered. This is not a claim that it is broken.")
    lines = [headline,
             "",
             "Measured 2026-08-30 (probe_hook_envelope.py, three headless runs "
             "with a positive control): additionalContext reaches the model ONLY as",
             '    {"hookSpecificOutput": {"hookEventName": "<Event>", '
             '"additionalContext": "..."}}',
             "Both a missing hookEventName and a top-level additionalContext were "
             "measured ABSENT. The published docs call the key optional; they are wrong.",
             ""]
    for s in bad:
        lines.append("  %s:%d  %s%s" % (s.path, s.line, s.verdict,
                                        "  (%s)" % s.detail if s.detail else ""))
    lines.append("")
    lines.append("Set hookEventName to the event this hook is wired to. "
                 "UNKNOWN means the envelope is not a literal dict here, so the "
                 "audit cannot verify it -- make it literal, or move the emission "
                 "to one chokepoint that is.")
    lines.append("If the shape is deliberate and you have verified delivery "
                 "yourself, put `%s` in the file to bypass this gate for it."
                 % SKIP_MARKER)
    sys.stderr.write("\n".join(lines) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("roots", nargs="*", help="files or directories to audit")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--fix", metavar="EVENT",
                    help="add the missing hookEventName=EVENT to every "
                         "NO_EVENT_NAME site (never TOP_LEVEL/UNKNOWN)")
    ap.add_argument("--hook", action="store_true",
                    help="PostToolUse mode: hook JSON on stdin, exit 2 to block")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--all", action="store_true",
                    help="print OK sites too (default: only the broken ones)")
    args = ap.parse_args(argv)

    if args.hook:
        return hook_mode()

    if args.self_test:
        print("self-test:")
        failures = self_test()
        if failures:
            print("SELF-TEST FAILED: %r" % (failures,))
            return 2
        print("self-test OK (%d cases, incl. 3 negative arms)"
              % (len(SELF_TEST_CASES) + len(SELF_TEST_SHELL)))
        return 0

    if not args.roots:
        ap.error("give at least one path, or --self-test")

    # The audit refuses to report on the fleet unless it can still tell the
    # three shapes apart on this machine, today.
    failures = self_test(verbose=False)
    if failures:
        print("SELF-TEST FAILED, refusing to audit: %r" % (failures,), file=sys.stderr)
        return 2

    if args.fix:
        total, files = 0, 0
        for path in walk(args.roots):
            try:
                n, _ = fix_no_event_name(path, args.fix)
            except OSError:
                continue
            if n:
                total += n
                files += 1
                print("fixed %d site(s) in %s" % (n, path))
        print("\n%d site(s) across %d file(s)" % (total, files))

    sites = []
    for path in walk(args.roots):
        try:
            sites.extend(audit_file(path))
        except OSError:
            continue

    bad = [s for s in sites if s.verdict != OK]
    if args.json:
        print(json.dumps([s.as_dict() for s in (sites if args.all else bad)], indent=2))
    else:
        shown = sites if args.all else bad
        for s in sorted(shown, key=lambda s: (s.verdict, s.path, s.line)):
            print("%-14s %s:%d%s%s" % (s.verdict, s.path, s.line,
                                       "  event=%s" % s.event if s.event else "",
                                       "  %s" % s.detail if s.detail else ""))
        print("\n%d emission site(s), %d OK, %d broken"
              % (len(sites), len(sites) - len(bad), len(bad)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
