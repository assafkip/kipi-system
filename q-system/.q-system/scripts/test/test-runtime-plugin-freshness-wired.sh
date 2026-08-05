#!/usr/bin/env bash
# Pairs with detect_stale_runtime_plugins in
# q-system/.q-system/scripts/fleet-health-daily.py.
#
# Scar (codex review of PR #105, blocker, 2026-08-05): runtime-plugin-freshness.py
# shipped with its own green test and NO production caller. The capability gate
# ran the checker against fixtures and nothing ever pointed it at real runtime
# state, so a detector that could never fire read as protection.
#
# test-runtime-plugin-freshness.sh already covers the CHECKER. This file covers
# the thing that one structurally cannot: that the checker is REACHED from the
# unattended daily job, and that the reaching code turns a stale runtime into a
# finding. Deleting the DETECTORS entry must make this go red -- that is the
# whole point of a wiring test, and a suite where removing the call site stays
# green is the defect this repo keeps re-finding.
#
# Hermetic: builds its own plugin root under mktemp and points the detector at it
# by monkeypatching the checker module's DEFAULT_PLUGIN_ROOT. Nothing here reads
# the real ~/.claude/plugins and nothing reaches the network.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  ok   - $1"; }
bad() { FAIL=$((FAIL+1)); echo "  FAIL - $1"; }

echo "== runtime-plugin-freshness is wired to the daily job =="

# ---------------------------------------------------------------------------
# 1. THE WIRING ITSELF. Registered in DETECTORS, with a callable detect.
# ---------------------------------------------------------------------------
WIRED="$(ROOT="$ROOT" python3 - <<'PY'
import importlib.util, os, sys
root = os.environ["ROOT"]
spec = importlib.util.spec_from_file_location(
    "fh", os.path.join(root, "q-system/.q-system/scripts/fleet-health-daily.py"))
fh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fh)
hits = [d for d in fh.DETECTORS if d.get("id") == "runtime-plugin-stale"]
if not hits:
    print("MISSING"); sys.exit(0)
d = hits[0]
if not callable(d.get("detect")):
    print("NOTCALLABLE"); sys.exit(0)
if d["detect"].__name__ != "detect_stale_runtime_plugins":
    print("WRONGFN"); sys.exit(0)
print("OK")
PY
)"
[ "$WIRED" = "OK" ] \
  && ok "runtime-plugin-stale is in DETECTORS and calls detect_stale_runtime_plugins" \
  || bad "the detector is NOT wired into the daily job (got '$WIRED') -- the checker has no production caller"

# ---------------------------------------------------------------------------
# 2. IT FIRES on a stale runtime, and 3. STAYS QUIET on a matching one.
#
# Both directions, because a detector that always fires and a detector that
# never fires are equally useless and only the pair tells them apart.
# ---------------------------------------------------------------------------
RESULT="$(ROOT="$ROOT" python3 - <<'PY'
import importlib.util, json, os, tempfile
from pathlib import Path

root = os.environ["ROOT"]
S = os.path.join(root, "q-system/.q-system/scripts")


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def build(plugin_root, installed_version, marketplace_version):
    """A plugin root shaped like the REAL producer.

    Shapes copied from the live files rather than invented: installed_plugins.json
    keys are '<name>@<marketplace>' mapping to a LIST of {scope, version}, and
    each marketplace plugin carries .claude-plugin/plugin.json with name+version.
    A fixture whose shape the producer never emits tests nothing.
    """
    p = Path(plugin_root)
    mk = p / "marketplaces" / "kipi" / "plugins" / "prd-os" / ".claude-plugin"
    mk.mkdir(parents=True)
    (mk / "plugin.json").write_text(
        json.dumps({"name": "prd-os", "version": marketplace_version}))
    (p / "installed_plugins.json").write_text(json.dumps(
        {"plugins": {"prd-os@kipi": [{"scope": "user", "version": installed_version}]}}))


