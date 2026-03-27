**Step 0 — Session bootstrap (runs before everything else):**

> **PREFERRED: Use the agent pipeline.** Read `.q-system/steps/step-orchestrator.md` and execute phases 0-8 using the Agent tool. The monolithic steps below are fallback only. The orchestrator spawns 19 sub-agents across 8 phases, communicating through `bus/` JSON files. This is faster, uses fewer tokens, and produces better output per step.

> **MANDATORY:** Before executing ANY step, read `.q-system/preflight.md`. It contains the tool manifest, known issues, session budget, and step logging format.

> **HARNESS RULE:** Every step must end with a call to the log helper. Replace DATE with today's date in every call.
> ```
> # Log a completed step:
> Use the `log_step` MCP tool with date=DATE, step_id, status="done", result="result summary"
> # Log a failed step:
> Use the `log_step` MCP tool with date=DATE, step_id, status="failed", error="error message"
> # Log a skipped step:
> Use the `log_step` MCP tool with date=DATE, step_id, status="skipped", error="reason"
> # Log a partially completed step:
> Use the `log_step` MCP tool with date=DATE, step_id, status="partial", result="what completed"
> # Add an action card (for any founder-facing draft):
> Use the `log_add_card` MCP tool with date=DATE, card_id="C1", card_type="linkedin_comment", target="Person Name", text="Draft text...", url="https://url"
> # Run a gate check (at Steps 8, 9, 11):
> Use the `log_gate_check` MCP tool with date=DATE, gate_name="step_8", passed=true
> # Record state checksums:
> Use the `log_checksum` MCP tool with date=DATE, phase="start", field_name, value
> Use the `log_checksum` MCP tool with date=DATE, phase="end", field_name, value
> # Mark all cards as delivered (after Step 11 HTML opens):
> Use the `log_deliver_cards` MCP tool with date=DATE
> ```
> **No step is complete until the log MCP tool runs.** The tool writes to disk. Context rot cannot affect it.

This step replaces the need to manually run `/q-begin` or `/q-end`. The founder only needs `/q-morning`.
