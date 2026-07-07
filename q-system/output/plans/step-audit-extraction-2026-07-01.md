# Generic step audit: expected − logged = silently skipped, for any job

**What/why:** The "verify the steps a job claims actually ran" capability exists only inside audit-morning.py (~5-line kernel at lines 92-96/119-123, buried in 250 lines of morning specifics). launchd-health catches jobs that DIE; nothing catches a job that exits 0 having silently skipped work. The open-loops heartbeat is the live example: freeform log, no expected-vs-actual diff — an agent sweep can miss instances invisibly (same class as the 6-day scanner-death scar). Item #2 of morning-extraction-audit-2026-07-01.md, founder-approved.

**Approach (pick):** New parameterized auditor script + heartbeat emits a structured run-log and self-audits post-sweep. audit-morning.py stays untouched as the morning-specific wrapper (refactoring it to call the new kernel = scope creep + regression risk on a working gate; revisit only if they drift). (Alternatives: refactor audit-morning to import the kernel — rejected for now, noted here; put the auditor inside the heartbeat — rejected, other jobs can't reuse it.)

**Files to touch:**
- `q-system/.q-system/scripts/run-step-audit.py` (new: `--expected a,b,c | --manifest file.json`, `--log runlog.json`, `--job NAME`; OK statuses completed/skipped, problems = failed/other, silent = expected but never logged; exit 0 clean / 1 findings / 2 unreadable)
- `q-system/.q-system/scripts/open-loops-heartbeat.sh` (log_step chokepoint writes per-instance status to `q-system/output/heartbeat-run-last.json`; post-sweep runs the auditor with expected = registry instances + kipi-system; non-zero → slack-notify)

**Acceptance criteria:**
- [x] Auditor fixture tests: all six ran (clean 0 / failed 1 / silent-skip 1 named / bad-input 2 / manifest mode / negative)
- [x] Negative self-test: green fixture flips red when one logged step dropped
- [x] Heartbeat integration on isolated copy + stubbed claude: success sweep = 4/4 logged (completed/completed/skipped/skipped), audit OK, no slack ping; failing stub = failed statuses + step-audit slack ping fired
- [x] Freeform .log untouched; run-log additive at q-system/output/heartbeat-run-last.json

**Patterns to follow:** heartbeat's existing TS/log idiom + slack-notify sink (founder-notifications rule); single-writer chokepoint for the run-log (fable-discipline); QROOT resolution for scripts/ depth (folder-structure.md).
