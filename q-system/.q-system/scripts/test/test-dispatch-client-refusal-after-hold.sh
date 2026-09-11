#!/usr/bin/env bash
# THE GUARD THAT REPLACES THE HOLD (ASK-738 + ASK-741).
#
# kipi-dispatch.sh used to refuse EVERY non-home repo unconditionally
# ("HOLD ...: cross-repo gh scoping is unfinished", sp-9421b9b7). ASK-738 fixed
# the gh scoping and removed that line. The HOLD was also, incidentally, the
# thing standing between an unattended self-merging loop and twelve client
# engagement repos -- so removing it moves that job onto repo-preflight.sh
# check 0 alone (ASK-741, PR #144).
#
# Founder decision 2026-08-13, verbatim: "no. unattended agents should not reach
# a client repo."
#
# So this test asserts BOTH directions through the REAL dispatcher, because
# either one alone is worthless:
#
#   1. a client-shaped repo, OPTED IN with dispatch.enabled: true, is refused and
#      never reaches `kipi work`;
#   2. an ordinary opted-in repo IS entered, with --repo pointing at it.
#
# Without (2) this suite would pass on a dispatcher that refuses everything --
# which is exactly what the HOLD did, and it would report "client repos are
# protected" while the whole feature was dead. Without (1) the founder's
# constraint is unenforced. The pair is the test.
#
# THE ASSERTION IS ON WHAT `kipi work` WAS CALLED WITH, not on a log line. A log
# line is what the dispatcher SAYS; argv is what it DID. The fixture's `kipi` is a
# recorder, so "did the client path ever reach the worker" is answered by a file.
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
CLIENT="$WORK/consulting/projects/alice"
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
mkrepo "$CLIENT"   alice        0
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
# to carry the REAL one -- a stub here would test nothing. PLAIN must then CLEAR
# all seven checks, which means it needs byte-identical control code and the same
# wired hook scripts. Copying the same tree into both is the only way to satisfy
# a check whose whole point is byte equality.
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
seed_control_code "$CLIENT"

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

# --- both non-home rows OPTED IN. That is the point: enabled is not consent. ---
REG="$WORK/registry.json"
cat > "$REG" <<JSON
{"instances":[
  {"name":"alice","path":"$CLIENT","has_git":true,
   "dispatch":{"enabled":true,"expected_remote":"https://github.com/assafkip/alice.git"}},
  {"name":"plainrepo","path":"$PLAIN","has_git":true,
   "dispatch":{"enabled":true,"expected_remote":"https://github.com/assafkip/plainrepo.git"}}
]}
JSON

# --- CASE 0, NEGATIVE SELF-TEST: check 0 fires on the fixture's own shape -----
# If the client path does not trip the preflight directly, nothing below means
# anything -- the dispatcher would be refusing it for some unrelated reason.
PF_OUT="$(bash "$ROOT/q-system/.q-system/scripts/repo-preflight.sh" "$CLIENT" "https://github.com/assafkip/alice.git" 2>&1)"
PF_RC=$?
printf '%s' "$PF_OUT" | grep -q '^FAIL client-repo:' \
  || fail "negative self-test: repo-preflight.sh did not refuse the client-shaped fixture $CLIENT as a client repo (rc=$PF_RC). It said:
$(printf '%s' "$PF_OUT" | sed 's/^/        /')"
[ "$PF_RC" -ne 0 ] || fail "negative self-test: the client refusal printed but exited 0"
ok "negative self-test: check 0 refuses $CLIENT by path shape (rc=$PF_RC)"

# --- CASE 0b: and it does NOT refuse the ordinary repo as a client -----------
# A check that refused everything would satisfy case 1 while being useless.
PF_PLAIN="$(bash "$ROOT/q-system/.q-system/scripts/repo-preflight.sh" "$PLAIN" "https://github.com/assafkip/plainrepo.git" 2>&1)"
printf '%s' "$PF_PLAIN" | grep -q '^FAIL client-repo:' \
  && fail "check 0 called the ORDINARY repo $PLAIN a client engagement repo; the shape rule is over-broad"
ok "negative self-test: check 0 does not fire on the ordinary repo"

# --- the dispatcher run -----------------------------------------------------
# HOME, registry, cursor and turn lock all redirected into the temp dir so this
# cannot touch the founder's live dispatch state.
run_dispatch() {
  ( cd "$HOMEREPO" \
    && HOME="$WORK/home" KIPI_REPO="$HOMEREPO" \
       KIPI_DISPATCH_REGISTRY="$REG" \
       KIPI_DISPATCH_CURSOR="$WORK/cursor" \
       KIPI_DISPATCH_TURNLOCK="$WORK/turn.lock" \
       KIPI_NOTIFY="/usr/bin/true" \
       bash "$DISPATCH" ) >>"$WORK/stdout.txt" 2>&1
}
mkdir -p "$WORK/home/.config/kipi"
DLOG="$WORK/home/.config/kipi/dispatch.log"
: > "$WORK/stdout.txt"
# Several cycles: the rotation hands the turn on each time, so every row gets a
# turn rather than the first one pinning the loop.
for _ in 1 2 3 4; do run_dispatch; done

echo "  [ctx] kipi work was called with:"
sed 's/^/        /' "$WORK/kipi-calls.txt" 2>/dev/null | head -10
echo "  [ctx] dispatcher said:"
grep -E 'REFUSED|entering|HOLD|client engagement' "$DLOG" 2>/dev/null | sed 's/^/        /' | head -8

# --- 1. THE CLIENT REPO NEVER REACHED THE WORKER ----------------------------
if grep -q -- "$CLIENT" "$WORK/kipi-calls.txt" 2>/dev/null; then
  fail "CLIENT REPO ENTERED: \`kipi work\` was invoked with the client engagement repo $CLIENT.
      Founder decision 2026-08-13: unattended agents must not reach a client repo.
      calls: $(tr '\n' ' ' < "$WORK/kipi-calls.txt")"
fi
ok "the opted-in CLIENT repo never reached kipi work"

# --- 2. and the dispatcher said why, in the digest's shape ------------------
# A silent refusal is indistinguishable from an empty queue (ASK-741).
grep -q 'client engagement repos' "$DLOG" \
  || fail "the dispatcher refused the client repo without saying so; the daily digest scrapes this line, so the refusal is invisible to the founder.
$(tail -15 "$DLOG" | sed 's/^/        /')"
ok "the refusal is stated in the log in the digest's own shape"

# --- 3. THE ORDINARY REPO IS ACTUALLY ENTERED -------------------------------
# Without this the suite would pass on a dispatcher that refuses everything --
# which is precisely what the HOLD did while reporting healthy.
grep -q -- "--repo $PLAIN" "$WORK/kipi-calls.txt" 2>/dev/null \
  || fail "THE HOLD IS EFFECTIVELY STILL THERE: the ordinary opted-in repo $PLAIN was never dispatched with --repo.
      Cross-repo dispatch is the whole point of ASK-738; a suite green on refusal alone would hide that it does nothing.
      calls: $(tr '\n' ' ' < "$WORK/kipi-calls.txt")
      log:
$(tail -20 "$DLOG" | sed 's/^/        /')"
ok "the ordinary opted-in repo IS entered, with --repo pointing at it"

# --- 4. no HOLD line survives anywhere --------------------------------------
grep -q 'cross-repo gh scoping is unfinished' "$DLOG" \
  && fail "the dispatcher still emits the sp-9421b9b7 HOLD; ASK-738 was supposed to remove it"
ok "the sp-9421b9b7 HOLD no longer fires"

echo "PASS ($PASS checks) test-dispatch-client-refusal-after-hold.sh"
