---
description: Lint an RCA or premortem document against the canonical template.
allowed-tools: Bash
---

Run the deterministic RCA lint on a document. The author passes a file path; if
none is given, lint every RCA/premortem doc found.

## Single file

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/rca/scripts/rca-lint.py" "$ARGUMENTS"
```

## All RCA docs (when no path given)

```bash
found=0
for f in $(find . -type f \( -name 'rca-*.md' -o -name 'premortem-*.md' \) -not -path '*/.git/*' 2>/dev/null); do
  found=1
  python3 "${CLAUDE_PLUGIN_ROOT}/skills/rca/scripts/rca-lint.py" "$f" || true
done
[ "$found" = 0 ] && echo "no rca-*.md / premortem-*.md docs found"
```

Exit 0 means clean. Exit 2 lists exactly which required sections, cause-type
tags, verification evidence, checkbox action items, or blameless rules are
missing. Surface the report verbatim and fix per the template.
