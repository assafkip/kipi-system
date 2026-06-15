# Fable-Discipline Pre-Done Checklist

Copy into the task. Check each box before claiming done. Skip a box only with a
one-line reason next to it.

## Running the task
- [ ] Stage plan written; each stage names one checkable artifact
- [ ] Each stage has a check that can fail (not "looks right")
- [ ] Done-criteria written before starting
- [ ] (multi-session) work log kept and re-read before continuing
- [ ] Confirmed the error actually reproduces before diagnosing it

## Before editing
- [ ] Read the target file this session (not assumed from memory)
- [ ] Grepped the real schema / call-sites the change depends on
- [ ] Re-read exact field/column names instead of guessing them

## While building
- [ ] New dependency: declared and pinned in the manifest, same edit
- [ ] Degenerate cases defined: empty / single / disconnected / non-converging
- [ ] Persisted external input is validated before it is stored
- [ ] Mutations of the shared resource go through one writer
- [ ] Why-comments encode the constraint + the named scar, not the "what"

## Verification (ran, not assumed)
- [ ] Reproducer runs against a temp/copy resource or :memory:, never live
- [ ] Negative self-test: a corrupted input makes the gate FAIL (no rubber stamp)
- [ ] Re-ran after the fix and saw green; pasted the command and the result
- [ ] Grepped every call-site the change had to reach; all covered
- [ ] Guard test proves no caller bypasses the single-writer (if applicable)

## Communication
- [ ] Terse mid-task; one "Verification (ran, not assumed):" block at the seam
- [ ] Options named + pick marked when a real choice existed
- [ ] No style rules applied to shipped output but skipped in your own narration

Bypass the paired hook on a specific file with `# fable-discipline-lint-skip`.
