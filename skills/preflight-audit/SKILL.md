---
description: "Execution harness rules — fail-fast, flight recorder, audit enforcement"
user-invocable: false
paths:
  - "**/agent-pipeline/**"
  - "**/output/**"
---

# Execution Harness (ENFORCED)

Every phase must log completion via `log_step` MCP tool. The morning log at `{state_dir}/output/morning-log-YYYY-MM-DD.json` is a file on disk, not context. Even if context rots, the log is accurate. If a phase isn't logged, it didn't happen.

Before gate phases (6, 7, 8), call `kipi_gate_check` MCP tool. If it returns passed=false, STOP and report missing phases.

Before synthesis (Phase 6), call `kipi_deliverables_check` MCP tool. If it returns passed=false, go back and generate missing work.

After the routine ends, run `kipi_audit_morning` MCP tool. Show the output to the founder. This is not optional.

If any MCP server is unavailable or any phase fails during `/q-morning`, STOP immediately and report what broke. Do NOT continue with partial data.
