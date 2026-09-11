#!/usr/bin/env bash
# Reproducer + acceptance for call site 1 of ASK-738: linear-worker.sh's
# existing-PR lookup binds to the CWD's repo, not to --repo's target.
#
# THE DEFECT, measured 2026-08-13 before the fix:
#   cwd = kipi-system checkout, TARGET_REPO=<other>  ->  gh answers about kipi-system
#   cwd = <other>                                    ->  gh answers about <other>
# `gh` resolves its repository from the process working directory and ignores
# TARGET_REPO entirely. kipi-dispatch.sh:205 does `cd "$REPO"` and never leaves,
# so `gh pr list --head "$BRANCH"` at linear-worker.sh:902 asks the HOME repo
# whether the target's branch already has a PR. It answers about the wrong
# repository, and every gate downstream of that answer (the severity floor, the
# rework round, the reviewer invocation) inherits the wrong subject.
#
# WHY A FAKE gh AND NOT A REAL ONE. The subject is *which repository the call
# resolves to*, which is a property of the argv and the cwd -- not of GitHub. A
# fake that reproduces gh's own cwd-binding rule (read origin from cwd when no
# -R is given) makes that property observable and keeps the test off the network.
# The fake is deliberately FAITHFUL to the bug: with no -R it binds to cwd, so a
# fix that merely moves the call inside a `cd` would also pass -- and that is a
# real fix. What it cannot do is pass while the call stays unqualified from home.
#
# NEGATIVE SELF-TEST (case 0): the harness first proves the fake gh actually
# reports the HOME slug when run unqualified from the home checkout. Without that,
# a fake that silently failed to log anything would make every assertion below
# vacuously true.
#
# Isolation: HOME / KIPI_SKEL / KIPI_STATE_DIR all inside a temp dir; python3,
# gh, claude and the reviewer are stubbed. `git` stays REAL -- real remotes are
# the subject.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
WORKER="$ROOT/q-system/.q-system/scripts/linear-worker.sh"

PASS=0
fail() { echo "FAIL: $1" >&2; exit 1; }
ok()   { PASS=$((PASS + 1)); echo "  ok: $1"; }

[ -f "$WORKER" ] || fail "linear-worker.sh does not exist at $WORKER"
REAL_PY="$(command -v python3)" || fail "python3 not on PATH"
REAL_GIT="$(command -v git)"    || fail "git not on PATH"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
unset KIPI_LINEAR_CLAIMS KIPI_SESSION_ID CLAUDE_SESSION_ID KIPI_TARGET_REPO 2>/dev/null || true

G() { git -c user.email=t@t.t -c user.name=t "$@"; }
STUB="$WORK/bin"; mkdir -p "$STUB" "$WORK/home"

HOME_SLUG="assafkip/homerepo"
TARGET_SLUG="assafkip/targetrepo"

# --- two real repos with two DIFFERENT origins ------------------------------
#
# THE ORIGIN URL MUST BE GITHUB-SHAPED *AND* FETCHABLE. The first cut pointed
# origin at a real https://github.com/... URL, so the worker's own `git fetch`
# guard exited 9 before the run ever reached the call site under test -- the
# reproducer reported "no gh pr list call at all" instead of the leak. Pointing
# origin at a local path instead would have made the slug a filesystem path and
# tested a shape the shipping code never sees. `insteadOf` gets both: the
# configured URL (what slug derivation reads) stays github.com, while the
# transport is redirected to a bare repo on disk.
mkrepo() {  # mkrepo <dir> <name>
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

# --- the fake gh: reproduces gh's cwd binding, records what it resolved ------
GH_LOG="$WORK/gh-resolved.txt"; : > "$GH_LOG"
cat > "$STUB/gh" <<EOF
#!/usr/bin/env bash
# Faithful to real gh: -R/--repo wins; otherwise the repo comes from CWD.
R=""
prev=""
for a in "\$@"; do
  case "\$prev" in -R|--repo) R="\$a" ;; esac
  prev="\$a"
