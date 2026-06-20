#!/usr/bin/env python3
"""
dogfood_gate.py  (pairs with the eyeball design/UX gate + .claude/rules/dogfood-gate.md)

Deterministic FAST layer of the "never ship a website without running it through
our own tool" gate. PostToolUse on Write|Edit: when a PUBLIC-FACING .html page is
written, statically scan it for the AI-slop + UX tells and BLOCK (exit 2) so the
page cannot ship unseen. The authoritative deep check is the rendered read:
`node ~/projects/eyeball/web/scan.mjs <file>`.

FINGERPRINT-DRIVEN (2026-06-20). The tell lists (fonts, palette hues, copy
phrases, badge text) are NOT hardcoded here anymore — they are read from the baked
default-fingerprint.json that the eyeball harvest produces. A hardcoded blocklist
is always one model-generation behind: a warm-cream / serif / amber page sailed
past the old gate that only knew the garish violet/Inter/emoji tells. The RULE
("never reach for the current default") is this code; the LIST rotates in the
fingerprint. The fingerprint is DATA ONLY (strings, numbers, HSL ranges); nothing
read from it is ever exec'd.

Fingerprint path: $EYEBALL_FINGERPRINT, else ~/projects/eyeball/web/fingerprint/
default-fingerprint.json, else a small embedded fallback so the gate never breaks.

Scope: only public-facing landing/marketing HTML. Internal HTML (dashboards,
schedules, logs, templates, tests, system output, node_modules) is skipped fast.
Bypass one file with the marker:  <!-- eyeball-gate-skip -->

Exit codes: 2 = block (findings to stderr), 0 = pass / out-of-scope.
"""
import json, os, re, sys

DEFAULT_FP_PATH = os.path.expanduser("~/projects/eyeball/web/fingerprint/default-fingerprint.json")

# last-known-good net so the gate works even with no eyeball repo on disk. NOT the
# source of truth (the JSON is) — just the high-pull tells incl. the warm-cream fix.
EMBEDDED_FALLBACK = {
    "active_threshold": 0.25,
    "categories": {
        "fonts": {"kind": "font_family", "tokens": [
            {"value": "inter", "label": "Inter", "pull_strength": 0.97},
            {"value": "geist", "label": "Geist", "pull_strength": 0.74},
            {"value": "instrument serif", "label": "Instrument Serif", "pull_strength": 0.58},
            {"value": "space grotesk", "label": "Space Grotesk", "pull_strength": 0.52},
            {"value": "plus jakarta", "label": "Plus Jakarta Sans", "pull_strength": 0.5},
            {"value": "poppins", "label": "Poppins", "pull_strength": 0.5},
            {"value": "manrope", "label": "Manrope", "pull_strength": 0.48},
            {"value": "dm sans", "label": "DM Sans", "pull_strength": 0.46},
        ]},
        "palette": {"kind": "palette", "tokens": [
            {"value": "violet-accent", "label": "the violet/indigo 'AI' accent", "pull_strength": 0.78,
             "range": {"h": [248, 280], "s": [0.4, 1], "l": [0.4, 0.78]},
             "fix": "Pick an accent that means something for your brand, not the default model violet."},
            {"value": "warm-cream-bg", "label": "warm cream / paper background", "pull_strength": 0.66,
             "range": {"h": [20, 60], "s": [0.12, 0.6], "l": [0.88, 0.985]},
             "fix": "Warm-cream paper is the current 'tasteful' default. A real surface choice beats the reflex."},
            {"value": "amber-accent", "label": "amber/orange accent", "pull_strength": 0.62,
             "range": {"h": [25, 50], "s": [0.55, 1], "l": [0.45, 0.68]},
             "fix": "The warm amber accent is the new default. Make sure it is a choice, not a reflex."},
            {"value": "electric-blue-accent", "label": "electric blue accent", "pull_strength": 0.5,
             "range": {"h": [205, 248], "s": [0.5, 1], "l": [0.45, 0.7]}},
        ]},
        "gradients": {"kind": "gradient", "tokens": [
            {"value": "text-gradient", "label": "gradient text on the headline", "pull_strength": 0.84,
             "fix": "Make the headline one solid, confident color."},
        ]},
        "iconography": {"kind": "emoji_icon", "tokens": [
            {"value": "emoji-as-icon", "label": "emoji as icons", "pull_strength": 0.6}]},
        "copy": {"kind": "generic_copy", "tokens": [
            {"value": v, "label": '"%s"' % v, "pull_strength": 0.6} for v in
            ["seamlessly", "leverage", "cutting-edge", "unlock the", "revolutionize", "empower",
             "supercharge", "next-gen", "elevate your", "to the next level", "effortless", "transform your"]]},
        "badge": {"kind": "badge", "tokens": [
            {"value": "powered by ai", "label": "a 'Powered by AI' badge", "pull_strength": 0.7},
            {"value": "ai-powered", "label": "an 'AI-powered' badge", "pull_strength": 0.65}]},
    },
}


