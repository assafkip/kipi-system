#!/usr/bin/env python3
"""The content key: one hash, so two ledgers cannot disagree about what a post IS.

why this is ENGINE code (2026-09-06, VoiceLoop package extraction, slice 6). The
function lived in the deployment's append-only ledger, and `critic` reached across to
it for one call. That import is the reason slice 6 could not run as drafted: a fleet
package may not import one operator's receipt log.

The plan named two fixes and preferred this one. Passing a `sha_fn` into the judge
would also have removed the import, but it leaves the door open for a second caller to
pass a different function, and the whole value of a content key is that everyone
computes the same one. The lessons corpus states it directly: a value compared against
its own source proves only that the code agrees with itself.

WHAT IT IS. A sha256 over the text with runs of whitespace collapsed, truncated to 32
characters. The normalisation is the point: trivial reflow is still the same post, so
a body republished with different line breaks does not read as new.

why a hash and not the body (2026-08-05, ASK-424): the ledger stayed small on purpose,
holding `chars` rather than the text, and that is exactly why nothing could tell that
the X slot was republishing the draft LinkedIn had shipped six minutes earlier. A
32-character digest gives the supply a key to dedupe on without turning the receipt log
into a content store.

The deployment's `postbook.text_sha` now delegates here, so the ledger, the queue, the
cycle and the critic all key on ONE implementation.
"""
from __future__ import annotations

import hashlib


def text_sha(text):
    """The content key. Normalised on whitespace so trivial reflow is still the same post."""
    return hashlib.sha256(" ".join((text or "").split()).encode("utf-8")).hexdigest()[:32]
