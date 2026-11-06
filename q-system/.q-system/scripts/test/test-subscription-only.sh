#!/usr/bin/env bash
# Subscription only, never the billed API (founder, 2026-09-28: "I don't want to
# use the API"). `claude` prefers ANTHROPIC_API_KEY over the subscription login
# when both exist, so one exported key in a launchd env turns every unattended
# run into metered API spend. Every headless model call must make inheriting the
# key impossible AT THE CALL, not somewhere earlier in the file.
#
# WHICH FILES: every file that shells the model on its own. That is the
# inventory q-system/.q-system/model-call-sites.json (`wrapper` + `shared` +
# `skeleton` rows whose file is in this tree) UNION what the detector
# plugins/kipi-core/voiceloop/call_sites.py finds here right now. A hard-coded
# list missed morning-brief.py and lessons-distill.py (Codex, PR #464 P1); the
# inventory is already held complete by tests/test_model_call_sites.py.
# PLUS every instance-local caller in each registered instance checked out on
# this machine (the `instances` rows; codex major, PR #464 round 3), labelled by
# hash because this repo is public. One not checked out here prints NOT CHECKED.
#
# WHAT EACH CALL MUST CARRY:
#   shell   every non-comment `claude ... -p/--print` command, including one
#           inside a `bash -c` string, a `$( )` substitution or a string held
#           in a variable for later execution, has `env -u ANTHROPIC_API_KEY`
#           in front of the binary in the SAME command. A file-level `unset`
#           counts for nothing: a later `source` or `export` can put the key
#           back before the call (Codex, PR #464 P2).
#   python  the subprocess call whose argv runs the model passes
#           `env=subscription_env()` (or a name bound to it), the helper returns
#           os.environ minus the key (proved by CALLING it with the key set),
#           and no other line in the file names ANTHROPIC_API_KEY (no re-add).
#           `env=os.environ`, `env=dict(os.environ)` or no env= all fail.
#           An `opencode run` argv counts as a model call: it reads the key too.
# Negative controls at the end prove each of those shapes is caught.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
exec python3 - "$ROOT" <<'PY'
import ast
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(sys.argv[1])
sys.path.insert(0, str(ROOT / "plugins" / "kipi-core"))
from voiceloop import call_sites as cs  # noqa: E402

KEY = "ANTHROPIC_API_KEY"
PASS = FAIL = 0


def ok(msg):
    global PASS
    PASS += 1
    print("  ok   " + msg)


def bad(msg):
    global FAIL
    FAIL += 1
    print("  FAIL " + msg)


# ---------------------------------------------------------------- shell ----
_NAME_EQ = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
# `${VAR-claude -p ...}`: a default command held in a parameter expansion
# (linear-worker.sh SECOND_RUNNER_FALLBACK), executed later as `$VAR "$1"`.
_EXPANSION_DEFAULT = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*:?[-=]([^}]*)\}")


def _strips(prefix):
    """Does this command prefix run the binary under `env -u ANTHROPIC_API_KEY`?"""
    seen_env = False
    for i, tok in enumerate(prefix):
        if tok.rsplit("/", 1)[-1] == "env":
            seen_env = True
        elif seen_env and tok in ("-u", "--unset") and i + 1 < len(prefix) and prefix[i + 1] == KEY:
            return True
        elif seen_env and tok in ("-u" + KEY, "--unset=" + KEY):
            return True
    return False


def _seg_bad(seg, depth):
    tokens = cs._tokens(seg)
    ci = cs._command_index(tokens)
    out = []
    if ci >= 0 and cs._BINARY_TOKEN.match(tokens[ci]) \
            and any(cs._FLAG_TOKEN.match(t) for t in tokens[ci + 1:]) \
            and not _strips(tokens[:ci]):
        out.append(seg.strip())
    # A command string carried as one token: `bash -c "..."`, a quoted case-arm
    # continuation, or `NAME="... claude -p ..."` executed later.
    for tok in tokens:
        body = _NAME_EQ.sub("", tok, count=1)
        if " " in body and cs._CLAUDE_WORD.search(body):
            out += _line_bad(body, depth + 1)
    return out


def _line_bad(line, depth=0):
    if depth > cs._MAX_DEPTH:
        return []
    out = []
    # The default is scanned as a command of its own, then the expansion is
    # read as the plain variable it evaluates to.
    for default in _EXPANSION_DEFAULT.findall(line):
        out += _line_bad(default, depth + 1)
    line = _EXPANSION_DEFAULT.sub("$_VAR", line)
    segs = cs._segments(line)
    if cs._SH_PRINTS.match(line):
        segs = segs[1:]
    for seg in segs:
        out += _seg_bad(seg, depth)
    for sub in cs._substitutions(line):
        out += _line_bad(sub, depth + 1)
    return out


