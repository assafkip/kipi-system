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
- [ ] Any out-of-scope finding noticed is CAPTURED to the spillover ledger (`prd_runner.py spillover add`), never just mentioned — the standing gate holds it until it is fixed as a tracked issue

## Gap classes (build against these)
Defect shapes that repeatedly ship past review on changes that scale or touch
sensitive data. Check only the ones this change touches.
- [ ] New append-only store ships compaction + a bounded read in THIS change (an in-memory cap bounds memory, not the file or read cost); compaction runs before any boot-time whole-file read
- [ ] Search/filter applied to the cheap key set BEFORE per-item enrichment (cost scales with the filtered set, not the catalog)
- [ ] New capability is additive: new params default-off, new data in a header/new field; existing response body that has consumers is not reshaped
- [ ] Persistence change verified to land on a durable mount in the deploy target (not just in code)
- [ ] State (archived/retired/blocked) enforced at the ACTION endpoint on every reachable path (API, CLI, replay), not only the list view
- [ ] A gate fails CLOSED (refuses when it cannot verify); a filter may fail open; they do NOT share one helper
- [ ] Redaction is at the egress edge; nothing augments/mutates the payload after it (or every post-step re-redacts)
- [ ] What gets persisted is a redacted, whitelisted, JSON-safe projection, never the raw in-memory object
- [ ] Exposure classified by recipient (authorized?) + necessity before masking; the fix does not break the core workflow
- [ ] Hiding/suppressing a thing does not bury an open obligation (block the hide while work is open)
- [ ] A new flag/field reaches EVERY reader of the store (raw readers patched; canonical/replay-view readers inherit it); asked "what else reads this?" until nothing
- [ ] Overloading an existing field: audited every existing consumer of that field
- [ ] Check-then-mutate on shared state under one lock; compaction uses a SEPARATE stable lock file; shared counters guarded; proven with an N-thread reproducer
- [ ] Liveness/health endpoint is per-line tolerant; never 500s on one bad row
- [ ] Version/identity single-sourced; a test asserts the copies match
- [ ] Cross-cutting invariant has a WRITTEN scope (what it does and does NOT cover) and a guard test that enumerates targets from the system (routes/registries), not a hand list

## Verification (ran, not assumed)
- [ ] Reproducer runs against a temp/copy resource or :memory:, never live
- [ ] Negative self-test: a corrupted input makes the gate FAIL (no rubber stamp)
- [ ] Re-ran after the fix and saw green; pasted the command and the result
- [ ] Grepped every call-site the change had to reach; all covered
- [ ] Guard test proves no caller bypasses the single-writer (if applicable)
- [ ] Load-path proof: confirmed the RUNNING system loads the copy I edited (not a marketplace/skeleton/third-party copy); text-in-a-file is not wired

## Communication
- [ ] Terse mid-task; one "Verification (ran, not assumed):" block at the seam
- [ ] Options named + pick marked when a real choice existed
- [ ] No style rules applied to shipped output but skipped in your own narration

Bypass the paired hook on a specific file with `# fable-discipline-lint-skip`.
