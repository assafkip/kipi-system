#!/usr/bin/env bash
# Reproducer for ASK-362 stage 2's switch: WHICH identity posts
# kipi/reviewer-approved.
#
# THE DEFECT. The reviewer posts its status with the ambient `gh` login, which
# is the same admin token that authors every PR and arms every merge. So the
# identity that merges can also write the gate that is supposed to hold it
# (sp-c442613c). The platform fix is a second identity (a GitHub App or a
# machine user) and pinning the required context to it. That needs the identity
# to exist first. This suite pins the half that lives in code: the status POST
# can be sent through a DIFFERENT token chosen by environment, so moving the
# gate off the admin token is one secret, not a code change.
#
# THE CONTRACT, three cases:
#   1. KIPI_REVIEWER_TOKEN_ENV unset  -> today's behaviour, ambient gh auth.
#   2. set, and the named var holds a token -> the statuses POST carries THAT
#      token as GH_TOKEN, and only that call does.
#   3. set, and the named var is empty -> REFUSE. No status is posted at all.
#      Falling back to the ambient login would silently put the gate back on
#      the admin token while the operator believes it moved.
#
# Driven end to end: the REAL pr-review-agent.sh, --post, a stub `claude` that
# returns a REAL captured review (fixtures/pr-verdict/real-review-request-
# changes.md, a live 8-minute review of PR #74), and a stub `gh` that logs the
# GH_TOKEN each call carried. Never the live API.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
SRC_DIR="$ROOT/q-system/.q-system/scripts"
FIXTURE="$SRC_DIR/test/fixtures/pr-verdict/real-review-request-changes.md"

PASS=0
fail() { echo "FAIL: $1" >&2; exit 1; }
ok()   { PASS=$((PASS + 1)); echo "  ok: $1"; }

[ -f "$SRC_DIR/pr-review-agent.sh" ] || fail "pr-review-agent.sh missing at $SRC_DIR"
[ -s "$FIXTURE" ] || fail "the captured review fixture is missing: $FIXTURE"
REAL_GIT="$(command -v git)" || fail "git not on PATH"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
unset KIPI_TARGET_REPO KIPI_REVIEW_ENGINE KIPI_REVIEWER_TOKEN_ENV GH_TOKEN GITHUB_TOKEN 2>/dev/null || true

G() { git -c user.email=t@t.t -c user.name=t "$@"; }
STUB="$WORK/bin"; mkdir -p "$STUB" "$WORK/home"

# One repo, its own bare origin, the agent and its libs copied in, so the
# reviewer never resolves the checkout this suite runs from.
git init -q --bare "$WORK/origin-homerepo.git"
git -C "$WORK/origin-homerepo.git" symbolic-ref HEAD refs/heads/main
mkdir -p "$WORK/skel/q-system/.q-system/scripts"
git init -q "$WORK/skel"
git -C "$WORK/skel" config "url.$WORK/origin-.insteadOf" "https://github.com/owner/"
cp "$SRC_DIR/pr-review-agent.sh" "$SRC_DIR/pr-verdict-lib.sh" "$SRC_DIR/repo-slug-lib.sh" \
   "$SRC_DIR/env-failure-lib.sh" "$SRC_DIR/reviewer-token-lib.sh" \
   "$WORK/skel/q-system/.q-system/scripts/"
G -C "$WORK/skel" add -A; G -C "$WORK/skel" commit -q -m "c1"
git -C "$WORK/skel" branch -M main
git -C "$WORK/skel" remote add origin "https://github.com/owner/homerepo.git"
git -C "$WORK/skel" push -q -u origin main
SHA="$(git -C "$WORK/skel" rev-parse HEAD)"
AGENT="$WORK/skel/q-system/.q-system/scripts/pr-review-agent.sh"

GH_LOG="$WORK/gh.txt"
cat > "$STUB/gh" <<EOF
#!/usr/bin/env bash
printf '%s\t%s\n' "\${GH_TOKEN:-<ambient>}" "\$*" >> "$GH_LOG"
case "\$*" in
  *"pr view"*"headRefOid"*) printf '%s\t%s\n' "$SHA" "PR 42 (ASK-AAA)" ;;
  *"pr diff"*)              echo "diff --git a/x b/x" ;;
  *"pr comment"*)           echo "https://github.com/owner/homerepo/pull/42#issuecomment-1" ;;
  *"api"*)                  echo '{}' ;;
