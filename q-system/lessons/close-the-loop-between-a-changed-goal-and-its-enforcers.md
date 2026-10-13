---
id: close-the-loop-between-a-changed-goal-and-its-enforcers
kind: methodology
title: Close the Loop Between a Changed Goal and Its Enforcers
date: 2026-10-12
---

When the goal of a generation pipeline changes (for example from 'write in our usual style' to 'imitate a reference set'), output can keep missing the target even after you edit the prompts. Four checks find why.

1. Audit the enforcers, not just the instructions. Relaxing a rule in the prompt or copy does nothing if validators, filters, option lists, or injected guidance elsewhere still forbid the behavior. List every place that can veto or steer output and reconcile each against the new goal. Look for options that exist but are never selected, since a weighted choice that never fires is a hidden block.

2. Treat the input as the biggest lever on shape. A generator that only receives finished events (cases, incident reports, others' finished work) will produce reports of those events, whatever the style instructions say. If the reference set starts from opinions, questions, or shared moments, add input types of that kind. Layering more style guidance on top of unchanged input rarely changes the structure.

3. Compare distributions, not counts. If you already classify or tag outputs, compare the tag distribution of your drafts against the reference set's, per feature, and flag large ratios. Surface-level metrics such as banned phrases, gate passes, or readability checks can improve while overall shape stays wrong. Make the distribution comparison an automated step in each iteration.

4. Fix the system, not only the latest symptom. When each round patches only the most recent visible flaw, earlier gaps persist and new ones appear. After each round, re-measure against the full reference profile and record which root causes remain open.
