---
id: one-heredoc-per-shell-invocation
kind: pattern
title: One Heredoc Per Shell Invocation
date: 2026-10-31
---

## Rule

Use at most one heredoc per shell command invocation. If a single command string needs two inline payloads, write one of them to a file first and pass the file path instead.

## Why it breaks

A heredoc body is not attached to the redirect operator's position in the command string. The shell collects heredoc bodies in order, starting on the line after the whole command line is parsed. So in:

```
cmdA -F - <<EOF ; cmdB > out <<PY
```

everything after the newline up to the first terminator is handed to `cmdA`, including the lines you intended as `cmdB`'s input. `cmdB` then receives empty input and usually succeeds silently. There is no syntax error and often no non-zero exit code, so the failure surfaces only in the artifacts: one command gets a payload that looks like the other's, and the second produces an empty or default result.

## How to do it safely

1. **Single payload per call.** One heredoc, one command, one invocation.
2. **Materialize extra payloads first.** Write the second body to a file in a prior step (an editor/file-write tool, or a separate command), then reference it by path: `cmdB < payload.txt` or `cmdA -F payload.txt`.
3. **Prefer file arguments over stdin** for anything multi-line that a tool can read from a path. It makes the content reviewable before it is consumed.
4. **Avoid chaining with `;` or `&&` when a heredoc is present.** Split into separate invocations so each has its own stdin.
5. **Verify the artifact, not the exit code.** After a command that consumed a heredoc, read back what it actually recorded or wrote.

## Why the stakes are asymmetric

Some operations are cheap to retry and some are not. When a mangled payload lands in an append-only or non-rewritable record — an immutable history, a published message, an audit log, a sent notification — the only remedy is a follow-up entry that explains the mistake; the bad entry stays forever. Treat any heredoc feeding such an operation as a one-shot action: stage the payload to a file, inspect it, then run the command.

## Generalization

The underlying hazard is any construct where multiple logical inputs share one physical channel with implicit, order-based assignment: stacked heredocs, repeated stdin redirects in a pipeline, multiple interactive prompts answered by one piped stream, or several tools reading from the same consumed generator. When two consumers share one stream, give each its own named source.
