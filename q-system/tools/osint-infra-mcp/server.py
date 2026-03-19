#!/usr/bin/env python3
"""
OSINT Infrastructure MCP Server
5 tools for infrastructure reconnaissance. No API keys needed.
Uses system CLI tools (whois, dig) and Wayback Machine CDX API.

Run: uv run --with "fastmcp>=2.0.0" --with "httpx>=0.27.0" server.py
"""

import subprocess
import json
from datetime import datetime

from fastmcp import FastMCP
import httpx

mcp = FastMCP("osint-infra")


@mcp.tool()
def whois_lookup(domain: str) -> str:
    """Look up WHOIS registration data for a domain. Returns registrant, dates, nameservers."""
    try:
        result = subprocess.run(
            ["whois", domain],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            return f"WHOIS lookup failed: {result.stderr.strip()}"
        return result.stdout[:4000]  # Cap output
    except FileNotFoundError:
        return "Error: 'whois' command not found. Install with: brew install whois (macOS) or apt install whois (Linux)"
    except subprocess.TimeoutExpired:
        return "Error: WHOIS lookup timed out after 15 seconds"


@mcp.tool()
def dns_lookup(domain: str, record_type: str = "A") -> str:
    """Query DNS records for a domain. record_type: A, AAAA, MX, NS, TXT, CNAME, SOA."""
    valid_types = ["A", "AAAA", "MX", "NS", "TXT", "CNAME", "SOA", "PTR", "SRV"]
    record_type = record_type.upper()
    if record_type not in valid_types:
        return f"Invalid record type. Use one of: {', '.join(valid_types)}"
    try:
        result = subprocess.run(
            ["dig", "+short", domain, record_type],
            capture_output=True, text=True, timeout=10
        )
        output = result.stdout.strip()
        if not output:
            return f"No {record_type} records found for {domain}"
        return f"{record_type} records for {domain}:\n{output}"
    except FileNotFoundError:
        return "Error: 'dig' command not found. Install with: brew install bind (macOS) or apt install dnsutils (Linux)"
    except subprocess.TimeoutExpired:
        return "Error: DNS lookup timed out after 10 seconds"


@mcp.tool()
def reverse_dns(ip_address: str) -> str:
    """Reverse DNS lookup for an IP address. Returns hostnames pointing to this IP."""
    try:
        result = subprocess.run(
            ["dig", "+short", "-x", ip_address],
            capture_output=True, text=True, timeout=10
        )
        output = result.stdout.strip()
        if not output:
            return f"No reverse DNS records found for {ip_address}"
        return f"Reverse DNS for {ip_address}:\n{output}"
    except FileNotFoundError:
        return "Error: 'dig' command not found."
    except subprocess.TimeoutExpired:
        return "Error: Reverse DNS lookup timed out after 10 seconds"


@mcp.tool()
def wayback_snapshots(url: str, limit: int = 10) -> str:
    """List Wayback Machine snapshots for a URL. Returns timestamps and archive URLs."""
    cdx_url = "https://web.archive.org/cdx/search/cdx"
    params = {
        "url": url,
        "output": "json",
        "limit": min(limit, 50),
        "fl": "timestamp,original,statuscode,mimetype",
        "collapse": "timestamp:8"  # One per day
    }
    try:
        with httpx.Client(timeout=20) as client:
            resp = client.get(cdx_url, params=params)
            resp.raise_for_status()
            data = resp.json()

        if len(data) <= 1:  # First row is headers
            return f"No Wayback Machine snapshots found for {url}"

        headers = data[0]
        rows = data[1:]
        results = []
        for row in rows:
            entry = dict(zip(headers, row))
            ts = entry["timestamp"]
            date_str = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"
            archive_url = f"https://web.archive.org/web/{ts}/{entry['original']}"
            results.append(f"  {date_str} (HTTP {entry['statuscode']}) {archive_url}")

        return f"Wayback snapshots for {url} ({len(rows)} found):\n" + "\n".join(results)
    except httpx.HTTPError as e:
        return f"Error querying Wayback Machine: {e}"


@mcp.tool()
def wayback_fetch(url: str, timestamp: str = "") -> str:
    """Fetch a specific Wayback Machine snapshot. timestamp format: YYYYMMDD (or empty for latest)."""
    if timestamp:
        archive_url = f"https://web.archive.org/web/{timestamp}/{url}"
    else:
        archive_url = f"https://web.archive.org/web/{url}"

    try:
        with httpx.Client(timeout=30, follow_redirects=True) as client:
            resp = client.get(archive_url)
            resp.raise_for_status()
            content = resp.text[:8000]  # Cap at 8K chars
            return f"Fetched: {archive_url}\n\nContent (first 8000 chars):\n{content}"
    except httpx.HTTPError as e:
        return f"Error fetching Wayback snapshot: {e}"


if __name__ == "__main__":
    mcp.run()
