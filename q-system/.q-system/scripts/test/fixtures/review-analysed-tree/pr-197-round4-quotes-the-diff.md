## Verdict: REQUEST CHANGES

**DEGRADED**: codex was down, this is the Opus fallback. Not an independent second opinion.

Reviewer engine: `codex`. Full review on disk: `/Users/assafkipnis/.config/kipi/pr-reviews/codex/assafkip_kipi-system__pr-197-20260816-084939.md` (9037 bytes).

```
FINDINGS:
major|read_from_worktree matches the path as a substring, so reading an extracted "$tmp/<path>" copy clears the off-head bucket and posts kipi/reviewer-approved on an unread tree|q-system/.q-system/scripts/pr-review-agent.sh:940
major|the DECLARATION window [^\w]{1,4} cannot span the measured payload's escaped python quoting (\",\" = 5 chars), so the real ASK-830 shape yields zero declarations and the fixture's finding-bearing path fleet-unblock.py is excused|q-system/.q-system/scripts/pr-review-agent.sh:875
major|a review that quotes a sha-qualified git show out of the diff under review is refused with no status and no comment, which wedges the required check on every review of the files this PR adds|q-system/.q-system/scripts/pr-review-agent.sh:965
minor|\btip\b plus a sha within 4 non-word chars turns ordinary prose into a whole-tree declaration with no worktree-read escape, refusing a review that ran no git command|q-system/.q-system/scripts/pr-review-agent.sh:877
END FINDINGS
```

--- reviewer output ---

Repo untouched — only the pre-existing untracked `.scratch-ask830/` (my probes live there). I ran the PR's own suite first (`PASS (21 checks)`), then attacked the guard end-to-end through the real `pr-review-agent.sh` with a stubbed `gh`/`codex`, asserting on the `statuses/` POST rather than on stdout prose.

---

## Findings

### 1. major — `read_from_worktree()` is a substring test, so reading the file you extracted off-head excuses the off-head read

`q-system/.q-system/scripts/pr-review-agent.sh:940` (`read_from_worktree` / `any(path in m.group(1))`)

The escape added in round 3 ("a plain read of a path is a head read") matches the path **anywhere** in a 200-char window after a read verb. `"$tmp/fleet-unblock.py"` contains the substring `fleet-unblock.py`. So the canonical off-head idiom — extract, then read the extraction — clears its own bucket.

The redirect half is not invented: it is fixture line 459 verbatim (`git show 0880859e:fleet-unblock.py > "$review_tmp/fleet-unblock.py"`). The test's own case 5 blesses this exact shape with `@HEAD@` substituted.

```
$ bash .scratch-ask830/adv/harness.sh .scratch-ask830/adv/A2-redirect-only.md A2   # control: no read verb
CASE=A2 rc=1 status_posted=no
    REFUSING: the review of PR #901 read tree 0880859e but the status would name c87245b0.

$ bash .scratch-ask830/adv/harness.sh .scratch-ask830/adv/A3-approve-tmp.md A3     # + one sed of the extracted copy
CASE=A3 rc=0 status_posted=yes
$ cat .scratch-ask830/adv/w-A3/gh-calls.log
api -X POST repos/{owner}/{repo}/statuses/c87245b06e0f2c9e0c4b7a1d3f5e8a2b9c6d4e10 -f state=success -f context=kipi/reviewer-approved -f description=APPROVE ...
```

One `sed` line turns a refusal into `kipi/reviewer-approved=success` on a tree the review never opened. That is the ASK-830 headline defect, with auto-merge on.

### 2. major — the declaration regex cannot span the measured payload's own quoting, and the guard is escaped on the finding-bearing path of the real fixture

`q-system/.q-system/scripts/pr-review-agent.sh:875` (`DECLARATION`, the `[^\w]{1,4}` window)

The real round-2 payload writes its python-quoted show two ways. The caught one is `"git","show"` (3 chars between the tokens). The one that matters is `\",\"` — 5 chars — which the 1-4 window cannot cross. Fed that form alone, the guard finds **zero** declarations:

```
$ bash .scratch-ask830/adv/harness.sh .scratch-ask830/adv/C-real-pyquoted.md C
CASE=C rc=0 status_posted=yes
$ python3 .scratch-ask830/adv/dump.py .scratch-ask830/adv/C-real-pyquoted.md c87245b0...
VERDICT_OUT=''
```

Worse, on the shipped fixture itself the path the wrong findings are *about* is excused, because that unscrubbed escaped form then reads as a `python3` worktree read:

```
$ python3 .scratch-ask830/adv/dump.py q-system/.q-system/scripts/test/fixtures/review-analysed-tree/pr-165-round2-wrong-tree.md c87245b0...
VERDICT_OUT='0880859e'
  path='fleet-unblock.py'      shas=['0880859e' x6]  head_seen=False worktree_read=True    <-- EXCUSED
  path='fleet-reach-audit.py'  shas=['0880859e']     head_seen=False worktree_read=False
  path='test_fleet_unblock.py' shas=['c87245b0']     head_seen=True  worktree_read=True
  path=''                      shas=['0880859e' x2]  head_seen=False worktree_read=None
```

Case 1 goes green off `fleet-reach-audit.py` and the prose-tip bucket, not off the path the per-path argument is written about.

This also falsifies a test claim. `test-review-analysed-tree.sh:~470` says of case 14: *"THE BODY IS COPIED FROM THE MEASURED PAYLOAD, not paraphrased."* It is paraphrased — `"git","show"` where the payload has `\",\"`:

