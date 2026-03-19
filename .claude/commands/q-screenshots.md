Capture full-page PDF screenshots of all URLs referenced in a report or brief.

## Instructions

1. Read the target file (passed as argument, or the most recent file in `q-system/output/`)
2. Extract all URLs from the document (links, references, appendix citations)
3. Deduplicate and filter:
   - Skip internal file paths
   - Skip mailto: links
   - Skip URLs that are clearly API endpoints (not human-readable pages)
4. For each URL, use Chrome MCP to:
   - Navigate to the URL
   - Wait for page load
   - Use the GO FULL PAGE Chrome extension (or equivalent) to capture a full-page screenshot
   - Save as PDF to `screenshots/` subfolder in the same directory as the target file
5. Name files descriptively: `screenshot-{domain}-{slug}.pdf`

## Output

Create a `screenshots/` directory alongside the report with all captured PDFs.
Add an appendix section to the report listing each screenshot with its source URL.

## Fallback

If Chrome MCP is unavailable or a page fails to load:
- Log the failed URL
- Continue with remaining URLs
- Note failures in the appendix

## Usage

```
/q-screenshots q-system/output/brief-2026-03-19.md
```
