Reviewer: claude (adversarial), commit 403e3994
Verdict: APPROVE

Attack surface tried against the frozen tree (scripts extracted with git archive into a temp dir; every instance built under my own temp dir with CLAUDE_PROJECT_DIR set to it and KIPI_EVIDENCE_REGISTRY pointing at a nonexistent file):

- Types in every field: path, reason, created, expires as int, list, object, null; owner as list and object (owner case is in the standard pass: fails closed but unnamed). No exit 1 from any of the three lints.
- Dates: 2026-13-45, words, compact form, created in the future, expires before or equal to created, 31-day span, 30-day span (allowed). All rejected or allowed as the K7 contract says; UTC clock only, so the host timezone cannot stretch the window.
- Paths: absolute, leading tilde, drive letter, glob characters, '..', './', '//', trailing slash, control characters, over 512 chars. All rejected. Matching is exact on the draft relative to the root, as written and with symlinks resolved; a draft outside the root yields no relative path and cannot match. Case-variant spellings on APFS miss, which fails closed.
- Files: malformed JSON, empty, top-level list, suppressions not a list, 100000-deep nesting, oversized (over 256 KiB), a directory in its place, a self-symlink loop, a dangling symlink. Each yields present=True, nothing suppressed, one named note, markers off.
- A 50000-deep list as a ROW inside suppressions (Python 3.14 parses it): reported as 'row is not an object' with a bounded repr, and the valid row after it still suppresses. No RecursionError at that depth.
- Resolver refusal (two q-* dirs holding canonical/) with the file present: 'NOT READ' note, nothing suppressed, markers off. Without the file: silent, markers on, as before.
- Output channel: on exit 0 every lint prints exactly one JSON object on stdout (band lint through its atexit flush), so the notes are parseable; on exit 2 they follow the report on stderr.

Two hostile file states get through the reader's guards. Neither lets a row suppress a draft it should not, and neither is reachable without someone deliberately building the file, so both are minor.

```json
[
  {
    "severity": "minor",
    "body": "A FIFO at the suppression path hangs every voice lint until the hook timeout, and a PostToolUse timeout is non-blocking, so voice-lint.py fails open for every draft in that instance while the FIFO exists. _read calls os.stat (st_size 0 for a FIFO, so the MAX_BYTES guard passes) and then open(), which blocks waiting for a writer. The reader already guards directories, symlink loops and dangling links; a non-regular file is the one state it does not check. settings-template.json gives voice-lint.py and voice-substance-lint.py a 5 s timeout. Reproducer: temp instance, `mkfifo q-consult/config/voice-suppressions.json`, blocking draft at drafts/x-launch.md, voice-lint hook mode under subprocess.run(timeout=8): TimeoutExpired, no exit code, no output (the child was killed by the timeout; no process left behind). Fix: after os.stat, refuse anything that is not stat.S_ISREG(st.st_mode) with Decision(True, False, ['<path> is not a regular file; suppressing nothing.'], source), and add a FIFO case next to test_a_directory_in_place_of_the_file_suppresses_nothing.",
    "affected_path": "q-system/.q-system/scripts/voice_suppressions.py"
  },
  {
    "severity": "minor",
    "body": "Expired-row notes are unbounded, so one file can put hundreds of KB into additionalContext on every write of a draft, three times per write (one per lint). The module header says output is bounded so a hostile file cannot put megabytes into a hook's output, and invalid rows are capped at MAX_REPORTED plus one summary line, but evaluate appends one 'expired on ...' note per expired row that names the draft, with no cap. Reproducer: temp instance whose file holds 2200 copies of a valid row for drafts/x-launch.md with created 20 days ago and expires yesterday (250818 bytes, under MAX_BYTES), clean draft, voice-lint hook mode: exit 0, additionalContext of 2200 lines and 606089 bytes. Fix: count expired matches like bad rows, report at most MAX_REPORTED of them and one 'and N more expired rows' line, and add a test next to test_many_bad_rows_are_reported_in_a_bounded_number_of_lines.",
    "affected_path": "q-system/.q-system/scripts/voice_suppressions.py"
  }
]
```
