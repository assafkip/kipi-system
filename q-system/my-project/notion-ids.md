# Notion Database IDs

> Populated during setup if using Notion as CRM. All IDs stored here.
> Agents read this file instead of hardcoding IDs. Full UUIDs required.

## Workspace
- **Account:** {{YOUR_NOTION_EMAIL}}
- **Parent page ID:** {{PARENT_PAGE_ID}}

## Databases

Each database has two IDs:
- `database_id` - used when CREATING pages (`API-post-page`)
- `data_source_id` - used when QUERYING (`API-query-data-source`)

| Database | database_id | data_source_id | Purpose |
|----------|-------------|----------------|---------|
| Contacts | | | People + relationship data |
| Interactions | | | Conversation logs |
| Pipeline | | | Investor/prospect tracking |
| Actions | | | Task management |
| LinkedIn Tracker | | | Social engagement logging |
| Content Pipeline | | | Content status tracking |
| Editorial Calendar | | | Publishing schedule |

## Pages (for checklist updates)

| Page | page_id | Purpose |
|------|---------|---------|
| Daily Actions | | Checklist page updated each morning |
| Daily Posts | | Post drafts checklist updated each morning |
| Today Dashboard | | Main daily view |

## How to find IDs

**database_id:** Open a database in Notion, copy the URL. The 32-char hex string is the database_id. Add hyphens in UUID format: 8-4-4-4-12.

**data_source_id:** Run `mcp__notion_api__API-post-search` with query "database name" and filter `{"property": "object", "value": "data_source"}`. The returned id is the data_source_id.

**page_id:** Open a page in Notion, copy the URL. The last path segment (32-char hex) is the page_id.

## VC Pipeline API (Optional)

If using a local VC pipeline manager:
- **URL:** {{VC_PIPELINE_URL}} (e.g. http://localhost:5050/api/pipeline)
- Leave blank if not using

## Setup Status
- [ ] Notion MCP server configured in settings.json
- [ ] Databases created
- [ ] All database_ids recorded above
- [ ] All data_source_ids recorded above
- [ ] Page IDs recorded above
- [ ] Test query successful
