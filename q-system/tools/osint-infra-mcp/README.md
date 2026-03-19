# OSINT Infrastructure MCP Server

Lightweight infrastructure reconnaissance tools. No API keys needed.

## Tools

| Tool | What it does | Requires |
|------|-------------|----------|
| `whois_lookup` | Domain registration data (registrant, dates, nameservers) | `whois` CLI |
| `dns_lookup` | DNS records (A, AAAA, MX, NS, TXT, CNAME, SOA) | `dig` CLI |
| `reverse_dns` | Reverse DNS for IP addresses | `dig` CLI |
| `wayback_snapshots` | List Wayback Machine snapshots for a URL | Internet |
| `wayback_fetch` | Fetch a specific Wayback Machine snapshot | Internet |

## Run

```bash
uv run --with "fastmcp>=2.0.0" --with "httpx>=0.27.0" server.py
```

## Register in Claude Code

Add to `.mcp.json` or `settings.json`:

```json
{
  "osint-infra": {
    "command": "uv",
    "args": ["run", "--with", "fastmcp>=2.0.0", "--with", "httpx>=0.27.0", "q-system/tools/osint-infra-mcp/server.py"]
  }
}
```

Or via CLI:
```bash
claude mcp add osint-infra -s user -- uv run --with "fastmcp>=2.0.0" --with "httpx>=0.27.0" q-system/tools/osint-infra-mcp/server.py
```
