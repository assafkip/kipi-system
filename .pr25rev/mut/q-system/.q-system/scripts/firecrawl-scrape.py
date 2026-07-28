#!/usr/bin/env python3
"""Firecrawl scrape-to-FILE (H7). Persists the FULL source markdown of a web page to
a file instead of summarizing it into context (so the research cascade can search and
cite thousands of saved sources without hitting context limits).

Env-key gated: FIRECRAWL_API_KEY (env var ONLY; never a committed secret). Fail-CLOSED
on an empty body (persists nothing). stdlib only (urllib). Set FIRECRAWL_MOCK_RESPONSE
to a JSON file to inject a canned response for offline testing.

Usage: firecrawl-scrape.py <url> <output-dir>
"""
import json
import os
import re
import sys
import urllib.request

API = "https://api.firecrawl.dev/v1/scrape"


def sanitize(url):
    name = re.sub(r"^https?://", "", url)
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-")[:120]
    return name or "scrape"


def fetch(url, api_key):
    mock = os.environ.get("FIRECRAWL_MOCK_RESPONSE")
    if mock:
        with open(mock, encoding="utf-8") as f:
            return json.load(f)
    payload = json.dumps({"url": url, "formats": ["markdown"], "onlyMainContent": True}).encode()
    req = urllib.request.Request(
        API, data=payload,
        headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    if len(sys.argv) != 3:
        sys.stderr.write("usage: firecrawl-scrape.py <url> <output-dir>\n")
        sys.exit(1)
    url, out_dir = sys.argv[1], sys.argv[2]
    if not os.environ.get("FIRECRAWL_API_KEY") and not os.environ.get("FIRECRAWL_MOCK_RESPONSE"):
        sys.stderr.write("error: FIRECRAWL_API_KEY not set (env var only; no committed secret)\n")
        sys.exit(3)
    try:
        data = fetch(url, os.environ.get("FIRECRAWL_API_KEY", ""))
    except Exception as e:
        sys.stderr.write("error: scrape failed: " + str(e) + "\n")
        sys.exit(4)
    # Coerce to str before strip: Firecrawl returns markdown:null on a no-content
    # scrape, and data can come back as a list -- both must land on fail-closed
    # exit 5, not crash with AttributeError (review finding, H7).
    inner = data.get("data") if isinstance(data, dict) else None
    md_val = inner.get("markdown") if isinstance(inner, dict) else None
    md = md_val if isinstance(md_val, str) else ""
    if not md.strip():
        sys.stderr.write("error: empty body returned (fail-closed; nothing persisted)\n")
        sys.exit(5)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, sanitize(url) + ".md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(md)
    print(path)


if __name__ == "__main__":
    main()
