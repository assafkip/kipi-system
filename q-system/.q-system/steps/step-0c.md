Re-read the same key fields from Step 0c:
```bash
bash q-system/.q-system/log-step.sh DATE checksum-end last_calendar_sync "2026-03-14"
bash q-system/.q-system/log-step.sh DATE checksum-end last_gmail_sync "2026-03-14"
bash q-system/.q-system/log-step.sh DATE checksum-end dp_prospect_count "17"
bash q-system/.q-system/log-step.sh DATE checksum-end dp_outreach_count "3"
bash q-system/.q-system/log-step.sh DATE checksum-end decisions_rule_count "17"
bash q-system/.q-system/log-step.sh DATE checksum-end last_publish_date "2026-03-14"
```
The script auto-detects drift between start and end values.

**12b. Mark action cards as delivered:**
```bash
bash q-system/.q-system/log-step.sh DATE deliver-cards
```

**12c. Run the audit harness:**
```bash
python3 q-system/.q-system/audit-morning.py q-system/output/morning-log-DATE.json
```
**Always show the audit output to the founder.** This is not optional.

**12d. Log Step 12 and update morning-state.md:**
```bash
bash q-system/.q-system/log-step.sh DATE 12_audit done "VERDICT - X/Y steps"
```
Update `memory/morning-state.md` with today's sync dates, audit verdict, and any open items.

**12e. Recovery (if audit verdict is not COMPLETE):**
Show the founder the full audit output. Ask: "The routine completed at X%. Here are the gaps: [list]. Options: (1) I go back and run the missing steps now, (2) we accept today's run as-is and fix it tomorrow, (3) we start a fresh session." The founder decides.

---
