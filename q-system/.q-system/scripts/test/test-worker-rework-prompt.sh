#!/usr/bin/env bash
# The prompts the worker hands Sana and Codex reach them as written (ASK-1512).
#
# THE DEFECT
# ----------
# Every rework run logged `linear-worker.sh: line 1960: one: No such file or
# directory`. The rework branch assigns its text inside a double-quoted string,
# and the reply template in it carried UNESCAPED double quotes:
#
#     "<one line per finding: ...>" \\
#
# The first `"` closed the string. `<one` became an input redirect, the rest of
# the "assignment" became a command named `line`, the redirect failed, and the
# command never ran. So REWORK kept its initial empty value: on every rework
# round Sana got the FRESH-START prompt, with no review to answer and no
# instruction to push to the existing PR. The run proceeded, which is why
# nobody noticed. Observed 2026-09-12 17:07Z on ASK-135.
#
# Same class, same builder: the unescaped backticks in "Never `cd` to ..." are a
# command substitution. `cd` ran in a subshell and the word vanished, so every
# dispatch prompt read "Never  to <repo>".
#
# WHAT IT PROVES
# --------------
# 1. every branch of the builder (fresh, rework, rebase, re-review) and the Codex
#    prompt render with NOTHING on stderr
# 2. each branch carries its own header, so a branch that silently renders empty
#    is RED, not a pass
# 3. every <placeholder> and every backticked span in the builder source appears
#    verbatim in a rendered prompt. The list is DERIVED from the worker source,
#    never retyped here, so a new placeholder is covered the day it is written.
#
# The builder blocks are extracted from the worker and evaluated with stub
# values, the same seam test-worker-refusal.sh uses for run_bounded. A copy of
# the prompt text would prove the copy is quoted correctly, which nobody needs.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_SCRIPTS="$(cd "$SCRIPT_DIR/.." && pwd)"
WORKER="${KIPI_WORKER_UNDER_TEST:-$REPO_SCRIPTS/linear-worker.sh}"

PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); printf '  ok   %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  FAIL %s\n     %s\n' "$1" "${2:-}"; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
# An empty cwd, as in production: a redirect from a stray file named like a
# placeholder word must fail here exactly as it fails in the worker's cwd.
mkdir -p "$WORK/cwd"

# The Sana builder: from the `if` that opens the REWORK chain through the last
# line of the PROMPT assignment. The comment block after it is not prompt text.
extract_sana_builder() {
  awk '
    prev ~ /^  if \[ -n "\$CONFLICT_ROUND" \]; then$/ && $0 ~ /^    REWORK="$/ { p = 1; print prev }
    p { print }
    p && /spillover add --source \$ISSUE --desc/ { exit }
    { prev = $0 }
  ' "$1"
}
# The Codex prompt: its assignment up to the run_bounded call that consumes it.
extract_codex_builder() {
  awk '
    /^      CODEX_PROMPT="You are Codex/ { p = 1 }
    p && /_ "\$CODEX_PROMPT"; then$/ { exit }
    p { print }
  ' "$1"
}

SANA_SRC="$(extract_sana_builder "$WORKER")"
CODEX_SRC="$(extract_codex_builder "$WORKER")"

# 1. SELF-TEST FOR THE EXTRACTION. An awk that matched nothing evals to nothing,
# stderr is empty, and every stderr assertion below passes on a test that ran no
# worker code at all.
if printf '%s' "$SANA_SRC" | grep -q '^  PROMPT="You are Sana' \
   && printf '%s' "$SANA_SRC" | grep -q 'spillover add --source \$ISSUE' \
   && [ "$(printf '%s\n' "$SANA_SRC" | wc -l)" -gt 100 ]; then
  ok "self-test: the Sana builder (REWORK chain + PROMPT) was extracted from the worker"
else
  bad "self-test: the Sana builder was extracted from the worker" \
      "got $(printf '%s\n' "$SANA_SRC" | wc -l) line(s) -- every case below is vacuous"
fi
if printf '%s' "$CODEX_SRC" | grep -q 'CODEX_PROMPT="You are Codex' \
   && [ "$(printf '%s\n' "$CODEX_SRC" | wc -l)" -gt 20 ]; then
  ok "self-test: the Codex prompt builder was extracted from the worker"
else
  bad "self-test: the Codex prompt builder was extracted from the worker" \
      "got $(printf '%s\n' "$CODEX_SRC" | wc -l) line(s)"
fi

# render <name> <source> <var=value>... : evaluates the builder in a subshell
# under set -u with the stub values, writes the prompt to $WORK/<name>.prompt and
# everything the evaluation printed to stderr to $WORK/<name>.err.
render() {
  local name="$1" src="$2"; shift 2
  (
    set -u
    cd "$WORK/cwd" || exit 97
    ISSUE=ASK-TEST BRANCH=sana/ask-test TREE=/tmp/tree TARGET_REPO=/tmp/repo
    SYNC=/tmp/sync.py SKEL=/tmp/skel PR_VERDICT=REQUEST_CHANGES MERGE_STATE=DIRTY
    EXISTING_PR= CONFLICT_ROUND= DRIFT_ROUND= MAX_CONFLICT_ROUNDS=3 MAX_DRIFT_ROUNDS=3
    REVIEWED_SHA=aaaaaaa CURRENT_SHA=bbbbbbb SCOPE_WHY="stub reason" REWORK=""
    local kv
    for kv in "$@"; do eval "$kv"; done
    eval "$src"
    printf '%s' "${PROMPT:-}${CODEX_PROMPT:-}" > "$WORK/$name.prompt"
  ) 2> "$WORK/$name.err"
}

