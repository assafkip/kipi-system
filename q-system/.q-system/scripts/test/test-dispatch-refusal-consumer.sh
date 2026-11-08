#!/usr/bin/env bash
# ASK-3958: A PREFLIGHT REFUSAL THAT DOES NOT HEAL GETS ONE CONSUMER, AT 12H.
#
# Before this, pick_list() logged "preflight REFUSED" once per tick and did
# nothing else. Measured: 469 identical lines for one repo in one run, and no
# ticket. Through the REAL dispatcher, with the REAL repo-preflight.sh:
#
#   1. a repo whose pin does not match its origin (check `remote`) is refused,
#      and the first refused tick files nothing;
#   2. 11h later, still refused: nothing filed (the mutant that fires early);
#   3. 13h after the first refusal: ONE alert naming the repo and the check;
#   4. a further refused tick inside the re-ping window files nothing more;
#   5. the pin is fixed, the repo passes: its refusal row and page key are gone.
#
# THE ASSERTION IS ON WHAT THE NOTIFIER RECEIVED, not on a log line. KIPI_NOTIFY
# is a recorder, so "did the dispatcher file it" is answered by a file. The clock
# is KIPI_DISPATCH_NOW, read only by dispatch-refusals.py.
#
# The repo fixtures and the gh stub are the ones test-dispatch-client-refusal-
# after-hold.sh builds, for the reasons its comments give.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
DISPATCH="$ROOT/kipi-dispatch.sh"

PASS=0
fail() { echo "FAIL: $1" >&2; exit 1; }
ok()   { PASS=$((PASS + 1)); echo "  ok: $1"; }

[ -f "$DISPATCH" ] || fail "kipi-dispatch.sh not found at $DISPATCH"
REAL_GIT="$(command -v git)" || fail "git not on PATH"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
G() { git -c user.email=t@t.t -c user.name=t "$@"; }

# --- the three repos --------------------------------------------------------
# CLIENT path shape is what check 0 keys on: <root>/consulting/projects/<thing>.
# Derived from shape, never from a list of client names, so this fixture is the
# same fact the shipping check reads.
HOMEREPO="$WORK/kipi-system"
PLAIN="$WORK/otherorg/projects/plainrepo"

# EVERY ORIGIN IS A LOCAL BARE REPO reached through insteadOf. The first cut gave
# the fixture a real https://github.com/... origin; the dispatcher's stale-checkout
# refusal then compared it against the REAL kipi-system main and reported "origin
# /main holds 1030 commit(s) this checkout lacks", so the run refused before
# pick_list and the suite proved nothing. The URL still has to READ as github.com
# because repo-preflight.sh derives its slug from it.
# ONLY THE HOME REPO GETS insteadOf. It needs a reachable origin/main or the
# dispatcher's stale-checkout refusal fires before pick_list ever runs. The two
# TARGETS must NOT have it: repo-preflight.sh check 4 compares
# `git remote get-url origin` against the registry's pin, and get-url APPLIES
# insteadOf rewriting -- so the rewrite made check 4 report
# "origin is <local path> but the registry pins https://github.com/...".
# That is not a fixture quirk, it is a live defect in preflight on any box that
# rewrites github.com to a mirror (captured as sp-72ee0308). Here the targets
# simply keep an unrewritten github URL; nothing fetches them.
mkrepo() {  # mkrepo <dir> <name> <rewrite:0|1>
  mkdir -p "$1"
  git init -q "$1"
  echo x > "$1/f.txt"
  G -C "$1" add -A; G -C "$1" commit -q -m c1
  git -C "$1" branch -M main
  git -C "$1" remote add origin "https://github.com/assafkip/$2.git"
  if [ "$3" = "1" ]; then
    git init -q --bare "$WORK/origin-$2.git"
    git -C "$WORK/origin-$2.git" symbolic-ref HEAD refs/heads/main
    git -C "$1" config "url.$WORK/origin-.insteadOf" "https://github.com/assafkip/"
    git -C "$1" push -q -u origin main
  fi
}
mkrepo "$HOMEREPO" kipi-system 1
mkrepo "$PLAIN"    plainrepo    0

