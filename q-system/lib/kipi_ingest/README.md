# kipi_ingest — fleet-canonical ingestion coverage contract

One read-boundary contract shared by every document-ingesting instance
(kipi-investigations, QEP, 4_points, product). Canonical source lives here in the
kipi-system skeleton and propagates unchanged to every instance via `kipi update`
(git archive `q-system/` + rsync `--delete`). **Do not edit an instance's copy** —
edit canonical here; the drift gate rejects a hand-edited instance copy.

PRD: `prd-fleet-ingestion-coverage-contract-2026-07-06`.

## The contract (two layers, best-of-breed from two audits)

- **Counting (from QEP):** `ReadResult(attempted, captured, truncated, dropped)` +
  `reconcile()`. A cap or per-unit failure is counted, never silent; `reconcile()`
  raises and names any enumerated unit with no result.
- **Provenance (from the product):** `Block(block_id, text-derived-from-source)` +
  `index_blocks()` + `ground()`. A downstream reference to a unit that was not read
  raises; "captured" is unfakeable.

## Import (the shim every instance uses)

`kipi_ingest` ships to each instance at `q-system/lib/kipi_ingest/`. Add
`q-system/lib` to `sys.path`, then import:

```python
import sys
from pathlib import Path
_LIB = Path(__file__).resolve()  # walk up to the instance root, then q-system/lib
# ... add "<instance-root>/q-system/lib" to sys.path ...
from kipi_ingest import ReadResult, Block, reconcile, ground
from kipi_ingest.readers import read_md, read_csv, read_xlsx
```

Each reader returns `(list[Block], ReadResult)`.

## Adopting in an instance (the wiring)

1. Route the instance's ingest chokepoint through the readers instead of its
   legacy `extract_text`. Stamp the returned `ReadResult` onto the report/record
   and flag when `receipt.is_lossy()`.
2. Add `python3 q-system/lib/kipi_ingest/conformance.py` as a required_check
   (behavior gate: proves the readers still catch every planted loss).
3. Add `python3 q-system/lib/kipi_ingest/drift_check.py --check q-system/lib/kipi_ingest`
   as a required_check (drift gate: proves the instance copy matches canonical).

## Gates

- **Behavior:** `python3 conformance.py` — plants the audited losses, asserts each
  is caught. Currently 29 checks (contract + markdown + csv + xlsx).
- **Drift:** `drift_check.py --emit` (skeleton, regenerates `canonical.sha256`) /
  `drift_check.py --check <dir>` (instance, fails on any drift, names the file).

## Status

Built + tested: contract core, `read_md`, `read_csv`, `read_xlsx`, both gates.
Next: `read_pdf` + `read_docx` (need a PDF engine / python-docx; built+tested in an
instance that has them), then the five instance adopters.