done
if [ -z "\$R" ]; then
  # config --get, not \`remote get-url\`: get-url APPLIES insteadOf rewriting, so
  # under this fixture it returns the local bare path and the slug never forms.
  # Measured here on first run. The raw configured value is what gh reports on.
  url="\$("$REAL_GIT" config --get remote.origin.url 2>/dev/null)"
  R="\${url#https://github.com/}"; R="\${R%.git}"
  [ "\$R" = "\$url" ] && R="UNRESOLVED"
fi
printf '%s\t%s\n' "\$R" "\$*" >> "$GH_LOG"
# No PR exists anywhere: the lookup returns empty and the worker moves on.
exit 0
EOF
chmod +x "$STUB/gh"

# Never let this suite reach the real reviewer (sp-cb48c3c0).
cat > "$STUB/reviewer-noop" <<'NOOP'
#!/usr/bin/env bash
echo "  [stub reviewer] would review PR $1 ($*)"
exit 0
NOOP
chmod +x "$STUB/reviewer-noop"
printf '#!/usr/bin/env bash\nexit 0\n' > "$STUB/claude"; chmod +x "$STUB/claude"

picker_stub() {
  cat > "$STUB/python3" <<EOF
#!/usr/bin/env bash
case "\${1:-}" in
  -)  cat >/dev/null
      printf '%s\n' '$1'
      exit 0 ;;
  *linear-sync.py) exit 0 ;;
esac
exec "$REAL_PY" "\$@"
EOF
  chmod +x "$STUB/python3"
}

export PATH="$STUB:$PATH"
[ "$(command -v git)" = "$REAL_GIT" ] || fail "git was shadowed by a stub; real remotes are the subject"

# --- the registry that pins the target's remote -----------------------------
# expected_remote is the ONE authority for the target slug (ASK-738 acceptance 2).
cat > "$WORK/skel/instance-registry.json" <<JSON
{"instances":[
  {"name":"targetproj","path":"$WORK/target","has_git":true,
   "dispatch":{"enabled":true,"expected_remote":"https://github.com/assafkip/targetrepo.git"}}
]}
JSON

# ===========================================================================
# CASE 0 -- NEGATIVE SELF-TEST: the fake gh really does bind to cwd
# ===========================================================================
# If this does not report the HOME slug, the fake is not reproducing the bug and
# every assertion below would pass for the wrong reason.
( cd "$WORK/skel" && gh pr list --head probe --json number >/dev/null 2>&1 )
SELF="$(awk -F'\t' '$2 ~ /--head probe/ {print $1}' "$GH_LOG" | head -1)"
[ "$SELF" = "$HOME_SLUG" ] \
  || fail "negative self-test: an unqualified gh run from the home checkout resolved to '${SELF:-<nothing logged>}', expected $HOME_SLUG. The fake gh is not reproducing gh's cwd binding, so this suite proves nothing."
ok "negative self-test: unqualified gh from the home checkout resolves to $HOME_SLUG"
: > "$GH_LOG"

# ===========================================================================
# CASE 1 -- the existing-PR lookup, run from HOME against a --repo TARGET
# ===========================================================================
picker_stub '{"ready":[{"id":"ASK-AAA","title":"t","project":"targetproj"}],"total_open":1}'

# cwd is the HOME checkout, which is exactly where kipi-dispatch.sh:205 leaves it.
( cd "$WORK/skel" \
  && HOME="$WORK/home" KIPI_SKEL="$WORK/skel" KIPI_STATE_DIR="$WORK/state" \
     KIPI_NOTIFY="/usr/bin/true" KIPI_PR_REVIEWER="$STUB/reviewer-noop" \
     KIPI_LINEAR_PROJECT="targetproj" \
     bash "$WORKER" --apply --repo "$WORK/target" --issue ASK-AAA --limit 1 \
) >"$WORK/run.out" 2>&1
RC=$?

