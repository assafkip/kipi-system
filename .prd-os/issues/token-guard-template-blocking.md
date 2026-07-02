---
id: token-guard-template-blocking
title: settings-template.json token-guard wiring must propagate exit 2 while no-opping when the script is missing (sp-dd731488)
status: closed
priority: p2
parent_prd: prd-token-guard-template-blocking-2026-07-02
allowed_files:
  - settings-template.json
  - q-system/.q-system/scripts/test/test-token-guard-template-wiring.sh
disallowed_files: []
required_checks:
  - bash q-system/.q-system/scripts/test/test-token-guard-template-wiring.sh
required_reviews: []
bypass_check: "bash q-system/.q-system/scripts/test/test-token-guard-template-wiring.sh"
---
<!-- generated-by: prd_split.py prd=prd-token-guard-template-blocking-2026-07-02 finding=finding-1 at=2026-07-02T00:38:00Z -->

# settings-template.json token-guard wiring must propagate exit 2 while no-opping when the script is missing (sp-dd731488)

## Context

Parent PRD: `.prd-os/prds/prd-token-guard-template-blocking-2026-07-02.md`

## Acceptance

Both template token-guard wirings use the if-then form (no `|| true` on a blocking hook command). The regression test extracts the real command strings from the template JSON, proves exit-2 propagation with a fixture guard and exit-0 with the script absent, and was shown failing against the old `test -f X && python3 X || true` form (negative self-test).
