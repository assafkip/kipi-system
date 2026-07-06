# Dogfood Gate: every public page clears our own design bar before it ships (ENFORCED)

We build a tool whose job is catching bad / AI-generated web design. A page we
ship that fails that bar is the worst possible miss. So no public-facing website
page is "done" until it has cleared our own design gate. This is not a reminder; it
is a gate.

## Fires when

- Building, redesigning, or editing any public-facing landing/marketing page or
  product site (the same trigger as `design-process.md` / `design-auto-invoke.md`).

## The gate (two layers)

1. **Fast deterministic tripwire (automatic).** The `kipi-design` plugin's
   `dogfood_gate.py` hook fires PostToolUse on Write/Edit of a public `.html` and
   BLOCKS (exit 2) if it statically detects AI-slop or a missing primary action
   (converged font, gradient-text headline, emoji icons, stock-prompt copy, no
   interactive element). It runs standalone on a baked/embedded AI-default
   fingerprint — no external repo required. Internal HTML (dashboards, schedules,
   logs, templates, tests, system output) is skipped. Bypass one file only when
   the slop is intentional (a parody/demo): add `<!-- eyeball-gate-skip -->` (the
   bypass marker keeps its legacy name).

2. **Authoritative design + UX read (required before deploy).** Run the
   `design-room` skill on the page — multi-lens design review + visual-diff critic.
   It judges the AI-design tells AND the UX read (seconds to understand, primary
   action in the first screen, bounce risk, conversion fixes). A website is not
   done until design-room passes (or the founder explicitly signs off on an
   intentional exception).

## What the gate checks (design + UX)

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
