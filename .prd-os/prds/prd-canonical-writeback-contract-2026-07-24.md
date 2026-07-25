---
id: prd-canonical-writeback-contract-2026-07-24
title: Canonical Writeback Contract
status: approved
created_at: 2026-07-24T21:05:00Z
updated_at: 2026-07-24T21:05:26Z
owner: senior-staff
reviewers: []
depends_on: prd-single-runtime-state-authority-2026-07-24
findings_path: .prd-os/findings/prd-canonical-writeback-contract-2026-07-24-findings.jsonl
codex_reviewed_at: 2026-07-24T21:04:20Z
---

# Canonical Writeback Contract

## Problem

The repository contains eight canonical files duplicated under
`plugins/kipi-core/kipi-mcp/canonical/`: content intelligence, decisions,
discovery, engagement playbook, lead lifecycle rules, market intelligence,
objections, and talk tracks. The file OS reads `q-system/canonical`, while MCP
paths currently resolve a separate runtime store
[`plugins/kipi-core/kipi-mcp/src/kipi_mcp/paths.py:130-151`].
The architecture and anti-hallucination method say canonical claims and
`graph.jsonl` provide provenance
[`ARCHITECTURE.md:9`, `q-system/methodology/anti-hallucination.md:23-44`], but
no `graph.jsonl` exists in the repository command result from
`rg --files | rg 'graph.jsonl$'` on 2026-07-24.

The autonomous-system record names RULE-A through RULE-E
[`q-system/canonical/autonomous-systems-record-2026-06-30.md:83-89`], while
`q-system/canonical/decisions.md` records only RULE-001 through RULE-003
[`q-system/canonical/decisions.md:18-36`]. The derived-copy RCA says multiple
representations drifted because no agreement check compared their meaning
[`q-system/output/rca/rca-derived-copy-drift-2026-06-30.md:39-77`].

## Goals

- After `single-runtime-state-authority` closes, remove the eight MCP duplicates
  or generate them from the authority with deterministic agreement checks.
- Define one owner and write-back path for changelog, decisions, market
  intelligence, content intelligence, and objections.
- Reconcile RULE-A through RULE-E with the decision log without inventing
  decisions.
- Define how `graph.jsonl` initializes, persists, backs up, restores, and
  survives a fresh clone.
- Prove debrief and calibration writes reach the same store morning and MCP
  read.
- Add freshness and provenance checks that validate structure and source
  references without generating content.

## Non-goals

- Choosing the state authority before the dependency closes.
- Inventing market, content, objection, or decision records.
- Rewriting append-only graph history.
- Editing external instance repositories during this PRD program.

## Proposed approach

1. Block all implementation issues until
   `prd-single-runtime-state-authority-2026-07-24` has closed issues and an
   authoritative-path receipt.
2. Inventory every canonical producer and reader. Assign each logical record
   class one authoritative file and write-back owner. Derived copies declare
   source, generator version, source hash, and generated timestamp.
3. Remove the eight plugin copies if no installed consumer requires them.
   Otherwise generate them from authority and compare normalized semantics on
   every build and startup.
4. Record RULE-A through RULE-E in the decision authority using the existing
   autonomous-system evidence. Stop on any wording conflict and surface it as
   an open decision.
5. Define graph lifecycle: empty schema-valid initialization on fresh clone,
   append-only writes, durable authoritative path, backup and import receipts,
   per-record provenance, and reader tolerance for one corrupt line. Compact
   before boot-time reads when the file exceeds 10,000 records, retain a
   receipt-linked archive, and bound active-file read cost in tests.
6. Run debrief, calibration, morning, and MCP against a fixture authority.
   Write one synthetic record and prove both readers see the same hash.

## Alternatives considered

- **Keep hand-maintained duplicates.** Rejected because the RCA documents drift
  without agreement checks. [E4]
- **Delete all plugin copies immediately.** Rejected until installed consumers
  are enumerated after the state-authority decision.
- **Seed graph content on fresh clone.** Rejected because freshness checks must
  not invent claims.

## Scenarios

- **Derived copy.** A canonical source changes. Generation updates the copy and
  source hash; a manual edit fails agreement.
- **Decision reconciliation.** RULE-C exists in the system record but not the
  decision log. The issue writes only the evidenced rule and cites its source.
- **Fresh clone.** Initialization creates a schema-valid empty graph at the
  authoritative durable path. Import restores records and verifies hashes.
- **Write-back.** Debrief writes a synthetic fixture record. Calibration,
  morning, and MCP read the same authority and report the same provenance.

## Resolved decisions

