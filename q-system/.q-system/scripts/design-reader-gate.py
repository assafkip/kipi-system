#!/usr/bin/env python3
"""The reader gate: fresh model readers, given the persona of the buyer, look at the first screen
of each page and answer a fixed set of questions. One row per page, viewport and reader.

WHY IT LIVES HERE (dc-06, ASK-1796). The only reader gate was consulting's gate_icp.py: one
instance, and it read PNGs the round supplied. So readers could be shown a screenshot of a page
other than the one being sealed, and no row said which page bytes or which image its answers were
about. This script renders every page ITSELF from the served round, at the configured viewports,
hashes the page and the screenshot, and never opens a PNG from the round.

Every row carries:
  page, viewport, instance, html_sha256 (the local page, equal to the served bytes or this refuses),
  png_sha256 (the screenshot this run took), answers (verbatim, in question order), contaminated
  (the control question did not come back "unknown"), and _provenance {runner, model,
  persona_file, persona_sha256, questions_sha256, at}.

WHAT IT DOES NOT DO: judge. Whether a row says STAY or LEAVE, and what seal does about it, is
dc-07. A reader is a machine check of what a first screen communicates, not buyer research.

Usage:
  design-reader-gate.py <round> --url-base <served round> --config <design-chain.json>
                        [--page NAME ...] [--runner claude|injected] [--answers FILE]
                        [--keep-screens DIR]
  readers block in design-chain.json: {"persona_file": "<path relative to the config>",
                                       "n": 3, "viewports": [[1440, 900]], "model": "..."}
Exit 0 rows written; 2 could not run (no persona, served bytes differ, no browser, a runner
failure, or a real model called from a test).

The model call is injectable: --runner injected answers from --answers (a JSON list of answers,
used for every reader), and its rows say runner=injected. The claude runner refuses to run while
PYTEST_CURRENT_TEST is set, so a test cannot spend a model call by forgetting to inject.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

DEFAULT_MODEL = "claude-haiku-4-5"
DEFAULT_VIEWPORTS = [[1440, 900]]
DEFAULT_N = 3
# The default questions. An instance sets its own in design-chain.json readers.questions; the
# LAST question is always the control, a fact the page does not state, whose honest answer is
# "unknown". Written for any page, not one consultant: the first version asked what "he" sells
# and was consulting's own list (standard review of c911e33f, std-7).
QUESTIONS = [
    "Is this page about a problem you actually have? Which one, in your words?",
    "What is being offered here?",
    "What would happen if you took it up?",
    "Why would you believe it, or not?",
    "What would the first step cost you, in time or money?",
    "In three words or fewer, who is this for?",
    "Would you keep reading, or leave? Why?",
    "What, if anything, confused you or put you off?",
    "CONTROL: In what year was the organisation behind this page founded?",
]
FRAME = ("You have just landed on this page. You know nothing about the person beyond what is in the "
         "screenshot. Answer only from what you can see; if the page does not tell you, say 'unknown'.")
HTML_SUFFIXES = {".html", ".htm"}


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def refuse(msg: str) -> int:
    print(f"could not run: {msg}", file=sys.stderr)
    return 2


def served_bytes_differ(url: str, local: Path) -> str | None:
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            got = r.read()
    except OSError as e:
        return f"could not fetch {url}: {e}"
    if sha(got) != sha(local.read_bytes()):
        return f"served bytes differ from {local.name} at {url}"
    return None


def shoot(url: str, viewports: list, dest: Path) -> list[tuple[list, Path]]:
    """One first-screen screenshot per viewport, taken by this run into `dest`."""
    from playwright.sync_api import sync_playwright
    out = []
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        try:
            for w, h in viewports:
                pg = b.new_page(viewport={"width": int(w), "height": int(h)})
                pg.goto(url, wait_until="networkidle")
                pg.wait_for_timeout(600)
                f = dest / f"{Path(url).stem}-{w}x{h}.png"
                pg.screenshot(path=str(f))
                pg.close()
                out.append(([int(w), int(h)], f))
        finally:
            b.close()
    return out


def ask_claude(png: Path, system: str, model: str, questions: list[str]) -> dict:
    """One fresh reader: a clean temp dir holding only the screenshot, --safe-mode, Read only."""
    prompt = ("Use the Read tool to open the image file 'screen.png' in the current directory. It is a "
              "screenshot of the first screen of a website. Then answer each question in one or two plain "
              "sentences, as JSON keyed by question number: {\"answers\": {\"1\": \"...\", \"2\": \"...\"}}, "
              "one key for every question below and no other keys.\n\n"
              + "\n".join(f"{i + 1}. {q}" for i, q in enumerate(questions)))
    with tempfile.TemporaryDirectory(prefix="reader-") as wd:
        shutil.copy(png, Path(wd) / "screen.png")
        r = subprocess.run(["claude", "-p", "--safe-mode", "--model", model, "--system-prompt", system,
                            "--allowedTools", "Read", "--output-format", "json", prompt],
                           cwd=wd, capture_output=True, text=True, timeout=300)
    try:
        doc = json.loads(r.stdout)
        text = doc.get("result", "")
        s, e = text.find("{"), text.rfind("}")
        answers = json.loads(text[s:e + 1]).get("answers")
    except (ValueError, AttributeError):
        return {"error": (r.stdout + r.stderr)[-600:]}
    # the model that ANSWERED, as the CLI reports it: the row used to carry the configured name,
    # so any `claude` on PATH produced rows labelled with the real model (review of c911e33f, adv-4)
    usage = doc.get("modelUsage")
    reported = sorted(usage) if isinstance(usage, dict) else []
    return {"answers": answers, "model_reported": reported}


MAX_ATTEMPTS = 3


def keyed_answers(obj, n: int) -> list[str] | None:
    """The answers as a list in question order, or None when the shape is wrong: a dict keyed
    exactly "1".."n". Positional answers let a skipped or merged question shift every answer after
    it, so the control was read off another question (4 real calls on 2026-09-19 returned 9, 8, 9, 9
    answers to 9 questions); a key cannot shift."""
    if not isinstance(obj, dict) or set(obj) != {str(i) for i in range(1, n + 1)}:
        return None
    # each answer is text: a null or a nested object was stored as the string "None" or its repr,
    # and the control check read that (review of 2d342634)
    if not all(isinstance(obj[k], str) for k in obj):
        return None
    return [obj[str(i)] for i in range(1, n + 1)]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("round")
    ap.add_argument("--url-base", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--page", action="append", default=[])
    # required: with a default of claude, a test that forgot to inject spent a model call, and the
    # PYTEST_CURRENT_TEST guard never fires under a unittest run (review of c911e33f, adv-3)
    ap.add_argument("--runner", choices=("claude", "injected"), required=True)
    ap.add_argument("--answers", help="for --runner injected: a JSON object keyed '1'..'N' used for every "
                                      "reader, or {\"responses\": [...]} consumed one per model call")
    ap.add_argument("--keep-screens", help="copy every screenshot this run took into DIR")
    a = ap.parse_args(argv)

    rd = Path(a.round).resolve()
    cfg_path = Path(a.config).resolve()
    try:
        cfg = json.loads(cfg_path.read_text())
    except (OSError, ValueError) as e:
        return refuse(f"config {cfg_path}: {e}")
    readers = cfg.get("readers") if isinstance(cfg.get("readers"), dict) else {}
    pf = readers.get("persona_file")
    if not isinstance(pf, str) or not pf.strip():
        return refuse("design-chain.json names no readers.persona_file: a reader with no persona is "
                      "a reader of nobody")
    if os.path.isabs(pf) or cfg_path.parent.resolve() not in (cfg_path.parent / pf).resolve().parents:
        return refuse(f"readers.persona_file {pf!r} is not a file inside {cfg_path.parent}; name it "
                      f"relative to the config")
    persona_path = cfg_path.parent / pf
    try:
        persona = persona_path.read_bytes()
    except OSError as e:
        return refuse(f"persona file {persona_path}: {e}")
    viewports = readers.get("viewports", DEFAULT_VIEWPORTS)
    n = readers.get("n", DEFAULT_N)
    model = readers.get("model", DEFAULT_MODEL)
    questions = readers.get("questions", QUESTIONS)
    if (not isinstance(questions, list) or len(questions) < 2
            or not all(isinstance(q, str) and q.strip() for q in questions)):
        return refuse("readers.questions must be a list of at least two questions, the last of them "
                      "the control")
    if (not isinstance(viewports, list) or not viewports
            or not all(isinstance(v, list) and len(v) == 2 and all(isinstance(x, int) and 0 < x <= 10000 for x in v)
                       for v in viewports)):
        return refuse(f"readers.viewports is {viewports!r}; a list of [width, height] in pixels")
    if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= 20:
        return refuse(f"readers.n is {n!r}; a whole number of readers from 1 to 20")

    if a.runner == "claude":
        if os.environ.get("PYTEST_CURRENT_TEST"):
            return refuse("refusing to call a model from a test (PYTEST_CURRENT_TEST is set); "
                          "pass --runner injected")
        if not shutil.which("claude"):
            return refuse("the claude CLI is not on PATH")
        def answer(png):
            res = ask_claude(png, persona.decode("utf-8", "replace") + "\n\n" + FRAME, model, questions)
            if "answers" in res and res.get("model_reported") != [model]:
                return {"error": f"the answering model was {res.get('model_reported')}, not the "
                                 f"configured {model!r}; name the exact model id in readers.model"}
            return res
        model_used = model
    else:
        try:
            canned = json.loads(Path(a.answers or "").read_text())
        except (OSError, ValueError) as e:
            return refuse(f"--runner injected needs --answers FILE (JSON): {e}")
        seq = canned.get("responses") if isinstance(canned, dict) and "responses" in canned else None
        if seq is not None and (not isinstance(seq, list) or not seq):
            return refuse("--answers responses must be a non-empty list")
        calls = {"n": 0}

        def answer(png):
            if seq is None:
                return {"answers": canned}
            got = seq[min(calls["n"], len(seq) - 1)]
            calls["n"] += 1
            return {"answers": got}
        model_used = "injected"

    html = sorted(p.name for p in rd.iterdir() if p.is_file() and p.suffix.lower() in HTML_SUFFIXES)
    names = a.page or html
    outside = [x for x in names if Path(x).name != x]
    if outside:
        return refuse(f"{outside} is not a page in the round: name a page file in {rd} by its name")
    bad = [x for x in names if Path(x).suffix.lower() not in HTML_SUFFIXES or not (rd / x).is_file()]
    if not names or bad:
        return refuse(f"no readable HTML page to show readers{': ' + str(bad) if bad else ''}")

    prov = {"runner": a.runner, "model": model_used, "persona_file": pf,
            "persona_sha256": sha(persona), "questions_sha256": sha(json.dumps(questions).encode()),
            "at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")}
    rows = []
    with tempfile.TemporaryDirectory(prefix="reader-shots-") as shots:
        for name in names:
            page = rd / name
            url = f"{a.url_base.rstrip('/')}/{name}"
            why = served_bytes_differ(url, page)
            if why:
                return refuse(why)
            html_sha = sha(page.read_bytes())
            try:
                taken = shoot(url, viewports, Path(shots))
            except Exception as e:           # no browser, a crash: never a row
                return refuse(f"could not render {name}: {type(e).__name__}: {e}")
            for vp, png in taken:
                png_sha = sha(png.read_bytes())
                if a.keep_screens:
                    keep = Path(a.keep_screens)
                    keep.mkdir(parents=True, exist_ok=True)
                    shutil.copy(png, keep / png.name)
                for i in range(n):
                    # Retried ONLY on a structural failure (no answers, the wrong key set), never on
                    # what an answer says: retrying on content would let a run pick the answers it
                    # likes (Sana, 2026-09-19). Still all-or-nothing after MAX_ATTEMPTS.
                    ans, why = None, ""
                    for attempt in range(1, MAX_ATTEMPTS + 1):
                        res = answer(png)
                        if "answers" not in res:
                            why = res.get("error", "no answers")
                            if "answering model" in why:
                                return refuse(f"reader {i + 1} on {name} {vp}: {why}")
                            continue
                        ans = keyed_answers(res["answers"], len(questions))
                        if ans is not None:
                            break
                        why = (f"answers not keyed exactly 1..{len(questions)}: got "
                               f"{sorted(res['answers']) if isinstance(res['answers'], dict) else type(res['answers']).__name__}")
                    if ans is None:
                        return refuse(f"reader {i + 1} on {name} {vp}, {MAX_ATTEMPTS} attempts: {why}")
                    row_prov = dict(prov, model_reported=res.get("model_reported", ["injected"]), attempts=attempt)
                    rows.append({"page": name, "viewport": vp, "instance": i + 1,
                                 "html_sha256": html_sha, "png_sha256": png_sha, "answers": ans,
                                 # the control's honest answer IS "unknown"; containing the word
                                 # anywhere passed "his school is not unknown to me" (adv-2)
                                 "contaminated": not ans[-1].strip().lower().startswith("unknown"),
                                 "_provenance": row_prov})
    out = rd / "gate" / "reader-runs.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r) + "\n" for r in rows))
    print(f"wrote {len(rows)} reader row(s) to {out} (runner {a.runner})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