def sh_violations(text):
    out = []
    for line in cs._logical_lines(text):
        if line.lstrip().startswith("#"):
            continue
        out += _line_bad(line)
    return out


# --------------------------------------------------------------- python ----
_SUBPROCESS = {"run", "Popen", "check_output", "check_call", "call"}
# lean_call.run (scripts/lean_call.py) is subprocess.run with the lean flags; its
# env= is the caller's, so the caller is checked exactly like a subprocess call.
_RUNNERS = {"subprocess", "lean_call"}


def _argv_list(node):
    elts = node.elts
    # OpenCode runs Anthropic models too and reads the same key, so its argv is a
    # model call (codex minor on #464: prompt_render.py's OpenCode branch had no env=).
    if elts and isinstance(elts[0], ast.Constant) and elts[0].value == "opencode":
        return True
    if elts and cs._is_dash_p(elts[0]) and any(
            not (isinstance(e, ast.Constant) and isinstance(e.value, str) and e.value.startswith("-"))
            for e in elts[1:]):
        return True
    return any(cs._is_dash_p(elts[i]) and cs._binary_like(elts[i - 1]) for i in range(1, len(elts)))


def _assigned(name, scope):
    for n in ast.walk(scope):
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in n.targets):
            yield n.value
        elif isinstance(n, (ast.AugAssign, ast.AnnAssign)) and isinstance(n.target, ast.Name) \
                and n.target.id == name and n.value is not None:
            yield n.value


def _model_expr(node, scope, funcs, depth=0):
    if depth > 6 or node is None:
        return False
    rec = lambda n, s=scope: _model_expr(n, s, funcs, depth + 1)  # noqa: E731
    if isinstance(node, (ast.List, ast.Tuple)):
        return _argv_list(node)
    if isinstance(node, ast.BinOp):
        return rec(node.left) or rec(node.right)
    if isinstance(node, ast.IfExp):
        return rec(node.body) or rec(node.orelse)
    if isinstance(node, ast.BoolOp):
        return any(rec(v) for v in node.values)
    if isinstance(node, ast.ListComp):
        return rec(node.generators[0].iter)
    if isinstance(node, ast.Name):
        return any(rec(v) for v in _assigned(node.id, scope))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in funcs:
        fn = funcs[node.func.id]
        return any(rec(r.value, fn) for r in ast.walk(fn) if isinstance(r, ast.Return))
    return False


def _is_helper_call(node):
    if not isinstance(node, ast.Call):
        return False
    f = node.func
    name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
    return name.endswith("subscription_env")


def _env_ok(call, scope):
    env = next((k.value for k in call.keywords if k.arg == "env"), None)
    if env is None:
        return "no env= (inherits os.environ, key included)"
    if _is_helper_call(env):
        return None
    if isinstance(env, ast.Name):
        vals = list(_assigned(env.id, scope))
        if vals and all(_is_helper_call(v) for v in vals):
            return None
    return "env=%s does not come from subscription_env()" % ast.unparse(env)


def _helper_ok(tree, text, path):
    """The file's subscription_env strips the key when CALLED with it set."""
    defs = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name.endswith("subscription_env")]
    imported = any(isinstance(n, ast.ImportFrom) and (n.module or "").endswith("prompt_render")
                   and any(a.name == "subscription_env" for a in n.names) for n in ast.walk(tree))
    if not defs and imported:
        return None
    if not defs:
        return "no subscription_env() defined or imported"
    fn = defs[0]
    ns = {"os": os}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(path), "exec"), ns)
    saved = os.environ.get(KEY)
    os.environ[KEY] = "sk-ant-negative-control"
    try:
        got = ns[fn.name]()
    finally:
        if saved is None:
            os.environ.pop(KEY, None)
        else:
            os.environ[KEY] = saved
    if KEY in got or "PATH" not in got:
        return "%s() does not return os.environ minus %s" % (fn.name, KEY)
    # No re-add: the key is named only inside the helper.
    helper_lines = set(range(fn.lineno, fn.end_lineno + 1))
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and n.value == KEY and n.lineno not in helper_lines:
            return "line %d names %s outside the helper (a re-add?)" % (n.lineno, KEY)
    return None


