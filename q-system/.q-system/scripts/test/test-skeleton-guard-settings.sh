#!/usr/bin/env bash
# Reproducer + acceptance for ASK-3529: a dispatch target that carries no
# .claude/settings.json of its own ran the agent with NONE of the skeleton's
# guards, and repo-preflight.sh check 3 refused it forever ("settings.json is
# missing"), because the only cure it knew was seeding 66 hook commands into
# the target.
#
# The cure is skeleton-guard-settings.py: the template's hooks and deny rules,
# with "$CLAUDE_PROJECT_DIR/" rewritten to the skeleton's own root and the hooks
# that break outside an instance removed BY NAME. This file asserts its output
# contract against the REAL template, and its refusals against a fake skeleton
# copy. Never a live data path: the fake skeleton is built under mktemp.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
GEN="$ROOT/q-system/.q-system/scripts/skeleton-guard-settings.py"
TPL="$ROOT/settings-template.json"

PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  PASS: $1"; }
bad() { FAIL=$((FAIL+1)); echo "  FAIL: $1"; }

if [ ! -f "$GEN" ]; then
  echo "  FAIL: THE DEFECT: no skeleton-guard-settings.py, so a target without"
  echo "        project settings gets no guards and check 3 can only refuse it."
  echo "-------- 0 passed, 1 failed --------"
  exit 1
fi
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "== 1. the rendered set, from the real template =="
OUT="$(python3 "$GEN")"; RC=$?
[ "$RC" = "0" ] && ok "renders with exit 0" || bad "render exited $RC: $OUT"
printf '%s' "$OUT" > "$WORK/set.json"

python3 - "$WORK/set.json" "$TPL" "$ROOT" "$GEN" <<'PY'
import json, os, re, sys, importlib.util
s = json.load(open(sys.argv[1])); t = json.load(open(sys.argv[2])); root = sys.argv[3]
spec = importlib.util.spec_from_file_location("g", sys.argv[4]); g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
fails = []
def check(cond, msg):
    print(("  PASS: " if cond else "  FAIL: ") + msg)
    if not cond: fails.append(msg)

# Guards only. The template also sets model, plugins, allow rules and a default
# permission mode; supplying those would change what the agent CAN do, not
# what stops it, so they are out of the set by design.
check(sorted(s) == ["hooks", "permissions"], "only hooks and permissions are supplied (got %s)" % sorted(s))
check(sorted(s.get("permissions", {})) == ["deny"], "permissions carries deny only, never allow or defaultMode")
check(s["permissions"]["deny"] == t["permissions"]["deny"], "the deny list is the template's, verbatim")

cmds = [(ev, h["command"]) for ev, arr in s["hooks"].items() for m in arr for h in m["hooks"]]
check(len(cmds) > 0, "the set is not empty (%d hook commands)" % len(cmds))
check(not any("$CLAUDE_PROJECT_DIR/" in c for _, c in cmds), "no command still resolves from the target's tree")
paths = sorted({p for _, c in cmds for p in re.findall(re.escape(root) + r"/[\w./-]+\.(?:py|sh)", c)})
missing = [p for p in paths if not os.path.isfile(p)]
check(paths and not missing, "every script a kept hook names exists under the skeleton root (%d paths; missing %s)" % (len(paths), missing[:3]))

named = lambda c: set(re.findall(r"[\w.-]+\.(?:py|sh)", c))
leaked = sorted({n for _, c in cmds for n in named(c)} & set(g.EXCLUDED))
check(not leaked, "no excluded hook is in the set (leaked: %s)" % leaked)

tpl_names = {n for arr in t["hooks"].values() for m in arr for h in m["hooks"] for n in named(h["command"])}
stale = sorted(set(g.EXCLUDED) - tpl_names)
# A stale exclusion is harmless at runtime, so it is a TEST failure, not a
# dispatch refusal: refusing on it would darken a target over an unrelated
# template edit, the exact scar check 2 was retired for (ASK-3526).
check(not stale, "every exclusion names a hook the template still wires (stale: %s)" % stale)
check(all(isinstance(v, str) and len(v) > 40 for v in g.EXCLUDED.values()), "every exclusion carries a written reason")

# Every kept template hook survives, rewritten and nothing else. Counted from
# the template, never from a list written here.
kept_tpl = [(ev, h["command"]) for ev, arr in t["hooks"].items() for m in arr for h in m["hooks"]
            if not (named(h["command"]) & set(g.EXCLUDED))]
