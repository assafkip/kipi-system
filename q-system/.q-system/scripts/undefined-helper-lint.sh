#!/usr/bin/env bash
# undefined-helper-lint.sh -- catch a helper that is CALLED but never DEFINED.
#
# WHY. Under `set -uo pipefail` (no `-e`, which is this fleet's house style) a
# call to a function that does not exist is a command-not-found: it prints to
# stderr and the script CARRIES ON. In a scheduled job whose stderr goes to a log
# nobody reads, that is a silent no-op.
#
# The scar, 2026-07-30 (ASK-221): the fix for "a terminal state that pages nobody"
# called `page "..."` inside linear-worker.sh. That file has no `page()` -- it uses
# `bash "$NOTIFY" ...`, the shape at five other call sites. So the fix for terminal
# states that page nobody would itself have paged nobody. The class eating its own
# tail, and nothing would have reported it.
#
# SCOPE, deliberately narrow. Resolving every bare word against PATH, builtins,
# aliases and functions is a shell-parsing problem, and a lint with false
# positives gets turned off (the portability lint learned that the hard way in the
# same session). So this checks a SMALL ALLOWLIST of helper names this fleet
# actually uses for cross-cutting concerns -- the ones whose absence is silent and
# consequential. It will miss others. Missing some is fine; crying wolf is not.
#
# Exit 0 = clean, 1 = findings.
set -uo pipefail

ROOT="${1:-.}"
# Helpers whose silent absence changes behaviour rather than just erroring loudly.
HELPERS="page page_ok say notify warn fail ok info die"
# A HEREDOC BODY IS DATA, NOT CODE (2026-08-03). This grepped the raw file, so a
# helper name appearing inside `cat > out.sh <<'EOF' ... EOF` was reported as an
# undefined call -- even though those lines are written to ANOTHER file and never
# executed here. It blocked a test whose fixture deliberately contains producer
# code. Same blindness the human-handoff audit had, found the same day.
#
# Line numbers are preserved: body lines are BLANKED, not removed, so every
# reported line still points at the right place in the real file.
strip_heredocs() {
  awk '
    inside {
      sub(/[ \t]+$/, "", $0)
      if ($0 == marker) { inside = 0 }
      print ""; next
    }
    {
      line = $0
      if (match(line, /<<-?[ \t]*['"'"'"]?[A-Za-z_][A-Za-z0-9_]*['"'"'"]?/)) {
        m = substr(line, RSTART, RLENGTH)
        gsub(/^<<-?[ \t]*['"'"'"]?/, "", m)
        gsub(/['"'"'"]?$/, "", m)
        marker = m; inside = 1
      }
      print line
    }
  ' "$1"
}

FOUND=0

while IFS= read -r f; do
  [ -f "$f" ] || continue
  case "$(basename "$f")" in undefined-helper-lint.sh) continue ;; esac
  scan="$(mktemp)"
  strip_heredocs "$f" > "$scan" 2>/dev/null || cp "$f" "$scan"
  for h in $HELPERS; do
    # Called: the name at the start of a command position. Not `foo_page`, not
    # `--page`, not inside a longer word.
    calls="$(grep -nE "(^|[;&|(]|then |else |do |\{ )[[:space:]]*${h}[[:space:]]+[\"'\$-]" "$scan" 2>/dev/null \
             | grep -v "^[0-9]*:[[:space:]]*#" || true)"
    [ -n "$calls" ] || continue
    # Defined here, or inherited by being sourced into a file that defines it.
    # Both `h() {` and `function h` count.
    if grep -qE "^[[:space:]]*(function[[:space:]]+)?${h}[[:space:]]*\(\)" "$scan" 2>/dev/null; then
      continue
    fi
    # A file that sources another may legitimately inherit the helper. Only flag
    # when nothing it sources defines it either -- checked shallowly, one level,
    # because a deeper chain is rare here and guessing costs false positives.
    inherited=0
    while IFS= read -r src; do
      cand="$(dirname "$f")/$(basename "$src")"
      [ -f "$cand" ] || continue
      if grep -qE "^[[:space:]]*(function[[:space:]]+)?${h}[[:space:]]*\(\)" "$cand" 2>/dev/null; then
        inherited=1; break
      fi
    done < <(grep -oE '(^|[[:space:]])(\.|source)[[:space:]]+[^[:space:]]+' "$f" 2>/dev/null \
             | awk '{print $NF}' || true)
    [ "$inherited" = "1" ] && continue

    FOUND=$((FOUND + 1))
    printf 'UNDEFINED HELPER: %s() is called but never defined\n' "$h"
    printf '  %s\n' "$f"
    printf '%s\n' "$calls" | head -3 | sed 's/^/    /'
    printf '  why it matters: under `set -uo pipefail` this is command-not-found on stderr and the script CONTINUES.\n'
    printf '  fix: define it, or use the shape this file already uses for that concern.\n\n'
  done
done < <(find "$ROOT" -name '*.sh' -type f \
           -not -path '*/.git/*' -not -path '*/node_modules/*' -not -path '*/.pr*rev*/*' 2>/dev/null)

if [ "$FOUND" -eq 0 ]; then
  echo "undefined-helper-lint: clean"
  exit 0
fi
echo "undefined-helper-lint: $FOUND finding(s)"
exit 1
