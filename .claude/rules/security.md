---
paths:
  - "**/*.py"
  - "**/*.ts"
  - "**/*.tsx"
  - "**/*.js"
  - "**/*.jsx"
---

# Security Best Practices

These rules apply to ALL code changes. No exceptions.

- Never hardcode secrets, API keys, credentials, or tokens. Use environment variables.
- Validate and sanitize all user input at the boundary where it enters the system.
- Use parameterized queries for all database access. Never use string concatenation or interpolation for SQL.
- Apply principle of least privilege for file access, network access, and permissions.
- Never use eval(), exec(), or any form of dynamic code execution with user-supplied data.
- Check dependencies for known vulnerabilities before adding them (npm audit / pip audit).
- Use HTTPS for all external API calls.
- Never log sensitive data (passwords, tokens, PII). Scrub logs before writing.
- Set appropriate CORS policies. Do not use wildcard origins in production.
- Use cryptographically secure random generators for tokens and session IDs, not Math.random() or similar.
