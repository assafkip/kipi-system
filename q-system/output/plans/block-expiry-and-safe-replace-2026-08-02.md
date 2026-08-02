# Two loop blocks with no autonomous continuation (2026-08-02)

## Recon corrections to the brief (measured, not assumed)

1. **Ten issues carry `blocked:capability`, not four.** Live query against the ASK
   team: ASK-140, 139, 138, 137, 136, 135, 134, 133, 132, 116. The brief named
   four. A mechanism sized for four that silently leaves six parked is the same
   defect one layer down.
2. **Removing the label is NOT sufficient to make ASK-140 pickable.** `ready()`
   (linear-worker.sh:359) also requires `state.type in ("backlog","unstarted")`.
   ASK-140/134/133/132 are all `started`. An expiry that only drops the label
   clears the picker's label test and still fails its state test, so the issue
   stays invisible and the mechanism reports success. The un-block is
   label-removal AND a state move.
3. **`linear-sync.py` has no unlabel and no state-set command.** `cmd_label`
   (line 702) is add-only by construction. `reopen_state_id` + `ISSUE_UPDATE`
   exist, so the machinery is there; the CLI verb is not.
4. **The refusal records the missing capability as free prose.** linear-worker.sh
   :1270 asks for `<the exact capability missing, what refused it, and what it
   unblocks>`. Prose cannot be re-tested mechanically. This is the actual root
   cause of BLOCK 1 — not the label, the unmeasurable cause behind it.
5. **The apply-route census is blind to rule CONTENT.** `census()`
   (apply_claude_changes.py:388) counts rule/agent/output-style FILE NAMES
   (`_dir_names`), hook command strings, and the deny list. Nothing reads inside
   a `.claude/rules/*.md`. This is decisive for BLOCK 2.

## BLOCK 1 — a block expires by re-test, not by time

**Defect:** a block records a point-in-time verdict about the environment and
never re-tests it. Inflow is automated, outflow is manual, so blocks only
accumulate.

**Mechanism: probe-gated expiry, evaluated by the worker at pick time.**

- The refusal records a **probe**, not only prose. Enumerated vocabulary, no
  arbitrary shell: `file:<repo-rel-path>`, `exec:<bin>`, `env:<VAR>`,
  `manifest_test:<path>`. The worker runs unattended with the founder's
  privileges; persisting agent-authored shell to be executed later at pick time
  would be a new code-execution path, and the whole point of ASK-282 was closing
  one of those. An enumerated vocabulary is deterministic and cannot execute.
- The probe is persisted in the Linear comment the refusal already posts, inside
  a fenced machine-readable block. Linear is the durable store and the label
  lives there too; a local state file would be lost on a fresh checkout.
- The picker's existing paginated GraphQL query is extended to pull comments in
  the same round trip, so expiry costs zero extra API calls.
- **Probe passes -> the block expired.** The worker removes the label, moves the
  state back to unstarted, and records why. **Probe still fails -> stays blocked,
  not offered, no pick burned, no write.** That is the anti-thrash property.
- **No probe (legacy block, written before this existed) -> UNVERIFIABLE.** An
  unverifiable block is not evidence the block is still real. It gets exactly one
  re-offer, recorded durably so it is once-ever. If it re-blocks, the new refusal
  writes a probe and it is probe-gated from then on. Converges after one
  re-offer per legacy issue, never repeats.

Backfilling probes onto the ten legacy issues by hand is the thing the founder
ruled out, so the legacy path has to be a rule, not an edit.

## BLOCK 2 — replace, gated by a census that can see rule content

**Verdict: replace CAN be made safe. The current ratchet CANNOT make it safe.**

The safety property is the ratchet, not additivity — the founder's frame is
right. But the ratchet as built only sees rule FILE NAMES. A `replace` op under
today's census would pass while gutting a rule's entire body, because the
filename survives. So `replace` requires the census to grow first.

New census keys, over `.claude/rules/*.md` content:
- `enforced_claims` — files declaring ENFORCED. A rule cannot silently stop
  claiming enforcement.
- `named_executables` — (rule file, script name) pairs **where the named script
  actually exists on disk**. Only real executables are protected.

That existence qualifier is the load-bearing part. Three PRs tonight found rules
carrying FALSE enforcement claims, and fixing a false claim is exactly a replace.
If a rule names `foo.py` and `foo.py` does not exist, that name is a lie, not
enforcement, and dropping it is a correction. If it names `voice-lint.py` and
that file exists and is wired, dropping it weakens a real claim and is refused.
This makes the ratchet more correct, not merely more permissive.

## Acceptance criteria

- [ ] BLOCK 1 reproducer red: a frozen fixture of the REAL ASK-140 shape is not
      pickable; the expiry pass does not clear it (no probe re-test exists).
- [ ] BLOCK 1 green: expiry clears it and it becomes pickable.
- [ ] Anti-thrash test: a block whose probe still fails is not offered.
- [ ] BLOCK 2 reproducer red: a content-gutting `replace` PASSES the current
      ratchet (proving the census gap is real, not theoretical).
- [ ] BLOCK 2 green: same replace is refused by the extended census.
- [ ] Mutation test: delete each new ratchet check, confirm a test goes red.
- [ ] A legitimate false-claim correction (dropping a name for a script that does
      not exist) is ALLOWED.
- [ ] Two separate issues, two separate branches, two separate PRs.
