**Step 5.86 - Open loop review (daily, CANNOT BE SKIPPED):**
> **HARNESS:** Log as `5.86_loop_review`. This step CANNOT be skipped. Open loops are the #1 AUDHD failure mode. New leads (5.9) do NOT replace closing existing loops.

This is the core loop-closing forcing function. It reads all open loops and generates follow-up actions.

1. Use the `kipi://loops/open` MCP resource (filter for min_level=1) to get all loops at level 1+ (3+ days old)
2. **Level 1 loops (3-6 days):** Generate a copy-paste follow-up message for each. Add as action card in morning log. Show in Pipeline Follow-ups section of HTML with yellow `daysAgo` tag.
3. **Level 2 loops (7-13 days):** Generate follow-up AND flag prominently. Show at top of Pipeline Follow-ups with red `daysAgo` tag. If touch_count >= 3 on same channel, switch to a different channel.
4. **Level 3 loops (14+ days):** Present forced choice to founder:
   - "Act now" - generate follow-up, reset to level 2
   - "Park" - close loop, re-engage only on trigger
   - "Kill" - close permanently
   **Step 8 gate BLOCKS if any level 3 loops are unresolved.** The HTML cannot be generated with open level 3 loops.
5. **For each follow-up generated:** Open or update the loop with new touch_count
   ```
   Use the `loop_touch` MCP tool with loop_id=<loop_id>
   ```
6. **Output to HTML:** "Open Loops" section (accent: red, position 2 in section order). Only level 2+ loops show here. Level 0-1 appear as a count in FYI.
```
Use the `log_step` MCP tool with date=DATE, step_id="5.86_loop_review", status="done", result="X loops reviewed, Y follow-ups generated, Z force-closed"
```

---