def load_fingerprint():
    path = os.environ.get("EYEBALL_FINGERPRINT") or DEFAULT_FP_PATH
    try:
        with open(path, "r", encoding="utf-8") as f:
            fp = json.load(f)
        if fp and isinstance(fp.get("categories"), dict):
            return fp
    except Exception:
        pass
    return EMBEDDED_FALLBACK


# web-safe/system/generic fonts: a deliberate human choice, never the AI "designer
# font" tell. Mirrors lib/fingerprint.mjs SYSTEM_FONTS.
SYSTEM_FONTS = frozenset((
    "system-ui", "ui-sans-serif", "ui-serif", "ui-monospace", "ui-rounded",
    "-apple-system", "blinkmacsystemfont", "segoe ui", "helvetica neue", "helvetica",
    "arial", "georgia", "times new roman", "times", "verdana", "tahoma", "trebuchet ms",
    "courier new", "courier", "monospace", "sans-serif", "serif", "cursive", "fantasy",
))


def active_tokens(fp, kind):
    thr = fp.get("active_threshold", 0.25)
    for cat in (fp.get("categories") or {}).values():
        if cat.get("kind") == kind:
            return [t for t in cat.get("tokens", []) if isinstance(t.get("pull_strength"), (int, float)) and t["pull_strength"] >= thr]
    return []


# ── color parsing -> HSL, mirrors lib/buckets.mjs (kept in lockstep by shared fp ranges)
def _hsl(r, g, b):
    r, g, b = r / 255.0, g / 255.0, b / 255.0
    mx, mn = max(r, g, b), min(r, g, b)
    l = (mx + mn) / 2.0
    d = mx - mn
    if d == 0:
        return (0.0, 0.0, l)
    s = d / (2 - mx - mn) if l > 0.5 else d / (mx + mn)
    if mx == r:
        h = ((g - b) / d) % 6
    elif mx == g:
        h = (b - r) / d + 2
    else:
        h = (r - g) / d + 4
    h *= 60
    if h < 0:
        h += 360
    return (h, s, l)


def _u8(x):
    # clamp a CSS numeric to a 0..255 int. A crafted/accidental overflow value (e.g.
    # rgb(999...400 digits...)) makes float()->inf and int(inf) raise OverflowError; an
    # unguarded crash here exits 1, which the PostToolUse contract treats as a hook
    # error -> the page ships UNGATED (fail-open). So coerce defensively, never raise.
    try:
        v = float(x)
    except Exception:
        return 0
    if v != v or v in (float("inf"), float("-inf")):   # NaN / inf
        return 0
    return min(255, max(0, int(v)))


