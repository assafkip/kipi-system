---
id: a-supervised-restart-runs-in-a-stripped-environment-and-auth
kind: pattern
title: A supervised restart runs in a stripped environment, and auth errors will lie about it
date: 2026-07-27
---

## The failure shape

A long-lived process is kept alive by a supervisor (init system, service manager, container restart policy, cron-style respawn). It was first started by hand from an interactive shell, so it inherited that shell's full environment. When it dies and the supervisor recreates it, it comes back under the supervisor's own environment: a minimal set of variables, often missing identity variables (user, home, login name), PATH entries, and anything sourced from a shell profile.

The process starts. It looks healthy. But a dependency that resolves credentials by looking up the current user's config location now can't find anything, and reports the only failure it knows how to report: "not authenticated" / "session expired" / "please log in again."

The credential was never stale. The process could not reach the store. Two different faults, one error string. Chasing the error string sends you to re-authenticate something that was already valid, and the real cause survives the fix.

## Why it stays invisible

- The hand-started run and the supervisor-started run are the *same command*, so nothing in your config or your logs distinguishes them.
- The first restart may be days or weeks after deploy, so the failure arrives detached from any change you made.
- Restarts are usually silent by design; the supervisor's job is to make death invisible.
- Downstream, the process often degrades quietly: it does zero work instead of crashing, so uptime and liveness checks stay green.

## What to do

**1. Separate "cannot reach the credential store" from "credential is invalid."**

Any code path that concludes "expired, re-authenticate" should first check whether the store was even reachable and readable. Emit distinct diagnostics for: store path could not be resolved (missing env), store path resolved but absent, store present but rejected. Only the third one is an actual expiry. If you don't own the dependency emitting the misleading message, wrap it: probe the preconditions yourself before you trust its verdict.

**2. Pin the environment in the supervisor definition, not in a shell profile.**

Declare every variable the process needs explicitly in the service[PATH] definition, including the identity variables you never think about because a login shell always sets them, and an absolute PATH covering every interpreter and binary you shell out to. Profile files are not read by supervisors. Treat "works when I run it in my terminal" as unverified for the supervised case.

**3. Make the two launch modes provably identical.**

Dump the environment at startup (names, plus values for the non-secret ones) into the process log. Then compare a hand-started run against a supervisor-started run. The diff is the bug list. Do this once at build time rather than at 3am during an outage.

**4. Gate the real work behind a startup precondition check.**

Before the process arms its main loop, have it verify the things it silently assumes: required variables present, credential store readable, external interpreters resolvable. Fail loudly and refuse to enter the loop if any check fails. A process that exits with a specific error is far cheaper to debug than one that runs all day doing nothing.

**5. Alarm on absence of output, not on presence of errors.**

This class of failure produces no errors, no crash, and no restart loop. It produces zero. If a job is supposed to do N units of work per window, alert when the count is zero at the end of the window. Liveness checks that only ask "is the process running?" will pass through the entire outage.

## Wider application

The same shape appears anywhere execution context silently changes between the run you tested and the run that matters: a scheduled task versus an interactive one, a CI job versus a local build, a container's entrypoint versus an exec into that container, a background worker versus the request handler that spawned it. The generalizable rule is: an error message describes what a component observed, not what caused it. When a component says "credentials are bad," verify it could actually see the credentials before you act on that claim.
