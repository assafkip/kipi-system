#!/usr/bin/env bash
# reviewer-token-lib.sh -- the ONE rule for which identity writes the reviewer
# gate (ASK-362 stage 2, sp-c442613c). Sourced by every script that POSTs
# kipi/reviewer-approved: pr-review-agent.sh (the verdict) and
# receipt-carry-approval.sh (the carry onto a receipt-only head).
#
# WHY ONE HELPER: the first cut of ASK-362 moved only pr-review-agent.sh's POST.
# Review of PR #431 found carry_post still writing state=success with the ambient
# admin login, so the gate had two writers and only one of them moved. Two copies
# of this rule is how that happens again.
#
# reviewer_status_run <gh argv...>
#   KIPI_REVIEWER_TOKEN_ENV unset -> run the command as given (ambient gh login).
#   set to a var holding a token  -> run it with GH_TOKEN=<that token>, this call only.
#   set, but empty/unset/invalid  -> REFUSE: print why on stderr, run nothing,
#                                    return 3. Never fall back to the ambient
#                                    login: the operator believes the gate moved.

REVIEWER_TOKEN_REFUSED=3

reviewer_status_run() {
  local token_env="${KIPI_REVIEWER_TOKEN_ENV:-}" token=""
  if [ -z "$token_env" ]; then
    "$@"
    return $?
  fi
  case "$token_env" in
    *[!A-Za-z0-9_]*|[0-9]*)
      echo "REFUSED: KIPI_REVIEWER_TOKEN_ENV='$token_env' is not a variable name; no reviewer status posted" >&2
      return "$REVIEWER_TOKEN_REFUSED" ;;
  esac
  token="${!token_env:-}"
  if [ -z "$token" ]; then
    echo "REFUSED: KIPI_REVIEWER_TOKEN_ENV names $token_env, which is empty or unset; no reviewer status posted (never falling back to the ambient gh login)" >&2
    return "$REVIEWER_TOKEN_REFUSED"
  fi
  GH_TOKEN="$token" "$@"
}
