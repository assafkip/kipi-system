---
id: re-point-every-check-when-a-removed-variant-comes-back
kind: methodology
title: Re-point every check when a removed variant comes back
date: 2026-11-10
---

Failure pattern: a variant (a channel, lane, tenant, locale, or similar) is removed. Its data and config get renamed or folded into a sibling. Later the variant is restored, and the content rules are audited for the return. The checks that enforce those rules are never re-pointed, so they quietly run against the wrong target or an empty one.

Why it hides: a check keyed to a variant that has no reference data, rules, or rows usually returns an empty result. An empty result looks like a pass. A check that cannot fail is worse than having no check, because it produces false evidence. Path-based routers and hooks make this worse. They may send the restored variant to a key that resolves to nothing, so the run looks complete.

A second, related failure: work is allowed to be done 'by hand' while automation is not ready. People read that permission as covering verification too. If the full check exists only as several separate tools, a manual run usually executes some of them, sometimes with the wrong parameters. The run still gets recorded as if the whole check passed.

How to prevent it:
1. When you restore or add a variant, list every consumer of the variant key: CLI choices, rule and critic tables, reference corpora, path-to-variant maps in hooks, and gates. Treat 're-point the checks' as its own audit item. It is separate from auditing the rules.
2. Make empty inputs fail loudly. If a validator finds zero rules, zero reference samples, or an unknown variant, it should error or report 'not checked'. It should never return an empty pass.
3. Add a coverage test: for every live variant, each check loads a non-zero rule or reference set and rejects a known-bad sample.
4. Give the full verification a single entry point that runs every part with the right variant and source inputs. Require that entry point for manual work as well as automated work.
5. Record what actually ran: which parts, against which variant, with which inputs. Do not record one 'check passed' flag. Reviewers can then see a partial run as partial.
6. When you grant a temporary manual workaround, say explicitly that it relaxes production, not verification.
