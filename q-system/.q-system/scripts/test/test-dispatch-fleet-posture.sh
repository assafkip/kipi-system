#!/usr/bin/env bash
# Pairs with: kipi-dispatch.sh, the FLEET POSTURE line (ASK-1176).
#
# WHY THIS EXISTS
# ---------------
# The dispatcher logged "2 of 25 registered repo(s) opted in for cross-repo
# dispatch" every cycle. 23 repos got no automated work, and the line read the
# same whether that was a deliberate containment or a default nobody revisited.
# Measured 2026-09-14 against the registry's 42 commits: none of the 23 was ever
# opted in, 2 carry a recorded ASK-842 decision (`enabled: false`), and 21 have
# no dispatch key at all. The registry already held that split; the log line
# collapsed it into one number.
#
# ASK-842 set the convention this test pins: an ABSENT dispatch key is a default,
# and a default is not a refusal. Only the JSON boolean `false` is a decision.
# So the line must count the two apart, and a newly registered repo (which
# kipi-new-instance.sh and registry.py add_instance both write with no dispatch
# key) must land in the default bucket, never in the decided one.
#
# THE ASSERTION IS ON THE REAL DISPATCHER'S LOG, not on a copy of its logic. The
# fixture drives kipi-dispatch.sh end to end with HOME, registry, cursor and turn
# lock redirected into a temp dir, so nothing live is read or written.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
DISPATCH="${KIPI_POSTURE_DISPATCH:-$ROOT/kipi-dispatch.sh}"

PASS=0
fail() { echo "FAIL: $1" >&2; exit 1; }
ok()   { PASS=$((PASS + 1)); echo "  ok: $1"; }

[ -f "$DISPATCH" ] || fail "kipi-dispatch.sh not found at $DISPATCH"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
G() { git -c user.email=t@t.t -c user.name=t "$@"; }

# --- the home repo ----------------------------------------------------------
# It needs a reachable origin/main or the stale-checkout refusal exits before the
# posture line is ever written. Same local-bare-origin shape as
# test-dispatch-client-refusal-after-hold.sh.
HOMEREPO="$WORK/kipi-system"
mkdir -p "$HOMEREPO"
git init -q "$HOMEREPO"
echo x > "$HOMEREPO/f.txt"
G -C "$HOMEREPO" add -A; G -C "$HOMEREPO" commit -q -m c1
git -C "$HOMEREPO" branch -M main
git -C "$HOMEREPO" remote add origin "https://github.com/assafkip/kipi-system.git"
git init -q --bare "$WORK/origin-kipi-system.git"
git -C "$WORK/origin-kipi-system.git" symbolic-ref HEAD refs/heads/main
git -C "$HOMEREPO" config "url.$WORK/origin-.insteadOf" "https://github.com/assafkip/"
git -C "$HOMEREPO" push -q -u origin main

# `kipi work` is a recorder; this suite asserts on the log, not on dispatch.
cat > "$HOMEREPO/kipi" <<'EOF'
#!/usr/bin/env bash
echo "no ready issues"
exit 0
EOF
chmod +x "$HOMEREPO/kipi"

# gh answers the questions preflight asks; every opted-in row below points at a
# path that does not exist, so preflight refuses it before any gh call matters.
STUB="$WORK/bin"; mkdir -p "$STUB"
printf '#!/usr/bin/env bash\nexit 0\n' > "$STUB/gh"
chmod +x "$STUB/gh"
export PATH="$STUB:$PATH"

run_dispatch() {  # run_dispatch <registry>
  mkdir -p "$WORK/home/.config/kipi"
  : > "$WORK/home/.config/kipi/dispatch.log"
  rm -f "$WORK/cursor" "$WORK/turn.lock"
  ( cd "$HOMEREPO" \
    && HOME="$WORK/home" KIPI_REPO="$HOMEREPO" \
       KIPI_DISPATCH_REGISTRY="$1" \
       KIPI_DISPATCH_CURSOR="$WORK/cursor" \
       KIPI_DISPATCH_TURNLOCK="$WORK/turn.lock" \
       KIPI_NOTIFY="/usr/bin/true" \
       bash "$DISPATCH" ) >>"$WORK/stdout.txt" 2>&1
  grep 'dispatch: [0-9]* of [0-9]* registered repo(s) opted in' "$WORK/home/.config/kipi/dispatch.log" | tail -1
}