want = sorted((ev, c.replace("$CLAUDE_PROJECT_DIR/", root + "/")) for ev, c in kept_tpl)
check(sorted(cmds) == want, "every non-excluded template hook is present, rewritten and otherwise byte-identical (%d of %d)" % (len(cmds), len(kept_tpl)))
sys.exit(1 if fails else 0)
PY
[ $? = 0 ] && PASS=$((PASS+1)) || FAIL=$((FAIL+1))

echo
echo "== 2. --check passes on the real skeleton =="
OUT="$(python3 "$GEN" --check 2>&1)"; RC=$?
[ "$RC" = "0" ] && ok "--check exits 0 on the real skeleton: $OUT" || bad "--check refused the real skeleton (rc=$RC): $OUT"

echo
echo "== 3. refusals, against a fake skeleton COPY =="
# fake_skel <name>: the generator and the real template, in the same layout, so
# the generator derives this root from its own location exactly as it does in
# the pinned checkout. Each case breaks one thing.
fake_skel() {
  local d="$WORK/$1"
  mkdir -p "$d/q-system/.q-system/scripts"
  cp "$GEN" "$d/q-system/.q-system/scripts/"
  cp "$TPL" "$d/settings-template.json"
  python3 - "$TPL" "$ROOT" "$d" <<'PY'
import json, os, re, shutil, sys
t, src, dst = sys.argv[1:]
for arr in json.load(open(t))["hooks"].values():
    for m in arr:
        for h in m["hooks"]:
            for rel in re.findall(r"\$CLAUDE_PROJECT_DIR/([\w./-]+\.(?:py|sh))", h["command"]):
                if os.path.isfile(os.path.join(src, rel)):
                    os.makedirs(os.path.dirname(os.path.join(dst, rel)), exist_ok=True)
                    shutil.copy2(os.path.join(src, rel), os.path.join(dst, rel))
PY
  printf '%s' "$d"
}
G="$(fake_skel good)"
python3 "$G/q-system/.q-system/scripts/skeleton-guard-settings.py" --check >/dev/null 2>&1 \
  && ok "control: an intact fake skeleton passes --check (so the refusals below mean something)" \
  || bad "control: the intact fake skeleton was refused, so every refusal below is unproven"
grep -q "$G/" <(python3 "$G/q-system/.q-system/scripts/skeleton-guard-settings.py") \
  && ok "the copy rewrites to ITS OWN root, not the tree it was copied from" \
  || bad "the copy did not rewrite to its own root"

# 3a. a guard the template wires is missing from the skeleton
M="$(fake_skel missing)"
rm -f "$M/q-system/.q-system/scripts/merge-bypass-gate.py"
OUT="$(python3 "$M/q-system/.q-system/scripts/skeleton-guard-settings.py" --check 2>&1)"; RC=$?
{ [ "$RC" != "0" ] && echo "$OUT" | grep -q 'merge-bypass-gate.py'; } \
  && ok "a wired guard absent from the skeleton refuses, naming it" \
  || bad "a missing guard did not refuse or did not name itself (rc=$RC): $OUT"
python3 "$M/q-system/.q-system/scripts/skeleton-guard-settings.py" >/dev/null 2>&1 \
  && bad "render printed a set although a guard does not resolve" \
  || ok "render fails closed too: no set is printed for an unresolvable skeleton"

# 3b. no template at all
N="$(fake_skel notemplate)"; rm -f "$N/settings-template.json"
python3 "$N/q-system/.q-system/scripts/skeleton-guard-settings.py" --check >/dev/null 2>&1 \
  && bad "a skeleton with no template passed --check" \
  || ok "no template refuses"

# 3c. a template whose hooks are all excluded renders nothing to supply
E="$(fake_skel empty)"
python3 - "$E/settings-template.json" <<'PY'
import json, sys
p = sys.argv[1]; t = json.load(open(p))
t["hooks"] = {"Stop": [{"hooks": [{"type": "command", "command": "bash \"$CLAUDE_PROJECT_DIR/q-system/hooks/stop-logger.sh\""}]}]}
json.dump(t, open(p, "w"))
PY
python3 "$E/q-system/.q-system/scripts/skeleton-guard-settings.py" --check >/dev/null 2>&1 \
  && bad "an empty guard set passed --check" \
  || ok "a set with no hooks left refuses (an empty set is no guard)"

# 3d. a root that would need shell quoting
Q="$WORK/has space"; mkdir -p "$Q"; cp -R "$G/." "$Q/"
python3 "$Q/q-system/.q-system/scripts/skeleton-guard-settings.py" --check >/dev/null 2>&1 \
  && bad "a root with a space passed; the rewritten commands would split on it" \
  || ok "a root with characters a hook command cannot carry unquoted refuses"

echo
echo "-------- $PASS passed, $FAIL failed --------"
[ "$FAIL" = "0" ]
