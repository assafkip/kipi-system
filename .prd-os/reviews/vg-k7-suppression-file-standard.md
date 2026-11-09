Reviewer: claude (standard), commit 403e3994
Verdict: APPROVE

Scope: `git diff origin/main...403e3994` (merge base d6ed7bd5 equals origin/main). Read voice_suppressions.py in full, the three lint diffs, both test diffs, the expected_tests fragment, the issue spec and the PRD sections "Shared discovery rule" and "K7 row contract".

What I ran:
- `pytest -q test_voice_suppressions.py`: 42 passed (Python 3.14.7). `pytest -q test_voiceloop_band_lint.py -k "suppressed or band_marker"`: 2 passed.
- Byte-for-byte comparison, origin/main scripts tree versus 403e3994 scripts tree (both extracted with git archive into a temp dir), with NO suppression file: 6 bodies (blocking, blocking plus voice-lint-skip marker, no-anchor, no-anchor plus marker, band marker, clean) x 3 lints x 2 discovery states (temp instance via CLAUDE_PROJECT_DIR; plain dir with no CLAUDE_PROJECT_DIR and no git). Hook mode for all three and CLI mode for voice-lint and voice-substance-lint, comparing (exit, stdout, stderr). Result: 36 of 36 identical. Question (2) holds.
- Malformed file (`{not json`) with the marker in the draft, all three lints in hook mode: each exits 0 or 2 as before for the body, prints "unreadable (JSONDecodeError); suppressing nothing" and "in-file marker ... ignored" inside ONE valid hookSpecificOutput.additionalContext JSON object on stdout, and the band lint still calls the engine (stub argv log written). Question (3) holds.
- Skip channel: SUPPRESSED line carries owner, bounded reason and expires, reaches additionalContext on exit 0 in all three lints; on exit 2 notes go to stderr after the report. Question (4) holds.
- Window: created must be on or before UTC today, expires strictly after created and at most 30 days after it, skip only while UTC today is before expires. A row cannot outlive 30 days from a created date that is not in the future. Question (5) holds.
- Latency: voice-lint hook median 0.030 s on main, 0.046 s at 403e3994 (5 runs each), well inside the 5 s hook timeout in settings-template.json.
- Tests versus named defects (question 6): removing `created > today`, changing `>=` to `>` on expiry, removing the absolute or glob check, or making `_read` return present=False on error each flips at least one assertion (exit code or the one-report-line count). The census has a working negative control.

Findings are below. None makes a lint exit 1 or suppress a draft it should not; all three fail closed. They are contract gaps against the issue text and a stale remedy line.

```json
[
  {
    "severity": "minor",
    "body": "One row whose owner is a JSON list or object disables every valid row in the file and is not reported by name. row_problem does `owner not in OWNERS` on a frozenset, which raises TypeError for an unhashable value; evaluate is outside _read's try, so the exception reaches check()'s outer handler, which returns present=True, skip=False and the note 'voice_suppressions.py failed (TypeError ...)'. That note names neither the file nor the row, and a valid live row for the draft in the same file stops skipping. The issue deliverable and the K7 row contract say an invalid row suppresses nothing and is reported by name; the other rows are supposed to keep working. Reproducer: temp instance with rows [{path: drafts/other.md, owner: [\"sana\"], valid dates}, {path: drafts/x-launch.md, owner: sana, valid dates}], blocking draft at drafts/x-launch.md, voice-lint hook mode: exit 2, last stderr line \"voice-lint: voice_suppressions.py failed (TypeError: cannot use 'list' as a set element (unhashable type: 'list')); suppressing nothing.\" Same with owner {\"a\": 1}. Fix: test `isinstance(owner, str) and owner in OWNERS` in row_problem (and add a list-owner case to BAD_ROWS so the one-report-line assertion pins it).",
    "affected_path": "q-system/.q-system/scripts/voice_suppressions.py"
  },
  {
    "severity": "minor",
    "body": "In an instance that has the suppression file, the blocking report still tells the agent to add the voice-lint-skip marker, which this change makes a no-op there. format_report ends with 'Fix in place, or add (the voice-lint-skip marker) to bypass', and the band lint's DETECTED message says to add the voiceloop-band-lint-skip marker to silence the file. Following that advice costs one more blocked write before the 'marker ignored' note appears. Reproducer: temp instance with a valid file holding one row for drafts/other.md, blocking draft at drafts/x-launch.md with no marker, voice-lint hook mode: exit 2, stderr ends with the 'add ... voice-lint-skip ... to bypass' line and nothing about the suppression file. Fix: when the reader reports present, make the remedy line name the suppression file and the row fields instead of the marker (voice-lint.py format_report caller and the band lint's DETECTED line).",
    "affected_path": "q-system/.q-system/scripts/voice-lint.py"
  },
  {
    "severity": "minor",
    "body": "The census test accepts a script that only mentions voice_suppressions.py in a comment, so it does not prove what the deliverable says (every script that defines a voice skip marker imports the reader). _marker_readers_missing_the_reader passes any file whose text contains the substring 'voice_suppressions.py'; its own negative control asserts that good-lint.py, whose only reference is a trailing comment, is NOT missing. Reproducer: ran test_the_census_catches_a_marker_reader_that_skips_the_reader, which passes with good-lint.py = 'SKIP = \"voice-lint-skip\"  # voice_suppressions.py'. A new marker reader with a comment and its own marker check would pass the census while bypassing the file. Fix: require a load, for example parse the script with ast and look for a call that loads voice_suppressions.py (spec_from_file_location with that name, or an import of voice_suppressions) and a call to `.check(`, and flip the control so a comment-only file is reported missing.",
    "affected_path": "q-system/.q-system/scripts/test/test_voice_suppressions.py"
  }
]
```