esac
exit 0
EOF
cat > "$STUB/claude" <<EOF
#!/usr/bin/env bash
cat "$FIXTURE"
exit 0
EOF
printf '#!/usr/bin/env bash\necho "STUB codex ran"\nexit 0\n' > "$STUB/codex"
chmod +x "$STUB/gh" "$STUB/claude" "$STUB/codex"
export PATH="$STUB:$PATH"
[ "$(command -v git)" = "$REAL_GIT" ] || fail "git was shadowed by a stub"

RC=0
run_agent() {  # run_agent <out> [VAR=value ...]
  local out="$1"; shift
  : > "$GH_LOG"
  ( cd "$WORK/skel" \
    && env HOME="$WORK/home" KIPI_STATE_DIR="$WORK/state" KIPI_NOTIFY="/usr/bin/true" \
       "$@" bash "$AGENT" 42 --issue ASK-AAA --post ) >"$out" 2>&1
  RC=$?
}
status_posts() { awk -F'\t' '$2 ~ /statuses\// {print $1}' "$GH_LOG"; }

# --- 1. default: unchanged ---------------------------------------------------
run_agent "$WORK/run1.out"
S1="$(status_posts)"
[ -n "$S1" ] \
  || fail "the default run posted NO commit status (rc=$RC), so this fixture cannot judge who posts it.
      gh calls:
$(sed 's/^/        /' "$GH_LOG")
      output tail:
$(tail -15 "$WORK/run1.out" | sed 's/^/        /')"
[ "$S1" = "<ambient>" ] \
  || fail "with no identity configured the status POST carried a token '$S1'; the default must stay the ambient gh login"
ok "default: the status is posted with the ambient gh login, exactly as before"

# --- 2. selected and present: THAT token, on the status call only -------------
run_agent "$WORK/run2.out" KIPI_REVIEWER_TOKEN_ENV=KIPI_TEST_REVIEWER_TOKEN KIPI_TEST_REVIEWER_TOKEN=tok-reviewer-identity
S2="$(status_posts)"
[ "$S2" = "tok-reviewer-identity" ] \
  || fail "THE DEFECT: KIPI_REVIEWER_TOKEN_ENV named a reviewer token and the statuses POST carried
      '${S2:-<no status posted>}'. The gate is still written by whatever identity gh is logged in as.
      gh calls:
$(sed 's/^/        /' "$GH_LOG")"
OTHER="$(awk -F'\t' '$2 !~ /statuses\// && $1 != "<ambient>"' "$GH_LOG")"
[ -z "$OTHER" ] \
  || fail "the reviewer token leaked onto calls that are not the status POST:
$(printf '%s\n' "$OTHER" | sed 's/^/        /')"
ok "configured: the status POST, and only it, carries the reviewer identity's token"

# --- 3. selected and absent: refuse, never fall back --------------------------
run_agent "$WORK/run3.out" KIPI_REVIEWER_TOKEN_ENV=KIPI_TEST_REVIEWER_TOKEN
S3="$(status_posts)"
[ -z "$S3" ] \
  || fail "SILENT FALLBACK: the reviewer identity was configured but its token is empty, and the
      status was posted anyway with '$S3'. The operator believes the gate moved off the admin
      token; it did not. gh calls:
$(sed 's/^/        /' "$GH_LOG")"
grep -q 'KIPI_TEST_REVIEWER_TOKEN' "$WORK/run3.out" \
  || fail "the refusal does not name the empty variable, so nobody can tell what to fix. Output:
$(tail -15 "$WORK/run3.out" | sed 's/^/        /')"
ok "configured but empty: no status is posted, and the refusal names the missing variable"

# --- 4. ASK-318: a caller-pinned head that is not the PR's head -------------
run_agent "$WORK/run4.out" KIPI_REVIEW_EXPECT_HEAD=0123456789abcdef0123456789abcdef01234567
S4="$(status_posts)"
[ -z "$S4" ] \
  || fail "ASK-318 PR #437 major: the caller verified a different head and the agent posted a status anyway ('$S4').
$(tail -8 "$WORK/run4.out" | sed 's/^/        /')"
grep -c 'KIPI_REVIEW_EXPECT_HEAD' "$WORK/run4.out" >/dev/null \
  || fail "the head-mismatch refusal does not name KIPI_REVIEW_EXPECT_HEAD:
$(tail -8 "$WORK/run4.out" | sed 's/^/        /')"
ok "a head other than the one the caller verified: refused, no status posted"
run_agent "$WORK/run5.out" KIPI_REVIEW_EXPECT_HEAD="$SHA"
[ -n "$(status_posts)" ] || fail "the matching pinned head was refused; the pin must only refuse a DIFFERENT head"
ok "the head the caller verified: reviewed and posted as usual"

echo "PASS: $PASS/5 reviewer-status identity checks"