# The dispatcher runs `bash ./kipi work $WORK_ARGS` from $REPO. This recorder IS
# the assertion surface: argv is what it DID.
cat > "$HOMEREPO/kipi" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$WORK/kipi-calls.txt"
echo "no ready issues"
exit 0
EOF
chmod +x "$HOMEREPO/kipi"
: > "$WORK/kipi-calls.txt"

# The dispatcher resolves the preflight off $REPO, so the fixture home repo has
# to carry the REAL one -- a stub here would test nothing. PLAIN and CLIENT must
# then clear every check, which means the same wired hook scripts as the home
# fixture. Copying the same tree into all three is the simplest way to get there.
# (The worker copy is still copied; since check 2 was retired it is not needed.)
seed_control_code() {  # seed_control_code <repo>
  mkdir -p "$1/q-system/.q-system/scripts" "$1/.claude"
  cp "$ROOT/q-system/.q-system/scripts/repo-preflight.sh" \
     "$ROOT/q-system/.q-system/scripts/linear-worker.sh" "$1/q-system/.q-system/scripts/"
  printf '{"hooks":{}}\n' > "$1/.claude/settings.json"
  G -C "$1" add -A; G -C "$1" commit -q -m "control code"
  # Only the home repo has a reachable origin; the targets are never fetched.
  git -C "$1" push -q origin main 2>/dev/null || true
}
seed_control_code "$HOMEREPO"
seed_control_code "$PLAIN"

# --- gh, stubbed so checks 6 and 7 can be answered offline -------------------
# NOT a blanket exit 0: check 7 is the one that matters most for a client repo,
# and a stub that made everything pass would let this suite go green against a
# dispatcher with no branch-protection check at all. It answers only the two
# questions preflight asks, and answers them truthfully for the fixture.
STUB="$WORK/bin"; mkdir -p "$STUB"
cat > "$STUB/gh" <<'GHEOF'
#!/usr/bin/env bash
case "$*" in
  "auth status"*)            exit 0 ;;
  "repo view"*)              echo "ok"; exit 0 ;;
  *"/branches/"*"/protection") echo '{"required_pull_request_reviews":{},"required_status_checks":{"contexts":["kipi/reviewer-approved"]}}'; exit 0 ;;
  "api repos/"*)             echo "main"; exit 0 ;;
esac
exit 0
GHEOF
chmod +x "$STUB/gh"
export PATH="$STUB:$PATH"

# One opted-in repo whose registry pin names a DIFFERENT repo than its origin, so
# preflight check `remote` refuses it on every tick, deterministically.
REG="$WORK/registry.json"
write_reg() {  # write_reg <pinned remote>
  cat > "$REG" <<JSON
{"instances":[
  {"name":"plainrepo","path":"$PLAIN","has_git":true,
   "dispatch":{"enabled":true,"expected_remote":"$1"}}
]}
JSON
}
write_reg "https://github.com/assafkip/not-plainrepo.git"

# The consumer under test lives beside the preflight in the fixture home repo,
# which is where the dispatcher resolves it ($REPO/q-system/.q-system/scripts).
cp "$ROOT/q-system/.q-system/scripts/dispatch-refusals.py" "$HOMEREPO/q-system/.q-system/scripts/"

NOTES="$WORK/notify-calls.txt"; : > "$NOTES"
cat > "$WORK/notify" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$1" >> "$NOTES"
exit 0
EOF
chmod +x "$WORK/notify"

