---
id: enumerate-a-guard-s-population-from-code-and-test-data-flow-
kind: methodology
title: Enumerate a guard's population from code, and test data flow, not text
date: 2026-10-05
---

Three defects compound when a pipeline stage protects shared state and its health is judged by whether it ran.

1. Derive the guarded population mechanically. A guard designed against a remembered list of writers protects only those writers. Any path that mutates the protected state and was not remembered stays open, and an audit that also works from memory misses it the same way. Build the list by search: find every call site that writes the resource, then make a test fail when a new writer appears that the guard does not cover. Put the check where the write happens, not only at the first step of the pipeline.

2. Test behaviour across stages. Checks that ask whether a line exists in a script, or whether a scheduler config names the script, say nothing about ordering or data flow. When a defect lives in how stage A's output feeds stage B, run the stages against a throwaway copy of the data and assert on what the final stage emitted. Include a case where the earlier stage destroys or empties its input, and require that the later stage notices.

3. Do not read a finished run as a healthy run. Exit code zero and a heartbeat prove the process ended. If the output for 'nothing happened' is byte-identical to the output for 'the inputs were lost', every surface looks fine. Make the empty case distinguishable: emit a count of inputs seen alongside the result, fail when the input count is zero where zero is implausible, and verify a run by checking the output against a known non-empty fixture before calling it live.
