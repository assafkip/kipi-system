---
id: prd-skeleton-data-containment-2026-07-24
title: Skeleton Data Containment
status: approved
created_at: 2026-07-24T20:42:16Z
updated_at: 2026-07-24T20:50:12Z
owner: senior-staff
reviewers: []
findings_path: .prd-os/findings/prd-skeleton-data-containment-2026-07-24-findings.jsonl
codex_reviewed_at: 2026-07-24T20:47:46Z
---

# Skeleton Data Containment

## Problem

The generic skeleton promises that project facts live in instances, while
generic paths contain templates and shared capabilities
[`ARCHITECTURE.md:5`, `ARCHITECTURE.md:15-23`, `ARCHITECTURE.md:29-36`].
That contract is broken. `q-system/canonical/discovery.md` names Ally, Ethan,
Active Fence, Tova, an FBI contractor, and live investigation proof gaps
[`q-system/canonical/discovery.md:18-49`].
`q-system/canonical/pricing-framework.md` names Chris and records exact setup,
support, and hourly pricing
[`q-system/canonical/pricing-framework.md:21-39`].

The current separation gate only searches a short set of names and phrases
[`validate-separation.py:339-340`, `validate-separation.py:390-406`]. A fresh
run of `python3 validate-separation.py 3` on 2026-07-24 reported
`No KTLYST content in canonical templates (0 files)` while the cited prospect,
pricing, and investigation facts were present. That is a semantic false
negative. Any generic content that reaches an updater source can cross an
instance boundary, which violates the explicit rule that instance-specific
content must never live in `q-system/` [`ARCHITECTURE.md:93-95`].

## Goals

- Inventory every instance-specific fact under generic paths, including names,
  relationships, prices, investigations, client evidence, and live proof gaps.
- Move the current instance material into the verified owner instance through
  an implementation issue, with a receipt that proves the destination before
  the generic copy is replaced by its documented template form.
- Add deterministic fixtures that detect semantic client leakage rather than
  relying only on a short name blacklist.
- Prove the final state modeled by `kipi update` cannot introduce skeleton
  instance content into any registered destination.
- Preserve generic templates and their documented schema
  [`ARCHITECTURE.md:15-23`, `ARCHITECTURE.md:49-57`].
- Record a separate, explicit decision for public Git history. This PRD does
  not authorize history rewriting.

## Non-goals

- Rewriting Git history, force pushing, deleting branches, or removing public
  history.
- Changing the updater's preservation algorithm. That belongs to
  `fail-closed-fleet-updater`.
- Choosing a new canonical schema or inventing replacement content.
- Editing an external instance repo as part of this PRD authoring run.
- Replacing the existing capability gate without proof that its working checks
  remain covered.

## Proposed approach

1. Enumerate tracked text files under `q-system/`, `plugins/`, `.claude/`, and
   the repository root from Git, with explicit exclusions for `.prd-os/`,
   `q-system/output/`, `q-system/memory/`, generated assets, and binary files.
   Produce a machine-readable leak inventory from that repository-derived
   target set. Raw facts never enter a committed skeleton artifact. The
   committed report contains source coordinates, fact class, redacted
   identifier, and content hash. Unknown ownership remains unresolved.
2. Add a reproducer fixture containing synthetic names, a relationship, a
   price, and an investigation fact that are absent from the current blacklist.
   The existing validator must fail that fixture before its detection logic is
   changed. The deterministic grammar treats populated canonical fields,
   currency amounts, person or organization source fields, dated interaction
   records, and case-specific proof gaps as asserted facts. Placeholder tokens
   and fixtures marked `fixture: synthetic` are generic. Any unclassified
   populated record fails closed.
3. Export the cited material to the `investigations` registry entry at
   `/Users/assafkipnis/projects/intel/projects/kipi-investigations/q-system/canonical/`,
   verify hashes at that exact destination, then restore the generic files to
   their existing template schema. A 2026-07-24 read-only command confirmed
   that the destination canonical files exist and do not yet contain the cited
   Ally or Chris records. The registry identifies this instance at
   `instance-registry.json:92-97`.
4. Treat update propagation as preventive hardening. The current updater
   excludes canonical content
   [`validate-separation.py:390-396`, `kipi-update.sh:179-184`], so the cited
   leak is a storage separation breach, not proof of observed propagation.
   Block propagation proof on closed issue `fcu-dry-run-final-state` from
   `prd-fail-closed-fleet-updater-2026-07-24`, then assert that no injected
   instance fact appears in a destination final state.
