#!/usr/bin/env python3
"""roadmap_scope.py -- the ONE deterministic classifier for the product/roadmap
boundary of the self-improvement loops (prd-morning-brief-learns-2026-09-01).

The hard constraint it enforces, from the plan's first amendment: a loop MAY
propose a fix to a stage, a skill for manual work, a rule/lint/prompt change, or
a context entry. A loop MAY NOT propose what to build, sell, publish, or what a
client should do. Those arrive from a human conversation.

Why a module and not a paragraph: `wire-a-hard-constraint-into-the-done-gate-
and-halt-when-a-plan-quietly-relaxes-it`. A constraint with no failing input is
decoration.

Why the TEXT is read and not only the declared target: Codex finding-1 on the
PRD (2026-09-01). The first draft trusted the friction author's `--target`
field, so a product proposal labelled `target=rule` would have passed both
checks. Now the text is classified too, and a roadmap match in the text beats
any system target.

Why `unknown` exists and is a refusal: fail closed. Empty text, a missing
target, or a target this module does not know all return `unknown`, and every
consumer (friction-note.sh, weekly-improve.py, improve_ground.py) refuses on
it. A gate fails closed; a filter fails open; this is a gate.

No LLM, no network, no child process. Importable, and a CLI so a shell writer
can call it: exit 0 = system, 2 = roadmap, 3 = unknown.

Pairs with: test_roadmap_scope.py (RED first), test_roadmap_scope_suite.py
(the paraphrase suite, issue mbl-roadmap-scope-paraphrase-suite).
"""
from __future__ import annotations

import argparse
import json
import re
import sys

# Targets a friction line or proposal may declare. Anything else is unknown.
SYSTEM_TARGETS = frozenset({
    "rule", "lint", "hook", "trigger", "context", "skill", "prompt", "test",
    "script", "job", "plist", "docs", "gate", "brief",
})
ROADMAP_TARGETS = frozenset({
    "product", "roadmap", "pricing", "publish", "client-advice", "sales",
    "marketing", "content",
})

# The pattern lists live HERE and nowhere else. Extend them to make the
# paraphrase suite green; never delete a suite case to make it green.
ROADMAP_PATTERNS = {
    "PRODUCT": [
        r"\bsell(ing)?\b",
        r"\bmoneti[sz]e\b",
        r"\b(launch|ship|build|offer)\b[^.]{0,40}\b(product|feature|tier|plan|app|saas|template|package|service)\b",
        r"\b(paid|premium|pro)\s+(tier|plan|version)\b",
        r"\bcustomers?\s+(want|need|would pay)\b",
        r"\b(market|position)\s+(it|this|the)\b",
        r"\bgo[- ]to[- ]market\b",
        r"\bwhat (we|to) (should )?build next\b",
    ],
    "PRICING": [
        r"\bpric(e|ing|es)\b",
        r"\bcharge\b",
        r"\$\s?\d",
        r"\bper\s+(seat|user|month|year|hour)\b",
        r"\bdiscount\b",
        r"\bretainer\b",
        r"\brate card\b",
        r"\binvoice (them|the client)\b",
    ],
    "PUBLISH": [
        r"\bpublish\b",
        r"\bpost (this|it|that)\b",
        r"\b(linkedin|twitter|x|reddit|medium|substack)\s+(post|thread|article)\b",
        r"\bnewsletter\b",
        r"\bblog\s*post\b",
        r"\bwrite (a|an|the) (post|article|thread)\b",
    ],
    "CLIENT_ADVICE": [
        r"\b(tell|advise|recommend to)\s+(the\s+)?client\b",
        r"\bthe client (should|needs to|must|ought to)\b",
        r"\bclient should\b",
        r"\bproposal (to|for) (the\s+)?client\b",
        r"\badvice for (the\s+)?client\b",
    ],
}
_COMPILED = {name: [re.compile(p, re.IGNORECASE) for p in pats]
             for name, pats in ROADMAP_PATTERNS.items()}


def classify(text: str, declared_target) -> dict:
    """{"verdict": system|roadmap|unknown, "matched": [...], "target": ...}.

    Order matters and is the whole point:
    1. empty text or no target -> unknown (fail closed)
    2. a roadmap target -> roadmap, whatever the text says
    3. a roadmap pattern in the text -> roadmap, whatever the target says
    4. a known system target -> system
    5. anything else -> unknown
    """
    target = (declared_target or "").strip().lower() or None
    body = (text or "").strip()
    if not body or target is None:
        return {"verdict": "unknown", "matched": [], "target": target,
                "reason": "empty text or missing target"}
    if target in ROADMAP_TARGETS:
        return {"verdict": "roadmap", "matched": [f"target:{target}"], "target": target}
    matched = [f"{name}:{rx.pattern}" for name, rxs in _COMPILED.items()
               for rx in rxs if rx.search(body)]
    if matched:
        return {"verdict": "roadmap", "matched": matched, "target": target}
    if target in SYSTEM_TARGETS:
        return {"verdict": "system", "matched": [], "target": target}
    return {"verdict": "unknown", "matched": [], "target": target,
            "reason": f"unrecognised target {target!r}"}


EXIT = {"system": 0, "roadmap": 2, "unknown": 3}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--target", required=True, help="declared target of the proposal")
    ap.add_argument("text", nargs="?", help="proposal text (stdin when omitted)")
    args = ap.parse_args(argv)
    text = args.text if args.text is not None else sys.stdin.read()
    out = classify(text, args.target)
    print(json.dumps(out))
    return EXIT[out["verdict"]]


if __name__ == "__main__":
    raise SystemExit(main())
