#!/usr/bin/env bash
# Reproducer + acceptance for call site 2 of ASK-738: converge.sh resolves the
# PR from the CWD's repo, not from the repo the work is in.
#
# THE DEFECT: converge.sh:68
#   pr_for_branch() { gh pr list --head "$BRANCH" --json number -q '.[0].number'; }
# runs with no `cd` and no `-R`, so it inherits kipi-dispatch.sh's cwd (the home
# checkout, kipi-dispatch.sh:205). After linear-worker.sh opens a PR in the
# TARGET repo, converge asks the HOME repo whether that branch has a PR, gets
# nothing, and stops -- the convergence loop never runs a second round on any
# repo but its own. `pr_head_sha` (pr-verdict-lib.sh) has the same shape.
#
# WHY --dry IS THE DRIVER. --dry is the shortest path that calls pr_for_branch
# for real, with no agent spend and no network. The subject is which repository
# the call resolves to, and --dry resolves it exactly the way a live round does
# because it is the same function.
#
# NEGATIVE SELF-TEST (case 0) proves the fake gh reports the HOME slug from the
# home checkout before any assertion below is trusted.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
CONVERGE="$ROOT/q-system/.q-system/scripts/converge.sh"

PASS=0
fail() { echo "FAIL: $1" >&2; exit 1; }
ok()   { PASS=$((PASS + 1)); echo "  ok: $1"; }

[ -f "$CONVERGE" ] || fail "converge.sh does not exist at $CONVERGE"
REAL_GIT="$(command -v git)" || fail "git not on PATH"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
unset KIPI_TARGET_REPO KIPI_LINEAR_CLAIMS 2>/dev/null || true

G() { git -c user.email=t@t.t -c user.name=t "$@"; }
STUB="$WORK/bin"; mkdir -p "$STUB" "$WORK/home"

HOME_SLUG="assafkip/homerepo"
TARGET_SLUG="assafkip/targetrepo"

mkrepo() {  # mkrepo <dir> <name>  -- github-shaped origin, local transport
  git init -q --bare "$WORK/origin-$2.git"
  git -C "$WORK/origin-$2.git" symbolic-ref HEAD refs/heads/main
  git init -q "$1"
  git -C "$1" config "url.$WORK/origin-.insteadOf" "https://github.com/assafkip/"
  G -C "$1" commit -q --allow-empty -m c1
  git -C "$1" branch -M main
  git -C "$1" remote add origin "https://github.com/assafkip/$2.git"
  git -C "$1" push -q -u origin main
}
mkrepo "$WORK/skel"   homerepo
mkrepo "$WORK/target" targetrepo

GH_LOG="$WORK/gh-resolved.txt"; : > "$GH_LOG"
cat > "$STUB/gh" <<EOF
#!/usr/bin/env bash
R=""; prev=""
for a in "\$@"; do
  case "\$prev" in -R|--repo) R="\$a" ;; esac
  prev="\$a"
done
if [ -z "\$R" ]; then
  # config --get, not \`remote get-url\`: get-url applies insteadOf rewriting.
  url="\$("$REAL_GIT" config --get remote.origin.url 2>/dev/null)"
  R="\${url#https://github.com/}"; R="\${R%.git}"
  [ "\$R" = "\$url" ] && R="UNRESOLVED"
fi
printf '%s\t%s\n' "\$R" "\$*" >> "$GH_LOG"
# A PR exists in whichever repo is asked, so a leak is visible as a WRONG
# SUBJECT rather than as an empty answer that could have many causes.
case "\$*" in
  *"pr list"*)  echo 42 ;;
  *"pr view"*)  echo deadbeefdeadbeefdeadbeefdeadbeefdeadbeef ;;
esac
exit 0
EOF
chmod +x "$STUB/gh"
export PATH="$STUB:$PATH"
[ "$(command -v git)" = "$REAL_GIT" ] || fail "git was shadowed by a stub"

cat > "$WORK/skel/instance-registry.json" <<JSON
{"instances":[
  {"name":"targetproj","path":"$WORK/target","has_git":true,
   "dispatch":{"enabled":true,"expected_remote":"https://github.com/assafkip/targetrepo.git"}}
]}
JSON