def py_violations(text, path="<src>"):
    tree = ast.parse(text)
    funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    scopes = [tree] + list(funcs.values())
    calls = []
    for scope in scopes:
        for n in ast.walk(scope):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                    and n.func.attr in _SUBPROCESS and isinstance(n.func.value, ast.Name) \
                    and n.func.value.id in _RUNNERS:
                argv = n.args[0] if n.args else next((k.value for k in n.keywords if k.arg == "args"), None)
                if _model_expr(argv, scope, funcs):
                    calls.append((n, scope))
    # innermost scope wins for a call seen from the module and its function
    seen, out = {}, []
    for n, scope in calls:
        if id(n) not in seen or scope is not tree:
            seen[id(n)] = (n, scope)
    if not seen:
        return ["no model subprocess call recognized (the resolver is blind to this file's shape)"]
    for n, scope in seen.values():
        why = _env_ok(n, scope)
        if why:
            out.append("line %d: %s" % (n.lineno, why))
    if not out:
        why = _helper_ok(tree, text, path)
        if why:
            out.append(why)
    return out


# ---------------------------------------------------------------- sites ----
spec = json.loads((ROOT / "q-system" / ".q-system" / "model-call-sites.json").read_text())
rows = set(spec.get("wrapper", [])) | set(spec.get("shared", {})) | set(spec.get("skeleton", {}))
sites = sorted({r for r in rows if (ROOT / r).is_file()} | cs.call_sites(ROOT))

print("subscription-only guard: %d model call sites" % len(sites))
for rel in sites:
    text = (ROOT / rel).read_text(errors="replace")
    v = py_violations(text, rel) if rel.endswith(".py") else sh_violations(text)
    if v:
        bad("%s can run claude on the billed API key: %s" % (rel, v[0][:160]))
        for extra in v[1:]:
            print("         also: " + extra[:160])
    else:
        ok("%s strips %s at every call" % (rel, KEY))

# ------------------------------------------------------------ instances ----
# Codex major, PR #464 round 3: the rows above are this tree only, so the 41
# inventoried instance-local callers (model-call-sites.json `instances`) were
# never read and the guard said green while scheduled instance jobs could still
# inherit the key. Every registered instance checked out on this machine is now
# scanned with the same checkers. Labels are hashes, never paths or names: this
# repo is public and a review run posts this output to the PR. The real path of a
# hash prints with `python3 q-system/.q-system/tests/test_model_call_sites.py`.
# An instance not checked out here (CI, a cloud session) is NOT CHECKED, counted
# and printed, never counted as a pass.
import hashlib  # noqa: E402


def _key(s):
    return hashlib.sha256(s.encode()).hexdigest()[:12]


def instance_roots():
    """(name, path or None) per registry instance. KIPI_INSTANCE_PATHS is a JSON
    {name: path} override for a clone that lives elsewhere (tests, a cloud session)."""
    reg = json.loads((ROOT / "instance-registry.json").read_text())
    moved = json.loads(os.environ.get("KIPI_INSTANCE_PATHS") or "{}")
    for it in reg.get("instances", []):
        p = Path(os.path.expanduser(str(moved.get(it["name"], it.get("path", "")))))
        yield it["name"], (p if it.get("has_git") and (p / ".git").exists() else None)


def instance_sites(path):
    return sorted(r for r in cs.call_sites(path) - set(spec.get("wrapper", []))
                  if not r.startswith(("q-system/", "plugins/")))


def instance_violations(path):
    """(rel, first violation or None) for every instance-local model caller under path."""
    for rel in instance_sites(path):
        text = (path / rel).read_text(errors="replace")
        v = py_violations(text, rel) if rel.endswith(".py") else sh_violations(text)
        yield rel, v


not_checked = []
for name, path in instance_roots():
    rows = spec.get("instances", {}).get(_key(name), {})
    if path is None:
        if rows:
            not_checked.append((_key(name), len(rows)))
        continue
    waived = spec.get("api_by_design", {}).get(_key(name), {})
    for rel, v in instance_violations(path):
        label = "instance %s file %s" % (_key(name), _key(rel))
        if _key(rel) in waived:
            # A founder-recorded exception waives only the names-the-key check;
            # an unstripped model call in the same file still fails.
            v = [x for x in v if "outside the helper" not in x]
            if not v:
                ok("%s: API path kept by founder decision (api_by_design); every claude call strips %s"
                   % (label, KEY))
                continue
        if v:
            bad("%s can run claude on the billed API key: %s" % (label, v[0][:160]))
        else:
            ok("%s strips %s at every call" % (label, KEY))
NOT_CHECKED = sum(n for _, n in not_checked)
for h, n in not_checked:
    print("  NOT CHECKED instance %s: %d inventoried caller(s), no checkout on this machine" % (h, n))

