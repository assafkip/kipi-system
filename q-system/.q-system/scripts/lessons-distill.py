#!/usr/bin/env python3
"""lessons-distill: autonomously turn every instance's new learnings into fleet-wide lessons.

Founder model (2026-06-30, inverts the prior PRD): EVERY learning is shareable to ALL instances;
de-identify by SCRUBBING client data, not by requiring recurrence. Fully autonomous — no human queue.

Per new learning (RCA):
  1. DISTILL it into a HOW-only lesson via `claude -p` (drop all WHAT / specifics).
  2. GATE (fail-closed, lessons_scrub): find client-data signals; scrub them; a lesson PUBLISHES only
     if the scrubbed text is deterministically clean AND an LLM semantic pass confirms no residual
     real entity. Anything the gate can't clear is HELD (written to the held dir), never published.
  3. PUBLISH clean lessons to q-system/lessons/<id>.md (frontmatter {id,kind,title,date}); the rail
     fans them read-only to every instance on the next `kipi update`.
  4. LEDGER every source so each learning is processed once (idempotent daily runs).

Emits a JSON summary (published / held / scanned) for the daily heartbeat to Slack.

Test hooks: --distilled-file (inject distillations, skip claude), --test-verify {real,clean,held}.
"""
import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("lessons_scrub", SCRIPTS / "lessons_scrub.py")
scrub_mod = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(scrub_mod)


def load_instances(registry_path):
    data = json.loads(Path(registry_path).read_text())
    return [(e["name"], e["path"]) for e in data.get("instances", [])
            if not str(e.get("status", "")).startswith("merged")]


def new_rcas(instances, ledger):
    """Yield (instance, path, source_hash, text) for RCAs not yet in the ledger."""
    for name, path in instances:
        rca_dir = Path(path) / "q-system" / "output" / "rca"
        if not rca_dir.is_dir():
            continue
        for rca in sorted(rca_dir.glob("*.md")):
            if rca.name.lower() == "readme.md":
                continue
            text = rca.read_text(errors="ignore")
            h = hashlib.sha1(text.encode()).hexdigest()[:16]
            if h not in ledger:
                yield name, str(rca), h, text


def structural_cause(text):
    m = re.search(r"##\s*Structural root cause\s*\n(.+?)(?:\n##\s|\Z)", text, re.S | re.I)
    return (m.group(1).strip() if m else text[:1500]).strip()


def rca_title(text):
    m = re.search(r"^#\s+(.+)$", text, re.M)
    return m.group(1).strip() if m else "untitled"


def distill_with_claude(title, cause):
    """Return {title, body, kind} HOW-only, or None on failure."""
    prompt = (
        "Turn this RCA's structural root cause into a REUSABLE, HOW-ONLY lesson for engineers on "
        "unrelated projects. Output STRICT JSON {\"title\":..,\"body\":..,\"kind\":\"pattern|methodology\"}. "
        "RULES: the body is a net-new general restatement; NO client/product/person/company names, NO "
        "file paths, NO specifics that identify the source. Title is short and generic.\n\n"
        f"RCA title: {title}\nStructural root cause:\n{cause[:1800]}"
    )
    try:
        r = subprocess.run(["claude", "-p", prompt], capture_output=True, text=True, timeout=120)
        m = re.search(r"\{.*\}", r.stdout, re.S)
        obj = json.loads(m.group(0)) if m else None
    except Exception:
        return None
    if not obj or obj.get("kind") not in ("pattern", "methodology"):
        return None
    return {"title": str(obj["title"]).strip(), "body": str(obj["body"]).strip(), "kind": obj["kind"]}


def llm_verify_clean(text, mode):
    """Semantic backstop. mode: real (ask claude), clean (test: pass), held (test: fail)."""
    if mode == "clean":
        return True
    if mode == "held":
        return False
    prompt = ("Does the text contain ANY specific real client, product, person, company, matter, or "
              "identifying number/codename? Reply exactly CLEAN or HELD.\n\n" + text[:2000])
    try:
        r = subprocess.run(["claude", "-p", prompt], capture_output=True, text=True, timeout=90)
        return r.stdout.strip().upper().startswith("CLEAN")
    except Exception:
        return False  # fail-closed: cannot verify -> hold


