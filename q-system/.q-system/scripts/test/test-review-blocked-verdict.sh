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

# another phrasing of "I read nothing" (review round 1, major 2)
printf 'codex\n**VERDICT: REVIEW NOT ISSUED**\nCould not fetch the diff.\n\nFINDINGS:\nEND FINDINGS\n' > "$WORK/review-not-issued.md"
printf 'codex\nVERDICT: unable to review (no diff)\n\nFINDINGS:\nEND FINDINGS\n' > "$WORK/unable.md"
# a REAL review that quotes a blocked verdict must still land (review round 1, major 1)
cat > "$WORK/quotes-in-row.md" <<'R'
codex
Read every changed file. One finding.

VERDICT: REQUEST CHANGES

FINDINGS:
major|the parser misses a reviewer line "VERDICT: NOT ISSUED" in fixtures|lib.sh:10
END FINDINGS
R
cat > "$WORK/quotes-in-prose.md" <<'R'
codex
Read every changed file. The fixture contains:

    VERDICT: REVIEW BLOCKED

which is test data, not my verdict.

VERDICT: APPROVE

FINDINGS:
END FINDINGS
R
# a blocked verdict from an EARLIER round's block, then a real final answer
cat > "$WORK/earlier-round.md" <<'R'
Round 1 said:
VERDICT: NOT ISSUED
FINDINGS:
END FINDINGS
codex
Read the diff and both files this round; nothing remains.

VERDICT: APPROVE

FINDINGS:
END FINDINGS
R

# round 2: other refusals, and real verdicts that carry refusal-ish words
printf 'codex\nVERDICT: INCONCLUSIVE\n\nFINDINGS:\nEND FINDINGS\n' > "$WORK/inconclusive.md"
printf 'codex\n**VERDICT: NO REVIEW**\n\nFINDINGS:\nEND FINDINGS\n' > "$WORK/no-review.md"
printf 'codex\nVERDICT: BLOCKED\n\nFINDINGS:\nEND FINDINGS\n' > "$WORK/bare-blocked.md"
printf 'codex\nRead both files.\n\nVERDICT: REQUEST CHANGES, cannot merge until the lock is fixed\n\nFINDINGS:\nmajor|lock is not released|a.sh:3\nEND FINDINGS\n' > "$WORK/rc-cannot.md"
printf 'codex\nRead both files.\n\n**VERDICT: APPROVE WITH NITS** (unable to test on Linux)\n\nFINDINGS:\nnit|typo|a.sh:1\nEND FINDINGS\n' > "$WORK/nits-unable.md"
printf 'codex\nRead every file.\n\nVERDICT: BLOCK\n\nFINDINGS:\nblocker|leaks a token|a.sh:9\nEND FINDINGS\n' > "$WORK/block.md"
for x in inconclusive no-review bare-blocked; do
  if review_is_usable "$WORK/$x.md"; then bad "$x read as usable"; else ok "$x is unusable"; fi
done
for x in rc-cannot nits-unable block; do
  if review_is_usable "$WORK/$x.md"; then ok "real verdict $x stays usable"; else bad "real verdict $x discarded"; fi
done

if review_is_usable "$WORK/not-issued.md"; then bad "NOT ISSUED + empty block read as usable"; else ok "NOT ISSUED is unusable"; fi
if review_is_usable "$WORK/blocked.md"; then bad "REVIEW BLOCKED + empty block read as usable"; else ok "REVIEW BLOCKED is unusable"; fi
if review_is_usable "$WORK/review-not-issued.md"; then bad "REVIEW NOT ISSUED read as usable"; else ok "REVIEW NOT ISSUED is unusable"; fi
if review_is_usable "$WORK/unable.md"; then bad "'unable to review' read as usable"; else ok "'unable to review' is unusable"; fi
if review_is_usable "$WORK/clean.md"; then ok "a real empty-findings APPROVE stays usable"; else bad "real clean review rejected"; fi
if review_is_usable "$WORK/quotes-in-row.md"; then ok "a findings row quoting a blocked verdict stays usable"; else bad "quote inside a findings row discarded the review"; fi
if review_is_usable "$WORK/quotes-in-prose.md"; then ok "an indented quote in prose stays usable"; else bad "indented quote discarded the review"; fi
if review_is_usable "$WORK/earlier-round.md"; then ok "an earlier round's blocked verdict does not void this round"; else bad "earlier round voided a real review"; fi

# write + network only in the isolated tree (review round 1, major 3). The block
# is EXECUTED both ways, not grepped. Network was proven live 2026-10-13: codex
# 0.153.4 ran gh pr view in workspace-write with network_access=true.
block="$(sed -n '/^# codex-sandbox-begin/,/^# codex-sandbox-end/p' "$AGENT")"
[ -n "$block" ] || bad "codex-sandbox block missing from pr-review-agent.sh"
iso="$(HEAD_SHA_ISOLATED=1; eval "$block"; echo "$CODEX_SANDBOX")"
live="$(HEAD_SHA_ISOLATED=0; eval "$block"; echo "$CODEX_SANDBOX")"
unset_="$(unset HEAD_SHA_ISOLATED; eval "$block"; echo "$CODEX_SANDBOX")"
[ "$iso" = "-s workspace-write -c sandbox_workspace_write.network_access=true" ] \
  && ok "isolated tree: write confined there, network on" || bad "isolated tree got: $iso"
[ "$live" = "-s read-only" ] && ok "found or live tree: read-only" || bad "found tree got: $live"
[ "$unset_" = "-s read-only" ] && ok "unknown isolation: read-only" || bad "unset isolation got: $unset_"
grep -qE '"codex exec [^"]*\$CODEX_SANDBOX' "$AGENT" && ok "codex exec uses CODEX_SANDBOX" \
  || bad "codex exec does not use CODEX_SANDBOX"

echo "$PASS passed, $FAIL failed"
[ "$FAIL" = 0 ]