out = {}
# label, installed, marketplace, extra source appended to the shim, corrupt-registry
CASES = (
    ("stale",  "0.1.0",  "0.16.6", "", False),
    ("fresh",  "0.16.6", "0.16.6", "", False),
    # A plugin commit that changes runtime code WITHOUT bumping a version: every
    # installed version matches, and the clone is still behind origin/main. The
    # detector dropped this signal entirely until codex round 2 caught it.
    # Unreadable state must not read as healthy state.
    ("broken", "0.16.6", "0.16.6", "", True),
    # Installed but retired from the marketplace: still loaded at runtime.
    ("retired", "0.16.6", "0.16.6", "", False),
)
for label, inst, mkt, extra, corrupt in CASES:
    with tempfile.TemporaryDirectory() as td:
        build(td, inst, mkt)
        if corrupt:
            (Path(td) / "installed_plugins.json").write_text("{not json at all")
        if label == "retired":
            # A plugin the registry still installs but the marketplace no longer
            # ships. Same producer shape, one extra key.
            reg = Path(td) / "installed_plugins.json"
            data = json.loads(reg.read_text())
            data["plugins"]["ghost-plugin@kipi"] = [{"scope": "user", "version": "0.4.0"}]
            reg.write_text(json.dumps(data))
        fh = load("fh", os.path.join(S, "fleet-health-daily.py"))
        # THE SEAM IS fh.HERE. The detector resolves the checker as
        # `HERE / "runtime-plugin-freshness.py"` and imports it fresh, so the
        # only way to aim it at a fixture is to hand it a directory holding a
        # copy whose DEFAULT_PLUGIN_ROOT points at that fixture. Stubbing the
        # seam rather than the real path is what keeps this off the live
        # ~/.claude/plugins -- a suite that is quiet because it happened to read
        # a healthy real runtime is not isolation.
        src = open(os.path.join(S, "runtime-plugin-freshness.py")).read().replace(
            'DEFAULT_PLUGIN_ROOT = Path.home() / ".claude" / "plugins"',
            f'DEFAULT_PLUGIN_ROOT = Path({td!r})')
        assert f'Path({td!r})' in src, "the DEFAULT_PLUGIN_ROOT patch did not apply"
        if extra:
            before = src
            src = src + extra
            assert src != before, "the shim override did not apply"
        shim = Path(td) / "shim"
        shim.mkdir()
        (shim / "runtime-plugin-freshness.py").write_text(src)
        fh.HERE = shim
        out[label] = fh.detect_stale_runtime_plugins(None)

# The missing-checker case needs no plugin root at all: point HERE at an empty dir.
with tempfile.TemporaryDirectory() as td:
    fh = load("fh", os.path.join(S, "fleet-health-daily.py"))
    empty = Path(td) / "empty"
    empty.mkdir()
    fh.HERE = empty
    out["nochecker"] = fh.detect_stale_runtime_plugins(None)


def sub(label):
    return out[label][0]["subject"] if out[label] else ""


print(json.dumps({
    "stale_count": len(out["stale"]),
    "stale_subject": sub("stale"),
    "stale_body_has_versions": bool(out["stale"]) and "0.16.6" in out["stale"][0]["body"] and "0.1.0" in out["stale"][0]["body"],
    "fresh_count": len(out["fresh"]),
    "broken_count": len(out["broken"]),
    "broken_subject": sub("broken"),
    "nochecker_count": len(out["nochecker"]),
    "nochecker_subject": sub("nochecker"),
    "retired_count": len(out["retired"]),
    "retired_subject": sub("retired"),
    "retired_names_ghost": bool(out["retired"]) and "ghost-plugin" in out["retired"][0]["body"],
}))
PY
)"
echo "    detector result: $RESULT"

get() { printf '%s' "$RESULT" | python3 -c "import json,sys;print(json.load(sys.stdin)['$1'])" 2>/dev/null; }

[ "$(get stale_count)" = "1" ] \
  && ok "a stale runtime produces exactly one finding" \
  || bad "a stale runtime produced $(get stale_count) findings (want 1) -- the detector cannot fire"

[ "$(get stale_subject)" = "runtime-plugin-freshness" ] \
  && ok "the finding carries the stable dedup subject" \
  || bad "subject was '$(get stale_subject)' -- an unstable subject files a new Linear issue every run"

[ "$(get stale_body_has_versions)" = "True" ] \
  && ok "the body names both the installed and the marketplace version" \
  || bad "the body does not name both versions, so the issue is not actionable"

