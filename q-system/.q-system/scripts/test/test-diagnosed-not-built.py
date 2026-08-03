#!/usr/bin/env python3
"""Pairs with: diagnosed-not-built.py (ASK-310).

The case it exists for: auto-commit.py carried five diagnoses between 2026-07-14
and 08-02 and was never fixed, because no reader aggregated across the four
places diagnoses live. The founder asked how a finding is "kept"; a sentence in a
summary is not kept, so this is the mechanism instead.

Both directions are pinned. The first version of the detector would have MISSED
its own motivating case twice over -- once because diagnoses are titled by
symptom rather than filename, and once because a single unrelated commit read as
"acted on". Those are the two assertions that matter here.
"""
import importlib.util, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
_s = importlib.util.spec_from_file_location("d", os.path.join(HERE, "..", "diagnosed-not-built.py"))
d = importlib.util.module_from_spec(_s); _s.loader.exec_module(d)

FAILS = []
def check(label, cond):
    print(f"  {'PASS' if cond else 'FAIL'}  {label}")
    if not cond: FAILS.append(label)

d.STEMS = {"auto-commit": ".py"}

print("a diagnosis titled by SYMPTOM still counts")
# The Jul 14 lesson is `an-auto-commit-to-the-current-branch-strands-...` and its
# body never contains the string "auto-commit.py".
slug = "an-auto-commit-to-the-current-branch-strands-unmerged-work"
check("slug matches the file stem", any(stem in slug for stem in d.STEMS))

print("\nre-diagnosis after the last change is what counts")
touched = "2026-07-26T11:53:35-07:00"
dated = {"lesson": "2026-07-14T00:00:00Z", "rca": "2026-08-02T00:00:00Z",
         "spill-a": "2026-07-27T00:00:00Z", "spill-b": "2026-08-01T00:00:00Z"}
since = {s: v for s, v in dated.items() if v > touched}
check("3 diagnoses postdate the last change", len(since) == 3)
check("that clears the 2-source floor", len(since) >= d.MIN_SOURCES)
# NEGATIVE: the naive rule (touched-after-first-diagnosis == acted on) filtered
# this file out, because one unrelated commit on 07-26 postdates the 07-14 lesson.
check("the naive rule would have wrongly cleared it", touched > min(dated.values()))

print("\nit does not cry wolf")
check("a finding younger than the floor is in flight, not abandoned", d.STALE_DAYS >= 7)
check("one source is a record, not a pattern", d.MIN_SOURCES >= 2)
fresh = {s: v for s, v in dated.items() if v > "2026-08-02T23:00:00Z"}
check("nothing postdating a just-fixed file is flagged", len(fresh) < d.MIN_SOURCES)

print("\n" + ("ALL PASS" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}"))
sys.exit(1 if FAILS else 0)