5. Publish a history-handling decision that states whether public history is
   accepted, documented, or handled by a separate approved program. No command
   in this work rewrites history.

## Alternatives considered

- **Expand the name blacklist.** Rejected because the observed miss is semantic.
  New names, prices, and relationships would remain invisible
  [`validate-separation.py:339-340`].
- **Delete the material from the skeleton immediately.** Rejected because it
  risks data loss and does not prove the correct instance received the source
  facts.
- **Rewrite public history now.** Rejected because the founder contract
  explicitly separates that decision and excludes history rewriting here.

## Scenarios

- **Known leak migration.** An engineer runs the inventory, sees the cited
  Chris pricing record, verifies its owner from registry and destination
  evidence, writes it to that instance-owned store, verifies the receipt, and
  restores the skeleton file to the same template schema.
- **Unknown client name.** A fixture uses a synthetic client name not present
  in any blacklist plus a price and relationship. The semantic separation test
  fails before the fix and passes only after the content is classified as
  instance-specific.
- **Fleet update proof.** A fixture injects an instance fact into a generic
  source, models `kipi update` for registered layout variants, and fails when
  the fact appears in any final destination.
- **Public history.** A maintainer finds a removed fact in a historical commit.
  The containment work records the finding and applies the separate history
  decision. It does not rewrite history.

## Resolved decisions

- **Containment is evidence-first.** Decided: export and verify before restoring
  templates. Rationale: deletion alone can lose the only current copy.
- **Detection is semantic and fixture-backed.** Decided: keep blacklist checks
  as a defense layer, but do not treat them as the separation contract.
  Rationale: the 2026-07-24 run passed the named check while cited instance
  facts remained.
- **The target set self-enumerates.** Decided: derive tracked text targets from
  Git and validate an explicit exclusion allowlist. Rationale: a hand-maintained
  file list would miss the next generic surface.
- **Raw facts stay outside committed skeleton artifacts.** Decided: skeleton
  reports carry hashes and redacted identifiers only. Rationale: an inventory
  must not turn the same exposure into a durable second copy.
- **Issue order is serial.** Decided: inventory scope and quarantine land
  before export, export receipt lands before template restoration, semantic
  classification lands before the self-enumerating guard, and preventive
  propagation proof waits for `fcu-dry-run-final-state`. Rationale: overlapping
  data movement and enforcement changes are not independently safe.
- **Template shape stays stable.** Decided: restore placeholders and documented
  sections rather than redesign canonical files. Rationale: the architecture
  identifies those files as shared templates [`ARCHITECTURE.md:15-23`].
- **History is a separate decision.** Decided: no history rewrite is authorized
  by this PRD. Rationale: it is an explicit founder constraint.

## Risks and rollback

- **Wrong owner selection.** Stop before removing the generic copy unless the
  destination receipt identifies the `investigations` registry entry and
  confirms the full exported payload. Rollback retains the payload in protected
  quarantine or the verified destination. It never republishes raw facts into
  generic files.
- **False positives in generic examples.** Fixtures must distinguish synthetic
  schema examples from asserted facts. Rollback disables only the new semantic
  rule while retaining the inventory and current blacklist gate.
- **Updater proof tests the wrong model.** The propagation issue depends on the
  closed `fcu-dry-run-final-state` receipt from
  `prd-fail-closed-fleet-updater-2026-07-24`. Until that receipt exists, the
  issue stays blocked and cannot claim fleet proof.
- **Sensitive data remains in public history.** The repository records the
  exposure and follows the separate decision. Rollback is not a history
  rewrite.

## Open questions

- Does the `investigations` owner want the records in its excluded
  `q-system/canonical/` files or a dedicated instance content directory? The
  export issue must settle this before writing and record the exact path.
- Does any current public-history exposure require a separate security or legal
  response? This PRD records the decision owner but does not decide or execute a
  rewrite.
- Which generic narrative examples, if any, are explicitly approved fixtures
  rather than instance facts? They need an allowlisted provenance record.

## Evidence

- **E1:** Skeleton and instance separation contract:
  `ARCHITECTURE.md:5`, `ARCHITECTURE.md:15-23`,
  `ARCHITECTURE.md:29-36`, `ARCHITECTURE.md:86-95`.