mkdir -p "$WORK/home/.config/kipi"
DLOG="$WORK/home/.config/kipi/dispatch.log"
STATE="$WORK/home/.config/kipi/dispatch-refusals.tsv"
MARK="$WORK/home/.config/kipi/paged-preflight-plainrepo-remote"
T0=1800000000
# LIVE_PATTERN is pinned to a name no process has. The default counts every live
# converge on the machine running the suite, and a busy fleet made the first cut
# exit at "skip: 2 converge run(s) live" before pick_list ever ran.
run_dispatch() {  # run_dispatch <epoch>
  ( cd "$HOMEREPO" \
    && HOME="$WORK/home" KIPI_REPO="$HOMEREPO" \
       KIPI_DISPATCH_REGISTRY="$REG" \
       KIPI_DISPATCH_TARGETS="" \
       KIPI_DISPATCH_CURSOR="$WORK/cursor" \
       KIPI_DISPATCH_TURNLOCK="$WORK/turn.lock" \
       KIPI_NOTIFY="$WORK/notify" \
       KIPI_DISPATCH_NOW="$1" \
       KIPI_DISPATCH_LIVE_PATTERN="no-such-process-refusal-consumer-$$" \
       bash "$DISPATCH" ) >>"$WORK/stdout.txt" 2>&1
}
filed() { grep -c "refused plainrepo .* on check 'remote'" "$NOTES" 2>/dev/null || true; }
ctx() { echo "      notify calls:"; cut -c1-200 "$NOTES" | tail -5 | sed 's/^/        /'
        echo "      log:"; tail -8 "$DLOG" 2>/dev/null | cut -c1-200 | sed 's/^/        /'; }

# --- 1. refused, first tick: nothing filed ---------------------------------
run_dispatch "$T0"
grep -q "preflight REFUSED plainrepo" "$DLOG" \
  || { ctx; fail "the fixture repo was not refused, so nothing below tests a refusal"; }
grep -q "FAIL remote" "$DLOG" || { ctx; fail "the refusal is not the remote check the fixture sets up"; }
[ "$(filed)" = 0 ] || { ctx; fail "a FIRST refusal filed an alert; the consumer must wait 12h"; }
ok "a first refusal is logged and files nothing"

# --- 2. 11h later, still refused: nothing filed ------------------------------
run_dispatch "$((T0 + 11 * 3600))"
[ "$(filed)" = 0 ] || { ctx; fail "an 11h refusal filed an alert; that would file every measured transient"; }
ok "an 11h refusal files nothing"

# --- 3. 13h: ONE alert, naming the repo and the check ------------------------
run_dispatch "$((T0 + 13 * 3600))"
[ "$(filed)" = 1 ] || { ctx; fail "a 13h refusal filed $(filed) alert(s), want exactly 1"; }
[ -f "$MARK" ] || { ctx; fail "no page key at $MARK, so a pass has nothing to clear"; }
ok "a 13h refusal files one alert naming plainrepo and check 'remote'"

# --- 4. still refused, inside the re-ping window: no second alert ------------
run_dispatch "$((T0 + 14 * 3600))"
[ "$(filed)" = 1 ] || { ctx; fail "a repeat tick filed again ($(filed) alerts); one per state, not one per tick"; }
ok "a repeat refused tick files nothing more"

# --- 5. fixed: the pass clears the row and the key ---------------------------
write_reg "https://github.com/assafkip/plainrepo.git"
BEFORE="$(wc -l < "$DLOG")"
run_dispatch "$((T0 + 15 * 3600))"
# Only this run's lines: the earlier refused ticks are still in the log.
tail -n +"$((BEFORE + 1))" "$DLOG" | grep -q "entering plainrepo" \
  || { ctx; fail "the fixed repo was not entered, so the clear path was never reached"; }
grep -qF "plainrepo	" "$STATE" 2>/dev/null && { ctx; fail "the pass left plainrepo's refusal row in $STATE"; }
[ -f "$MARK" ] && { ctx; fail "the pass left the page key, so a recurrence inside 24h would be swallowed"; }
ok "a pass clears the refusal row and the page key"

# --- 6. nothing leaked into the rotation -------------------------------------
# pick_list's stdout IS the rotation; a stray DUE/CLEARED line would be a repo.
grep -qE "entering (DUE|CLEARED)" "$DLOG" && { ctx; fail "a refusal_note line leaked into pick_list's stdout"; }
ok "no refusal_note output reached the rotation"

echo "PASS ($PASS checks) test-dispatch-refusal-consumer.sh"
