# Discovery

> Questions asked by prospects, investors, and partners. Answers refined over time.

## Format <!-- pin -->

```
### Q: "[Question as asked]"
- **Asked by:** [persona type]
- **Context:** (why they asked)
- **Best answer:** (current best response)
- **Gaps:** (what we still can't answer well)
- **Source:** [Person] - [Date]
```

## Questions & Answers

### Q: "Where is the data stored?"
- **Asked by:** Practitioner / design partner (Ally)
- **Context:** Evaluating whether kipi-investigations is deployable for her team
- **Best answer:** Local SQLite on a computer everyone accesses, or AWS instance using customer's own API key. Customer owns the data and the storage.
- **Gaps:** Need to verify the AWS deployment path works end-to-end. Currently theoretical.
- **Source:** Ally - 2026-05-27

### Q: "Can I scrape telegram chats and just throw them all in here?"
- **Asked by:** Practitioner (Ally)
- **Context:** Connecting the existing telegram scraper to the investigation memory layer
- **Best answer:** Yes. Telegram scraper exists in kipi-core harvest pipeline. Pipes into ingestion module same as any other report source.
- **Gaps:** Need to document the scraper-to-ingest path inside kipi-investigations specifically. {{NEEDS_PROOF}} once wired.
- **Source:** Ally - 2026-05-27

### Q: "Why wouldn't you make this a SaaS?"
- **Asked by:** Practitioner / design partner (Ally)
- **Context:** Pushing back on consultant-deploy model
- **Best answer:** Could. v1 is consultant-deployed because the deploy-day cost is one day and the surface area for SaaS infra (auth, multi-tenant, billing) is months. Validate the wedge first, productize second.
- **Gaps:** No pricing model validated. {{NEEDS_VALIDATION}}
- **Source:** Ally - 2026-05-27

## Open Questions (need answers before next conversation)

- What's a fair price for a boutique intel firm to pay for this annually? (Ally said "subscription" but no number.) Target $5K-$50K/seat? Per-org?
- Will Ethan (FBI contractor) need the tool to run in a SCIF-compatible way? If so, what's the offline/airgapped path?
- Does Active Fence's misogynistic culture extend to procurement decisions, or just internal vibe? (Tova channel may be useless if procurement is hostile.)

## Proof Gaps

- **Proof needed:** Cross-investigation entity correlation working on real reports (>10 reports, multiple investigations)
  - **Context:** Came up in conversation as the core "the magic" moment
  - **Potential source:** Ally's handala reports + Iranian NVE reports once she sends them
