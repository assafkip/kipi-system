Generate marketing content. Read the full workflow from q-system/.q-system/commands.md under "/q-market-create".

Arguments: $ARGUMENTS

Supported types: linkedin, x, medium, one-pager, outreach, deck, follow-up

If no arguments, ask: "What type? (linkedin, x, medium, one-pager, outreach, deck, follow-up) And what topic?"

Workflow:
1. Read the corresponding template from q-system/marketing/templates/
2. Follow template's pre-generation steps (canonical sources, NotebookLM queries, CRM lookup)
3. Generate content following template structure
4. For deck: Call mcp__gamma__generate_gamma (presentation format)
5. For one-pager: Call mcp__gamma__generate_gamma (document format)
6. For medium (optional): Also generate Gamma social card (social format)
7. Run q-system/marketing/content-guardrails.md checks automatically
8. Save to appropriate output directory under q-system/output/marketing/
9. Create Content Pipeline DB entry (DS 9a0c086e-484c-4f3a-a47b-fb2774fc2f14, Status: Drafted)
10. Output: draft text + guardrail result + file path (+ Gamma URL if applicable)
