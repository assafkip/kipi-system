# Test LinkedIn (Chrome Automation) Connection

## How to Test

### Test 1: Can we see the browser?

**What to try:**
- Use the Chrome MCP tools to get current tab context
- If it returns tab info: PASS
- If it errors: FAIL

**On PASS:**
> "I can see your browser!"

**On FAIL:**
> "I can't connect to your Chrome browser. Make sure:
> - Google Chrome is open (not Safari or Firefox)
> - The Claude-in-Chrome extension is installed and shows 'Connected'
> - Try clicking the extension icon to toggle it"

### Test 2: Is LinkedIn open and logged in?

**What to try:**
- Check if any open tab has linkedin.com
- If yes and page shows a feed or profile: PASS
- If yes but shows login page: FAIL (not logged in)
- If no LinkedIn tab: FAIL (not open)

**On PASS:**
> "I can see your LinkedIn feed. Chrome automation is ready!"

**On FAIL (not logged in):**
> "LinkedIn is open but you're not logged in. Sign into LinkedIn in Chrome, then let me know."

**On FAIL (not open):**
> "Open linkedin.com in Chrome and make sure you're signed in. Then say 'ready' and I'll check again."

### Test 3: Can we read a page?

**What to try:**
- Read the page title or feed content from the LinkedIn tab
- If it returns content: PASS
- If blocked or empty: FAIL

**On PASS:**
> "Everything's working. I can read and interact with LinkedIn through your browser."

**On FAIL:**
> "I can see the tab but can't read the content. Try refreshing the LinkedIn page and let me know."
