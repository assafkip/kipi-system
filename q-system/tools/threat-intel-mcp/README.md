# Threat Intel MCP Server (add-on)

URL/domain/IP reputation tools as Claude Code MCP tools. Zero context bloat.

## Tools
| Tool | Source | What it does |
|------|--------|--------------|
| `vt_lookup` | VirusTotal | Domain/URL/IP/hash reputation across 70+ engines |
| `urlhaus_lookup` | URLhaus (abuse.ch) | Malware URL database lookup |
| `threatfox_lookup` | ThreatFox (abuse.ch) | IOC search -- IPs, domains, hashes, malware families |
| `crt_lookup` | crt.sh | Certificate transparency history (no key needed) |

## Install

```bash
git clone https://github.com/assafkip/threat-intel-mcp.git ~/threat-intel-mcp
claude mcp add threat-intel -s user -- uv run ~/threat-intel-mcp/server.py
```

## API Keys Required

Add to `~/.claude/settings.json` or `.claude/settings.local.json`:

```json
{
  "env": {
    "VIRUSTOTAL_API_KEY": "your-key (free: virustotal.com/gui/join-us, 500/day)",
    "ABUSECH_AUTH_KEY": "your-key (free: auth.abuse.ch, covers URLhaus + ThreatFox)"
  }
}
```

## When to Use
- Investigating prospect domains before outreach
- Due diligence on leads from unknown sources
- Security consulting engagements
- Vetting URLs shared in DMs or emails
