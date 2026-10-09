#!/usr/bin/env python3
"""Break every exemplar down into what it is MADE of: its technologies, its design path
(the sections in order, top to bottom), its techniques, its trust signals and its place in
a design taxonomy. Writes ANALYSIS.json (the record the gate reads) and ANALYSIS.md (the
human view), both regenerated, never hand-edited.

WHY (founder, 2026-10-09): "have a full analysis and breakdown of the techniques, design
taxonomy, design path and actual technologies used on the exemplar sites and bake that into
design-chain itself". design-exemplar-capture.py measures only the FIRST SCREEN, and only
its surface (type sizes, colours, word counts). A designer's read of the same set found
what that misses: the whole-page story, the trust signals an expert practice lives on, and
the stack and techniques that produce the look. Those numbers turned six software sites
into a rule set for a one-person practice, and the founder's verdict was "not sold".

What it records per site, from a real browser at 1440x900 scrolled to the bottom:
  technologies  site builder or framework, CSS approach, animation libraries, analytics and
                marketing tags, font hosting, hosting/CDN (from HTML, globals and headers)
  page_path     every top-level section in order, each classified into SECTION_KINDS
  techniques    sticky nav, scroll reveal, video, carousel, marquee, smooth scroll, grids,
                dark/light alternation, content width, page length
  trust_signals which of TRUST_KINDS the page shows, and in which section
  taxonomy      role (peer or craft, from the roster), hero archetype, density, colour mode

Classification is done HERE in Python on raw features the probe returns, so it is testable
without a browser (test/test_dc_exemplar_analysis.py). The probe only measures.

Usage:
  design-exemplar-analysis.py <references-dir> [--only HOST]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
ANALYSIS_JSON = "ANALYSIS.json"
ANALYSIS_MD = "ANALYSIS.md"
ROLES = ("peer", "craft")

# The closed vocabulary a direction's "Page path:" must be written in (design-reference-check.py).
SECTION_KINDS = (
    "nav", "hero", "logo-wall", "stats", "testimonials", "case-studies", "services",
    "process", "about-person", "team", "writing", "pricing", "faq", "cta-band",
    "contact-form", "footer", "content",
)
TRUST_KINDS = (
    "face-photo", "client-logos", "testimonials", "numbers", "credentials", "writing",
    "case-studies", "press-awards", "certifications",
)

# ---------------------------------------------------------------- technologies

# (category, name, regex over the joined HTML signals) -- order is irrelevant, all matches kept
TECH_SIGNATURES = [
    ("builder", "Webflow", r"data-wf-(page|site)|webflow\.(com|js)|wf-cdn|website-files\.com"),
    ("builder", "Framer", r"framerusercontent\.com|data-framer-|__framer"),
    ("builder", "Squarespace", r"static1\.squarespace\.com|squarespace-cdn|Squarespace"),
    ("builder", "Wix", r"static\.wixstatic\.com|wix-code|_wixCIDX"),
    ("builder", "WordPress", r"wp-content/|wp-includes/|wp-json"),
    ("builder", "Ghost", r"ghost-(portal|sdk)|content=\"Ghost"),
    ("builder", "HubSpot CMS", r"hs-sites\.com|hubspotusercontent|hs-scripts"),
    ("builder", "Shopify", r"cdn\.shopify\.com|Shopify\.theme"),
    ("builder", "Substack", r"substackcdn\.com"),
    ("framework", "Next.js", r"__NEXT_DATA__|/_next/static|next-route-announcer"),
    ("framework", "Nuxt", r"__NUXT__|/_nuxt/"),
    ("framework", "Gatsby", r"___gatsby|gatsby-"),
    ("framework", "Astro", r"astro-island|data-astro-|/_astro/"),
    ("framework", "SvelteKit", r"__sveltekit|svelte-[a-z0-9]{6}"),
    ("framework", "Hugo", r"content=\"Hugo"),
    ("framework", "Jekyll", r"content=\"Jekyll"),
    ("framework", "Remix", r"__remixContext"),
    ("framework", "React", r"data-reactroot|__REACT|react-dom"),
    ("framework", "Vue", r"__vue_app__|data-v-[a-f0-9]{8}"),
    ("css", "Tailwind", r"TAILWIND_HINT"),
    ("css", "Bootstrap", r"bootstrap(\.min)?\.(css|js)"),
    ("animation", "GSAP", r"gsap|ScrollTrigger|greensock"),
    ("animation", "Lottie", r"lottie|bodymovin"),
    ("animation", "Framer Motion", r"framer-motion|data-projection-id"),
    ("animation", "Three.js", r"three(\.module)?\.(min\.)?js|THREE\."),
    ("animation", "Lenis", r"lenis"),
    ("animation", "Locomotive Scroll", r"locomotive-scroll|data-scroll-container"),
    ("animation", "AOS", r"data-aos|aos\.(css|js)"),
    ("animation", "Rive", r"rive\.(app|wasm)|@rive-app"),
    ("analytics", "Google Analytics", r"googletagmanager\.com/gtag|google-analytics\.com|gtag\("),
    ("analytics", "Google Tag Manager", r"googletagmanager\.com/gtm"),
    ("analytics", "Segment", r"cdn\.segment\.com|analytics\.js"),
    ("analytics", "HubSpot", r"js\.hs-scripts\.com|js\.hsforms|hs-analytics"),
    ("analytics", "Plausible", r"plausible\.io"),
    ("analytics", "Fathom", r"usefathom\.com"),
    ("analytics", "Hotjar", r"hotjar"),
    ("analytics", "PostHog", r"posthog"),
    ("analytics", "Vercel Analytics", r"/_vercel/insights"),
    ("analytics", "LinkedIn Insight", r"snap\.licdn\.com"),
    ("analytics", "Meta Pixel", r"connect\.facebook\.net"),
    ("marketing", "Calendly embed", r"assets\.calendly\.com|calendly\.com/"),
    ("marketing", "Intercom", r"widget\.intercom\.io|intercomSettings"),
    ("marketing", "Drift", r"js\.driftt\.com"),
    ("marketing", "Mailchimp", r"list-manage\.com|mailchimp"),
    ("marketing", "ConvertKit", r"convertkit|ck\.page"),
    ("marketing", "Typeform", r"typeform\.com"),
    ("fonts", "Google Fonts", r"fonts\.googleapis\.com|fonts\.gstatic\.com"),
    ("fonts", "Adobe Fonts", r"use\.typekit\.net|p\.typekit\.net"),
    ("fonts", "Fontshare", r"api\.fontshare\.com"),
]
HEADER_SIGNATURES = [
    ("hosting", "Vercel", lambda h: "x-vercel-id" in h or h.get("server") == "vercel"),
    ("hosting", "Netlify", lambda h: "x-nf-request-id" in h or h.get("server", "").startswith("netlify")),
    ("hosting", "Cloudflare", lambda h: "cf-ray" in h),
    ("hosting", "Fastly", lambda h: "fastly" in h.get("via", "") + h.get("x-served-by", "")),
    ("hosting", "AWS CloudFront", lambda h: "x-amz-cf-id" in h),
    ("hosting", "GitHub Pages", lambda h: "x-github-request-id" in h),
    ("hosting", "nginx", lambda h: h.get("server", "").startswith("nginx")),
]
TAILWIND_CLASS = re.compile(r"(?:^|\s)(?:[a-z]+:)*(?:px|py|mt|mb|gap|text|bg|grid-cols|max-w|rounded)-[a-z0-9\[\]./-]+")


def detect_technologies(signals: str, classes: list[str], headers: dict, self_fonts: list[str]) -> dict:
    """Map raw page signals to {category: [names]}. Pure; no browser."""
    found: dict[str, list[str]] = {}
    tw_hits = sum(1 for c in classes if TAILWIND_CLASS.search(c))
    joined = signals + (" TAILWIND_HINT" if classes and tw_hits / len(classes) >= 0.25 else "")
    for cat, name, pat in TECH_SIGNATURES:
        if re.search(pat, joined, re.I if cat != "css" else 0):
            found.setdefault(cat, []).append(name)
    low = {k.lower(): str(v).lower() for k, v in (headers or {}).items()}
    for cat, name, test in HEADER_SIGNATURES:
        if test(low):
            found.setdefault(cat, []).append(name)
    if self_fonts:
        found.setdefault("fonts", []).append("self-hosted")
    if "React" in found.get("framework", []) and any(
            f in found.get("framework", []) for f in ("Next.js", "Gatsby", "Remix")):
        found["framework"].remove("React")      # a React meta-framework already says React
    return found


# ---------------------------------------------------------------- sections

def _kw(f: dict, *words: str) -> bool:
    hay = (f.get("hint", "") + " " + f.get("text", "")[:400]).lower()
    return any(w in hay for w in words)


def classify_section(f: dict, index: int, total: int) -> str:
    """One raw section feature dict -> one SECTION_KINDS value. Pure; ordered by specificity."""
    tag, hint = f.get("tag", ""), f.get("hint", "").lower()
    if tag == "nav" or (index == 0 and f.get("height", 0) < 140 and f.get("links", 0) >= 3):
        return "nav"
    if tag == "footer" or index == total - 1 or ("footer" in hint and f.get("links", 0) >= 8):
        return "footer"
    if f.get("first_content") and f.get("top", 9999) < 700:
        return "hero"                       # the first block below the nav that starts in screen one
    if f.get("forms", 0) and f.get("inputs", 0) >= 2:
        return "contact-form"
    if f.get("words", 0) < 120 and (f.get("logo_row", 0) >= 4 or _kw(
            f, "trusted by", "our clients", "clients include", "logo")):
        return "logo-wall"
    if f.get("blockquotes", 0) or _kw(f, "testimonial", "what clients say", "what our clients"):
        return "testimonials"
    if _kw(f, "pricing", "per month", "/mo", "plans"):
        return "pricing"
    if _kw(f, "faq", "frequently asked", "questions"):
        return "faq"
    if _kw(f, "case stud", "our work", "selected work", "client work", "results"):
        return "case-studies"
    if f.get("big_numbers", 0) >= 2:
        return "stats"
    if _kw(f, "how we work", "how it works", "our process", "step 1", "approach"):
        return "process"
    if _kw(f, "blog", "articles", "writing", "newsletter", "latest", "news", "insights", "research"):
        return "writing"
    if _kw(f, "our team", "the team", "leadership"):
        return "team"
    if f.get("portrait", 0) or _kw(f, "about me", "i'm ", "i am ", "hi, i", "about the founder"):
        return "about-person"
    if _kw(f, "services", "what we do", "capabilities", "offerings", "expertise"):
        return "services"
    if f.get("height", 0) < 420 and f.get("buttons", 0) >= 1 and f.get("words", 0) < 60:
        return "cta-band"
    return "content"


def trust_signals(sections: list[dict], page_text: str) -> dict:
    """Which TRUST_KINDS the page shows -> {kind: [section indexes]} (-1 = page-level text)."""
    out: dict[str, list[int]] = {}
    add = lambda k, i: out.setdefault(k, []).append(i) if i not in out.get(k, []) else None
    kind_map = {"logo-wall": "client-logos", "testimonials": "testimonials",
                "case-studies": "case-studies", "writing": "writing", "stats": "numbers"}
    for i, s in enumerate(sections):
        if s["kind"] in kind_map:
            add(kind_map[s["kind"]], i)
        if s.get("portrait"):
            add("face-photo", i)
        if s.get("big_numbers", 0) >= 2:
            add("numbers", i)
    t = page_text.lower()
    if re.search(r"\b(former(ly)?|ex-|previously at|years (of|at|in)|phd|led .{0,30} at)\b", t):
        add("credentials", -1)
    if re.search(r"\b(as seen in|featured in|award|speaker at|keynote|forbes|wired|techcrunch)\b", t):
        add("press-awards", -1)
    if re.search(r"\b(soc ?2|iso ?27001|cissp|oscp|certified|crest)\b", t):
        add("certifications", -1)
    return out


# ---------------------------------------------------------------- taxonomy

def _luminance(rgb: str) -> float | None:
    m = re.findall(r"[\d.]+", rgb or "")
    if len(m) < 3 or (len(m) == 4 and float(m[3]) == 0):
        return None
    r, g, b = (float(x) / 255 for x in m[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def hero_archetype(hero: dict | None) -> str:
    if not hero:
        return "no-hero"
    visual = hero.get("largest_visual_pct") or 0     # the key is present and None when unmeasured
    if hero.get("video") or visual >= 60:
        return "full-bleed-media"
    if visual >= 20:
        return "text-plus-visual"
    return "text-only"


def taxonomy(role: str, sections: list[dict], page: dict) -> dict:
    hero = next((s for s in sections if s["kind"] == "hero"), None)
    lum = _luminance((hero or {}).get("bg", "")) if hero else None
    lum = lum if lum is not None else _luminance(page.get("body_bg", ""))
    content = [s for s in sections if s["kind"] not in ("nav", "footer")]
    avg_h = round(sum(s.get("height", 0) for s in content) / len(content)) if content else 0
    return {
        "role": role,
        "hero_archetype": hero_archetype(hero),
        "colour_mode": "dark" if (lum is not None and lum < 0.35) else "light",
        "sections": len(content),
        "density": "sparse" if avg_h >= 700 else ("dense" if avg_h < 380 else "medium"),
        "page_screens": round(page.get("height", 0) / 900, 1),
        "first_screen_ctas": (hero or {}).get("buttons", 0),
        "type_families": page.get("families", [])[:3],
    }


def techniques(page: dict, sections: list[dict]) -> dict:
    bgs = [(_luminance(s.get("bg", "")) or 1.0) < 0.35 for s in sections]
    flips = sum(1 for a, b in zip(bgs, bgs[1:]) if a != b)
    return {
        "sticky_nav": bool(page.get("sticky_nav")),
        "scroll_reveal": page.get("reveal_hints", 0) > 0,
        "video": page.get("videos", 0),
        "carousel": bool(page.get("carousel")),
        "marquee": bool(page.get("marquee")),
        "css_grid_blocks": page.get("grids", 0),
        "animated_elements": page.get("animated", 0),
        "dark_light_alternations": flips,
        "content_width_px": page.get("content_width", 0),
        "page_height_px": page.get("height", 0),
        "custom_cursor": bool(page.get("custom_cursor")),
    }


# ---------------------------------------------------------------- browser probe

PROBE = r"""
() => {
  const vw = innerWidth;
  const deep = (root, out) => { for (const e of root.querySelectorAll('*')) { out.push(e);
      if (e.shadowRoot) deep(e.shadowRoot, out); } return out; };
  const all = deep(document.body, []);
  const visible = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const text = e => (e.innerText || '').replace(/\s+/g, ' ').trim();
  // the section list: descend from main/body while one child holds most of the height
  let host = document.querySelector('main') || document.body;
  for (let i = 0; i < 6; i++) {
    const kids = [...host.children].filter(visible);
    const tall = kids.filter(k => k.getBoundingClientRect().height > 80);
    if (tall.length === 1) host = tall[0]; else break;
  }
  let blocks = [...host.children].filter(e => visible(e) && e.getBoundingClientRect().height > 60);
  // a block taller than two screens is usually a wrapper around several sections: split it once
  // through single-child wrappers too, up to eight levels (nisos nests its sections six wrappers deep)
  const split = (b, depth) => { if (depth > 8 || b.getBoundingClientRect().height <= 1800) return [b];
    const kids = [...b.children].filter(k => visible(k) && k.getBoundingClientRect().height > 120);
    if (kids.length === 1) return split(kids[0], depth + 1);
    return kids.length >= 2 ? kids.flatMap(k => split(k, depth + 1)) : [b]; };
  blocks = blocks.flatMap(b => split(b, 0));
  if (host !== document.body) {
    const hdr = document.querySelector('header, nav'); const ftr = document.querySelector('footer');
    if (hdr && !blocks.some(b => b.contains(hdr) || hdr.contains(b))) blocks.unshift(hdr);
    if (ftr && !blocks.some(b => b.contains(ftr) || ftr.contains(b))) blocks.push(ftr);
  }
  const sy = scrollY;
  const feat = e => {
    const r = e.getBoundingClientRect(), c = getComputedStyle(e), t = text(e);
    const imgs = [...e.querySelectorAll('img')].filter(visible);
    const rowGroups = {};
    for (const im of imgs) { const ir = im.getBoundingClientRect();
      if (ir.height > 10 && ir.height < 90) { const k = Math.round((ir.top + sy) / 20);
        rowGroups[k] = (rowGroups[k] || 0) + 1; } }
    const svgsSmall = [...e.querySelectorAll('svg')].filter(s => { const q = s.getBoundingClientRect();
      return q.height > 10 && q.height < 70 && q.width > 40; }).length;
    const portrait = imgs.some(im => /(headshot|portrait|founder|team|avatar|profile|me\.|about)/i
      .test((im.alt || '') + ' ' + (im.currentSrc || im.src || '')) && im.getBoundingClientRect().width > 80);
    let largest = 0;
    for (const v of e.querySelectorAll('img,svg,video,canvas,picture')) { const q = v.getBoundingClientRect();
      largest = Math.max(largest, q.width * q.height); }
    return {
      tag: e.tagName.toLowerCase(),
      hint: ((e.id || '') + ' ' + (typeof e.className === 'string' ? e.className : '') + ' ' +
             (e.getAttribute('aria-label') || '')).slice(0, 200),
      top: Math.round(r.top + sy), height: Math.round(r.height), bg: c.backgroundColor,
      text: t.slice(0, 600), words: t.split(' ').filter(Boolean).length,
      headings_h1: e.querySelectorAll('h1').length, headings: e.querySelectorAll('h1,h2,h3').length,
      links: e.querySelectorAll('a[href]').length,
      buttons: [...e.querySelectorAll('a[href],button')].filter(b => { const s = getComputedStyle(b);
        return s.backgroundColor !== 'rgba(0, 0, 0, 0)' || s.borderStyle !== 'none'; }).length,
      imgs: imgs.length, video: e.querySelectorAll('video').length,
      forms: e.querySelectorAll('form').length, inputs: e.querySelectorAll('input:not([type=hidden]),textarea').length,
      blockquotes: e.querySelectorAll('blockquote').length,
      big_numbers: (t.match(/\b\d[\d,.]*\s?(\+|%|x|k|m|years?)\b/gi) || []).length,
      logo_row: Math.max(0, svgsSmall >= 4 ? svgsSmall : 0, ...Object.values(rowGroups)),
      portrait: portrait ? 1 : 0,
      largest_visual_pct: Math.round(100 * largest / (vw * innerHeight)),
    };
  };
  const sections = blocks.map(feat);
  const hdr = document.querySelector('header, nav');
  const hs = hdr ? getComputedStyle(hdr).position : '';
  const fams = {};
  for (const e of all) { if (!e.childNodes.length) continue;
    const f = getComputedStyle(e).fontFamily.split(',')[0].replace(/["']/g, '').trim();
    if (text(e)) fams[f] = (fams[f] || 0) + 1; }
  const selfFonts = [];
  for (const sh of document.styleSheets) { let rules; try { rules = sh.cssRules; } catch (_) { continue; }
    for (const rl of rules) if (rl.type === 5) { const src = rl.style.getPropertyValue('src');
      if (src && !/googleapis|gstatic|typekit|fontshare/.test(src)) selfFonts.push(rl.style.getPropertyValue('font-family')); } }
  let widest = 0;
  for (const p of document.querySelectorAll('p')) { if (text(p).split(' ').length > 15)
    widest = Math.max(widest, Math.round(p.getBoundingClientRect().width)); }
  const classes = all.slice(0, 1500).map(e => typeof e.className === 'string' ? e.className : '').filter(Boolean);
  const html = document.documentElement.outerHTML;
  const srcs = [...document.querySelectorAll('script[src],link[href]')].map(s => s.src || s.href).join(' ');
  const globals = ['__NEXT_DATA__','__NUXT__','___gatsby','Webflow','__framer','gsap','ScrollTrigger','THREE',
    'lottie','bodymovin','Shopify','__remixContext','__sveltekit','lenis','analytics','posthog','hj','Intercom']
    .filter(g => g in window).map(g => '__global_' + g + ' ' + g).join(' ');
  return {
    sections,
    page: {
      height: Math.round(document.documentElement.scrollHeight), body_bg: getComputedStyle(document.body).backgroundColor,
      sticky_nav: hs === 'fixed' || hs === 'sticky',
      reveal_hints: document.querySelectorAll('[data-aos],[data-scroll],[class*=reveal],[class*=fade-in],[data-animate]').length,
      videos: document.querySelectorAll('video').length,
      carousel: !!document.querySelector('[class*=swiper],[class*=slick],[class*=splide],[class*=carousel],[class*=embla]'),
      marquee: !!document.querySelector('marquee,[class*=marquee],[class*=ticker]'),
      grids: all.filter(e => getComputedStyle(e).display === 'grid').length,
      animated: all.filter(e => getComputedStyle(e).animationName !== 'none').length,
      content_width: widest,
      custom_cursor: getComputedStyle(document.body).cursor === 'none',
      families: Object.entries(fams).sort((a, b) => b[1] - a[1]).map(x => x[0]).slice(0, 4),
      text: text(document.body).slice(0, 20000),
    },
    signals: (html.slice(0, 400000) + ' ' + srcs + ' ' + globals),
    classes, self_fonts: [...new Set(selfFonts)].slice(0, 6),
  };
}
"""


def _scroll_to_bottom(pg) -> None:
    """Lazy sections and scroll-reveal content only exist after a scroll."""
    for _ in range(40):
        done = pg.evaluate("() => { scrollBy(0, innerHeight); return scrollY + innerHeight >= document.documentElement.scrollHeight - 4; }")
        pg.wait_for_timeout(250)
        if done:
            break
    pg.evaluate("() => scrollTo(0, 0)")
    pg.wait_for_timeout(600)


def probe_site(url: str, out_dir: Path) -> dict:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_context(user_agent=UA, viewport={"width": 1440, "height": 900}).new_page()
        try:
            resp = pg.goto(url, wait_until="domcontentloaded", timeout=45000)
            try:
                pg.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass                       # analytics beacons keep some sites from going idle
            _scroll_to_bottom(pg)
            raw = pg.evaluate(PROBE)
            raw["headers"] = dict(resp.headers) if resp else {}
            raw["final_url"] = pg.url
            slug = re.sub(r"[^a-z0-9]+", "-", host_of(url)).strip("-")
            pg.screenshot(path=str(out_dir / f"{slug}-fullpage.png"), full_page=True)
        finally:
            b.close()
    return raw


def host_of(url: str) -> str:
    return url.split("//")[-1].split("/")[0].lower().removeprefix("www.")


def analyse(raw: dict, role: str) -> dict:
    """Raw probe output -> the analysis record. Pure, so the tests drive it with fixtures."""
    secs = raw.get("sections") or []
    sections = []
    first = next((i for i, f in enumerate(secs) if classify_section(f, i, len(secs)) != "nav"), None)
    for i, f in enumerate(secs):
        kind = classify_section({**f, "first_content": i == first}, i, len(secs))
        sections.append({"kind": kind, **{k: f.get(k) for k in (
            "top", "height", "bg", "words", "buttons", "big_numbers", "portrait",
            "largest_visual_pct", "video")}, "text": (f.get("text") or "")[:140]})
    page = raw.get("page") or {}
    return {
        "technologies": detect_technologies(raw.get("signals", ""), raw.get("classes") or [],
                                            raw.get("headers") or {}, raw.get("self_fonts") or []),
        "page_path": [s["kind"] for s in sections],
        "sections": sections,
        "techniques": techniques(page, sections),
        "trust_signals": trust_signals(sections, page.get("text", "")),
        "taxonomy": taxonomy(role, sections, page),
    }


# ---------------------------------------------------------------- group synthesis + output

def roster_sha(roster: Path) -> str:
    return hashlib.sha256(roster.read_bytes()).hexdigest()


def synthesis(sites: dict) -> dict:
    """What the GROUP shares, per role: the evidence a direction cites instead of a prior."""
    out = {}
    for role in ROLES:
        ok = [s for s in sites.values() if s.get("role") == role and "error" not in s]
        if not ok:
            continue
        n = len(ok)
        kinds = Counter(k for s in ok for k in set(s["page_path"]))
        trust = Counter(k for s in ok for k in s["trust_signals"])
        tech = Counter(f"{c}: {name}" for s in ok for c, names in s["technologies"].items() for name in names)
        heroes = Counter(s["taxonomy"]["hero_archetype"] for s in ok)
        tq = Counter(k for s in ok for k, v in s["techniques"].items() if isinstance(v, bool) and v)
        out[role] = {
            "n": n,
            "section_kinds": dict(kinds.most_common()),
            "trust_signals": dict(trust.most_common()),
            "technologies": dict(tech.most_common()),
            "hero_archetypes": dict(heroes.most_common()),
            "techniques_used": dict(tq.most_common()),
            "median_sections": sorted(s["taxonomy"]["sections"] for s in ok)[n // 2],
            "median_page_screens": sorted(s["taxonomy"]["page_screens"] for s in ok)[n // 2],
        }
    return out


def render_md(data: dict) -> str:
    L = [f"<!-- generated by design-exemplar-analysis.py on {data['generated']}; do not hand-edit. -->",
         "# Exemplar analysis", "",
         f"{len(data['sites'])} site(s). Roster sha256 {data['roster_sha256'][:12]}. Whole page, 1440x900, "
         "scrolled to the bottom in a real browser. Classified by code; nothing here is recalled.", "",
         "## The group, by role", ""]
    for role, g in data["synthesis"].items():
        L += [f"### {role} (n={g['n']})",
              f"- sections seen (sites using each): {g['section_kinds']}",
              f"- trust signals: {g['trust_signals']}",
              f"- hero archetypes: {g['hero_archetypes']}",
              f"- techniques: {g['techniques_used']}",
              f"- technologies: {g['technologies']}",
              f"- median sections {g['median_sections']}, median page length {g['median_page_screens']} screens", ""]
    L += ["## Per site", ""]
    for host, s in data["sites"].items():
        L.append(f"### {host} ({s.get('role')}{', PRIMARY' if s.get('primary') else ''})")
        if "error" in s:
            L += [f"ANALYSIS FAILED: {s['error']}", ""]
            continue
        tx = s["taxonomy"]
        L += [f"- design path: {' > '.join(s['page_path'])}",
              f"- taxonomy: hero {tx['hero_archetype']}, {tx['colour_mode']}, {tx['sections']} sections, "
              f"{tx['density']}, {tx['page_screens']} screens, {tx['first_screen_ctas']} first-screen CTA(s), "
              f"type {tx['type_families']}",
              f"- trust signals: {sorted(s['trust_signals'])}",
              f"- techniques: {s['techniques']}",
              f"- technologies: {s['technologies']}", ""]
    return "\n".join(L) + "\n"


def load_roster(roster: Path) -> list[dict]:
    items = json.loads(roster.read_text())["exemplars"]
    bad = [e.get("url") for e in items if e.get("role") not in ROLES]
    if bad:
        raise SystemExit(f"{roster}: every exemplar needs \"role\": \"peer\" or \"craft\"; missing on {bad}")
    return items


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("refs")
    ap.add_argument("--only")
    a = ap.parse_args()
    refs = Path(a.refs).resolve()
    roster = refs / "exemplars.json"
    items = load_roster(roster)
    prior = refs / ANALYSIS_JSON
    sites = (json.loads(prior.read_text()).get("sites", {}) if (a.only and prior.is_file()) else {})
    for e in items:
        host = host_of(e["url"])
        if a.only and a.only not in host:
            continue
        print("analysing", e["url"], flush=True)
        try:
            rec = analyse(probe_site(e["url"], refs), e["role"])
        except Exception as ex:                    # one dead site must not kill the set; it is recorded
            rec = {"error": str(ex)[:200]}
        sites[host] = {"url": e["url"], "role": e["role"], "primary": bool(e.get("primary")), **rec}
    sites = {host_of(e["url"]): sites[host_of(e["url"])] for e in items if host_of(e["url"]) in sites}
    data = {"generated": date.today().isoformat(), "roster_sha256": roster_sha(roster),
            "section_kinds": list(SECTION_KINDS), "trust_kinds": list(TRUST_KINDS),
            "sites": sites, "synthesis": synthesis(sites)}
    prior.write_text(json.dumps(data, indent=2) + "\n")
    (refs / ANALYSIS_MD).write_text(render_md(data))
    failed = [h for h, s in sites.items() if "error" in s]
    print(f"wrote {prior} and {refs / ANALYSIS_MD}: {len(sites)} site(s), {len(failed)} failed {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
