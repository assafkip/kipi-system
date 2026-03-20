Validate content against q-system/marketing/content-guardrails.md. PASS/FAIL with specific fixes.

Arguments: $ARGUMENTS

If no file specified, ask which file to review.

Workflow:
1. Read the content file
2. Read q-system/marketing/content-guardrails.md
3. Run ALL checks: misclassification, language (banned words, emdashes), overclaiming (all 14 RULEs), decision compliance, voice (channel-appropriate), channel-specific
4. Output PASS/FAIL with specific issues and fix suggestions
5. If PASS: Update Content Pipeline DB entry (Status: Reviewed, Guardrails Passed: Yes)
