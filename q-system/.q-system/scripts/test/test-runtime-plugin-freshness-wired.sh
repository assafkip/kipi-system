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
for label, inst, mkt in (("stale", "0.1.0", "0.16.6"), ("fresh", "0.16.6", "0.16.6")):
    with tempfile.TemporaryDirectory() as td:
        build(td, inst, mkt)
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
        shim = Path(td) / "shim"
        shim.mkdir()
        (shim / "runtime-plugin-freshness.py").write_text(src)
        fh.HERE = shim
        out[label] = fh.detect_stale_runtime_plugins(None)

print(json.dumps({
    "stale_count": len(out["stale"]),
    "stale_subject": out["stale"][0]["subject"] if out["stale"] else "",
    "stale_body_has_versions": bool(out["stale"]) and "0.16.6" in out["stale"][0]["body"] and "0.1.0" in out["stale"][0]["body"],
    "fresh_count": len(out["fresh"]),
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

echo "  $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] || exit 1
