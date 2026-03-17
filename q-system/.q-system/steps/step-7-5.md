**Step 7.5 — Checkpoint drift detection:**

Catches sessions that ended without `/q-checkpoint` or `/q-end`.

- **Read `memory/morning-state.md`** -> get `Last checkpoint` timestamp
- **Read `my-project/progress.md`** -> get date of most recent log entry
- **Check canonical file modification times:** Use `ls -la` on `canonical/*.md` and `my-project/*.md`. If any file was modified AFTER the last checkpoint timestamp, those changes were made in a session that didn't checkpoint.
- **Drift detected if:** file mtime > last checkpoint timestamp AND no progress.md entry covers those changes
- **Output (only if drift found):**
  ```
  CHECKPOINT DRIFT DETECTED
  Last checkpoint: [date/time]
  Files modified since then: [list with mtimes]
  These changes were not logged. Running checkpoint now to capture them.
  ```
- **Auto-fix:** If drift is detected, run a lightweight checkpoint (log the changed files to `progress.md` with note "Auto-recovered from uncheckpointed session"). Update `morning-state.md` checkpoint timestamp.
- **Rules:**
  - This is a safety net, not a judgment. No pressure language. Just quietly fix it.
  - If no drift, skip this section entirely (no "All caught up!" noise).
