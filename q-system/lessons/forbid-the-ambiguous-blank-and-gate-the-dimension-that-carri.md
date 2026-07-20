---
id: forbid-the-ambiguous-blank-and-gate-the-dimension-that-carri
kind: pattern
title: Forbid the ambiguous blank, and gate the dimension that carries the signal
date: 2026-07-20
---

When a data slot can legitimately hold a value, a blank in it is ambiguous: it can mean "deliberately empty/not observed" or "skipped/never filled," and those are opposite facts. A convention that says "every slot is a value or an explicit marker" only holds if code enforces it. If the rule lives solely in an example row, older data, or a reviewer's habit, a later, thinner template will quietly redefine blank as "skipped" while the old readers still parse it as "nothing to report" — indistinguishable, and no one notices.

Two moves close this, and both are needed:

1. Kill the ambiguous empty. Make every populated-eligible slot require either a real value or an explicit sentinel ("not observed," "n/a," "none") — never a bare blank. Enforce it at write/validate time in code, not in a template comment or a good-example row, so a thinner future format cannot silently reintroduce the blank.

2. Gate the content dimension, not just the shape. Structural checks (headers present, row count, sections embedded) pass on a fully-hollow artifact — every content cell empty, every gate green. Add a completeness check that asserts each eligible slot is populated-or-marked. Validate the dimension that actually carries the signal, because that is exactly the one a mechanical shortcut will strip while leaving the shape intact.

General shape of the failure: a step is done carefully by hand for a while, then switched to a thinner mechanical form, and no deterministic check watches the field the meaning depended on. Whenever you rely on a fill-in convention, encode it as a required value-or-sentinel and add a gate over content presence — not just container structure.
