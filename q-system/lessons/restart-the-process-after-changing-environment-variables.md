---
id: restart-the-process-after-changing-environment-variables
kind: pattern
title: Restart the Process After Changing Environment Variables
date: 2026-11-03
---

## Principle

Most processes read environment variables once, at startup. Mutating a shell profile or exporting a variable in a new terminal does nothing for a process that is already running — it holds a snapshot of the environment it inherited at launch.

## How to apply

1. **Classify the setting before you debug.** Ask: is this value read from the process environment at start, or from a config source the process re-reads at use time? Only the first category requires a restart. In-session settings, config files polled on each request, and values fetched from a remote store usually take effect immediately.

2. **After changing a start-time variable, do a full relaunch.**
   - Fully exit the process (not just the subcomponent that consumes the value).
   - Open a *new* shell so the profile is re-sourced.
   - Launch the process from that new shell.

3. **Do not try partial recovery first.** Reconnecting a plugin, reloading an extension, restarting a worker, or re-running the failing command inside the same session will reproduce the identical error, because the parent process never acquired the new value. Repeating this is the most common way to lose time on this class of bug — the unchanged error message gets misread as "the value itself is wrong."

4. **Verify from inside the process, not from the shell.** Print or log the variable as the running process sees it. A value that is visible when you echo it in a terminal proves only that the profile change is correct, not that the target process inherited it.

## Diagnostic signal

An error that stays byte-for-byte identical after a credential or config change is strong evidence of a stale environment, not an incorrect value. Treat an unchanged error as "my change was never read" before treating it as "my change was wrong."

## Related traps

- Variables exported in one terminal tab are invisible to processes launched from another.
- GUI-launched applications often inherit a login environment that never sources an interactive shell profile, so a profile edit may require a logout or a session-level mechanism rather than a shell restart.
- Long-lived daemons, language servers, and background agents survive what looks like an application restart; confirm the old process is actually gone.
- Child processes inherit the parent's stale copy, so restarting only the child does not help.

## Preventive habit

When a system depends on start-time environment values, log the resolved configuration (with secrets redacted) at startup. That single line converts an opaque "same error again" loop into an immediate confirmation of what the process actually loaded.
