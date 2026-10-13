#!/usr/bin/env bash
# Pairs with pr-verdict-lib.sh review_is_usable / review_could_not_read and the
# codex invocation in pr-review-agent.sh run_engine.
#
# THE DEFECT (two instance PRs, 2026-10-13). The codex reviewer ran
# with no network (default read-only sandbox), `gh pr diff` failed with "error
# connecting to api.github.com", and the reviewer correctly stopped: it wrote
# "VERDICT: REVIEW BLOCKED" / "VERDICT: NOT ISSUED" and an EMPTY findings block.
# An empty block is structurally complete and derives APPROVE, the stated verdict
# parsed as 'none', and the harsher-of-two took APPROVE. kipi/reviewer-approved
# went green on a PR nobody had read, and one of them merged.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB="$HERE/../pr-verdict-lib.sh"
AGENT="$HERE/../pr-review-agent.sh"
# shellcheck source=/dev/null
. "$LIB"
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  ok   - $1"; }
bad() { FAIL=$((FAIL+1)); echo "  FAIL - $1"; }

# shape captured from the second 2026-10-13 artifact (codex repeats its final answer)
cat > "$WORK/not-issued.md" <<'R'
exec
/bin/zsh -lc 'gh -R o/r pr view 252 && gh -R o/r pr diff 252' in /tmp/tree
 exited 1 in 213ms:
error connecting to api.github.com
check your internet connection or https://githubstatus.com

codex
Review blocked before code inspection.

**VERDICT: NOT ISSUED**
No code was inspected, so approval or rejection would be fabricated.

FINDINGS:
END FINDINGS
tokens used
42,698
Review blocked before code inspection.

**VERDICT: NOT ISSUED**
No code was inspected, so approval or rejection would be fabricated.

FINDINGS:
END FINDINGS
R
# shape captured from the first 2026-10-13 artifact
cat > "$WORK/blocked.md" <<'R'
codex
VERDICT: REVIEW BLOCKED

The required GitHub read failed before the PR could be inspected.

FINDINGS:
END FINDINGS
R
# a real review that found nothing must still land
cat > "$WORK/clean.md" <<'R'
codex
Read the diff and both changed files; every path checked.

VERDICT: APPROVE

FINDINGS:
END FINDINGS
R

if review_is_usable "$WORK/not-issued.md"; then bad "NOT ISSUED + empty block read as usable"; else ok "NOT ISSUED is unusable"; fi
if review_is_usable "$WORK/blocked.md"; then bad "REVIEW BLOCKED + empty block read as usable"; else ok "REVIEW BLOCKED is unusable"; fi
if review_is_usable "$WORK/clean.md"; then ok "a real empty-findings APPROVE stays usable"; else bad "real clean review rejected"; fi

# the reviewer can read GitHub: workspace-write confined to the detached review
# tree, network on. Proven live 2026-10-13 (codex 0.153.4 ran gh pr view in this mode).
line="$(grep -E '^[[:space:]]*"codex exec ' "$AGENT")"
case "$line" in
  *"-s workspace-write"*"sandbox_workspace_write.network_access=true"*) ok "codex runs with network on" ;;
  *) bad "codex exec has no network: $line" ;;
esac

echo "$PASS passed, $FAIL failed"
[ "$FAIL" = 0 ]