# ------------------------------------------------------ negative controls --
SH_CONTROLS = {
    "a bare claude -p": 'claude -p "hi"\n',
    "unset, then source, then a bare call": 'unset ANTHROPIC_API_KEY\nsource ./env.sh\nclaude -p "hi"\n',
    "a bare call inside bash -c": 'run_bounded 60 bash -c "cd /x && claude -p \\"$1\\"" _ "$p"\n',
    "a bare call held in a variable": 'FALLBACK="claude -p --model x"\n',
    "a bare call in a substitution": 'out="$(claude --print "$p")"\n',
    "env without -u": 'env FOO=1 claude -p "hi"\n',
    "a bare call as a parameter-expansion default": 'FB="${OVERRIDE-claude -p --model x}"\n',
}
for label, src in SH_CONTROLS.items():
    if sh_violations(src):
        ok("negative control caught: shell, %s" % label)
    else:
        bad("negative control PASSED: shell, %s" % label)
if sh_violations('env -u ANTHROPIC_API_KEY claude -p "hi"\n$TO env -u ANTHROPIC_API_KEY "$CLAUDE_BIN" -p x\n'):
    bad("positive control: env -u ANTHROPIC_API_KEY was not accepted")
else:
    ok("positive control: env -u ANTHROPIC_API_KEY claude -p is accepted")

HELPER = ("def subscription_env():\n"
          "    return {k: v for k, v in os.environ.items() if k != 'ANTHROPIC_API_KEY'}\n")
PY_CONTROLS = {
    "no env= at all": 'import subprocess\nsubprocess.run(["claude", "-p", x])\n',
    "env=os.environ": 'import os, subprocess\nsubprocess.run(["claude", "-p", x], env=os.environ)\n',
    "env=dict(os.environ)": 'import os, subprocess\nenv = dict(os.environ)\nsubprocess.run(["claude", "-p", x], env=env)\n',
    "a helper that keeps the key": 'import os, subprocess\ndef subscription_env():\n    return dict(os.environ)\n'
                                   'subprocess.run(["claude", "-p", x], env=subscription_env())\n',
    "an opencode run with no env=": 'import subprocess\nargs = ["opencode", "run", "--pure"]\n'
                                    'args.append(p)\nsubprocess.run(args, text=True)\n',
    "a lean_call.run with no env=": 'import lean_call\nlean_call.run(["claude", "-p", x])\n',
    "a re-add after the helper": 'import os, subprocess\n' + HELPER +
                                 'e = subscription_env()\ne["ANTHROPIC_API_KEY"] = "k"\n'
                                 'subprocess.run(["claude", "-p", x], env=e)\n',
}
for label, src in PY_CONTROLS.items():
    if py_violations(src):
        ok("negative control caught: python, %s" % label)
    else:
        bad("negative control PASSED: python, %s" % label)
good = 'import os, subprocess\n' + HELPER + 'subprocess.run(["claude", "-p", x], env=subscription_env())\n'
if py_violations(good):
    bad("positive control: env=subscription_env() was not accepted: %s" % py_violations(good))
else:
    ok("positive control: env=subscription_env() is accepted")

# An instance checkout is really read: a bare call in a throwaway repo is caught,
# and the same file stripped at the call passes.
import subprocess as _sp  # noqa: E402
import tempfile  # noqa: E402
with tempfile.TemporaryDirectory() as _tmp:
    _t = Path(_tmp)
    _sp.run(["git", "init", "-q", str(_t)], check=True)
    (_t / "job.py").write_text('import subprocess\nsubprocess.run(["claude", "-p", "hi"])\n')
    (_t / "ok.sh").write_text('env -u ANTHROPIC_API_KEY claude -p "hi"\n')
    _sp.run(["git", "-C", str(_t), "add", "-A"], check=True)
    _found = dict(instance_violations(_t))
    if _found.get("job.py"):
        ok("negative control caught: an instance-local bare call")
    else:
        bad("negative control PASSED: an instance-local bare call (instance scan is blind)")
    if "ok.sh" in _found and not _found["ok.sh"]:
        ok("positive control: an instance-local stripped call is accepted")
    else:
        bad("positive control: instance-local stripped call: %r" % (_found.get("ok.sh"),))

# The wrapper's own helper, imported the way a caller would.
try:
    from voiceloop import prompt_render
    os.environ[KEY] = "sk-ant-negative-control"
    got = prompt_render.subscription_env()
    os.environ.pop(KEY, None)
    (ok if KEY not in got else bad)("prompt_render.subscription_env() drops %s" % KEY)
except Exception as exc:  # noqa: BLE001
    bad("prompt_render.subscription_env() unavailable: %s" % exc)

print()
print("passed %d, failed %d, NOT CHECKED %d instance caller(s)" % (PASS, FAIL, NOT_CHECKED))
sys.exit(0 if PASS > 0 and FAIL == 0 else 1)
PY