# --- CASE 1: every row shape, counted -----------------------------------------
# Six rows, one per shape the reader has to classify:
#   on           enabled: true                      -> opted in
#   off          enabled: false + decision          -> decided off
#   absent       no dispatch key (a NEW repo's shape)-> default
#   absent2      no dispatch key                    -> default
#   str_true     enabled: "true"  (string)          -> default: not a boolean, not a decision
#   str_false    enabled: "false" (string)          -> default: same strictness on the false side
REG="$WORK/registry.json"
cat > "$REG" <<JSON
{"instances":[
  {"name":"on","path":"$WORK/nope/on","dispatch":{"enabled":true,"expected_remote":"https://github.com/assafkip/on.git"}},
  {"name":"off","path":"$WORK/nope/off","dispatch":{"enabled":false,"decision":"ASK-TEST","reason":"fixture"}},
  {"name":"absent","path":"$WORK/nope/absent"},
  {"name":"absent2","path":"$WORK/nope/absent2"},
  {"name":"str_true","path":"$WORK/nope/str_true","dispatch":{"enabled":"true"}},
  {"name":"str_false","path":"$WORK/nope/str_false","dispatch":{"enabled":"false"}}
]}
JSON
LINE="$(run_dispatch "$REG")"
[ -n "$LINE" ] || fail "the dispatcher wrote no posture line at all. stdout:
$(tail -15 "$WORK/stdout.txt" | sed 's/^/        /')
      log:
$(tail -15 "$WORK/home/.config/kipi/dispatch.log" | sed 's/^/        /')"
echo "  [ctx] $LINE"

printf '%s' "$LINE" | grep -q 'dispatch: 1 of 6 registered repo(s) opted in' \
  || fail "the opted-in count or the total moved: $LINE"
ok "the opted-in count still reads 1 of 6"

printf '%s' "$LINE" | grep -q '1 decided off' \
  || fail "THE LINE DOES NOT NAME THE DECIDED-OFF ROWS. One row carries enabled:false with a decision; the line cannot tell it from a default: $LINE"
ok "the row with a recorded decision is counted as decided off"

printf '%s' "$LINE" | grep -q '4 off by default' \
  || fail "THE DEFAULT BUCKET IS WRONG. Two absent keys and two string values are defaults, not decisions (ASK-842: only the JSON boolean false is a decision): $LINE"
ok "absent keys and non-boolean values are counted as defaults, never as decisions"

# --- CASE 2: the real registry, paths neutralized ------------------------------
# The expected counts are DERIVED from the registry that owns them, never typed
# here, so this case goes on meaning something after the next opt-in. Every path
# is rewritten into the temp dir so preflight refuses each row without touching a
# real repo.
REAL="$ROOT/instance-registry.json"
[ -f "$REAL" ] || fail "no registry at $REAL"
NEUTRAL="$WORK/real-neutral.json"
read -r R_TOTAL R_ON R_OFF R_DEFAULT < <(python3 - "$REAL" "$NEUTRAL" "$WORK/nope" <<'PY'
import json, sys
src, dst, nowhere = sys.argv[1], sys.argv[2], sys.argv[3]
data = json.load(open(src))
rows = data.get("instances", [])
on = off = 0
for i, row in enumerate(rows):
    row["path"] = "%s/row%d" % (nowhere, i)
    d = row.get("dispatch")
    enabled = d.get("enabled") if isinstance(d, dict) else None
    if enabled is True:
        on += 1
    elif enabled is False:
        off += 1
json.dump(data, open(dst, "w"))
print(len(rows), on, off, len(rows) - on - off)
PY
)
[ "${R_TOTAL:-0}" -gt 0 ] || fail "derived zero rows from $REAL; every check below would be a no-op"
LINE2="$(run_dispatch "$NEUTRAL")"
echo "  [ctx] real registry: $LINE2"
printf '%s' "$LINE2" | grep -q "dispatch: $R_ON of $R_TOTAL registered repo(s) opted in" \
  || fail "real registry: expected $R_ON of $R_TOTAL opted in: $LINE2"
printf '%s' "$LINE2" | grep -q "$R_OFF decided off" \
  || fail "real registry: expected $R_OFF decided off: $LINE2"
printf '%s' "$LINE2" | grep -q "$R_DEFAULT off by default" \
  || fail "real registry: expected $R_DEFAULT off by default: $LINE2"
ok "real registry: $R_ON on, $R_OFF decided off, $R_DEFAULT off by default, of $R_TOTAL"

echo "PASS ($PASS checks) test-dispatch-fleet-posture.sh"