- **Authority precedes write-back.** Rationale: duplicate removal before path
  convergence can delete the only active copy.
- **Derived copies are generated or removed.** Rationale: hand-maintained peers
  preserve ambiguity.
- **Freshness never creates content.** Rationale: checks validate timestamp and
  provenance, not truth.
- **Graph initialization is empty and schema-valid.** Rationale: a fresh clone
  needs durable structure without fabricated knowledge.

## Risks and rollback

- Removing a duplicate can break an installed reader. Consumer enumeration and
  installed-cache tests run first. Rollback restores the generated copy from
  the authoritative source.
- Write-back can target the wrong store. The dependency receipt and two-reader
  contract fail before writes. Rollback restores the fixture backup.
- Graph import can duplicate events. Import uses stable record identity and
  hash receipts. Rollback restores the pre-import backup.
- Compaction can lose provenance. It writes a verified archive before replacing
  the active file and refuses replacement if record counts or hashes disagree.
- Decision reconciliation can change meaning. Any semantic mismatch remains an
  open question rather than being normalized automatically.

## Open questions

- Do any installed MCP consumers require canonical files inside the package
  after the state-authority repair?
- What stable identity already exists for graph records, and what migration is
  needed if none exists?
- Who owns final resolution when RULE-A through RULE-E wording conflicts with
  an existing decision entry?

## Evidence

- **E1:** Both `q-system/canonical/` and
  `plugins/kipi-core/kipi-mcp/canonical/`; duplicate file inventory command run
  2026-07-24.
- **E2:** `ARCHITECTURE.md:9`, `README.md:19-23`, `README.md:96-105`;
  `q-system/methodology/anti-hallucination.md:23-44`.
- **E3:** `q-system/canonical/autonomous-systems-record-2026-06-30.md:83-89`;
  `q-system/canonical/decisions.md:18-36`.
- **E4:** `q-system/output/rca/rca-derived-copy-drift-2026-06-30.md:39-98`,
  `q-system/output/rca/rca-derived-copy-drift-2026-06-30.md:120-121`.
- **E5:** `q-system/.q-system/scripts/canonical-digest.py:206-240`;
  `q-system/.q-system/scripts/changelog-write.py:28-30`.

## Issues