# ===========================================================================
# CASE 0 -- NEGATIVE SELF-TEST
# ===========================================================================
( cd "$WORK/skel" && gh pr list --head probe --json number >/dev/null 2>&1 )
SELF="$(awk -F'\t' '$2 ~ /--head probe/ {print $1}' "$GH_LOG" | head -1)"
[ "$SELF" = "$HOME_SLUG" ] \
  || fail "negative self-test: unqualified gh from the home checkout resolved to '${SELF:-<nothing logged>}', expected $HOME_SLUG. The fake is not reproducing gh's cwd binding."
ok "negative self-test: unqualified gh from the home checkout resolves to $HOME_SLUG"
: > "$GH_LOG"

# ===========================================================================
# CASE 1 -- pr_for_branch, run from HOME with the work in the TARGET
# ===========================================================================
# KIPI_TARGET_REPO is the carrier kipi-dispatch.sh uses to reach converge: it
# forwards only its own arguments to the worker, so the target crosses that
# boundary by inheritance.
( cd "$WORK/skel" \
  && HOME="$WORK/home" KIPI_SKEL="$WORK/skel" KIPI_STATE_DIR="$WORK/state" \
     KIPI_NOTIFY="/usr/bin/true" KIPI_TARGET_REPO="$WORK/target" \
     bash "$CONVERGE" --issue ASK-AAA --dry ) >"$WORK/run.out" 2>&1
RC=$?

echo "  [ctx] cwd during the run: $WORK/skel (slug $HOME_SLUG)"
echo "  [ctx] KIPI_TARGET_REPO:   $WORK/target (slug $TARGET_SLUG)"
echo "  [ctx] converge rc: $RC"
echo "  [ctx] converge said: $(tail -1 "$WORK/run.out")"

SLUGS="$(awk -F'\t' '$2 ~ /pr list/ {print $1}' "$GH_LOG" | sort -u)"
[ -n "$SLUGS" ] \
  || fail "converge made NO 'gh pr list' call (rc=$RC). The reproducer never reached pr_for_branch. Output:
$(tail -15 "$WORK/run.out")"

if printf '%s\n' "$SLUGS" | grep -qx "$HOME_SLUG"; then
  fail "CROSS-REPO LEAK at converge.sh:68 -- pr_for_branch resolved to the HOME repo ($HOME_SLUG) while the work is in $TARGET_SLUG.
      This is why converge finds no PR after the worker opens one in the target.
      gh calls:
$(sed 's/^/        /' "$GH_LOG")"
fi
[ "$SLUGS" = "$TARGET_SLUG" ] \
  || fail "pr_for_branch resolved to '$SLUGS', expected exactly $TARGET_SLUG"
ok "pr_for_branch is scoped to the target repo ($TARGET_SLUG)"

# --- 2. no call in the run falls back to cwd --------------------------------
LEAKED="$(awk -F'\t' -v h="$HOME_SLUG" '$1 == h' "$GH_LOG")"
[ -z "$LEAKED" ] \
  || fail "some gh call in converge still resolves to the HOME repo:
$(printf '%s\n' "$LEAKED" | sed 's/^/        /')"
ok "no gh call in the converge run fell back to cwd"

# --- 3. no --repo / no KIPI_TARGET_REPO still resolves home -----------------
: > "$GH_LOG"
( cd "$WORK/skel" \
  && HOME="$WORK/home" KIPI_SKEL="$WORK/skel" KIPI_STATE_DIR="$WORK/state2" \
     KIPI_NOTIFY="/usr/bin/true" \
     bash "$CONVERGE" --issue ASK-BBB --dry ) >"$WORK/run2.out" 2>&1
HOME_SLUGS="$(awk -F'\t' '$2 ~ /pr list/ {print $1}' "$GH_LOG" | sort -u)"
[ "$HOME_SLUGS" = "$HOME_SLUG" ] \
  || fail "an unscoped converge run resolved to '${HOME_SLUGS:-<nothing>}', expected the home slug $HOME_SLUG:
$(tail -10 "$WORK/run2.out")"
ok "an unscoped run still resolves to the home repo ($HOME_SLUG)"

echo "PASS ($PASS checks) test-gh-repo-scope-converge.sh"
