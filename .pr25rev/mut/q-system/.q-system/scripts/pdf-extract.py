#!/usr/bin/env python3
"""
pdf-extract.py — deterministic, token-aware extraction of a large PDF into a
navigable corpus, so an agent can reason over it by loading one section at a
time instead of the whole document.

No LLM in the extraction path. Uses the system `pdftotext` (poppler) on the
PDF's existing text layer. OCR is out of scope: if a page has no text layer
this records it as empty (est_tokens=0) so you can see the gap, rather than
silently guessing.

Why this shape (scar): a 425-page report is ~500k tokens of text. Dumping it
into context per question is the waste we are avoiding. The value is in being
able to load ONE chapter (~30-50k tokens) or grep a figure index, not the
whole thing. So the artifacts are: per-page text, a manifest with per-page
token estimates, a figure/source index (where the chart data points live),
and optional per-section markdown.

Usage:
    pdf-extract.py <pdf> <outdir>
        Extract every page to <outdir>/pages/page-0001.txt, write
        <outdir>/manifest.json and <outdir>/figures.jsonl.

    pdf-extract.py <pdf> <outdir> --sections sections.txt
        Also split into per-section markdown under <outdir>/sections/.
        sections.txt is one "Section Title" per line (regex, matched against
        the first ~6 lines of each page). Each section runs from its first
        matching page up to (not including) the next section's first match.
        Best-effort: fragile when chapter titles are split across lines or
        letter-spaced in the typography. Prefer --ranges when you know the
        physical page boundaries.

    pdf-extract.py <pdf> <outdir> --ranges "Title:start-end,Title2:s-e,..."
        Deterministic section split by EXPLICIT physical page ranges (1-based,
        inclusive). Bulletproof: no title matching. Use this when --sections
        mis-detects due to typography (letter-spaced headers, split titles).

    pdf-extract.py <pdf> <outdir> --layout
        Pass -layout to pdftotext (preserves columns/tables; default is
        reading order, better for prose).
"""
import json
import os
import re
import subprocess
import sys

# A figure/source line is where chart data points and attribution live. We keep
# these in a dedicated index because the plotted numbers themselves are images
# (not in the text layer) — the caption + source is the cheapest faithful proxy.
FIG_RE = re.compile(r'\b(figure|table|chart|exhibit)\s+\d', re.IGNORECASE)
SRC_RE = re.compile(r'^\s*source[s]?\s*[:—-]', re.IGNORECASE)


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def page_count(pdf):
    out = run(["pdfinfo", pdf]).stdout
    m = re.search(r'^Pages:\s+(\d+)', out, re.MULTILINE)
    if not m:
        sys.exit(f"pdf-extract: could not read page count from pdfinfo {pdf}")
    return int(m.group(1))


def extract_page(pdf, n, layout):
    cmd = ["pdftotext", "-f", str(n), "-l", str(n)]
    if layout:
        cmd.append("-layout")
    cmd += [pdf, "-"]
    # pdftotext emits "Syntax Warning: ..." to stderr on quirky fonts; the
    # stdout text is still good, so we ignore stderr.
    return run(cmd).stdout


def est_tokens(chars):
    # ~4 chars/token is the standard rough estimate for English prose.
    return round(chars / 4)


def load_sections(path):
    secs = []
    with open(path) as f:
        for line in f:
            t = line.strip()
            if t and not t.startswith("#"):
                secs.append(t)
    return secs


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    pdf, outdir = sys.argv[1], sys.argv[2]
    layout = "--layout" in sys.argv[3:]
    sections_file = None
    ranges_arg = None
    if "--sections" in sys.argv:
        i = sys.argv.index("--sections")
        sections_file = sys.argv[i + 1]
    if "--ranges" in sys.argv:
        i = sys.argv.index("--ranges")
        ranges_arg = sys.argv[i + 1]

    if not os.path.exists(pdf):
        sys.exit(f"pdf-extract: no such file: {pdf}")

    pages_dir = os.path.join(outdir, "pages")
    os.makedirs(pages_dir, exist_ok=True)

    n_pages = page_count(pdf)
    manifest = {"pdf": os.path.abspath(pdf), "pages": n_pages,
                "layout": layout, "total_est_tokens": 0, "page_index": []}
    figures = []

    for n in range(1, n_pages + 1):
        text = extract_page(pdf, n, layout)
        fname = f"page-{n:04d}.txt"
        with open(os.path.join(pages_dir, fname), "w") as f:
            f.write(text)
        chars = len(text)
        tok = est_tokens(chars)
        manifest["total_est_tokens"] += tok
        manifest["page_index"].append({"page": n, "chars": chars, "est_tokens": tok})

        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            kind = None
            if SRC_RE.search(line):
                kind = "source"
            elif FIG_RE.search(line):
                kind = "figure"
            if kind:
                figures.append({"page": n, "kind": kind, "text": line})

    def read_page(n):
        return open(os.path.join(pages_dir, f"page-{n:04d}.txt")).read()

    def write_sections(ranges):
        """ranges: list of (title, start, end). Writes per-section markdown."""
        sec_dir = os.path.join(outdir, "sections")
        os.makedirs(sec_dir, exist_ok=True)
        meta = []
        for title, start, end in ranges:
            slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')[:60]
            body, tok = [], 0
            for n in range(start, end + 1):
                pg = read_page(n)
                body.append(f"\n\n<!-- page {n} -->\n{pg}")
                tok += est_tokens(len(pg))
            with open(os.path.join(sec_dir, f"{slug}.md"), "w") as f:
                f.write(f"# {title}\n(pages {start}-{end})\n" + "".join(body))
            meta.append({"title": title, "slug": slug,
                         "start": start, "end": end, "est_tokens": tok})
        return meta

    sections_meta = []
    if ranges_arg:
        # Explicit physical ranges: "Title:start-end,Title2:s-e"
        ranges = []
        for part in ranges_arg.split(","):
            title, span = part.rsplit(":", 1)
            s, e = span.split("-")
            ranges.append((title.strip(), int(s), int(e)))
        sections_meta = write_sections(ranges)
        manifest["sections"] = sections_meta
    elif sections_file:
        # Best-effort title match against the first lines of each page.
        titles = load_sections(sections_file)
        starts = {}
        for title in titles:
            pat = re.compile(title, re.IGNORECASE)
            for n in range(1, n_pages + 1):
                head = "\n".join(read_page(n).splitlines()[:6])
                if pat.search(head):
                    starts[title] = n
                    break
        found = sorted(((p, t) for t, p in starts.items()))
        ranges = [(t, p, (found[i + 1][0] - 1 if i + 1 < len(found) else n_pages))
                  for i, (p, t) in enumerate(found)]
        sections_meta = write_sections(ranges)
        missing = [t for t in titles if t not in starts]
        if missing:
            sections_meta.append({"unmatched_titles": missing})
        manifest["sections"] = sections_meta

    with open(os.path.join(outdir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    with open(os.path.join(outdir, "figures.jsonl"), "w") as f:
        for row in figures:
            f.write(json.dumps(row) + "\n")

    print(f"pages={n_pages}  total_est_tokens={manifest['total_est_tokens']}  "
          f"figure_lines={len(figures)}")
    if sections_meta:
        for s in sections_meta:
            if "title" in s:
                print(f"  {s['start']:>3}-{s['end']:<3} "
                      f"{s['est_tokens']:>7} tok  {s['title']}")
            elif "unmatched_titles" in s:
                print(f"  UNMATCHED: {s['unmatched_titles']}")


if __name__ == "__main__":
    main()
