Reviewer: claude-adversarial (Opus general-purpose subagent, read-only), 2026-11-09.
Verdict: REQUEST CHANGES. 4 findings: RecursionError on deep JSON exits 1 (major); is_file PermissionError on py<=3.13 exits 1 (medium); malformed shapes silently fall back with no reported line (medium); unbounded repr in notes (minor).
All four fixed: broad except on read, lexists guarded, dict/str shape checks with one reported line, _short() bounds repr. 50 tests pass.
