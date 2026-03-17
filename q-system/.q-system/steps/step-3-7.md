- Monday Step 3.7: Review `weekly/` files, promote or archive
- 1st of month: Review `monthly/` files, promote or archive

---

### Graph knowledge base:

> Structured entity-relationship triples for fast queries across contacts, companies, and concepts.

**File:** `memory/graph.jsonl`

**Format:** One JSON object per line:
```jsonl
{"s":"Edoardo Ermotti","p":"works_at","o":"14 Peaks Capital","t":"2026-03-12"}
{"s":"14 Peaks Capital","p":"invested_in","o":"Cybersecurity","t":"2026-03-12"}
{"s":"Henry Cashin","p":"introduced","o":"Edoardo Ermotti","t":"2026-03-12"}
{"s":"Scattered Spider","p":"exploits","o":"identity_gaps","t":"2026-03-11"}
```

**Triple types:**
- `works_at`, `role_is` - person-company-role
- `introduced`, `knows` - relationship edges
- `invested_in`, `portfolio_includes` - VC-company relationships
- `cares_about`, `posted_about` - interest mapping
- `objected_to`, `resonated_with` - conversation insights
- `exploits`, `targets` - threat intelligence linkage

**When to write:**
- During `/q-debrief`: extract entities and relationships