def slugify(title):
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s[:60] or "lesson"


def gate(title, body, roster, verify_mode):
    """Return (published_text_or_None, held_reason_or_None). Fail-closed."""
    combined = f"{title}\n{body}"
    scrubbed, _hits = scrub_mod.scrub(combined, roster)
    if not scrub_mod.is_clean(scrubbed, roster):
        return None, "deterministic scrub could not clear all client-data signals"
    if not llm_verify_clean(scrubbed, verify_mode):
        return None, "LLM semantic check flagged a residual real entity"
    return scrubbed, None


def write_lesson(lessons_dir, distilled, published_text, stamp, used_ids):
    title = published_text.split("\n", 1)[0].strip() or distilled["title"]
    body = published_text.split("\n", 1)[1].strip() if "\n" in published_text else ""
    base = slugify(title); lid = base; n = 2
    while lid in used_ids or (lessons_dir / f"{lid}.md").exists():
        lid = f"{base}-{n}"; n += 1
    used_ids.add(lid)
    doc = (f"---\nid: {lid}\nkind: {distilled['kind']}\ntitle: {title}\ndate: {stamp}\n---\n\n{body}\n")
    (lessons_dir / f"{lid}.md").write_text(doc)
    return lid, title


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--registry", default=str(REPO_ROOT / "instance-registry.json"))
    ap.add_argument("--lessons-dir", default=str(REPO_ROOT / "q-system" / "lessons"))
    ap.add_argument("--held-dir", default=str(REPO_ROOT / "lesson-candidates"))
    ap.add_argument("--ledger", default=str(REPO_ROOT / "lesson-candidates" / ".processed.json"))
    ap.add_argument("--distilled-file", default=None, help="JSON {source_hash:{title,body,kind}} (test)")
    ap.add_argument("--test-verify", default="real", choices=["real", "clean", "held"])
    ap.add_argument("--limit", type=int, default=0, help="max learnings this run (0=all)")
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    if not Path(args.registry).exists():
        print(json.dumps({"skipped": "no registry (run from skeleton)"})); return 0

    lessons_dir = Path(args.lessons_dir); held_dir = Path(args.held_dir)
    ledger_path = Path(args.ledger)
    ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else {}
    injected = json.loads(Path(args.distilled_file).read_text()) if args.distilled_file else None
    roster = scrub_mod.codenames_from_registry(args.registry)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    used_ids = set()
    published, held, scanned = [], [], 0

    for name, path, h, text in new_rcas(load_instances(args.registry), ledger):
        if args.limit and scanned >= args.limit:
            break
        scanned += 1
        distilled = (injected.get(h) if injected is not None
                     else distill_with_claude(rca_title(text), structural_cause(text)))
        if not distilled:
            continue  # distillation failed/absent -> leave unprocessed, retry next run
        published_text, held_reason = gate(distilled["title"], distilled["body"], roster, args.test_verify)
        if args.dry:
            (published.append(distilled["title"]) if published_text else held.append(distilled["title"]))
            continue
        if published_text:
            lessons_dir.mkdir(parents=True, exist_ok=True)
            lid, title = write_lesson(lessons_dir, distilled, published_text, stamp, used_ids)
            published.append(title)
        else:
            held_dir.mkdir(parents=True, exist_ok=True)
            (held_dir / f"held-{h}.md").write_text(
                f"# HELD lesson (not published)\n\nreason: {held_reason}\nsource: {path}\n\n"
                f"proposed title: {distilled['title']}\n\n{distilled['body']}\n")
            held.append(distilled["title"])
        ledger[h] = {"instance": name, "status": "published" if published_text else "held", "date": stamp}

    if not args.dry:
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        ledger_path.write_text(json.dumps(ledger, indent=2))

    print(json.dumps({"scanned": scanned, "published": published, "held": held}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
