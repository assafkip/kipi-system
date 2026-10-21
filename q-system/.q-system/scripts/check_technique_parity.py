#!/usr/bin/env python3
"""Technique-parity checker for design-room (kill-the-green-state model).

The thesis Assaf confirmed 2026-06-25: "when you have a floor, you are programmed
to only pass the floor." Any visible PASS gets satisficed to. So this checker
NEVER emits PASS / DONE / GOOD. It does exactly two things:

1. Reads a steal-manifest (every technique the teardown said to steal from a
   reference, with a checkable fingerprint) + the built HTML.
2. Emits the GAP LIST: every DECLARED technique that is absent or not applied. If
   any declared technique is missing it BLOCKS (exit 2) — a regression alarm
   against "I dropped what I said I'd steal" (the exact TZOREF failure). When no
   technique is missing it still does NOT certify the page good; it prints the
   techniques that ARE present and hands the page to the founder's eye.

This is provenance-for-techniques, the twin of check_token_provenance.py
(provenance-for-tokens). Grounding becomes operative, not decorative: the teardown
must bind the build.

Scope (v1): regex over the built source proves PRESENCE + coarse role (import
fingerprint + an applied fingerprint). RESOLVING role precisely ("same way as the
example": glass on THE console, not just any blur) needs the computed-style
fingerprint (fingerprint_build.py, plan phase 2). v1 catches the class of failure
that shipped: a declared technique used nowhere.

Usage:
  check_technique_parity.py <steal-manifest.json> <build.html>
  check_technique_parity.py --selftest

Exit 0 = no declared technique missing (NOT "done" — founder's eye next).
Exit 2 = a declared technique is missing (regression alarm) OR bad input.
There is deliberately no exit code that means "good".
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# Words this tool must never print as a verdict (the green state we are killing).
# Guarded by selftest so the success path can't regress into a certificate.
FORBIDDEN_VERDICTS = ("PASS", "DONE", "GOOD", "SHIPPED", "APPROVED")


def _present(patterns: list[str], haystack: str) -> list[str]:
    """Return the patterns from `patterns` ABSENT in haystack ([] = all present).
    Case-SENSITIVE: code fingerprints like `new Lenis` must not be satisfied by a
    non-equivalent lowercase string (Codex review 2026-06-25)."""
    return [pat for pat in patterns if not re.search(pat, haystack)]


def _searchable(src: str) -> str:
    """Strip HTML and /* */ block comments so a fingerprint that survives only in
    commented-out code is NOT mistaken for real use (Codex review 2026-06-25). An
    inert string-literal match remains a documented v1 limitation — the
    computed-style fingerprint (plan phase 2) closes that."""
    src = re.sub(r"<!--.*?-->", " ", src, flags=re.DOTALL)
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.DOTALL)
    return src


def _claims(tech: dict, build_label: str) -> bool:
    """Does this technique claim this page?

    A technique may carry `pages`: the filenames it applies to. Absent or empty means
    EVERY page, so silence is still the strict reading and scoping has to be deliberate.
    Matched on basename so a caller passing a path and a caller passing a filename agree.
    """
    pages = tech.get("pages") or []
    if not pages:
        return True
    if not build_label:
        # No label means the caller cannot say which page this is, so it does not get the
        # narrower check. Silence must not be the easiest way out (the same posture the
        # design-chain gate takes on an undeclared tier).
        return True
    from os.path import basename
    return basename(build_label) in {basename(x) for x in pages}


def find_gaps(manifest: dict, build_src: str, build_label: str = "") -> list[dict]:
    """Return one gap record per declared technique that is absent/not-applied.
    A technique that declares NO fingerprint (empty import AND applied) is a gap —
    it cannot be verified present, so it must not silently pass (Codex review).
    A technique scoped to other pages via `pages` is not this page's business."""
    src = _searchable(build_src)
    gaps = []
    for tech in manifest.get("techniques", []):
        if not _claims(tech, build_label):
            continue
        imp = tech.get("import") or []
        app = tech.get("applied") or []
        base = {"id": tech.get("id", "?"), "technique": tech.get("technique", "?"),
                "role": tech.get("role", "?")}
        if not imp and not app:
            gaps.append({**base, "missing_import": ["(no fingerprint declared — cannot verify)"],
                         "missing_applied": []})
            continue
        missing_import = _present(imp, src)
        missing_applied = _present(app, src)
        if missing_import or missing_applied:
            gaps.append({**base, "missing_import": missing_import, "missing_applied": missing_applied})
    return gaps


def present_techniques(manifest: dict, build_src: str, build_label: str = "") -> list[str]:
    """Techniques whose fingerprints are all present (for the founder's eye to judge HOW WELL).
    A no-fingerprint technique is never 'present' — it is unverifiable (see find_gaps)."""
    src = _searchable(build_src)
    out = []
    for tech in manifest.get("techniques", []):
        if not _claims(tech, build_label):
            continue
        imp = tech.get("import") or []
        app = tech.get("applied") or []
        if (imp or app) and not _present(imp, src) and not _present(app, src):
            out.append(tech.get("technique", tech.get("id", "?")))
    return out


