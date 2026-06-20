# Dogfood Gate: every website passes eyeball before it ships (ENFORCED)

We build a tool whose job is catching bad / AI-generated web design. A page we
ship that fails that bar is the worst possible miss. So no public-facing website
page is "done" until it has been run through eyeball. This is not a reminder; it
is a gate.

## Fires when

- Building, redesigning, or editing any public-facing landing/marketing page or
  product site (the same trigger as `design-process.md` / `design-auto-invoke.md`).

## The gate (two layers)

1. **Fast deterministic tripwire (automatic).** The `kipi-design` plugin's
   `dogfood_gate.py` hook fires PostToolUse on Write/Edit of a public `.html` and
   BLOCKS (exit 2) if it statically detects AI-slop or a missing primary action
   (converged font, gradient-text headline, emoji icons, stock-prompt copy, no
   interactive element). Internal HTML (dashboards, schedules, logs, templates,
   tests, system output) is skipped. Bypass one file only when the slop is
   intentional (a parody/demo): add `<!-- eyeball-gate-skip -->`.

2. **Authoritative render + UX read (required before deploy).** Run the real
   thing — a browser renders the page and eyeball judges design + UX:
   ```
   node ~/projects/eyeball/web/scan.mjs <url-or-file>        # add --vision for the Claude UX read
   ```
   It exits non-zero (GATE: FAIL) when the AI-design score is too high OR the
   primary action is not in the first screen. A website is not done until this
   passes (or the founder explicitly signs off on an intentional exception).

## What eyeball checks (design + UX)

AI-design tells (fonts, gradients, cookie-cutter layout, emoji icons, stock copy)
AND the UX-researcher read: seconds to understand, does a first-time visitor grasp
what the page is and what to do, is the primary action reachable in the first
screen, bounce risk, and the conversion fixes. Tool-first beats clever: a page
that hides its purpose fails the gate.

## Scar

2026-06-20: the eyeball landing itself shipped as a clever slop-parody with the
input buried two-thirds down the page. It was never run through our own tool — the
check was silently skipped because "the slop is intentional." A design tool's own
page failing UX is a credibility hole. The fix is this gate, not better intentions.

## Does not fire

- Internal/founder-only HTML (dashboards, schedules, logs) — see the
  `design-auto-invoke.md` gate. Copy-only/typo edits to an existing passing page.