- **E2:** Named prospect and investigation facts:
  `q-system/canonical/discovery.md:18-49`.
- **E3:** Named client and exact pricing facts:
  `q-system/canonical/pricing-framework.md:21-39`.
- **E4:** Current lexical enforcement:
  `validate-separation.py:339-340`, `validate-separation.py:390-406`.
- **E5:** Command result: `python3 validate-separation.py 3`, run 2026-07-24,
  reported 70 pass, 1 fail, 1 warning and reported zero KTLYST content in
  canonical templates while E2 and E3 remained present.
- **E6:** Read-only ownership command result, run 2026-07-24: the
  `investigations` registry destination contains
  `q-system/canonical/discovery.md` and `pricing-framework.md`, and neither file
  matched `Ally|Chris|Active Fence|Tova|Ethan|6,500|1,500`.

## Superseded issue draft

```json
[
  {
    "id": "sdc-inventory-and-owner-receipts",
    "finding_id": "finding-1",
    "title": "Inventory instance facts and prove their owner destinations",
    "priority": "p0",
    "allowed_files": [
      "validate-separation.py",
      "q-system/.q-system/tests/separation/**",
      "q-system/canonical/discovery.md",
      "q-system/canonical/pricing-framework.md"
    ],
    "disallowed_files": [
      "instance-registry.json",
      ".prd-os/**",
      "kipi-update.sh",
      ".git/**"
    ],
    "required_checks": [
      "python3 -m pytest -q q-system/.q-system/tests/separation/test_instance_fact_inventory.py",
      "python3 validate-separation.py 3"
    ],
    "required_reviews": [
      "data-owner",
      "security"
    ],
    "acceptance": [
      "Write a failing inventory contract test before implementation.",
      "Inventory every asserted name, relationship, price, investigation fact, and live proof gap under generic paths.",
      "Every migrated record has a verified registry owner and byte-complete destination receipt before its generic source is restored to template form.",
      "Unknown ownership fails closed and leaves the source recoverable."
    ],
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/separation/test_instance_fact_inventory.py -k 'unknown_owner or destination_receipt'"
  },
  {
    "id": "sdc-semantic-separation-fixtures",
    "finding_id": "finding-2",
    "title": "Add semantic client leakage fixtures",
    "priority": "p0",
    "allowed_files": [
      "validate-separation.py",
      "q-system/.q-system/tests/separation/**"
    ],
    "disallowed_files": [
      "q-system/canonical/**",
      "instance-registry.json",
      ".prd-os/**",
      ".git/**"
    ],
    "required_checks": [
      "python3 -m pytest -q q-system/.q-system/tests/separation/test_semantic_client_leakage.py",
      "python3 validate-separation.py 3"
    ],
    "required_reviews": [
      "security"
    ],
    "acceptance": [
      "Write a failing synthetic leakage fixture before changing detection.",
      "The fixture uses names absent from the current blacklist and includes a relationship, price, and investigation fact.",
      "Generic placeholder examples still pass when their provenance is explicit.",
      "The current lexical checks remain active unless an equivalent deterministic assertion proves coverage."
    ],
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/separation/test_semantic_client_leakage.py -k 'unknown_name and price and relationship'"
  },
  {
    "id": "sdc-update-propagation-proof",
    "finding_id": "finding-3",
    "title": "Prove updater final states cannot propagate instance facts",
    "priority": "p0",
    "allowed_files": [
      "q-system/.q-system/scripts/test/test-kipi-update-safety.sh",
      "q-system/.q-system/tests/separation/**",
      "validate-separation.py"
    ],
    "disallowed_files": [
      "kipi-update.sh",
      "instance-registry.json",
      "q-system/canonical/**",
      ".prd-os/**"
    ],
    "required_checks": [
      "bash q-system/.q-system/scripts/test/test-kipi-update-safety.sh",
      "python3 -m pytest -q q-system/.q-system/tests/separation/test_update_propagation.py"
    ],
    "required_reviews": [
      "updater-owner",
      "security"
    ],
    "acceptance": [
      "Write a failing propagation reproducer before implementation.",
      "The check models the final destination state, not only rsync item output.",
      "A synthetic instance fact in a generic source fails every registered layout fixture.",
      "No production instance repo is changed by the test."
    ],
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/separation/test_update_propagation.py -k 'final_state and injected_fact'"
  },
  {
    "id": "sdc-public-history-decision",
    "finding_id": "finding-4",
    "title": "Record safe public-history handling without rewriting history",
    "priority": "p0",
    "allowed_files": [
      "ARCHITECTURE.md",
      "CONTRIBUTE.md",
      "q-system/.q-system/tests/separation/test_public_history_contract.py"
    ],
    "disallowed_files": [
      ".git/**",
      "q-system/canonical/**",
      "instance-registry.json",
      ".prd-os/**"
    ],
    "required_checks": [
      "python3 -m pytest -q q-system/.q-system/tests/separation/test_public_history_contract.py"
    ],
    "required_reviews": [
      "security",
      "repository-owner"
    ],
    "acceptance": [
      "Write a failing contract test for a missing history decision before documentation changes.",
      "The decision names an owner and one of accept, document, or separate approved response.",
      "The decision explicitly forbids history rewriting under this issue.",
      "The test fails if the runbook recommends destructive Git history operations."
    ],
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/separation/test_public_history_contract.py -k 'no_history_rewrite'"
  }
]
```