# STATE THE TARGET'S IDENTITY WITH THE RESULT (a failed setup that relocates the
# test is otherwise indistinguishable from a pass).
echo "  [ctx] cwd during the run: $WORK/skel (slug $HOME_SLUG)"
echo "  [ctx] --repo target:      $WORK/target (slug $TARGET_SLUG)"
echo "  [ctx] worker rc: $RC"

PRLIST_SLUGS="$(awk -F'\t' '$2 ~ /pr list/ {print $1}' "$GH_LOG" | sort -u)"
[ -n "$PRLIST_SLUGS" ] \
  || fail "the worker made NO 'gh pr list' call at all (rc=$RC). The reproducer never reached the call site it is about. Last output:
$(tail -15 "$WORK/run.out")"

if printf '%s\n' "$PRLIST_SLUGS" | grep -qx "$HOME_SLUG"; then
  fail "CROSS-REPO LEAK at linear-worker.sh:902 -- the existing-PR lookup resolved to the HOME repo ($HOME_SLUG) while the work targets $TARGET_SLUG.
      resolved slugs seen: $(printf '%s' "$PRLIST_SLUGS" | tr '\n' ' ')
      gh calls:
$(sed 's/^/        /' "$GH_LOG")"
fi
[ "$PRLIST_SLUGS" = "$TARGET_SLUG" ] \
  || fail "the existing-PR lookup resolved to '$PRLIST_SLUGS', expected exactly $TARGET_SLUG"
ok "the existing-PR lookup is scoped to the target repo ($TARGET_SLUG)"

# --- 2. NO gh call in the whole run may fall back to cwd --------------------
# The negative half of acceptance criterion 5: not just the one line, the chain.
LEAKED="$(awk -F'\t' -v h="$HOME_SLUG" '$1 == h' "$GH_LOG")"
[ -z "$LEAKED" ] \
  || fail "some gh call in the dispatched chain still resolves to the HOME repo:
$(printf '%s\n' "$LEAKED" | sed 's/^/        /')"
UNRES="$(awk -F'\t' '$1 == "UNRESOLVED"' "$GH_LOG")"
[ -z "$UNRES" ] \
  || fail "a gh call resolved against no known origin (ran from a non-repo cwd):
$(printf '%s\n' "$UNRES" | sed 's/^/        /')"
ok "every gh call in the dispatched chain resolved to the target, none to cwd"

# --- 3. the home repo still works when it IS the target ---------------------
# A fix that hard-codes a slug, or that refuses when no registry row exists,
# would break the only repo this loop runs in today. The home checkout carries no
# registry row of its own, so this is the fallback path, asserted explicitly.
: > "$GH_LOG"
picker_stub '{"ready":[{"id":"ASK-BBB","title":"t","project":"homerepo"}],"total_open":1}'
( cd "$WORK/skel" \
  && HOME="$WORK/home" KIPI_SKEL="$WORK/skel" KIPI_STATE_DIR="$WORK/state3" \
     KIPI_NOTIFY="/usr/bin/true" KIPI_PR_REVIEWER="$STUB/reviewer-noop" \
     KIPI_LINEAR_PROJECT="homerepo" \
     bash "$WORKER" --apply --issue ASK-BBB --limit 1 ) >"$WORK/run3.out" 2>&1

HOME_PRLIST="$(awk -F'\t' '$2 ~ /pr list/ {print $1}' "$GH_LOG" | sort -u)"
[ "$HOME_PRLIST" = "$HOME_SLUG" ] \
  || fail "a no---repo run resolved to '${HOME_PRLIST:-<nothing>}', expected the home slug $HOME_SLUG. The fix must not break the repo the loop runs in today.
$(tail -15 "$WORK/run3.out")"
ok "a run with no --repo still resolves to the home repo ($HOME_SLUG)"

echo "PASS ($PASS checks) test-gh-repo-scope-worker.sh"
