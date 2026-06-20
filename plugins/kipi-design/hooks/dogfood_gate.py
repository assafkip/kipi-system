#!/usr/bin/env python3
"""
dogfood_gate.py  (pairs with the eyeball design/UX gate + .claude/rules/dogfood-gate.md)

Deterministic FAST layer of the "never ship a website without running it through
our own tool" gate. PostToolUse on Write|Edit: when a PUBLIC-FACING .html page is
written, statically scan it for the obvious AI-slop + UX tells and BLOCK (exit 2)
so the page cannot ship unseen. The authoritative deep check is the rendered
read: `node ~/projects/eyeball/web/scan.mjs <file>` (render + design + UX). This
hook is the instant tripwire; the rule requires the full check before deploy.

Scope: only public-facing landing/marketing HTML. Internal HTML (dashboards,
schedules, logs, templates, tests, system output, node_modules) is skipped fast
(token discipline). Bypass one file with the marker:  <!-- eyeball-gate-skip -->

Exit codes: 2 = block (findings to stderr), 0 = pass / out-of-scope.
"""
import json, os, re, sys

def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    ti = data.get("tool_input", {}) or {}
    path = ti.get("file_path") or ti.get("path") or ""
    if not path or not path.lower().endswith(".html"):
        sys.exit(0)  # not HTML -> fast exit

    low = path.lower()
    # internal / non-public HTML -> skip (mirrors design-auto-invoke gate)
    SKIP = ("/q-system/", "/node_modules/", "/templates/", "/template/", "/test", "/tests/",
            "fixture", "dashboard", "schedule", "morning", "-log", "/logs/", "/output/",
            "/build/", "/dist/", "debug", "/.git/", "storybook")
    if any(s in low for s in SKIP):
        sys.exit(0)

    # read the written file (PostToolUse -> already on disk); fall back to tool_input.content
    content = ""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except Exception:
        content = ti.get("content") or ti.get("new_string") or ""
    if not content:
        sys.exit(0)

    # only gate real pages (must have an <html or <body>)
    cl = content.lower()
    if "<html" not in cl and "<body" not in cl:
        sys.exit(0)
    if "eyeball-gate-skip" in cl:
        sys.exit(0)  # explicit, intentional bypass (e.g. a parody page)

    findings = []
    EMOJI = "[←-⇿⌀-➿⬀-⯿✨⚡\U0001f000-\U0001faff]"

    # 1) converged / default font as a primary face
    if re.search(r"font-family\s*:\s*['\"]?\s*(inter|roboto|space grotesk|geist|plus jakarta|manrope|dm sans|poppins)\b", cl):
        findings.append("Converged font (Inter/Roboto/Space Grotesk/etc.) — the default of every AI builder. Use a face with a point of view.")
    # 2) the violet/blue gradient text
    if "linear-gradient" in cl and re.search(r"(-webkit-)?background-clip\s*:\s*text", cl):
        findings.append("Gradient text on a heading — the #1 'AI made this' tell. Make the headline one solid color.")
    # 3) emoji used as icons inside headings/buttons
    if re.search(r"<(h[1-3]|button)[^>]*>[^<]*" + EMOJI, content):
        findings.append("Emoji as icons in a heading/button. Use a real icon set or custom marks.")
    # 4) stock-prompt copy
    SLOP = ["seamlessly leverage", "unlock the power", "unlock the future", "revolutionize your",
            "cutting-edge", "powered by ai", "ai-powered", "supercharge your", "take your .* to the next level"]
    hit = [p for p in SLOP if re.search(p, cl)]
    if len(hit) >= 1:
        findings.append("Stock-prompt copy (e.g. '%s'). Say the specific thing your product does." % hit[0])
    # 5) UX: no interactive primary action anywhere
    if "<form" not in cl and "<input" not in cl and "<button" not in cl:
        findings.append("No form/input/button — no clear action for a visitor to take. Put the primary action in the first screen.")

    if findings:
        msg = ["eyeball gate BLOCKED a public page: " + path,
               "Tells found (static check):"]
        msg += ["  - " + f for f in findings]
        msg += ["",
                "Run the authoritative render+UX read before shipping:",
                "  node ~/projects/eyeball/web/scan.mjs " + path,
                "If the slop is intentional (a parody/demo), add  <!-- eyeball-gate-skip -->  to the file."]
        sys.stderr.write("\n".join(msg) + "\n")
        sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()
