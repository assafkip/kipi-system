## Text in his voice: call the writer lane, never draft it

Rule-ID: RULE-2026-11-18-WRITER-ENTRY
Enforced by: ~/projects/kipi-system/q-system/.q-system/tests/test_writer_lane_entry_points.py

Founder, 2026-11-16, verbatim: "If something is set to go through my voice in any way, it must go through the full voice loop."

- The writer lane lives in the consulting repo. Run it from there: `cd ~/projects/consulting/q-consult`. In any other instance there is no lane, and every text you write is HAND-WRITTEN (last bullet).
- A post, comment, reply, thread, Substack piece or host note on a channel the lane lists: `python3 -m pipeline.social idea --channel <linkedin|threads|reddit|host-note|listing|substack> [--reply] "<his idea>"`. A comment on someone's post is `--reply`. Show what it returns. Do not edit it and do not write a version of your own.
- An email in his voice: `python3 -m pipeline.draft_email --purpose "<why>" --client "<to>" --context-file <notes>`.
- The lane writes the text and records who wrote it. Text you type carries a `hand` receipt, and every exit refuses it (RULE-2026-11-16-V). If the lane refuses or fails, report its message. Do not write the text yourself to get past it.
- Where no lane exists (X, Medium, DMs, talk tracks, slide copy, reports, or any instance but consulting), a working draft for him to read is allowed. Label it HAND-WRITTEN. It does not leave until he runs `python3 -m pipeline.writer_provenance waive` for that one document, from the consulting repo.
- This section overrides any line in a voice skill that says a skill, rather than the lane, writes the text. The voice files a skill loads are the lane's reference and your check, not a licence to draft.
