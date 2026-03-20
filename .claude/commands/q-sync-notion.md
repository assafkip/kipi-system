Sync local files with Notion CRM. Push new contacts/interactions/pipeline changes to Notion. Pull follow-up date changes and status updates from Notion back to local files.

Notion database IDs:
- Contacts DB: DS 4cb26c24-dd0b-4240-9d7d-17ba8285e82d
- Interactions DB: DS c4ceadf2-2f21-4510-b07d-349ad3fd1fc1
- Investor Pipeline DB: DS acb2e5dd-95fd-4df1-89af-0d676e8c9dac
- LinkedIn Tracker DB: DS d6a4eeb8-bb93-4164-89e1-b48fa8640917
- Actions DB: DS 863bc9b6-762d-4577-8c4f-014625d30831

Workflow:
1. Read q-system/my-project/relationships.md for local changes
2. Pull Notion DBs for remote changes
3. Local -> Notion: New debriefs -> Interactions, updated contacts -> Contact properties, pipeline changes -> Investor Pipeline
4. Notion -> Local: Follow-up dates changed in Notion -> relationships.md, pipeline stage changes -> current-state.md
5. Report sync results