def parse_color(tok):
    tok = tok.strip().lower()
    m = re.match(r"^#([0-9a-f]{3})$", tok)
    if m:
        a, b, c = m.group(1)
        return (int(a * 2, 16), int(b * 2, 16), int(c * 2, 16))
    m = re.match(r"^#([0-9a-f]{6})$", tok)
    if m:
        h = m.group(1)
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    m = re.match(r"^rgba?\(\s*([\d.]+)[ ,]+([\d.]+)[ ,]+([\d.]+)", tok)
    if m:
        return (_u8(m.group(1)), _u8(m.group(2)), _u8(m.group(3)))
    m = re.match(r"^hsla?\(\s*([\d.]+)[ ,]+([\d.]+)%[ ,]+([\d.]+)%", tok)
    if m:
        try:
            h, s, l = float(m.group(1)), float(m.group(2)) / 100, float(m.group(3)) / 100
        except Exception:
            return None
        if any(v != v or v in (float("inf"), float("-inf")) for v in (h, s, l)):
            return None
        return _hsl_to_rgb(h, min(1.0, max(0.0, s)), min(1.0, max(0.0, l)))
    return None


def _hsl_to_rgb(h, s, l):
    h = ((h % 360) + 360) % 360 / 360.0
    q = l * (1 + s) if l < 0.5 else l + s - l * s
    p = 2 * l - q

    def t(x):
        if x < 0:
            x += 1
        if x > 1:
            x -= 1
        if x < 1 / 6:
            return p + (q - p) * 6 * x
        if x < 1 / 2:
            return q
        if x < 2 / 3:
            return p + (q - p) * (2 / 3 - x) * 6
        return p
    return (round(t(h + 1 / 3) * 255), round(t(h) * 255), round(t(h - 1 / 3) * 255))


def _in_range(hsl, rng):
    h, s, l = hsl
    hr = rng.get("h")
    if hr:
        lo, hi = hr
        h_ok = (lo <= h <= hi) if lo <= hi else (h >= lo or h <= hi)
    else:
        h_ok = True
    sr, lr = rng.get("s"), rng.get("l")
    s_ok = (not sr) or (sr[0] <= s <= sr[1])
    l_ok = (not lr) or (lr[0] <= l <= lr[1])
    return h_ok and s_ok and l_ok


