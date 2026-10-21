---
id: audit-every-path-to-output-for-quality-judges-not-just-the-m
kind: methodology
title: Audit Every Path to Output for Quality Judges, Not Just the Main One
date: 2026-10-19
---

When a system has several routes that produce the same kind of output, quality checks tend to be wired into the route that was built first or is most formalized, while alternate routes quietly skip them. Often the route people use most informally is the one with the least review. Compare each route's checks against the others and ask which routes lack a content-quality judge.

A second trap is mistaking structural validation for quality validation. A status like 'all gates clean' only shows that format, schema, or rule checks passed. It says nothing about whether the output is faithful to the intended style, voice, or meaning. A draft can pass every structural gate and still be wrong, and a repeated 'clean but wrong' result is a sign that acceptance rests on the wrong signal.

How to apply it:
1. List every path that can emit the artifact. For each, record which semantic checks (fidelity, style, correctness review) run on it. Treat any gap as a defect, not a design choice, unless the omission is documented and justified.
2. Share the quality judges across paths through a common interface instead of attaching them to one entry point.
3. Separate the structural pass signal from the quality pass signal in logs and reports, so a green structural result cannot be read as approval of content.
4. Run at least one end-to-end evaluation in which the pipeline generates a real batch and an independent judge scores it. If no build has ever done this, the system's quality is unmeasured.
5. When the same root cause recurs across reviews, escalate it. Restating it with fresh evidence without changing the system produces no improvement, so attach an owner and a concrete fix to it.
