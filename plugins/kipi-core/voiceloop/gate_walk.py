#!/usr/bin/env python3
"""Run a roster of gates and merge their verdicts. The walk, not the roster.

why this module exists (2026-09-05, VoiceLoop package extraction, slice 10). The
deployment's gate stack was a single `+` chain of calls. Every operator needs the
same WALK: run each gate, keep every row, in order. No operator needs the same
ROSTER, because which gates apply is a decision about one practice's rules, and this
one's includes a commercial price rule and a two-brand separation rule that mean
nothing to anyone else.

So the walk ships and the roster does not. The deployment builds a list of callables
and hands it here.

WHAT THIS DELIBERATELY DOES NOT DO, because each was considered and each would have
made it worse:

  It does not catch exceptions. A gate that raises is a defect, and swallowing it
  here would turn a broken gate into a silent pass on the publishing path. The
  deployment's own `post_repair.violations` already demonstrates the failure mode: a
  per-check guard converted a wiring mistake into a `voice-lint-error` row and the
  banned-phrase check silently stopped running while the verdict still looked like a
  verdict.

  It does not short-circuit on the first violation. Every gate runs on every draft,
  because the reviser is given the FULL list and a partial list would send it back to
  fix one thing while another still stood.

  It does not sort, dedupe or reorder. Order is the roster's, and the deployment's
  chain documents why several gates sit exactly where they do: `assistant_gate` runs
  LAST because a reviser asked to fix violations can answer with commentary about the
  violations.
"""
from __future__ import annotations


def walk(roster):
    """Call every gate in order and concatenate their rows.

    `roster` is a sequence of zero-argument callables, each returning a list of
    violation dicts. Zero-argument on purpose: the gates in a real stack take wildly
    different arguments (text alone, text and channel, text and a source, text and a
    resolved mode), and a signature that tried to serve all of them would either grow
    a parameter per gate or pass an opaque context object. A closure binds what each
    gate needs at the call site, where the reason it needs it is written down.
    """
    rows = []
    for gate in roster:
        rows.extend(gate())
    return rows