def scan_html(content, fp):
    """Return a list of {label, fix} findings. Public so it is unit-testable."""
    # Strip HTML comments first: a page that NAMES a tell in a comment (e.g.
    # "no Powered by AI here") must not be flagged for it. The rendered detector
    # reads innerText, so the static gate must mirror that and ignore comments.
    c = re.sub(r"<!--.*?-->", "", content, flags=re.S)
    cl = c.lower()                                 # CSS-bearing: font / gradient / palette
    # prose-only view (drop <style>/<script>) so CSS class names + JS strings can't
    # masquerade as copy/badge text.
    text = re.sub(r"<(style|script)[^>]*>.*?</\1>", " ", cl, flags=re.S)
    findings = []
    EMOJI = "[←-⇿⌀-➿⬀-⯿✨⚡\U0001f000-\U0001faff]"

    # 1) converged / default font as a primary face (fingerprint-driven)
    decls = re.findall(r"font-family\s*:\s*([^;{}]+)", cl)
    decl_blob = " | ".join(decls)
    for t in active_tokens(fp, "font_family"):
        v = t["value"]
        if v in SYSTEM_FONTS:
            continue
        if v in decl_blob:
            findings.append({"label": "Converged font: %s" % t.get("label", v),
                             "fix": t.get("fix", "Use a face with a point of view, not the default builder font.")})
            break

    # 2) gradient text on a heading
    if "linear-gradient" in cl and re.search(r"(-webkit-)?background-clip\s*:\s*text", cl):
        gt = active_tokens(fp, "gradient")
        fix = next((t.get("fix") for t in gt if t["value"] == "text-gradient" and t.get("fix")), "Make the headline one solid color.")
        findings.append({"label": "Gradient text on a heading — the #1 'AI made this' tell.", "fix": fix})

    # 3) palette: any current-default hue family present in the CSS (the warm-cream fix)
    palette = active_tokens(fp, "palette")
    if palette:
        colors = re.findall(r"#[0-9a-f]{3,6}\b|rgba?\([^)]*\)|hsla?\([^)]*\)", cl)
        seen = set()
        for col in colors:
            rgb = parse_color(col)
            if not rgb:
                continue
            hsl = _hsl(*rgb)
            if hsl[1] <= 0.08:        # neutral grayscale is never a tell
                continue
            for t in palette:
                rng = t.get("range")
                if rng and t["value"] not in seen and _in_range(hsl, rng):
                    seen.add(t["value"])
                    findings.append({"label": "Default palette: %s" % t.get("label", t["value"]),
                                     "fix": t.get("fix", "Pick a color with intent, not the current default hue.")})

    # 4) emoji used as icons inside headings/buttons
    if active_tokens(fp, "emoji_icon") and re.search(r"<(h[1-3]|button)[^>]*>[^<]*" + EMOJI, c):
        findings.append({"label": "Emoji as icons in a heading/button.", "fix": "Use a real icon set or custom marks."})

    # 5) stock-prompt copy (fingerprint copy list) — prose view only
    copy_hits = [t for t in active_tokens(fp, "generic_copy") if t["value"] in text]
    if copy_hits:
        findings.append({"label": "Stock-prompt copy (e.g. %s)." % copy_hits[0].get("label", copy_hits[0]["value"]),
                         "fix": "Say the specific thing your product does."})

    # 6) "powered by AI" badge text — prose view only
    badge_hits = [t for t in active_tokens(fp, "badge") if t["value"] in text]
    if badge_hits:
        findings.append({"label": "%s." % badge_hits[0].get("label", badge_hits[0]["value"]),
                         "fix": "Drop it. Let the product speak."})

    # 7) UX: no interactive primary action anywhere
    if "<form" not in cl and "<input" not in cl and "<button" not in cl:
        findings.append({"label": "No form/input/button — no clear action for a visitor to take.",
                         "fix": "Put the primary action in the first screen."})

    return findings


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    ti = data.get("tool_input", {}) or {}
    path = ti.get("file_path") or ti.get("path") or ""
    if not path or not path.lower().endswith(".html"):
        sys.exit(0)

    low = path.lower()
    SKIP = ("/q-system/", "/node_modules/", "/templates/", "/template/", "/test", "/tests/",
            "fixture", "dashboard", "schedule", "morning", "-log", "/logs/", "/output/",
            "/build/", "/dist/", "debug", "/.git/", "storybook",
            "/fingerprint/", "_harvest")   # internal harvest tooling, not a shipped page
    if any(s in low for s in SKIP):
        sys.exit(0)

    content = ""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except Exception:
        content = ti.get("content") or ti.get("new_string") or ""
    if not content:
        sys.exit(0)

    cl = content.lower()
    if "<html" not in cl and "<body" not in cl:
        sys.exit(0)
    if "eyeball-gate-skip" in cl:
        sys.exit(0)

    fp = load_fingerprint()
    # FAIL CLOSED: this gate's whole job is preventing a bad page from shipping. If the
    # scan itself errors, block (exit 2) and point to the manual render check, rather
    # than crashing to exit 1 (which the hook contract treats as a no-op = page ships).
    try:
        findings = scan_html(content, fp)
    except Exception as e:
        sys.stderr.write(
            "eyeball gate errored on %s (%s). Failing CLOSED — run the render check manually:\n"
            "  node ~/projects/eyeball/web/scan.mjs %s\n" % (path, e, path))
        sys.exit(2)

    if findings:
        msg = ["eyeball gate BLOCKED a public page: " + path,
               "Tells found (static check vs the current AI-default fingerprint):"]
        msg += ["  - %s  ->  %s" % (f["label"], f["fix"]) for f in findings]
        msg += ["",
                "Run the authoritative render+UX read before shipping:",
                "  node ~/projects/eyeball/web/scan.mjs " + path,
                "If the slop is intentional (a parody/demo), add  <!-- eyeball-gate-skip -->  to the file."]
        sys.stderr.write("\n".join(msg) + "\n")
        sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()
