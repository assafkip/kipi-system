# Deep Module Lens

Source: John Ousterhout, *A Philosophy of Software Design*. A module is deep
when its interface is much simpler than what it hides. A module is shallow
when the interface is almost as complex as the implementation — the caller
gets little benefit for the coupling it takes on.

## Classification questions (ask per module)

1. **Interface vs. implementation size.** Count what a caller must know:
   function/CLI signatures, required call order, config it must supply.
   Compare that to what the module actually does internally. A big gap =
   deep. A small gap = shallow, and shallow is the finding.
2. **Leakage.** Does the caller need to know an internal detail to use the
   module correctly (an internal file format, a specific call order, an
   internal flag)? Leakage is a seam that should have been hidden.
3. **Pass-through.** Does the module mostly forward calls to something else
   with little added value? Pass-through modules are a strong shallow
   signal — merging them with their caller or their callee often deepens
   both.
4. **Locality.** When a change to one piece of behavior requires touching
   this module AND two or three others in lockstep, the boundary is drawn
   in the wrong place. Note which modules move together.
5. **Untested seam.** A module only testable by exercising a much larger
   system (no unit boundary) usually means the interface doesn't actually
   isolate anything — it's decoration over shared state.

## What is NOT a finding

- A small module with a small interface (a single well-named function). Depth
  is relative to what the module does, not absolute size.
- Justified complexity at the boundary — e.g. a CLI arg parser has a wide
  interface because the domain genuinely has many independent options.
- A module already flagged and accepted as an intentional trade-off (check
  ADRs / `q-system/canonical/decisions.md` before re-raising it).

## Proposing a redesign

For each real finding, sketch what a deeper version would hide:

- **Adapter**: does one existing module already have the right depth, and
  the fix is routing callers through it instead of a shallow one?
- **Merge**: are two modules artificially split, so merging removes a
  pass-through layer?
- **New seam**: is there a genuinely missing abstraction — state that
  explicitly rather than forcing an existing module to absorb it.

Name the trade-off of each option (more code moved, more callers touched,
what gets easier vs. harder to test). Don't pick — that's the founder/Sana
call.
