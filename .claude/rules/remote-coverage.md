---
description: Every project lands in a private repo; laptop-only is a declared exception
paths:
  - "remote-coverage-*"
  - "kipi"
  - "kipi-new-instance.sh"
  - "instance-registry.json"
---

# Remote Coverage (ENFORCED)

Every project lands in a PRIVATE git repo. Laptop-only is a written exception,
never a default.

- `kipi new` creates and pushes a private repo by default. Opt out with
  `KIPI_LOCAL_ONLY=1 KIPI_LOCAL_ONLY_REASON="..."`, which records the decision.
- `remote-coverage-check.py` (skeleton root, first step of `kipi check`) exits 2
  on a repo with no off-disk remote, or a project dir that is not a repo and
  that no parent repo TRACKS (an ancestor `.git` is not coverage: a parent
  `.gitignore` of `projects/` hides every instance under it).
- It lives in ONE place and audits `~/projects` as a whole, so it returns the
  same answer from any cwd. This rule propagates; the script does not.
- Declare exceptions only via `remote-coverage-check.py --declare <path>
  --reason "..."` (single writer; refuses a non-sentence reason).
  `remote-coverage-allow.json` is in a PUBLIC repo: name the data CLASS and the
  carrier path, never the content. Never delete anything to clear the gate.

Scar 2026-07-29: `kipi new` never created a remote. 12 remote-less repos (oldest
219 commits, several client engagements) plus 475 client files in a directory
that was not a repo. Inflow automated, outflow manual, nothing reported it.
