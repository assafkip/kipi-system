# Connect Apify

## What This Does
Apify lets Kipi look up LinkedIn profiles, find relevant posts, scrape public data from social media, and research prospects. It's the research engine behind lead sourcing and engagement features.

## What the User Needs
- An Apify account (free tier gives ~$5/month of credits, enough for light use)
- A credit card for usage beyond free tier (optional)

## Walk-Through Script

### Part 1: Explain

Say:

> "Let's connect Apify - this is your research engine. It lets me:
> - Look up LinkedIn profiles for people you're meeting
> - Find relevant LinkedIn posts for engagement
> - Research prospects and companies
> - Scan Reddit, Twitter, and the web for relevant conversations
>
> Apify has a free tier that's enough to get started. You only pay more if you use it heavily."

### Part 2: Create Account

> "Here's what to do:
>
> 1. Open your browser and go to **apify.com**
> 2. Click **Sign up** (you can use Google sign-in to make it fast)
> 3. Once you're in, click your profile icon in the top right
> 4. Click **Settings**
> 5. Go to the **Integrations** tab
> 6. You'll see a section called **API token** - click **Copy** next to your personal token
> 7. Paste it here"

### Part 3: Save the Code

When they paste the token:

1. Validate it looks like an Apify token (typically `apify_api_` prefix or a long alphanumeric string)
2. If valid: Write to `.mcp.json`

Save to `.mcp.json`:
```json
{
  "mcpServers": {
    "apify": {
      "command": "npx",
      "args": ["-y", "@apify/actors-mcp-server@0.9.10"],
      "env": {
        "APIFY_TOKEN": "[their token]",
        "TOOLS": "actors,apify/linkedin-profile-scraper,apify/linkedin-posts-scraper,apify/linkedin-connections-scraper,curious_coder/twitter-scraper,apify/reddit-scraper,apify/web-scraper"
      }
    }
  }
}
```

> "Connected! I can now research people and find social media posts for you."

### Part 4: Brief on Costs

> "Quick heads up on costs:
> - Apify gives you about $5 free every month
> - Looking up a LinkedIn profile uses about $0.01-0.05
> - Scraping a batch of posts costs a bit more
> - For normal daily use, you'll probably spend $5-15/month
>
> If you want to set a spending limit, go to **Settings > Billing** on apify.com."

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "I can't find the API token" | "Go to apify.com, click your profile icon (top right), then Settings, then Integrations. The token is right there." |
| "It says I need to verify my email" | "Check your inbox for a verification email from Apify. Click the link, then come back and try again." |
| "I don't want to pay for anything" | "The free tier works fine for light use. If you go over, Apify just pauses until next month. No surprise charges unless you add a payment method." |
| "Is this legal? Scraping LinkedIn?" | "Apify uses LinkedIn's public data, similar to what anyone can see by visiting a profile. It's a widely used service by sales and marketing teams." |
