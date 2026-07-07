---
id: when-you-narrow-a-mechanism-re-derive-which-declared-fields-
kind: methodology
title: When you narrow a mechanism, re-derive which declared fields it still reads
date: 2026-07-06
---

A common way for dead code to ship quietly: an interface declares a set of fields, then a later change narrows *how* the feature works, but nobody re-checks the field list against the new mechanism. The fields stay declared, the tests stay green, and one or more of them is never read by any production path.

Two forces let this survive:

1. An amendment changes the mechanism but is copied from the original field list. The original design justified every declared field because the first mechanism consumed them all. When you replace or narrow that mechanism (a different input source, a new choke point, an optional override instead of a primary input), some of those fields are no longer needed. If the amendment only re-examines the code it touches and not the *declared surface* it inherited, orphan fields slip through. Some get wired by reflex (a one-line accessor); a sibling field with a slightly different shape silently does not.

2. Tests assert behavior, not readership. A behavior-only suite proves the paths it exercises work; it never proves that *every declared field has a reader*. A field can be fully declared, fully validated on input, and fully dead, while the suite is fully green. Strict input validation (reject-unknown-keys and the like) constrains what callers may send, but never requires that anything downstream consume what they did send.

How to apply:

- Treat 'the mechanism changed' as a trigger to re-derive the field list from scratch. Ask, for each declared field: which concrete line reads this under the new design? If the answer is 'none', delete the field or wire it. Do not carry a field forward on the assumption that it was justified once.
- When you narrow an input to an optional override, audit *all* the fields that override touches, not just the one you happened to think of. Overrides that come in families (a flag plus its associated count, a primary plus its qualifier) are where one member gets wired and the other is forgotten.
- Add a readership check, not just a behavior check. For a value type, assert that each declared field drives an observable decision: feed a value through that field alone and prove it changes the output. A field with no such test is a field with no proof of life.
- Where the language allows, add a static or lint-level check that fails when a declared field on a value type has no production reader. Input-validation strictness is not a substitute; it guards the entry, not the consumption.

The underlying rule: a declaration is a promise that something reads it. Narrowing a mechanism breaks that promise silently unless you re-derive the promise and test that it still holds.
