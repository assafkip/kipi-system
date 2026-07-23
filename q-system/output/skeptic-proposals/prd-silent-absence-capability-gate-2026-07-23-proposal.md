# Skeptic anti-pattern proposal - prd-silent-absence-capability-gate-2026-07-23

Generated: 2026-07-23T22:07:38Z

## Findings the Skeptic did not catch

### finding-1 (blocker, routed to uncategorized, class: no-known-class)

The Issues manifest is empty, so there is no atomic decomposition, no allowed_files, no required_checks, and no bypass checks. The PRD cannot be approved or independently verified against the rubric in this state.

**Proposed anti-pattern phrasing:**

Codex flagged this issue but it does not match any pre-defined anti-pattern class. Treat this as a candidate for a new Skeptic question or a different persona (PM, Architect, UX).

### finding-2 (blocker, routed to uncategorized, class: no-known-class)

The claimed fleet-side kipi check call site is not designed end to end. The kipi CLI changes directory to KIPI_HOME and runs the skeleton's validate-separation.py, so invoking kipi check from a consulting instance does not run the gate in that instance. A separate fleet-capability-verify.py is described, but nothing makes it an automatic required call site.

**Proposed anti-pattern phrasing:**

Codex flagged this issue but it does not match any pre-defined anti-pattern class. Treat this as a candidate for a new Skeptic question or a different persona (PM, Architect, UX).

### finding-3 (major, routed to uncategorized, class: no-known-class)

The goal says the gate runs in every registered instance, but instance-registry.json contains 24 entries including reddit-build-radar, a standalone entry with no skeleton subtree. fleet-capability-verify.py is specified to fail when an instance lacks the gate or manifest, making the stated success condition impossible unless standalone and skipped-instance semantics are defined.

**Proposed anti-pattern phrasing:**

Codex flagged this issue but it does not match any pre-defined anti-pattern class. Treat this as a candidate for a new Skeptic question or a different persona (PM, Architect, UX).

### finding-4 (major, routed to uncategorized, class: no-known-class)

The PRD never defines the manifest's validation contract: required keys, duplicate-path behavior, unknown-key handling, path normalization, glob rules, malformed JSON behavior, timeout bounds, or schema versioning. Different implementations can accept materially different declarations while still claiming compliance.

**Proposed anti-pattern phrasing:**

Codex flagged this issue but it does not match any pre-defined anti-pattern class. Treat this as a candidate for a new Skeptic question or a different persona (PM, Architect, UX).

### finding-5 (major, routed to uncategorized, class: no-known-class)

The local overlay is an unbounded gate-bypass surface. The PRD says the gate merges capability-manifest.local.json but does not define precedence or prohibit an instance overlay from removing canonical tests, quarantining them, changing skeleton_only membership, or weakening required_data scope.

**Proposed anti-pattern phrasing:**

Codex flagged this issue but it does not match any pre-defined anti-pattern class. Treat this as a candidate for a new Skeptic question or a different persona (PM, Architect, UX).

### finding-6 (major, routed to uncategorized, class: no-known-class)

Quarantine can preserve the exact absence this PRD is meant to eliminate. Any newly executed failing test may be skipped indefinitely with only a reason and spillover ID; there is no owner, expiry, review deadline, maximum quarantine count, or acceptance criterion requiring the quarantine set to decrease.

**Proposed anti-pattern phrasing:**

Codex flagged this issue but it does not match any pre-defined anti-pattern class. Treat this as a candidate for a new Skeptic question or a different persona (PM, Architect, UX).

### finding-7 (major, routed to uncategorized, class: no-known-class)

The negative proof is too weak to validate the design. An incomplete manifest trivially catches F1 as present-but-undeclared, satisfying catches at least one of F1-F4 without proving skeleton-only handling, required-data scope, inert-script detection, instance execution, or either token-guard fix.

**Proposed anti-pattern phrasing:**

Codex flagged this issue but it does not match any pre-defined anti-pattern class. Treat this as a candidate for a new Skeptic question or a different persona (PM, Architect, UX).

### finding-8 (major, routed to uncategorized, class: no-known-class)

The F2 detector has no precise discovery or reachability model. Scanning four textual wiring surfaces can label scripts inert even when invoked through imports, the root kipi CLI, another shell script, launchd or cron configuration, generated settings, or dynamic command construction, while references in comments can create false evidence of wiring.

**Proposed anti-pattern phrasing:**

Codex flagged this issue but it does not match any pre-defined anti-pattern class. Treat this as a candidate for a new Skeptic question or a different persona (PM, Architect, UX).

### finding-10 (major, routed to uncategorized, class: no-known-class)

The runner contract omits working directory, environment isolation, required binaries, network policy, output limits, and side-effect constraints. Running 38 heterogeneous standalone scripts as subprocesses in CI and across 23 managed instances is not independently reproducible without those inputs.

**Proposed anti-pattern phrasing:**

Codex flagged this issue but it does not match any pre-defined anti-pattern class. Treat this as a candidate for a new Skeptic question or a different persona (PM, Architect, UX).

### finding-11 (major, routed to uncategorized, class: no-known-class)

The scope line quick fixes yes is unbounded. It permits edits to any of the 34 newly executed tests and their production dependencies, but the blast-radius section only lists the gate, manifest, fleet verifier, validate.yml, validate-separation.py, and token-guard.py.

**Proposed anti-pattern phrasing:**

Codex flagged this issue but it does not match any pre-defined anti-pattern class. Treat this as a candidate for a new Skeptic question or a different persona (PM, Architect, UX).

### finding-12 (major, routed to uncategorized, class: no-known-class)

Rollback stops at reverting skeleton files, but the plan explicitly propagates and commits changes into the managed instances through kipi update. Reverting the skeleton does not remove or revert the already-created instance commits, manifests, or locally generated overlays.

**Proposed anti-pattern phrasing:**

Codex flagged this issue but it does not match any pre-defined anti-pattern class. Treat this as a candidate for a new Skeptic question or a different persona (PM, Architect, UX).

### finding-13 (major, routed to uncategorized, class: no-known-class)

The skeleton-versus-instance mode detector is described only as a repo basename plus instance-registry.json self-reference match, while the cited instance-automation-guard actually checks only for registry-file existence. The new algorithm, self-reference definition, and behavior for worktrees, renamed clones, stale registries, symlinks, and parse failures are unspecified even though misclassification changes which tests and data requirements are skipped.

**Proposed anti-pattern phrasing:**

Codex flagged this issue but it does not match any pre-defined anti-pattern class. Treat this as a candidate for a new Skeptic question or a different persona (PM, Architect, UX).

## Skeptic Q-A pairs captured

**Q1:** What is the strongest argument against doing this?

A declaration file devs must maintain can rot into ritual; if the gate is

**Q2:** What is the smallest experiment that would disprove the thesis?

Run the gate on today's untouched repo state. If it does not catch F1 (34

**Q3:** What is the cheapest non-build alternative?

A prose rule "declare your tests" — prompt-only enforcement, which this

## How to merge

1. Read each finding above. The 'routed to Qx' label tells you which Skeptic question should have surfaced it.
2. Edit the proposed anti-pattern phrasing to match your voice.
3. Append accepted anti-patterns to `plugins/prd-os/personas/skeptic.md` under '## Anti-patterns the Skeptic watches for'.
4. Commit through normal git flow so Codex review fires on the diff.
