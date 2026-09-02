---
id: a-fan-out-installer-must-refuse-where-its-job-cannot-run
kind: pattern
title: A fan-out installer must refuse where its job cannot run
date: 2026-09-02
---

The lessons-daily installer lived under the fanned-out scripts directory, so every instance carried it. Run in an instance it rebound the skeleton-only launchd label to that instance's copy of a job that shells the updater, which only works in the skeleton. `install-plist.sh --all` would have installed the template from an instance too. The installer now reads the registry and refuses unless its root is the skeleton path; the template carries a `kipi-scope: skeleton-only` marker that `--all` honours. Issue 5 of prd-lessons-rail-and-up-rail.

How to apply:

1. A script that fans out runs everywhere; decide where it may act and check that at runtime from a registry, not from a comment.
2. Anything that installs "everything" needs a per-item scope marker, or it re-creates the collision the marker exists to prevent.
