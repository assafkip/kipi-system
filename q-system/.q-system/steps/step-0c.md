Re-read the same key fields from Step 0c:
```
Use the `log_checksum` MCP tool with date=DATE, phase="end", field_name="last_calendar_sync", value="2026-03-14"
Use the `log_checksum` MCP tool with date=DATE, phase="end", field_name="last_gmail_sync", value="2026-03-14"
Use the `log_checksum` MCP tool with date=DATE, phase="end", field_name="dp_prospect_count", value="17"
Use the `log_checksum` MCP tool with date=DATE, phase="end", field_name="dp_outreach_count", value="3"
Use the `log_checksum` MCP tool with date=DATE, phase="end", field_name="decisions_rule_count", value="17"
Use the `log_checksum` MCP tool with date=DATE, phase="end", field_name="last_publish_date", value="2026-03-14"
```
The tool auto-detects drift between start and end values.

**12b. Mark action cards as delivered:**
```
Use the `log_deliver_cards` MCP tool with date=DATE
```

**12c. Run the audit harness:**
```bash
python3 q-system/.q-system/audit-morning.py q-system/output/morning-log-DATE.json
```
**Always show the audit output to the founder.** This is not optional.

**12d. Log Step 12 and update morning-state.md:**
```
Use the `log_step` MCP tool with date=DATE, step_id="12_audit", status="done", result="VERDICT - X/Y steps"
```
Update `memory/morning-state.md` with today's sync dates, audit verdict, and any open items.

**12e. Recovery (if audit verdict is not COMPLETE):**
Show the founder the full audit output. Ask: "The routine completed at X%. Here are the gaps: [list]. Options: (1) I go back and run the missing steps now, (2) we accept today's run as-is and fix it tomorrow, (3) we start a fresh session." The founder decides.

---