## Issues

```json
[
  {
    "id": "sdc-inventory-scope",
    "finding_id": "finding-1",
    "title": "Build the redacted instance-fact inventory",
    "priority": "p0",
    "allowed_files": ["q-system/.q-system/scripts/instance-fact-inventory.py", "q-system/.q-system/tests/separation/test_instance_fact_inventory.py"],
    "disallowed_files": ["q-system/canonical/**", "instance-registry.json", ".prd-os/**", ".git/**"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/separation/test_instance_fact_inventory.py"],
    "required_reviews": ["security"],
    "acceptance": "Write the failing inventory contract test first. Derive targets from tracked files, emit hashes and redacted identifiers only, and fail closed on unknown ownership.",
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/separation/test_instance_fact_inventory.py -k 'unknown_owner or raw_fact'"
  },
  {
    "id": "sdc-semantic-classifier",
    "finding_id": "finding-2",
    "title": "Add deterministic semantic leakage classification",
    "priority": "p0",
    "allowed_files": ["validate-separation.py", "q-system/.q-system/tests/separation/test_semantic_client_leakage.py"],
    "disallowed_files": ["q-system/canonical/**", "instance-registry.json", ".prd-os/**", ".git/**"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/separation/test_semantic_client_leakage.py"],
    "required_reviews": ["security"],
    "acceptance": "Write the failing synthetic fixture first. Detect populated fact fields, currency, sourced interactions, and case proof gaps while allowing placeholders and explicitly synthetic fixtures.",
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/separation/test_semantic_client_leakage.py -k 'unknown_name and unclassified'"
  },
  {
    "id": "sdc-update-propagation-proof",
    "finding_id": "finding-3",
    "title": "Prove updater final states reject injected instance facts",
    "priority": "p0",
    "allowed_files": ["q-system/.q-system/tests/separation/test_update_propagation.py"],
    "disallowed_files": ["kipi-update.sh", "q-system/canonical/**", "instance-registry.json", ".prd-os/**"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/separation/test_update_propagation.py"],
    "required_reviews": ["updater-owner", "security"],
    "acceptance": "Write the failing final-state reproducer first. Do not start until fcu-dry-run-final-state is closed. Test registered layout fixtures without changing production instances.",
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/separation/test_update_propagation.py -k 'final_state and injected_fact'"
  },
  {
    "id": "sdc-public-history-decision",
    "finding_id": "finding-4",
    "title": "Record public-history handling without rewriting history",
    "priority": "p0",
    "allowed_files": ["ARCHITECTURE.md", "q-system/.q-system/tests/separation/test_public_history_contract.py"],
    "disallowed_files": [".git/**", "q-system/canonical/**", "instance-registry.json", ".prd-os/**"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/separation/test_public_history_contract.py"],
    "required_reviews": ["security", "repository-owner"],
    "acceptance": "Write the failing contract test first. Record an owner and an accept, document, or separate-response decision, and forbid destructive history operations.",
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/separation/test_public_history_contract.py -k no_history_rewrite"
  },
  {
    "id": "sdc-scoped-green-checks",
    "finding_id": "finding-5",
    "title": "Use scoped green checks for containment issues",
    "priority": "p0",
    "allowed_files": ["q-system/.q-system/tests/separation/test_containment_scoped_checks.py"],
    "disallowed_files": ["validate-separation.py", "q-system/canonical/**", "instance-registry.json", ".prd-os/**"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/separation/test_containment_scoped_checks.py"],
    "required_reviews": ["test-owner"],
    "acceptance": "Write a failing test that proves containment checks do not inherit unrelated baseline failures, then require each scoped command to exit zero.",
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/separation/test_containment_scoped_checks.py -k unrelated_failure"
  },
  {
    "id": "sdc-owner-export",
    "finding_id": "finding-6",
    "title": "Export current facts to the verified investigations owner",
    "priority": "p0",
    "allowed_files": ["/Users/assafkipnis/projects/intel/projects/kipi-investigations/q-system/canonical/discovery.md", "/Users/assafkipnis/projects/intel/projects/kipi-investigations/q-system/canonical/pricing-framework.md", "/Users/assafkipnis/projects/intel/projects/kipi-investigations/q-system/canonical/.containment-receipt.json"],
    "disallowed_files": ["q-system/canonical/**", "instance-registry.json", ".prd-os/**", ".git/**"],
    "required_checks": ["python3 q-system/.q-system/scripts/verify-containment-export.py --instance investigations"],
    "required_reviews": ["data-owner", "security"],
    "acceptance": "Write a failing destination-receipt contract test first. Confirm the owner path, export the complete records, and record source and destination hashes before any skeleton source is restored.",
    "bypass_check": "python3 q-system/.q-system/scripts/verify-containment-export.py --instance investigations --require-hash-match"
  },
  {
    "id": "sdc-redacted-inventory-boundary",
    "finding_id": "finding-7",
    "title": "Enforce the inventory redaction boundary",
    "priority": "p0",
    "allowed_files": ["q-system/.q-system/schemas/containment-inventory.schema.json", "q-system/.q-system/tests/separation/test_inventory_redaction.py"],
    "disallowed_files": ["q-system/canonical/**", "q-system/output/**", "instance-registry.json", ".prd-os/**"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/separation/test_inventory_redaction.py"],
    "required_reviews": ["security"],
    "acceptance": "Write the failing raw-fact persistence test first. Permit hashes, coordinates, fact classes, and redacted identifiers only in committed skeleton artifacts.",
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/separation/test_inventory_redaction.py -k raw_payload"
  },
  {
    "id": "sdc-serial-execution-contract",
    "finding_id": "finding-8",
    "title": "Lock containment issue execution order",
    "priority": "p0",
    "allowed_files": ["q-system/.q-system/tests/separation/test_containment_sequence.py"],
    "disallowed_files": ["validate-separation.py", "q-system/canonical/**", "instance-registry.json", ".prd-os/**"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/separation/test_containment_sequence.py"],
    "required_reviews": ["test-owner"],
    "acceptance": "Write a failing ordering test first. Require inventory and quarantine before export, export receipt before template restoration, and updater final-state receipt before propagation proof.",
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/separation/test_containment_sequence.py -k refuses_out_of_order"
  },
  {
    "id": "sdc-preventive-propagation-label",
    "finding_id": "finding-9",
    "title": "Distinguish storage breach from preventive propagation proof",
    "priority": "p0",
    "allowed_files": ["q-system/.q-system/tests/separation/test_containment_claims.py"],
    "disallowed_files": ["kipi-update.sh", "q-system/canonical/**", "instance-registry.json", ".prd-os/**"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/separation/test_containment_claims.py"],
    "required_reviews": ["updater-owner"],
    "acceptance": "Write a failing claim-classification test first. Assert that current canonical exposure is a storage breach and propagation remains preventive until final-state evidence exists.",
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/separation/test_containment_claims.py -k no_unproven_propagation"
  },
  {
    "id": "sdc-fact-grammar-fixtures",
    "finding_id": "finding-10",
    "title": "Specify fact and template grammar fixtures",
    "priority": "p0",
    "allowed_files": ["q-system/.q-system/tests/separation/fixtures/fact-grammar.json", "q-system/.q-system/tests/separation/test_fact_grammar.py"],
    "disallowed_files": ["validate-separation.py", "q-system/canonical/**", "instance-registry.json", ".prd-os/**"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/separation/test_fact_grammar.py"],
    "required_reviews": ["security"],
    "acceptance": "Write failing boundary cases first. Cover populated fields, sourced dated interactions, currency, case facts, placeholders, synthetic markers, and unclassified fail-closed behavior.",
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/separation/test_fact_grammar.py -k boundary"
  },
  {
    "id": "sdc-self-enumerating-scope",
    "finding_id": "finding-11",
    "title": "Enumerate the containment scope from repository state",
    "priority": "p0",
    "allowed_files": ["q-system/.q-system/scripts/containment-targets.py", "q-system/.q-system/tests/separation/test_containment_targets.py"],
    "disallowed_files": ["validate-separation.py", "q-system/canonical/**", "instance-registry.json", ".prd-os/**"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/separation/test_containment_targets.py"],
    "required_reviews": ["repository-owner"],
    "acceptance": "Write a failing new-surface test first. Derive tracked text targets from Git and validate explicit exclusions for PRD state, output, memory, generated assets, and binaries.",
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/separation/test_containment_targets.py -k new_tracked_surface"
  },
  {
    "id": "sdc-quarantine-rollback",
    "finding_id": "finding-12",
    "title": "Keep rollback payloads out of generic paths",
    "priority": "p0",
    "allowed_files": ["q-system/.q-system/scripts/verify-containment-export.py", "q-system/.q-system/tests/separation/test_containment_rollback.py"],
    "disallowed_files": ["q-system/canonical/**", "q-system/output/**", "instance-registry.json", ".prd-os/**"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/separation/test_containment_rollback.py"],
    "required_reviews": ["security"],
    "acceptance": "Write a failing wrong-owner rollback reproducer first. Retain raw payloads only in protected quarantine or the verified owner and never restore them into generic files.",
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/separation/test_containment_rollback.py -k never_republish"
  },
  {
    "id": "sdc-updater-dependency-receipt",
    "finding_id": "finding-13",
    "title": "Require the updater final-state dependency receipt",
    "priority": "p0",
    "allowed_files": ["q-system/.q-system/tests/separation/test_updater_dependency_receipt.py"],
    "disallowed_files": ["kipi-update.sh", "q-system/canonical/**", "instance-registry.json", ".prd-os/**"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/separation/test_updater_dependency_receipt.py"],
    "required_reviews": ["updater-owner"],
    "acceptance": "Write a failing missing-receipt test first. Block propagation proof until issue fcu-dry-run-final-state from prd-fail-closed-fleet-updater-2026-07-24 is closed with verification receipts.",
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/separation/test_updater_dependency_receipt.py -k missing_or_open"
  },
  {
    "id": "sdc-versioned-baseline-receipt",
    "finding_id": "finding-14",
    "title": "Store a reproducible separation baseline receipt",
    "priority": "p0",
    "allowed_files": ["q-system/.q-system/tests/separation/fixtures/validate-separation-baseline.txt", "q-system/.q-system/tests/separation/test_baseline_receipt.py"],
    "disallowed_files": ["validate-separation.py", "q-system/canonical/**", "instance-registry.json", ".prd-os/**"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/separation/test_baseline_receipt.py"],
    "required_reviews": ["test-owner"],
    "acceptance": "Write a failing stale-receipt test first. Record the command, commit SHA, timestamp, exit code, and exact summary without attributing failures not present in the receipt.",
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/separation/test_baseline_receipt.py -k stale_or_unattributed"
  },
  {
    "id": "sdc-template-restoration",
    "finding_id": "sdc-missing-template-restoration-owner",
    "title": "Restore exported canonical files to generic template form",
    "priority": "p0",
    "allowed_files": ["q-system/canonical/discovery.md", "q-system/canonical/pricing-framework.md", "q-system/.q-system/tests/separation/test_template_restoration.py"],
    "disallowed_files": ["instance-registry.json", "kipi-update.sh", ".git/**", "/Users/assafkipnis/projects/intel/projects/kipi-investigations/**"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/separation/test_template_restoration.py"],
    "required_reviews": ["data-owner", "security"],
    "acceptance": "Write a failing instance-fact test first. Require the closed sdc-owner-export receipt before editing either source. Restore the existing documented sections with placeholders only, preserve both schemas, and prove no exported raw fact remains.",
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/separation/test_template_restoration.py -k export_receipt"
  }
]
```
