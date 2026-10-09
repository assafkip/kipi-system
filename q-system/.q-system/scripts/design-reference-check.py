#!/usr/bin/env python3
"""The reference stage of the design chain (dc-25): what a round is built FROM, checked.

WHY (founder, 2026-10-09): "change the design flow to include these steps and also have a
full analysis and breakdown of the techniques, design taxonomy, design path and actual
technologies used on the exemplar sites and bake that into design-chain itself". The steps
are a senior designer's read of why six measured rounds still produced a page he was "not
sold" on:

  1. the references were the wrong KIND of site (software companies, for a one-person
     practice), so a set needs peers, not only craft sites;
  2. no feeling was named, so numbers stood in for taste;
  3. limits taken from the busiest site and floors from the plainest average the set into
     a blend, so every direction goes deep on ONE primary reference;
  4. only the first screen was studied, so every direction writes its whole page path;
  5. the trust signals an expert practice lives on were never inventoried, so the brief
     names the ones the round uses, from what the peers actually show;
  6. rules stop bad design and cannot make good design, so the critique puts each
     direction next to its primary reference and says whether it is as good.
(Testing on real people was the seventh; the founder parked it the same day.)

Every check reads files only, and ANALYSIS.json is written by design-exemplar-analysis.py,
never by hand: a roster edited after the analysis makes the analysis stale.

Opt-in: the gate calls this only when design-chain.json carries a "references" block, and
only for rounds whose folder date is on or after references.since, so rounds that sealed
under the old bar are not re-litigated (the same grandfather chain_problems uses).
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROLES = ("peer", "craft")
DEFAULTS = {
    "roster": "design/references/exemplars.json",
    "vision": "design/VISION.md",
    "since": "0000-00-00",
    "min_peer": 3,
    "min_craft": 1,
    "feel_words": 3,
    "min_page_path": 4,
    "min_trust_signals": 2,
}
FEEL_RE = re.compile(r'(?m)^\*\*Feel \(founder, \d{4}-\d{2}-\d{2}\):\*\*\s*"([^"]+)"')
# labels may be written bold ("**Trust signals:**"), the way a brief usually is
PRIMARY_RE = re.compile(r"(?im)^\s*[-*]?\s*\**Primary reference:\**\s*(\S+)")
PATH_RE = re.compile(r"(?im)^\s*[-*]?\s*\**Page path:\**\s*(.+)$")
TRUST_RE = re.compile(r"(?im)^\s*[-*]?\s*\**Trust signals:\**\s*(.+)$")
SIDE_RE = re.compile(r"(?im)^\s*[-*]?\s*SIDE-BY-SIDE:\s*(.+?)\s+vs\s+(\S+?):\s*(AS GOOD|NOT AS GOOD)\b")


def host_of(url: str) -> str:
    return url.strip().split("//")[-1].split("/")[0].lower().removeprefix("www.").rstrip(".,;)")


def _items(text: str) -> list[str]:
    return [t.strip().strip("`*.").lower() for t in re.split(r">|,|;|->|→", text) if t.strip()]


def settings(cfg: dict) -> dict:
    out = dict(DEFAULTS)
    out.update((cfg or {}).get("references") or {})
    return out


def applies(rd: Path, cfg: dict) -> bool:
    if not (cfg or {}).get("references"):
        return False
    m = re.match(r"\d{4}-\d{2}-\d{2}", rd.name)
    return bool(m) and m.group(0) >= settings(cfg)["since"]


def roster_problems(roster: Path, s: dict) -> tuple[list[str], list[dict]]:
    if not roster.is_file():
        return [f"missing {roster}: the reference set is the input to every round"], []
    try:
        items = json.loads(roster.read_text())["exemplars"]
    except (ValueError, KeyError, TypeError) as e:
        return [f"{roster} cannot be read as {{\"exemplars\": [...]}}: {e}"], []
    probs = []
    bad = [e.get("url") for e in items if e.get("role") not in ROLES]
    if bad:
        probs.append(f"{roster.name}: every exemplar carries \"role\": \"peer\" (a practice like "
                     f"this one) or \"craft\" (borrowed for its craft only). Missing on {bad}")
    peers = [e for e in items if e.get("role") == "peer"]
    crafts = [e for e in items if e.get("role") == "craft"]
    if len(peers) < s["min_peer"]:
        probs.append(f"{roster.name} has {len(peers)} peer exemplar(s); {s['min_peer']} required. "
                     f"A set of only craft sites taught a one-person practice to look like a "
                     f"software company.")
    if len(crafts) < s["min_craft"]:
        probs.append(f"{roster.name} has {len(crafts)} craft exemplar(s); {s['min_craft']} required.")
    prim = [e.get("url") for e in items if e.get("primary") is True]
    if len(prim) != 1:
        probs.append(f"{roster.name} marks {len(prim)} exemplar(s) \"primary\": true; exactly one is "
                     f"required, and it is the founder's pick. One main reference, gone deep, "
                     f"instead of a blend of all of them.")
    elif not any(e.get("primary") is True and e.get("role") == "peer" for e in items):
        probs.append(f"{roster.name}: the primary exemplar {prim[0]} is not a peer. The main "
                     f"reference is a practice like this one; craft sites are borrowed from.")
    return probs, items


def analysis_problems(roster: Path, items: list[dict]) -> tuple[list[str], dict]:
    ap = roster.parent / "ANALYSIS.json"
    fix = f"run design-exemplar-analysis.py {roster.parent}"
    if not ap.is_file():
        return [f"missing {ap}: {fix}. The techniques, taxonomy, design path and technologies "
                f"of every exemplar are read from it."], {}
    try:
        data = json.loads(ap.read_text())
    except ValueError as e:
        return [f"{ap.name} is not valid JSON: {e}. {fix}"], {}
    probs = []
    if data.get("roster_sha256") != hashlib.sha256(roster.read_bytes()).hexdigest():
        probs.append(f"{ap.name} is stale: {roster.name} changed after it was written. {fix}")
    sites = data.get("sites") or {}
    for e in items:
        h = host_of(e.get("url", ""))
        if h not in sites:
            probs.append(f"{ap.name} has no analysis of {h}. {fix}")
        elif "error" in sites[h]:
            probs.append(f"{ap.name}: {h} failed to analyse ({sites[h]['error'][:80]}). Fix the "
                         f"capture or drop the site from the roster; an exemplar nobody read "
                         f"cannot be built from.")
    return probs, data


def feel_problems(vision: Path, brief: str, s: dict) -> list[str]:
    if not vision.is_file():
        return [f"missing {vision}: the feel is written there, in the founder's words"]
    m = FEEL_RE.search(vision.read_text())
    if not m:
        return [f"{vision.name} has no line '**Feel (founder, YYYY-MM-DD):** \"word, word, word\"'. "
                f"The founder names how the site should feel in {s['feel_words']} words before any "
                f"number is taken from an exemplar; numbers cannot tell whether it feels right."]
    words = _items(m.group(1))
    probs = []
    if len(words) != s["feel_words"]:
        probs.append(f"the Feel line names {len(words)} word(s) {words}; exactly {s['feel_words']}.")
    missing = [w for w in words if w not in brief.lower()]
    if missing:
        probs.append(f"brief.md does not carry the feel word(s) {missing}. The round is briefed "
                     f"against the feel, not near it.")
    return probs


def direction_problems(dirs: str, data: dict, items: list[dict], need: int, s: dict) -> list[str]:
    roles = {host_of(e.get("url", "")): e.get("role") for e in items}
    kinds = set(data.get("section_kinds") or [])
    probs = []
    prims = [host_of(x) for x in PRIMARY_RE.findall(dirs)]
    if len(prims) < need:
        probs.append(f"directions.md names {len(prims)} 'Primary reference:' line(s); one per "
                     f"direction ({need}) is required. Each direction goes deep on one site.")
    for h in prims:
        if roles.get(h) != "peer":
            probs.append(f"directions.md: primary reference {h} is "
                         f"{'not in the roster' if h not in roles else 'a craft site'}. A direction's "
                         f"primary is a peer from the roster.")
    paths = PATH_RE.findall(dirs)
    if len(paths) < need:
        probs.append(f"directions.md writes {len(paths)} 'Page path:' line(s); one per direction "
                     f"({need}) is required. The whole page is designed, not just the first screen.")
    for p in paths:
        steps = _items(p)
        unknown = [k for k in steps if k not in kinds]
        if len(steps) < s["min_page_path"]:
            probs.append(f"Page path '{p.strip()}' has {len(steps)} section(s); at least "
                         f"{s['min_page_path']}.")
        if unknown:
            probs.append(f"Page path '{p.strip()}' uses {unknown}, which are not section kinds in "
                         f"ANALYSIS.json {sorted(kinds)}. The path is written in the taxonomy the "
                         f"exemplars were read in.")
    return probs


def trust_problems(brief: str, data: dict, s: dict) -> list[str]:
    m = TRUST_RE.search(brief)
    if not m:
        return [f"brief.md has no 'Trust signals:' line. Name the {s['min_trust_signals']}+ trust "
                f"signals this round uses, from what the peer exemplars show in ANALYSIS.json."]
    named = _items(m.group(1))
    shown = {k for site in (data.get("sites") or {}).values()
             if site.get("role") == "peer" and "error" not in site for k in site.get("trust_signals", {})}
    probs = []
    if len(named) < s["min_trust_signals"]:
        probs.append(f"brief.md 'Trust signals:' names {len(named)}; at least {s['min_trust_signals']}.")
    unseen = [k for k in named if k not in shown]
    if unseen:
        probs.append(f"brief.md 'Trust signals:' names {unseen}, which no peer exemplar shows "
                     f"(peers show {sorted(shown)}). Use what a practice like this one is trusted on.")
    return probs


def side_by_side_problems(critique: str, items: list[dict], need: int) -> list[str]:
    rows = SIDE_RE.findall(critique)
    hosts = {host_of(e.get("url", "")) for e in items}
    probs = []
    if len(rows) < need:
        probs.append(f"critique.md has {len(rows)} 'SIDE-BY-SIDE: <direction> vs <host>: AS GOOD|NOT "
                     f"AS GOOD' line(s); one per direction ({need}). Put the page next to its primary "
                     f"reference's full-page capture and say plainly whether it is as good.")
    for name, h, verdict in rows:
        if host_of(h) not in hosts:
            probs.append(f"critique.md SIDE-BY-SIDE for {name} compares against {h}, not in the roster.")
        if verdict.upper() == "NOT AS GOOD":
            probs.append(f"critique.md: {name} is NOT AS GOOD as {h}. Change the page until it is; "
                         f"rules stop bad design, this is the step that asks for good.")
    return probs


def reference_problems(rd: Path, cfg: dict, cfg_path: Path, need_dirs: int) -> list[str]:
    if cfg_path is None or not applies(rd, cfg):
        return []
    s = settings(cfg)
    base = cfg_path.parent
    roster = base / s["roster"]
    probs, items = roster_problems(roster, s)
    if not items:
        return probs
    aprobs, data = analysis_problems(roster, items)
    probs += aprobs
    read = lambda n: (rd / n).read_text() if (rd / n).is_file() else ""
    brief = read("brief.md")
    probs += feel_problems(base / s["vision"], brief, s)
    if data:
        probs += direction_problems(read("directions.md"), data, items, need_dirs, s)
        probs += trust_problems(brief, data, s)
    probs += side_by_side_problems(read("critique.md"), items, need_dirs)
    return probs
