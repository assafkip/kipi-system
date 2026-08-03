<!-- Derived from real-review-request-changes.md, a genuine codex round-2
     transcript. ONLY the severity column is changed (major -> nit). The
     claims and file:line anchors are the producer's, not invented.

     WHY THIS FIXTURE EXISTS (ASK-312). The declined-to-start-*.md fixtures
     no longer reach resolve_verdict on this base: ASK-274 (6fe7a3c) added
     review_is_usable, which classifies them unusable and derives nothing,
     so their old precondition is dead. This is the shape that IS still
     live -- a review that PASSES the usability gate, files only nits, and
     whose author still said stop. Keep this header free of the literal
     verdict tokens: extract_verdict falls back to the first one ANYWHERE
     in the file, so a token in a comment silently becomes the stated
     verdict. That cost one debugging round while writing this. -->
FINDINGS:
nit|Hidden review artifacts are collected as real, trackable engines, producing false unattended audit findings.|q-system/.q-system/scripts/capability-map-gen.py:486
nit|A filename inside a comment or declaration counts as an executable caller, so known inert engines are reported LIVE.|q-system/.q-system/scripts/capability-map-gen.py:464
nit|One caller marks every engine sharing the same basename LIVE, including engines at unrelated paths.|q-system/.q-system/scripts/capability-map-gen.py:465
END FINDINGS

VERDICT: REQUEST CHANGES
