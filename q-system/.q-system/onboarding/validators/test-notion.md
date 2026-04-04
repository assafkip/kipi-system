# Test Notion Connection

## How to Test

After the user has connected Notion, run this validation sequence.

### Test 1: Can we reach the API?

Use the Notion MCP server to list available pages/databases.

**What to try:**
- Call the Notion MCP tool to search for pages (empty query)
- If it returns results: PASS
- If it errors: FAIL

**On PASS:**
> "I can see your Notion workspace! You have [N] pages available."

**On FAIL:**
> "I can't reach your Notion yet. Let's troubleshoot:
> - Did you copy the full code? (It should start with 'ntn_' or 'secret_')
> - Is the Notion integration still active? Check notion.so/profile/integrations
> - Try refreshing and copying the code again"

### Test 2: Can we write?

If Test 1 passes, try creating a test page (or adding a comment):

**What to try:**
- Create a test page titled "Kipi Test - Safe to Delete"
- If it works: delete it, PASS
- If it fails: the integration might have read-only permissions

**On PASS:**
> "Read and write access confirmed. Everything's working."

**On FAIL (write):**
> "I can read your Notion but can't write to it. This usually means the integration needs more permissions. Go to notion.so/profile/integrations, click on Kipi, and make sure all the capability checkboxes are enabled."

### Test 3: Database access (run during CRM setup, not during connection test)

When setting up CRM databases, verify each database is shared with the integration:

**What to try:**
- Query each database by ID from notion-ids.md
- If accessible: PASS
- If "not found": the database isn't shared with the integration

**On FAIL:**
> "I can't access your [database name] database. You need to share it with the Kipi integration:
> 1. Open that database in Notion
> 2. Click the ... menu
> 3. Go to Connections
> 4. Add Kipi"