```json
[
  {
    "id": "cwc-canonical-consumer-inventory",
    "finding_id": "finding-1",
    "title": "Inventory canonical readers and remove or generate eight duplicates",
    "priority": "p1",
    "allowed_files": ["plugins/kipi-core/kipi-mcp/canonical/**", "plugins/kipi-core/kipi-mcp/tests/test_canonical_authority.py"],
    "disallowed_files": ["q-system/canonical/**", "instance-registry.json", ".prd-os/**", ".git/**"],
    "required_checks": ["python3 -m pytest -q plugins/kipi-core/kipi-mcp/tests/test_canonical_authority.py"],
    "required_reviews": ["runtime-owner", "data-owner"],
    "acceptance": "Write a failing duplicate-authority test first. Wait for the state-authority receipt, enumerate consumers, and remove copies or generate them with source hashes and semantic agreement.",
    "bypass_check": "python3 -m pytest -q plugins/kipi-core/kipi-mcp/tests/test_canonical_authority.py -k manual_drift"
  },
  {
    "id": "cwc-writeback-ownership",
    "finding_id": "finding-2",
    "title": "Route every canonical write-back class to one owner",
    "priority": "p1",
    "allowed_files": ["q-system/.q-system/config/canonical-writeback.json", "q-system/.q-system/scripts/canonical-writeback.py", "q-system/.q-system/scripts/changelog-write.py", "q-system/.q-system/scripts/canonical-digest.py", "q-system/.q-system/tests/test_canonical_writeback.py"],
    "disallowed_files": ["q-system/canonical/**", "plugins/kipi-core/kipi-mcp/canonical/**", "instance-registry.json", ".prd-os/**"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/test_canonical_writeback.py"],
    "required_reviews": ["data-owner"],
    "acceptance": "Write a failing unmapped-writer test first. Cover changelog, decisions, market intelligence, content intelligence, and objections with one authority and owner each, and prove every mapping has a production reader and writer.",
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/test_canonical_writeback.py -k unmapped_writer"
  },
  {
    "id": "cwc-decision-reconciliation",
    "finding_id": "finding-3",
    "title": "Reconcile RULE-A through RULE-E with the decision authority",
    "priority": "p1",
    "allowed_files": ["q-system/canonical/decisions.md", "q-system/.q-system/tests/test_decision_agreement.py"],
    "disallowed_files": ["q-system/canonical/autonomous-systems-record-2026-06-30.md", "plugins/**", "instance-registry.json", ".prd-os/**"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/test_decision_agreement.py"],
    "required_reviews": ["decision-owner"],
    "acceptance": "Write the failing RULE-A through RULE-E agreement test first. Add only source-evidenced decisions and stop on semantic conflicts.",
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/test_decision_agreement.py -k missing_or_conflicting"
  },
  {
    "id": "cwc-graph-lifecycle",
    "finding_id": "finding-4",
    "title": "Define durable graph initialization, backup, and restore",
    "priority": "p1",
    "allowed_files": ["q-system/.q-system/schemas/graph-record.schema.json", "q-system/.q-system/scripts/graph-lifecycle.py", "q-system/.q-system/tests/test_graph_lifecycle.py"],
    "disallowed_files": ["q-system/memory/graph.jsonl", "q-system/canonical/**", "instance-registry.json", ".prd-os/**"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/test_graph_lifecycle.py"],
    "required_reviews": ["data-owner"],
    "acceptance": "Write failing fresh-clone, corrupt-line, duplicate-import, backup-restore, and 10,000-record boot tests first. Compact before read, archive with receipts, initialize empty, append with provenance, and verify durable hashes.",
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/test_graph_lifecycle.py -k 'fresh_clone or corrupt_line or duplicate_import'"
  },
  {
    "id": "cwc-end-to-end-writeback",
    "finding_id": "finding-5",
    "title": "Prove debrief, calibration, morning, and MCP share write-back",
    "priority": "p1",
    "allowed_files": ["q-system/.q-system/tests/test_canonical_writeback_e2e.py", "plugins/kipi-core/kipi-mcp/tests/test_canonical_writeback_e2e.py"],
    "disallowed_files": ["q-system/canonical/**", "plugins/kipi-core/kipi-mcp/src/**", "instance-registry.json", ".prd-os/**"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/test_canonical_writeback_e2e.py plugins/kipi-core/kipi-mcp/tests/test_canonical_writeback_e2e.py"],
    "required_reviews": ["runtime-owner", "data-owner"],
    "acceptance": "Write the failing two-reader fixture first. Treat this as proof-only and wait for cwc-writeback-ownership plus srsa-unified-readers to close. Write one synthetic record through debrief and calibration and prove morning and MCP read the same hash, freshness, and provenance.",
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/test_canonical_writeback_e2e.py -k two_brain"
  },
  {
    "id": "cwc-production-writeback-consumers",
    "finding_id": "finding-6",
    "title": "Prove every write-back mapping has production consumers",
    "priority": "p1",
    "allowed_files": ["q-system/.q-system/tests/test_writeback_production_consumers.py"],
    "disallowed_files": ["q-system/.q-system/scripts/**", "q-system/canonical/**", "plugins/**", ".prd-os/**"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/test_writeback_production_consumers.py"],
    "required_reviews": ["data-owner"],
    "acceptance": "Write a failing dead-mapping test first. Introspect every configured write-back class and require a non-test production reader and writer.",
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/test_writeback_production_consumers.py -k dead_mapping"
  },
  {
    "id": "cwc-proof-only-dependency-gate",
    "finding_id": "finding-7",
    "title": "Block end-to-end proof until production wiring closes",
    "priority": "p1",
    "allowed_files": ["q-system/.q-system/tests/test_writeback_dependency_gate.py"],
    "disallowed_files": ["q-system/.q-system/scripts/**", "plugins/**/src/**", "q-system/canonical/**", ".prd-os/**"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/test_writeback_dependency_gate.py"],
    "required_reviews": ["runtime-owner"],
    "acceptance": "Write a failing missing-receipt test first. Refuse end-to-end proof until cwc-writeback-ownership and srsa-unified-readers are closed with verification receipts.",
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/test_writeback_dependency_gate.py -k missing_receipt"
  },
  {
    "id": "cwc-graph-compaction-bound",
    "finding_id": "finding-8",
    "title": "Bound graph boot reads with receipt-backed compaction",
    "priority": "p1",
    "allowed_files": ["q-system/.q-system/tests/test_graph_compaction_bound.py"],
    "disallowed_files": ["q-system/.q-system/scripts/graph-lifecycle.py", "q-system/memory/**", "q-system/canonical/**", ".prd-os/**"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/test_graph_compaction_bound.py"],
    "required_reviews": ["data-owner"],
    "acceptance": "Write a failing 10,001-record boot test first. Require compaction before whole-file consumption, verified archive counts and hashes, and a bounded active-file read.",
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/test_graph_compaction_bound.py -k boot_bound"
  }
]
```
