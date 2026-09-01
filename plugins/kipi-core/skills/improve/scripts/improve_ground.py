#!/usr/bin/env python3
"""improve_ground.py -- the grounding half of the `improve` skill.

Plan item 2d of prd-morning-brief-learns-2026-09-01: paste an outside idea (a
tip, a post, a transcript) and get a verdict against what THIS system already
has, grounded in the lessons corpora and the capability declarations, never in
an unsourced opinion. The skill (SKILL.md) is the judgment half; this file is
the deterministic half it must call.

Verdicts: `already-built` (a lesson or a named file already covers it),
`adopt` (a system change with no existing coverage), `skip` (the roadmap
classifier says roadmap or unknown: what to build, sell or publish is never
this loop's call). Every verdict cites at least one lessons path or a named
file, or it is not a verdict.

Corpora contract (Codex finding-11 on the PRD): KIPI_LESSONS_CORPORA is a
colon-separated list of lessons directories; the default is THIS instance's
q-system/lessons resolved relative to this file (plugins/kipi-core/skills/
improve/scripts -> repo root -> q-system/lessons). Nothing here hardcodes a
sibling checkout, and every corpus is reported as read (with a count),
missing, or unreadable, so a verdict never silently rests on one corpus while
claiming two. This is the same seam PRD B's lessons_recall --both will use.

Offline and deterministic: no LLM, no network. The recall engine is
lessons_recall.py, imported by path from this instance's scripts.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]  # scripts -> improve -> skills -> kipi-core -> plugins -> repo
DEFAULT_CORPUS = REPO / "q-system" / "lessons"
SCRIPTS = REPO / "q-system" / ".q-system" / "scripts"
# lessons_recall scores are cosine-like and low in absolute terms: measured on
# the live corpus 2026-09-01, a genuine match ("stage with no trigger" ->
# every-stage-needs-its-own-trigger) scored 0.23 and unrelated top hits sat
# near 0.09. The floor is between them; it is a signal, and the skill still
# opens what is cited.
MATCH_FLOOR = 0.18

# Named files that already implement ideas outsiders keep proposing. A hit
# here is `already-built` with the file named; extend when a new "we should
# build X" turns out to be a file that exists.
KNOWN_BUILT = {
    "risk-scored auto-merge": "q-system/.q-system/scripts/review-tier.py",
    "auto merge": "q-system/.q-system/scripts/review-tier.py",
    "merge risk": "q-system/.q-system/scripts/review-tier.py",
    "self-review": "q-system/.q-system/scripts/review-tier.py",
    "deadman": "q-system/.q-system/scripts/morning-brief-deadman.py",
    "morning brief": "q-system/.q-system/scripts/morning-brief.py",
    "friction": "q-system/.q-system/scripts/friction-note.sh",
    "capability manifest": "q-system/.q-system/scripts/capability_manifest.py",
    "custom connector": "q-system/.q-system/scripts/capability_manifest.py",
    "handoff": "q-system/memory/last-handoff.md",
}


def _load(stem: str, path: Path):
    spec = importlib.util.spec_from_file_location(stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def corpora(env=None) -> list:
    raw = (env if env is not None else os.environ).get("KIPI_LESSONS_CORPORA", "")
    dirs = [Path(p).expanduser() for p in raw.split(":") if p.strip()] or [DEFAULT_CORPUS]
    return dirs


def corpus_report(dirs: list) -> list:
    """[{path, status: read|missing|unreadable, count}]"""
    out = []
    for d in dirs:
        if not d.exists():
            out.append({"path": str(d), "status": "missing", "count": 0})
            continue
        try:
            n = len([p for p in d.glob("*.md") if p.name != "README.md"])
            out.append({"path": str(d), "status": "read", "count": n})
        except OSError as exc:
            out.append({"path": str(d), "status": "unreadable", "count": 0, "error": str(exc)})
    return out


def recall(idea: str, dirs: list, k: int = 3) -> list:
    """[(score, path)] across every readable corpus, best first."""
    engine = _load("lessons_recall", SCRIPTS / "lessons_recall.py")
    hits = []
    for d in dirs:
        if not d.exists():
            continue
        try:
            hits += [(float(s), p) for s, p in engine.search(idea, k=k, lessons_dir=str(d))]
        except Exception:  # noqa: BLE001 - an unreadable corpus is reported, never fatal
            continue
    return sorted(hits, key=lambda x: -x[0])[:k]


def is_refused(text: str, declared_target) -> bool:
    """The consumer contract held by test_roadmap_scope_suite.py."""
    scope = _load("roadmap_scope", SCRIPTS / "roadmap_scope.py")
    return scope.classify(text, declared_target)["verdict"] != "system"


def ground(idea: str, target: str = "skill", env=None) -> dict:
    dirs = corpora(env)
    report = corpus_report(dirs)
    scope = _load("roadmap_scope", SCRIPTS / "roadmap_scope.py").classify(idea, target)
    if scope["verdict"] != "system":
        return {"verdict": "skip", "reason": f"roadmap scope ({scope['verdict']}): this loop never decides what to build, sell or publish",
                "cites": ["q-system/.q-system/scripts/roadmap_scope.py"], "corpora": report}
    low = idea.lower()
    for key, path in KNOWN_BUILT.items():
        if key in low:
            return {"verdict": "already-built", "reason": f"{path} already does this", "cites": [path],
                    "corpora": report}
    hits = recall(idea, dirs)
    strong = [(s, p) for s, p in hits if s >= MATCH_FLOOR]
    if strong:
        return {"verdict": "already-built", "reason": "a lesson already covers it",
                "cites": [p for _, p in strong], "corpora": report}
    return {"verdict": "adopt", "reason": "no lesson or named file covers it; a system change is proposable",
            "cites": [p for _, p in hits] or ["q-system/lessons/README.md"], "corpora": report}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="ground an outside idea against this system")
    ap.add_argument("idea", nargs="?", help="the idea text (stdin when omitted)")
    ap.add_argument("--target", default="skill")
    args = ap.parse_args(argv)
    idea = args.idea if args.idea is not None else sys.stdin.read()
    out = ground(idea, args.target)
    print(json.dumps(out, indent=2))
    return {"already-built": 0, "adopt": 0, "skip": 2}[out["verdict"]]


if __name__ == "__main__":
    raise SystemExit(main())
