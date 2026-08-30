# rescued/

Code that survived only by accident and had nowhere else to live.

**This directory does not ship.** `kipi update` syncs `q-system/`,
`.claude/{agents,output-styles,rules}/*.md`, `.claude/settings.json` and
`plugins/*/`. A top-level `rescued/` is in none of those sets, which is the
whole reason it is here rather than in `plugins/`.

That placement is deliberate and it is the point: rescuing code and
distributing code are two decisions, and the second one has a 23-instance blast
radius. Putting a rescue straight into `plugins/` would make the fleet-wide
change a side effect of the save. Anything here is preserved, in history, and
inert until someone decides otherwise on purpose.

## memory-lifecycle

Traced 2026-08-14 (sp-067fdd08).

The skeleton once shipped `plugins/memory-lifecycle` as a SYMLINK to
`/Users/assafkip/projects/memory-lifecycle` -- note `assafkip`, an old home
directory, not the current `assafkipnis`. Commit `1be3dfd0` removed it as a
"dead memory-lifecycle symlink", which it was: the target no longer exists, and
there is no copy under the current home and no git repo for it anywhere under
`~/projects`.

But `rsync` had already dereferenced that symlink on the way out. So three
instances -- interview-coach, fractional-cxo and negotiator -- each ended up
holding 10 REAL files, byte-identical across all three (`f1c515ed71aa`). Those
copies were the only ones left anywhere.

They read as instance dirt. `repo-preflight.sh` refuses interview-coach over
them, and `kipi-update.sh` already predicted the class in its own comment:

> an ORPHANED plugin dir -- one an older skeleton shipped and a newer one
> dropped, e.g. plugins/memory-lifecycle -- is no longer covered, so it still
> blocks that instance. That is the right answer.

Correct that it blocks. What nobody noticed is that the orphan was the last
copy, so every obvious way to clear that refusal -- delete the untracked
directory -- destroys a working plugin. Two of the three instances have it
STAGED, which is what a half-finished rescue looks like.

It is not dirt. It is 3 hooks (`session-start`, `compile-memories`,
`detect-pitfalls`), 3 test files, a `rules/memory-freshness.md`, a
`lefthook.yml` and a `plugin.json`. **Its own suite passes: 18 tests, 0
failures**, run before this commit.

### What is NOT decided here

Whether it becomes a managed plugin again. That would ship it to 23 instances
and its `lefthook.yml` could arm hooks nobody reviewed, so it earns its own
issue and its own review. Until then the code is safe and the instances stay
refusing, which is the honest state rather than a swept one.
