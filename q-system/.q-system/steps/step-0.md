**Step 0 — Session bootstrap (runs before everything else):**

> **PREFERRED: Use the agent pipeline.** Read `.q-system/steps/step-orchestrator.md` and execute phases 0-8 using the Agent tool. The monolithic steps below are fallback only. The orchestrator spawns 19 sub-agents across 8 phases, communicating through `bus/` JSON files. This is faster, uses fewer tokens, and produces better output per step.

> **MANDATORY:** Before executing ANY step, read `.q-system/preflight.md`. It contains the tool manifest, known issues, session budget, and step logging format.

> **HARNESS RULE:** Every step must end with a call to the log helper. Replace DATE with today's date in every call.
> ```bash
> # Log a completed step:
> bash q-system/.q-system/log-step.sh DATE step_id done "result summary"
> # Log a failed step:
> bash q-system/.q-system/log-step.sh DATE step_id failed "" "error message"
> # Log a skipped step:
> bash q-system/.q-system/log-step.sh DATE step_id skipped "" "reason"
> # Log a partially completed step:
> bash q-system/.q-system/log-step.sh DATE step_id partial "what completed"
> # Add an action card (for any founder-facing draft):
> bash q-system/.q-system/log-step.sh DATE add-card C1 linkedin_comment "Person Name" "Draft text..." "https://url"
> # Run a gate check (at Steps 8, 9, 11):
> bash q-system/.q-system/log-step.sh DATE gate-check step_8 true ""
> # Record state checksums:
> bash q-system/.q-system/log-step.sh DATE checksum-start field_name value
> bash q-system/.q-system/log-step.sh DATE checksum-end field_name value
> # Mark all cards as delivered (after Step 11 HTML opens):
> bash q-system/.q-system/log-step.sh DATE deliver-cards
> ```
> **No step is complete until `log-step.sh` runs.** The helper writes to disk. Context rot cannot affect it.

This step replaces the need to manually run `/q-begin` or `/q-end`. The founder only needs `/q-morning`.
