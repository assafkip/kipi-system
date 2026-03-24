# Output Templates

Reusable folder structures for repeatable outputs.
Copy a template folder, fill the placeholders, run the pipeline.

## Usage

```bash
bash q-system/.q-system/agent-pipeline/templates/create-from-template.sh <template-name> <output-name>
```

## Available Templates

### deck/
For investor decks, one-pagers, pitch materials.
- context.md  - audience, goal, key points
- sections.md - section outline with content slots
- assets.md   - which reusable assets to pull
- output/     - generated files land here

### outreach/
For outreach batches (prospects, investors, advisors).
- targets.md  - who, why, what channel
- hooks.md    - personalized hooks per target
- drafts/     - generated messages
- tracker.md  - sent/response status

### content/
For content creation (LinkedIn, Medium, X, Substack).
- brief.md    - topic, angle, audience, channel
- research.md - supporting data, quotes, references
- drafts/     - versions
- review/     - review pipeline output

### debrief/
For post-conversation debriefs.
- transcript.md  - raw conversation input
- extraction.md  - structured debrief output
- routing.md     - which canonical files to update
- actions.md     - follow-up action cards