render fresh    "$SANA_SRC"
render rework   "$SANA_SRC" EXISTING_PR=77
render rebase   "$SANA_SRC" EXISTING_PR=77 CONFLICT_ROUND=1
render rereview "$SANA_SRC" EXISTING_PR=77 DRIFT_ROUND=1
render codex    "$CODEX_SRC"

# 2. NOTHING ON STDERR, per branch. This is the `one: No such file` line.
for name in fresh rework rebase rereview codex; do
  if [ ! -s "$WORK/$name.err" ]; then
    ok "$name prompt renders with an empty stderr"
  else
    bad "$name prompt renders with an empty stderr" "$(head -3 "$WORK/$name.err")"
  fi
done

# 3. EACH BRANCH CARRIES ITS OWN HEADER. The defect left REWORK empty, so the
# rework round's prompt was indistinguishable from a fresh start.
has() {  # has <name> <literal> <label>
  if grep -qF -- "$2" "$WORK/$1.prompt"; then ok "$3"; else bad "$3" "not in the rendered $1 prompt: $2"; fi
}
has rework   "## THIS IS A REWORK, NOT A FRESH START" "rework prompt carries the rework section"
has rework   "Push to the SAME branch sana/ask-test. Do not open a second PR." "rework section reaches its last line"
has rebase   "## THIS IS A REBASE ROUND. THE CONFLICT IS THE ONLY TASK." "rebase prompt carries the rebase section"
has rereview "## THIS IS A RE-REVIEW ROUND." "re-review prompt carries the re-review section"
if grep -qF "## THIS IS A RE" "$WORK/fresh.prompt"; then
  bad "fresh prompt carries no round section" "a fresh start rendered a rework/rebase/re-review header"
else
  ok "fresh prompt carries no round section"
fi

# 4. THE REPLY TEMPLATE REACHES SANA VERBATIM, quotes included.
has rework '"<one line per finding: fixed + the test that now covers it, or answered + the file:line>"' \
    "rework reply template: the 'one line per finding' placeholder is present verbatim"
has rework '--agent sana --evidence "<the command you ran and its real output>"' \
    "rework reply template: the evidence placeholder is present verbatim"
has rework '"I ran X and got Y" is an answer;' "rework prompt keeps its own quoted example"
has fresh 'Never `cd` to /tmp/repo' "fresh prompt keeps the backticked \`cd\` (no command substitution)"

# 5. THE CLASS, NOT THE LINE. Every <placeholder> and every backticked span in the
# builder source must appear verbatim in some rendered prompt. Derived from the
# source, with shell comment lines (4+ spaces then #) excluded because they are
# not prompt text; prompt lines that start with # sit at column 0 or 2.
# Spans containing $ are skipped: they are interpolated on purpose.
ALL="$WORK/all.prompt"
cat "$WORK"/fresh.prompt "$WORK"/rework.prompt "$WORK"/rebase.prompt \
    "$WORK"/rereview.prompt "$WORK"/codex.prompt > "$ALL"
SRC_TEXT="$(printf '%s\n%s\n' "$SANA_SRC" "$CODEX_SRC" | grep -vE '^[[:space:]]{4,}#')"

PLACEHOLDERS="$(printf '%s\n' "$SRC_TEXT" | grep -oE '<[a-z][^<>$]*>' | sort -u)"
BACKTICKED="$(printf '%s\n' "$SRC_TEXT" | sed 's/\\`/`/g' | grep -oE '`[^`$]+`' | sort -u)"

# The derivation needs its own floor: a pattern that stops matching after a
# refactor would otherwise turn both loops below into silent no-ops.
n_ph="$(printf '%s\n' "$PLACEHOLDERS" | grep -c .)"
n_bt="$(printf '%s\n' "$BACKTICKED" | grep -c .)"
if [ "$n_ph" -ge 5 ] && [ "$n_bt" -ge 3 ]; then
  ok "self-test: derived $n_ph placeholder(s) and $n_bt backticked span(s) from the source"
else
  bad "self-test: derivation found placeholders and backticked spans" \
      "placeholders=$n_ph backticked=$n_bt -- the class checks below would be vacuous"
fi

missing=""
while IFS= read -r ph; do
  [ -n "$ph" ] || continue
  grep -qF -- "$ph" "$ALL" || missing="$missing
       $ph"
done <<< "$PLACEHOLDERS
$BACKTICKED"
if [ -z "$missing" ]; then
  ok "every placeholder and backticked span in the builders reaches a rendered prompt verbatim"
else
  bad "every placeholder and backticked span reaches a rendered prompt verbatim" \
      "missing:$missing"
fi

echo
echo "test-worker-rework-prompt: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