```
$ grep -o 'git\\*"*,*\\*"*show' .../pr-165-round2-wrong-tree.md | sort -u
git","show
git\",\"show          <-- the 5-char form, invisible to the detector
$ grep -o '"git","show"' .../test-review-analysed-tree.sh | head -1
"git","show"
```

Case 14 is green against a shape the producer emits *alongside* one it does not catch.

### 3. major — a review that quotes the code under review is refused, so this PR wedges its own required check

`q-system/.q-system/scripts/pr-review-agent.sh:965` (the `REFUSING` branch)

The comment names this as a known residual. It is not hypothetical here: the PR adds `git show 0880859e:...` and ``PR tip `0880859e` `` to four files, including the reviewer itself (lines 818, 891). Any automated review that quotes them is refused with no status and no comment.

```
$ bash .scratch-ask830/adv/harness.sh .scratch-ask830/adv/D-quote-diff.md D
CASE=D rc=1 status_posted=no
    REFUSING: the review of PR #901 read tree 0880859e but the status would name c87245b0.
```

Two aggravators: the refusal text asserts *"its findings are about a different commit"*, which is false for a quote and misdirects the operator; and `exit 1` fires before the verdict-record writer, so downstream (`review-redrive.py`) sees "never reviewed" rather than "refused". The comment says this is *"Captured as spillover against ASK-830"* — I could not verify that; `.prd-os/spillover.jsonl` does not exist in this worktree.

### 4. minor — `\btip\b` + a nearby sha makes ordinary prose a whole-tree declaration, with no escape

`q-system/.q-system/scripts/pr-review-agent.sh:877` (the `|\btip\b` alternative)

A review that ran no git command at all is refused because it mentions main's tip. The `WHOLE_TREE` bucket is deliberately excluded from the worktree-read escape, so nothing rescues it.

```
$ bash .scratch-ask830/adv/harness.sh .scratch-ask830/adv/B2-tip-tight.md B2
CASE=B2 rc=1 status_posted=no
    REFUSING: the review of PR #901 read tree 85f556dc but the status would name c87245b0.
```
Body: ``Baseline for the comparison below is main's tip (`85f556dc`) ...`` plus one `sed -n '138p' fleet-unblock.py`.

Dropped from major: I constructed this phrasing, and a repo-wide scan found the shape only in the defect fixture itself (`grep -rEon "tip[^a-zA-Z0-9]{1,4}.?[0-9a-fA-F]{7,40}"` → only ASK-830's own text).

---

## What is sound

Attacks that did **not** land, each run:

- **The shipped suite is real.** `PASS (21 checks)` on the working tree; `KIPI_TEST_REVIEWER_REF=85f556dc` drives case 1 red with the live-defect message. Case 5m's mutation genuinely applies and kills case 5 — I watched it report `ok`.
- **Loose prose does not false-refuse.** ``the tip of `origin/main` is 85f556dc`` (wide spacing) → `CASE=B rc=0 status_posted=yes`. The 1-4 window is tight enough to reject the common phrasing; only the parenthesised-backtick form (finding 4) squeaks through.
- **The flag and `-C` widenings work.** `git show --stat`, `--format=`, `git -C <dir> show <sha>:<path>`, bare `git checkout <sha>` all refuse (cases 7, 12, 8).
- **The any-match trap is correctly avoided.** Case 9's mixed body (head read of the test file, off-head read of the finding file) refuses.
- **`HEAD:` and `./` normalization** behave as documented (cases 11, 13).
- **ASK-221 is untouched** and still refuses before dispatch (case 4).
- **The refusal really is total** — no `statuses/` and no `pr comment` in `gh-calls.log` on every refusing case I ran, not just per stdout prose.
- The fixture `PROVENANCE.md` is unusually honest: it states the files are the rendered comment tails, not the on-disk reviews, and names what that costs.

---

## VERDICT: REQUEST CHANGES

Not BLOCK — nothing here is unrecoverable, and the guard is strictly better than the nothing that exists today.

**Fix first: finding 1.** The substring escape is the cheapest defeat of the whole change (`git show <base>:f > $tmp/f` then any read of `$tmp/f`), and it is the shape the measured payload already half-writes. Anchoring `read_from_worktree` on a path *boundary* — the match must not be preceded by `/` — closes 1 and, together with widening the `git`↔`show` window past `\",\"`, closes 2. Finding 3 wants the refusal downgraded to a warning when the only declaration appears inside a blockquote or a fenced diff hunk, or the guard will keep eating its own PR.

FINDINGS:
major|read_from_worktree matches the path as a substring, so reading an extracted "$tmp/<path>" copy clears the off-head bucket and posts kipi/reviewer-approved on an unread tree|q-system/.q-system/scripts/pr-review-agent.sh:940
major|the DECLARATION window [^\w]{1,4} cannot span the measured payload's escaped python quoting (\",\" = 5 chars), so the real ASK-830 shape yields zero declarations and the fixture's finding-bearing path fleet-unblock.py is excused|q-system/.q-system/scripts/pr-review-agent.sh:875
major|a review that quotes a sha-qualified git show out of the diff under review is refused with no status and no comment, which wedges the required check on every review of the files this PR adds|q-system/.q-system/scripts/pr-review-agent.sh:965
minor|\btip\b plus a sha within 4 non-word chars turns ordinary prose into a whole-tree declaration with no worktree-read escape, refusing a review that ran no git command|q-system/.q-system/scripts/pr-review-agent.sh:877
END FINDINGS