def report(manifest: dict, build_src: str, build_label: str) -> int:
    ref = manifest.get("reference", "the reference")
    if not (manifest.get("techniques") or []):
        print(f"manifest for {ref} declares NO techniques — nothing was verified. "
              "A steal-manifest must declare what the build steals (Codex review 2026-06-25).",
              file=sys.stderr)
        return 2
    gaps = find_gaps(manifest, build_src, build_label)
    if gaps:
        print(f"technique-parity vs {ref}: {len(gaps)} declared technique(s) MISSING from {build_label}:", file=sys.stderr)
        for g in gaps:
            bits = []
            if g["missing_import"]:
                bits.append(f"not imported ({', '.join(g['missing_import'])})")
            if g["missing_applied"]:
                bits.append(f"not applied to {g['role']} ({', '.join(g['missing_applied'])})")
            print(f"  - {g['technique']}: " + "; ".join(bits), file=sys.stderr)
        print("\nyou declared these and dropped them. not a verdict — a regression alarm.", file=sys.stderr)
        return 2
    # No technique missing. This does NOT certify the page — hand it to the eye.
    here = present_techniques(manifest, build_src, build_label)
    print(f"regression-clean vs {ref}: every declared technique is present.")
    print("this certifies nothing about craft. the founder's eye decides whether each")
    print("lands the same way as the reference:")
    for t in here:
        print(f"  - {t}  -> does it land like {ref}?")
    return 0


def _load(manifest_path: Path, build_path: Path) -> tuple[dict | None, str | None, str]:
    if not manifest_path.is_file():
        return None, None, f"steal-manifest not found: {manifest_path}"
    if not build_path.is_file():
        return None, None, f"build file not found: {build_path}"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return None, None, f"steal-manifest is not valid JSON: {exc}"
    return manifest, build_path.read_text(encoding="utf-8"), ""


def selftest() -> int:
    problems: list[str] = []
    manifest = {
        "reference": "pi.security",
        "techniques": [
            {"id": "lenis", "technique": "Lenis smooth scroll", "role": "page scroll",
             "import": ["lenis"], "applied": ["new Lenis"]},
            {"id": "splittext", "technique": "GSAP SplitText headline", "role": "hero h1",
             "import": ["SplitText"], "applied": [r"SplitText\("]},
        ],
    }
    good = '<script src="lenis.js"></script><script>new Lenis();const s=new SplitText("h1");</script>'
    bad = '<script src="lenis.js"></script><script>new Lenis();</script>'  # SplitText dropped

    if find_gaps(manifest, good):
        problems.append("GOOD build wrongly reported gaps (false alarm)")
    bad_gaps = find_gaps(manifest, bad)
    if not bad_gaps:
        problems.append("BAD build (dropped SplitText) reported NO gap — false green, the original failure")
    elif bad_gaps[0]["id"] != "splittext":
        problems.append("BAD build tripped the wrong technique")

    # Codex 2026-06-25: a technique whose fingerprint survives only in a comment is NOT present
    commented = '<script src="lenis.js"></script><script>new Lenis();</script><!-- new SplitText("h1") -->'
    if not find_gaps(manifest, commented):
        problems.append("fingerprint present only in an HTML comment was treated as real use (false green)")

    # Codex 2026-06-25: a technique with NO fingerprint cannot be verified -> must be a gap
    no_fp = {"reference": "x", "techniques": [{"id": "z", "technique": "Z", "role": "r"}]}
    if not find_gaps(no_fp, good):
        problems.append("a technique with no import/applied fingerprint silently passed (false green)")

    # Codex 2026-06-25: an empty manifest verifies nothing -> report must error, not pass
    if report({"reference": "x", "techniques": []}, good, "empty") != 2:
        problems.append("empty manifest (no techniques) returned 0 — false green, nothing verified")

    # the success path must never emit a green-state verdict word — on stdout OR stderr
    # (Codex 2026-06-25: a stderr-only regression would slip a stdout-only capture)
    import io, contextlib
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        report(manifest, good, "selftest-good")
    success_text = (out.getvalue() + "\n" + err.getvalue()).upper()
    for word in FORBIDDEN_VERDICTS:
        if re.search(rf"\b{word}\b", success_text):
            problems.append(f"success path printed a green-state verdict word: {word!r}")

    if problems:
        print("SELFTEST FAILED — parity checker not trustworthy:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 2
    print("selftest: good build has no gaps, dropped technique trips the alarm, success path emits no PASS/DONE")
    return 0


def main() -> int:
    args = sys.argv[1:]
    if args and args[0] == "--selftest":
        return selftest()
    if len(args) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    manifest, build_src, err = _load(Path(args[0]), Path(args[1]))
    if err:
        print(f"parity: {err}", file=sys.stderr)
        return 2
    return report(manifest, build_src, args[1])


if __name__ == "__main__":
    sys.exit(main())
