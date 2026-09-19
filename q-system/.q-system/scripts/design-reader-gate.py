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
QUESTIONS = [
    "Is this page about a problem you actually have? Which one, in your words?",
    "What does this person sell?",
    "What would happen if you hired him?",
    "Why would you believe him, or not?",
    "What do you think the first engagement buys?",
    "In three words or fewer, what kind of consultant is he?",
    "Would you keep reading, or leave? Why?",
    "What, if anything, confused you or put you off?",
    "CONTROL: Where did he go to school?",
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


def ask_claude(png: Path, system: str, model: str) -> dict:
    """One fresh reader: a clean temp dir holding only the screenshot, --safe-mode, Read only."""
    prompt = ("Use the Read tool to open the image file 'screen.png' in the current directory. It is a "
              "screenshot of the first screen of a website. Then answer each question in one or two plain "
              "sentences, as JSON: {\"answers\": [\"...\", ...]} in the same order.\n\n"
              + "\n".join(f"{i + 1}. {q}" for i, q in enumerate(QUESTIONS)))
    with tempfile.TemporaryDirectory(prefix="reader-") as wd:
        shutil.copy(png, Path(wd) / "screen.png")
        r = subprocess.run(["claude", "-p", "--safe-mode", "--model", model, "--system-prompt", system,
                            "--allowedTools", "Read", "--output-format", "json", prompt],
                           cwd=wd, capture_output=True, text=True, timeout=300)
    try:
        text = json.loads(r.stdout).get("result", "")
        s, e = text.find("{"), text.rfind("}")
        answers = json.loads(text[s:e + 1]).get("answers")
    except (ValueError, AttributeError):
        return {"error": (r.stdout + r.stderr)[-600:]}
    return {"answers": answers} if isinstance(answers, list) else {"error": text[-600:]}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("round")
    ap.add_argument("--url-base", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--page", action="append", default=[])
    ap.add_argument("--runner", choices=("claude", "injected"), default="claude")
    ap.add_argument("--answers", help="for --runner injected: a JSON list of answers")
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
    persona_path = cfg_path.parent / pf
    try:
        persona = persona_path.read_bytes()
    except OSError as e:
        return refuse(f"persona file {persona_path}: {e}")
    viewports = readers.get("viewports", DEFAULT_VIEWPORTS)
    n = readers.get("n", DEFAULT_N)
    model = readers.get("model", DEFAULT_MODEL)
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
        answer = lambda png: ask_claude(png, persona.decode("utf-8", "replace") + "\n\n" + FRAME, model)
        model_used = model
    else:
        try:
            canned = json.loads(Path(a.answers or "").read_text())
        except (OSError, ValueError) as e:
            return refuse(f"--runner injected needs --answers FILE (a JSON list): {e}")
        if not isinstance(canned, list):
            return refuse("--answers must hold a JSON list of answers")
        answer = lambda png: {"answers": canned}
        model_used = "injected"

    html = sorted(p.name for p in rd.iterdir() if p.is_file() and p.suffix.lower() in HTML_SUFFIXES)
    names = a.page or html
    bad = [x for x in names if Path(x).suffix.lower() not in HTML_SUFFIXES or not (rd / x).is_file()]
    if not names or bad:
        return refuse(f"no readable HTML page to show readers{': ' + str(bad) if bad else ''}")

    prov = {"runner": a.runner, "model": model_used, "persona_file": pf,
            "persona_sha256": sha(persona), "questions_sha256": sha(json.dumps(QUESTIONS).encode()),
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
                    res = answer(png)
                    if "answers" not in res:
                        return refuse(f"reader {i + 1} on {name} {vp}: {res.get('error', 'no answers')}")
                    ans = [str(x) for x in res["answers"]]
                    control = ans[-1] if ans else ""
                    rows.append({"page": name, "viewport": vp, "instance": i + 1,
                                 "html_sha256": html_sha, "png_sha256": png_sha, "answers": ans,
                                 "contaminated": "unknown" not in control.lower(),
                                 "_provenance": prov})
    out = rd / "gate" / "reader-runs.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r) + "\n" for r in rows))
    print(f"wrote {len(rows)} reader row(s) to {out} (runner {a.runner})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