[ "$(get fresh_count)" = "0" ] \
  && ok "a matching runtime produces NO finding" \
  || bad "a matching runtime still produced $(get fresh_count) findings -- the detector always fires, which is the same as never"

# --- unreadable state must not read as healthy state (codex round 2, major) --
[ "$(get broken_count)" = "1" ] \
  && ok "an unreadable plugin registry produces a finding, not silence" \
  || bad "malformed registry produced $(get broken_count) findings (want 1) -- silence is indistinguishable from healthy"

[ "$(get broken_subject)" = "runtime-plugin-freshness-unreadable" ] \
  && ok "the cannot-run finding has its own subject, so it cannot pose as a staleness verdict" \
  || bad "broken subject was '$(get broken_subject)'"

[ "$(get nochecker_count)" = "1" ] \
  && ok "a missing checker produces a finding, not silence" \
  || bad "a missing checker produced $(get nochecker_count) findings (want 1) -- the detector would disable itself quietly"

[ "$(get nochecker_subject)" = "runtime-plugin-freshness-unreadable" ] \
  && ok "the missing-checker finding uses the cannot-run subject" \
  || bad "nochecker subject was '$(get nochecker_subject)'"


# --- a retired plugin is still running code (codex round 4, major) -----------
[ "$(get retired_count)" = "1" ] \
  && ok "a plugin installed but absent from the marketplace produces a finding" \
  || bad "retired plugin produced $(get retired_count) findings (want 1) -- retired code keeps running unreported"

[ "$(get retired_names_ghost)" = "True" ] \
  && ok "the retired finding names the plugin" \
  || bad "the retired finding does not name the plugin, so it is not actionable"

# --- registry lists plugins, marketplace gone (round 9, major) ---------------
# Was folded into the no-registry SKIP, so it returned [] and read as healthy
# while those plugins keep loading from cache with nothing to compare against.
MKGONE="$(ROOT="$ROOT" python3 - <<'PY7'
import importlib.util, json, os, shutil, tempfile
from pathlib import Path
S=os.path.join(os.environ["ROOT"],"q-system/.q-system/scripts")
def load(n,p):
    sp=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m);return m
out={}
for label, installed in (("installed", {"prd-os@kipi":[{"scope":"user","version":"0.16.6"}]}),
                         ("none", {})):
    with tempfile.TemporaryDirectory() as td:
        rp=Path(td)
        (rp/"marketplaces"/"kipi").mkdir(parents=True)
        (rp/"installed_plugins.json").write_text(json.dumps({"plugins":installed}))
        fh=load("fh",os.path.join(S,"fleet-health-daily.py"))
        src=open(os.path.join(S,"runtime-plugin-freshness.py")).read().replace(
            'DEFAULT_PLUGIN_ROOT = Path.home() / ".claude" / "plugins"',
            f'DEFAULT_PLUGIN_ROOT = Path({td!r})')
        shim=rp/"shim"; shim.mkdir(); (shim/"runtime-plugin-freshness.py").write_text(src)
        fh.HERE=shim
        shutil.rmtree(rp/"marketplaces"/"kipi")     # marketplace gone
        f=fh.detect_stale_runtime_plugins(None)
        out[label]={"count":len(f),"subject":f[0]["subject"] if f else ""}
print(json.dumps(out))
PY7
)"
echo "    marketplace-gone result: $MKGONE"
mgget() { printf '%s' "$MKGONE" | python3 -c "import json,sys;print(json.load(sys.stdin)['$1']['$2'])" 2>/dev/null; }
[ "$(mgget installed count)" = "1" ] \
  && ok "plugins installed + marketplace missing produces a finding, not silence" \
  || bad "produced $(mgget installed count) findings (want 1) -- reported healthy with nothing to compare against"
[ "$(mgget installed subject)" = "runtime-plugin-freshness-unreadable" ] \
  && ok "it uses the cannot-run subject, not a staleness verdict" \
  || bad "subject was '$(mgget installed subject)'"
[ "$(mgget none count)" = "0" ] \
  && ok "nothing installed + marketplace missing stays silent (genuinely nothing to say)" \
  || bad "an uninstalled marketplace still fired -- that is noise on a clean box"

echo "  $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] || exit 1
