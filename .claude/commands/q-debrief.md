Enter DEBRIEF mode. This is the HIGHEST-PRIORITY workflow. Use the structured debrief template to process a conversation.

Arguments: $ARGUMENTS

If no person name provided, ask: "Who did you just talk to?"

Workflow:
1. Read q-system/methodology/debrief-template.md
2. Read q-system/my-project/relationships.md for prior history with this person
3. Ask the user to describe the conversation (or paste a summary)
4. Extract using the debrief template structure:
   - What resonated (exact phrases that landed)
   - What fell flat or got pushback
   - New objections surfaced
   - Competitive intel mentioned
   - Action items and commitments
   - Relationship status change
   - Positioning insights
5. Update canonical files:
   - objections.md (new objections)
   - discovery.md (new questions asked/answered)
   - talk-tracks.md (phrases that resonated)
   - relationships.md (conversation logged, status updated)
6. Create Notion Interaction entry via mcp__notion__notion-create-pages
7. Log to my-project/progress.md
8. Surface recommended next actions

Follow ADHD-aware rules: lead with wins, break into small chunks, tag actions with Energy + Time Est.
