#!/bin/bash
set -euo pipefail
trap "" PIPE
# Never let GPG signing or a credential prompt hang the updater. Updater commits
# still run the instance's active hooks and fail closed when a hook rejects them.
export GIT_TERMINAL_PROMPT=0

# kipi-update.sh - Sync latest kipi-system skeleton into all registered instances
# Usage: ./kipi-update.sh [--dry-run]
#
# Uses git archive + rsync (not git subtree pull) for speed and reliability.
# Instance-specific directories (my-project/, canonical/, memory/, output/, bus/)
# are preserved. Everything else syncs from the skeleton.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REGISTRY="$SCRIPT_DIR/instance-registry.json"
SKELETON_REMOTE="https://github.com/assafkip/kipi-system.git"
SKELETON_BRANCH="main"
# Args in any order: --dry-run and/or --only <name>. Without --only there is no
# way to verify a risky change against ONE repo before the other 22, and a
# staged rollout is the only safe way to ship anything with this blast radius.
DRY_RUN=""
ONLY=""
# --refuse-instance-ahead: abandon an instance BEFORE its pre-sync commit when
# the run would overwrite a file whose instance copy the skeleton never shipped
# (see instance_ahead_scan). Off by default: fleet-wide the hit is usually
# hook churn, and a refusal that fires on 24 instances gets switched off. The
# consulting run script passes it, because there "ahead" has meant real work
# every time (2026-09-06, three times in one day).
REFUSE_INSTANCE_AHEAD=0
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN="--dry-run"; shift ;;
    --refuse-instance-ahead) REFUSE_INSTANCE_AHEAD=1; shift ;;
    --only)
      ONLY="${2:-}"
      if [ -z "$ONLY" ]; then
        echo "ERROR: --only needs an instance name" >&2
        exit 1
      fi
      shift 2
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      echo "Usage: kipi-update.sh [--dry-run] [--only <instance-name>] [--refuse-instance-ahead]" >&2
      exit 1
      ;;
  esac
done

if [ ! -f "$REGISTRY" ]; then
  echo "ERROR: instance-registry.json not found at $REGISTRY"
  exit 1
fi

# Instance-owned subtrees: the skeleton never overwrites these, because each
# instance authors its own. This list was duplicated across four sites (the
# q-system rsync, the dry-run preview rsync, the untracked-collision scan, and
# the staging list) and drifted the moment a sixth entry was added -- the sync
# wrote files it then refused to stage, leaving the instance dirty with no
# commit. One list, four consumers.
# The single answer to "what does kipi update NEVER copy into an instance?".
# validate-separation.py's NON_PROPAGATED_PREFIXES mirrors this list and
# test-gate-13b-scope.py parses this array to block drift between them.
#
# `research` added 2026-07-27 (ASK-191): q-system/research/ held four notes
# written BY and ABOUT this instance (Claude Code workflow learnings, an RCA
# resource list, a SkillOpt paper + PDF) and shipped all four to every
# instance in the fleet, which has no use for them. That is a placement bug,
# and the honest fix is to call the directory instance-owned rather than to
# exclude the path from the gate that noticed.
INSTANCE_OWNED_SUBTREES=(
  my-project
  canonical
  memory
  output
  research
  .q-system/data
  .q-system/agent-pipeline/bus
)

# sp-a4a933ad. A dry run's output was TEXTUALLY IDENTICAL to a real one, because
# dry mode really does perform the update -- against a throwaway clone. It printed
# "OK (686 files updated)" and full commit diffs, and only a single banner 700
# lines earlier said it was a preview.
#
# The trap runs both ways, and the second direction is the dangerous one: a
# reader of a dry log reasonably concludes the instance was mutated, and a reader
# of a REAL log can mistake it for a dry one and believe nothing happened. That
# second reading is the one sp-46c73c76 needed a human to catch -- a guard let
# --dry-run genuinely commit into live instances, and the only defence was
# someone noticing. The log gave them nothing to notice with.
#
# say() tags the script's own lines. dry_filter tags the output of commands we
# shell out to (git prints its own "create mode ..." lines and does not know it
# is being previewed).
say() {
  if [ "${DRY_RUN:-}" = "--dry-run" ]; then
    printf 'DRY | %s\n' "$*"
  else
    printf '%s\n' "$*"
  fi
}

dry_filter() {
  if [ "${DRY_RUN:-}" = "--dry-run" ]; then
    sed 's/^/DRY | /'
  else
    cat
  fi
}

rsync_owned_excludes() {
  local sub
  for sub in "${INSTANCE_OWNED_SUBTREES[@]}"; do printf -- '--exclude=/%s/\n' "$sub"; done
}

pathspec_owned_excludes() {
  local sub
  for sub in "${INSTANCE_OWNED_SUBTREES[@]}"; do printf -- ':(exclude)%s/%s/\n' "$1" "$sub"; done
}

is_instance_owned() {
  local relative="$1" sub
  for sub in "${INSTANCE_OWNED_SUBTREES[@]}"; do
    case "$relative" in "$sub"/*) return 0 ;; esac
  done
  return 1
}

# One answer to "what is a plugin?". Decided independently in four places
# before this: the staging enumeration walked plugins/ wholesale and filtered
# afterwards, the copy loop globbed plugins/*/, and two more sites re-derived
# the same [ -d ] test. The enumeration and the copy disagreeing is what
# produced `pathspec ... did not match any files` -- the stager handed git a
# skeleton entry the syncer had skipped, and that failed the whole config sync.
#
# Scar 2026-07-25: plugins/memory-lifecycle points at
# /Users/assafkip/projects/memory-lifecycle -- an old username, long gone -- so
# all_points_setup and Prodigy_Gold both failed there while instances that
# received the plugin back when the link resolved passed. That asymmetry made a
# skeleton-wide defect look instance-specific.
SKELETON_PLUGIN_ROOT="$SCRIPT_DIR/plugins"

# The ONLY enumeration. `*/` resolves symlinks, so a dangling entry never
# appears here -- which is exactly why the stager can no longer name a path the
# syncer will not write. Both now iterate this.
#
# NUL-separated, not newline. A directory name may legally contain a newline,
# and both consumers read this back with `read -r`; newline framing split such
# a name into two nonexistent plugins, whose rsync then failed and abandoned
# the instance's whole config sync. The pre-consolidation code did not have
# that failure -- it carried names by `find -print0` and by the glob value
# directly -- so newline framing here would have been a real regression.
managed_plugin_names() {
  local plugin_dir
  for plugin_dir in "$SKELETON_PLUGIN_ROOT"/*/; do
    [ -d "$plugin_dir" ] || continue
    plugin_dir="${plugin_dir%/}"
    printf '%s\0' "${plugin_dir##*/}"
  done
}

# Membership in the enumeration above, not an independent `[ -d ]` test. Those
# two disagreed on DOT-named directories -- `*/` skips them, `[ -d ]` does not
# -- so plugins/.hidden/ counted as managed here while the stager and the copy
# loop both ignored it, and the collision guard refused the whole sync over an
# untracked file living there. Nothing ever rsyncs such a directory, so there
# was no collision to protect against: the refusal was a pure false positive,
# and it is the last place the "what is a plugin?" answer was still given twice.
is_managed_plugin_path() {
  local top="${1#plugins/}" name
  top="${top%%/*}"
  [ -n "$top" ] || return 1
  while IFS= read -r -d '' name; do
    [ "$name" = "$top" ] && return 0
  done < <(managed_plugin_names)
  return 1
}

# One answer to "what does the disposable dry-run copy contain?".
#
# Two consumers must agree: the rsync that BUILDS the model, and the symlink
# walk that VETS it. A path the rsync skips can never be reached by a write, so
# refusing on a symlink inside it blocks the instance forever -- personal-brand's
# broken canonical links refused cole-gtm, its parent, for a sync that never
# touches personal-brand. A path the walk skips but the rsync copies is
# unvetted. They were kept in step on 2026-07-25 by passing one list into the
# other as argv, which is a wire between two lists, not one list.
#
# Copy only what this sync can write into. A directory holding its own .git
# below the root is a SEPARATE repository -- in the fleet, another registered
# instance with its own entry and its own update run -- and the sync never
# descends into one; it writes to the subtree prefix, .claude/ and plugins/.
# Scar 2026-07-25: ASK_AI_consultant is /Users/assafkipnis/projects/consulting,
# the parent of ten nested instances, so a faithful whole-tree model wanted
# 21GB of scratch for a sync that touches about 100MB. It ran the data volume
# down to 605MB free before it was killed.
#
# Cached per instance root so two callers cannot observe two different trees.
# PATHS THE SYSTEM ITSELF WRITES INTO AN INSTANCE.
# The dirty-tree guard below refuses ANY tracked modification, which is correct
# for founder work and wrong for the updater's own exhaust: measured 2026-08-04,
# 6 of 23 instances sat 2-6 prd-os versions behind and 4 were blocked SOLELY by
# files this system wrote (the monthly sycophancy stamp, hook state, and a
# plugins/ tree an EARLIER update staged and never committed). The fleet updater
# was blocked by itself, silently. This list is deliberately narrow and explicit:
# anything not named here is treated as founder work and still refuses.
# THE ONE plugin-copy exclusion set (ASK-772). Two consumers derive from it and
# they answer halves of a single question:
#
#   the per-plugin rsync         -- "never copy this into an instance"
#   the source-provenance preflight -- "never alarm about this, because it is
#                                       never copied"
#
# Writing the set down twice is how a secret shipped. `.gitignore:3` is `*.env`
# and kipi-design's cip/generate.py reads a plugin-root .env for API keys, so a
# gitignored plugins/<name>/.env was invisible to `git status` and copied happily
# by rsync into all 23 instances (Codex, PR #149 round 3).
#
# Adding it to ONE consumer swaps one failure for another: rsync-only leaves the
# preflight aborting the whole fleet over a file that can no longer leak (a
# denial of service on every update), preflight-only leaves the leak open and
# silent. Hence one list.
#
# Each entry is "<rsync --exclude pattern>::<regex matching the same paths>".
# Two representations, adjacent, because rsync globs and grep regexes are not
# interconvertible in bash without a converter more fragile than the duplication
# it removes. `::` is the delimiter, not `|`, because the regexes contain `|`.
# test-kipi-update-plugin-excludes.sh drives BOTH consumers off this list and
# fails if they disagree, so agreement is proven behaviourally rather than by
# the two strings having been typed the same.
PLUGIN_COPY_EXCLUDES=(
  "/.git/::(^|/)\.git/"
  "__pycache__/::(^|/)__pycache__/"
  "*.pyc::\.pyc\$"
  ".venv/::(^|/)\.venv/"
  ".pytest_cache/::(^|/)\.pytest_cache/"
  ".env::(^|/)\.env\$"
  ".env.*::(^|/)\.env\."
)

# Was this exact content EVER shipped by the skeleton for this path? (Codex
# review of #151 round 6, major.)
#
# Comparing only against the CURRENT skeleton attributes nothing on the real
# fleet. Instances hold what an earlier fanout wrote -- ASK-728 pushed prd-os
# 0.27.1 -- while the skeleton has since moved to 0.27.3. Measured on a live
# blocked instance 2026-08-14: both plugins/prd-os/.claude-plugin/plugin.json and
# plugins/prd-os/tests/test_judgment_compiler.py DIFFER from the current
# skeleton, so a current-only test calls both founder work and the instance stays
# blocked on every unattended update. The fix would have unblocked zero
# instances, which is the same trap that killed ASK-775's first theory.
#
# The honest question is not "is this the newest skeleton content" but "did this
# content come from the fleet at all". A blob the skeleton ever committed at this
# path did. A founder edit essentially never collides with a historical skeleton
# blob, because it would have to reproduce a shipped revision byte for byte.
#
# Bounded on purpose: only paths already known dirty reach here (a handful per
# instance), and the walk is limited to commits touching that one path.
# "SHIPPED" IS THE FAN-OUT BRANCH, NOT EVERY REF IN THE CLONE (Codex review of
# #151 round 7, major). The first version walked `rev-list --all`, which includes
# unmerged feature branches, other people's work, and anything else this clone
# happens to hold. A blob that only ever existed on a branch was never shipped to
# any instance, so accepting it lets an unattended update commit over founder
# work that merely resembles someone's WIP. The fleet fans out from
# $SKELETON_BRANCH and only from there, so that is the boundary.
#
# origin/<branch> is preferred over the local branch deliberately: the ASK-762
# preflight already refuses to run unless HEAD equals origin/$SKELETON_BRANCH, so
# the remote ref is the one with a proven meaning. The local fallbacks exist for
# fixtures and clones with no origin, where there is no remote to disagree with.
fleet_ship_ref() {
  local ref
  for ref in "refs/remotes/origin/$SKELETON_BRANCH" "refs/heads/$SKELETON_BRANCH" HEAD; do
    if git -C "$SCRIPT_DIR" rev-parse --verify --quiet "$ref" >/dev/null 2>&1; then
      printf '%s\n' "$ref"
      return 0
    fi
  done
  return 1
}

fleet_authored_blob() {
  local rel="$1" file="$2" blob candidate commit ship_ref
  ship_ref="$(fleet_ship_ref)" || return 1
  blob="$(git -C "$SCRIPT_DIR" hash-object -- "$file" 2>/dev/null || true)"
  [ -n "$blob" ] || return 1
  while IFS= read -r commit; do
    [ -n "$commit" ] || continue
    candidate="$(git -C "$SCRIPT_DIR" rev-parse "$commit:$rel" 2>/dev/null || true)"
    [ "$candidate" = "$blob" ] && return 0
  done < <(git -C "$SCRIPT_DIR" rev-list "$ship_ref" -- "$rel" 2>/dev/null || true)
  return 1
}

plugin_copy_rsync_flags() {
  local entry
  for entry in "${PLUGIN_COPY_EXCLUDES[@]}"; do
    printf -- '--exclude=%s\n' "${entry%%::*}"
  done
}

# "Instance ahead of the skeleton" (sp-1ad08728): a file this run would
# OVERWRITE whose instance copy is content the skeleton never shipped for that
# path. Three times on 2026-09-06 the sync replaced exactly that and the
# instance's own gates went red only after the rsync had landed: the voiceloop
# engine (extra modules), voice-stop-gate.py (five extra defs, founder_typed_text
# among them, port still on an open PR) and voice-lint's BANNED_WORDS (two
# entries removed after measuring the founder's own corpus). Nothing in the
# updater said so beforehand; the dry run listed the files as changes like any
# other and the refusal came from a downstream gate with the damage done.
#
# The question is answered by fleet_authored_blob, the shipped-blob check the
# updater already uses for authorship: bytes equal to ANY skeleton version of
# the path are never "ahead" (a stale instance is behind, not ahead; a hook
# that committed the updater's own bytes is neither). Only content the skeleton
# never shipped counts, which is what makes this language-agnostic: a list, a
# rule, a script all read the same way. The candidate set comes from the same
# itemized rsync previews the real run uses, with the same excludes, so it
# cannot drift from what the run would change.
#
# Report by default, one line per file, and again in the run summary next to
# Updated/Failed, because a 1,100-line dry log hid rewritten=8 for a morning.
# --refuse-instance-ahead turns a hit into an abandon BEFORE the pre-sync
# commit: nothing staged, nothing deleted.
INSTANCE_AHEAD_REPORT=""
INSTANCE_AHEAD_TOTAL=0
INSTANCE_AHEAD_HITS=0

# $1 skeleton source dir for one scope, $2 the instance dir it lands in,
# $3 the scope's skeleton-relative prefix (for fleet_authored_blob),
# $4 the scope's instance-relative prefix ("" at the instance root),
# $5 the instance root (for git ls-files), $6 the instance name,
# $7.. the rsync flags the real run uses for this scope.
instance_ahead_scan() {
  local src="$1" dest="$2" skel_rel="$3" inst_rel="$4" root="$5" name="$6"
  shift 6
  [ -d "$src" ] && [ -d "$dest" ] || return 0
  local line rel inst_file skel_file shown detail
  while IFS= read -r line; do
    case "$line" in
      '>f+++++++++'*) continue ;;
      '>f'*) ;;
      *) continue ;;
    esac
    rel="${line#* }"
    inst_file="$dest/$rel"
    skel_file="$src/$rel"
    [ -f "$inst_file" ] && [ -f "$skel_file" ] || continue
    shown="$rel"
    [ -n "$inst_rel" ] && shown="$inst_rel/$rel"
    # Tracked only: an untracked or unstaged local edit is the dirty guard's
    # business further down, and it refuses the whole instance.
    git -C "$root" ls-files --error-unmatch -- "$shown" >/dev/null 2>&1 || continue
    fleet_authored_blob "$skel_rel/$rel" "$inst_file" && continue
    detail="$(python3 "$SCRIPT_DIR/kipi-update-instance-ahead.py" "$inst_file" "$skel_file" 2>/dev/null)" \
      || detail="differs"
    echo "  instance ahead: $shown ($detail)"
    INSTANCE_AHEAD_HITS=$((INSTANCE_AHEAD_HITS + 1))
    INSTANCE_AHEAD_TOTAL=$((INSTANCE_AHEAD_TOTAL + 1))
    INSTANCE_AHEAD_REPORT="$INSTANCE_AHEAD_REPORT
    - $name: $shown ($detail)"
  done < <(rsync -ain "$src/" "$dest/" "$@" 2>/dev/null || true)
}

# Every scope the run writes, from the same sources: the skeleton's committed
# q-system/ (git archive HEAD, as the real sync uses), each managed plugin from
# the working tree (as the plugins rsync uses), and the three .claude/ md dirs
# (copied per file). $1 instance path, $2 subtree prefix, $3 instance name.
instance_ahead_preflight() {
  local path="$1" prefix="$2" name="$3" src_tmp dest kind
  INSTANCE_AHEAD_HITS=0
  src_tmp="$(mktemp -d)"
  if git -C "$SCRIPT_DIR" archive --format=tar HEAD -- q-system/ 2>/dev/null \
      | tar -x -C "$src_tmp" 2>/dev/null; then
    dest="$path"
    [ -n "$prefix" ] && dest="$path/$prefix"
    # shellcheck disable=SC2046
    instance_ahead_scan "$src_tmp/q-system" "$dest" "q-system" "$prefix" "$path" "$name" \
      $(rsync_owned_excludes)
  else
    echo "  WARN: instance-ahead scan skipped for q-system (archive export failed)"
  fi
  rm -r -- "$src_tmp"
  if [ -d "$SKELETON_PLUGIN_ROOT" ]; then
    while IFS= read -r -d '' plugin_name; do
      # shellcheck disable=SC2046
      instance_ahead_scan "$SKELETON_PLUGIN_ROOT/$plugin_name" "$path/plugins/$plugin_name" \
        "plugins/$plugin_name" "plugins/$plugin_name" "$path" "$name" $(plugin_copy_rsync_flags)
    done < <(managed_plugin_names)
  fi
  for kind in agents output-styles rules; do
    instance_ahead_scan "$SCRIPT_DIR/.claude/$kind" "$path/.claude/$kind" ".claude/$kind" \
      ".claude/$kind" "$path" "$name" --include='*.md' --exclude='*'
  done
}

plugin_copy_filter_regex() {
  local entry out=""
  for entry in "${PLUGIN_COPY_EXCLUDES[@]}"; do
    out="${out:+$out|}${entry#*::}"
  done
  printf '%s\n' "$out"
}

SYSTEM_OWNED_PATHS=(
  "q-system/memory/.sycophancy-monthly-stamp"
  "q-system/.q-system/claude-integrity-baseline.json"
  ".claude/state/stop-gate-firings.json"
)

# INSTANCE-LOCAL, AND COMMITTING IT IS WHAT DESTROYS IT (measured 2026-08-14, 6 instances).
#
# Measured 2026-08-14: 6 instances lost their integrity baseline to `kipi update`
# and the tripwire then refused EVERY tool call on them
# (claude-integrity-tripwire.py: "BASELINE MISSING on an armed tree", exit 2).
# The chain is a loop this file closes on itself:
#
#   1. the block below COMMITS the baseline, so it becomes tracked;
#   2. the skeleton's `git archive HEAD` does not contain it (.gitignore:116 --
#      it is instance-local by ASK-282, and a shared baseline can never match a
#      per-instance .claude/settings.json);
#   3. kipi-update-preserve-scan.py rule 3 protects only paths the skeleton NEVER
#      tracked. The skeleton DID track this one (e25734cb / 629d01b2) and then
#      deleted it, so the scan reads a deliberate skeleton deletion and correctly
#      lets `rsync --delete` propagate it.
#
# Step 3 is not the bug and must not be "fixed": a never-delete exemption there
# would make preserve-scan lie about its own rule, which exists so real skeleton
# deletions reach the fleet. The two instances that escaped did so only because
# their baseline was still untracked, which is the state this list restores.
#
# It is a SEPARATE list applied AFTER both feeders, not an edit to the array
# above, and that is the whole point. Two independent things append to
# sys_owned_dirty: this hand list, and auto-commit.py --system-state, which
# classifies the entire tree. Removing the path from the array alone leaves the
# classifier free to re-add it -- and the classifier demonstrably does exactly
# that, having committed .claude-integrity-armed (a path this array never named)
# during the same 2026-08-14 sweep. One filter, past both, or it is not a fix.
SYSTEM_NEVER_COMMIT=(
  "q-system/.q-system/claude-integrity-baseline.json"
  "q-system/.q-system/claude-integrity-baseline.json.lock"
  # THE COMMENT ABOVE NAMED THIS PATH AND THE ARRAY DID NOT, AND THAT GAP COST
  # 13 OF 22 INSTANCES (measured 2026-08-14 by fleet-reach-audit.py, ASK-797).
  #
  # The marker's one line is a TIMESTAMP -- "armed 2026-08-14T20:13:59Z" -- that
  # claude-integrity-tripwire.py rewrites every time it arms. So committing it is
  # not merely untidy, it is self-poisoning, and the run that does it is the run
  # that blocks the next one:
  #
  #   13:10  this updater commits the marker as system state
  #   20:13  the tripwire arms and rewrites the timestamp
  #   next run: tracked, dirty, inside the synced prefix -> the dirty-tree guard
  #             refuses, forever, and the instance never receives another update
  #
  # Verified in two registered instances (commits bdcf7a2 and 50040a6): the sole
  # commit that ever added the path is this updater's own "commit system-written
  # state before skeleton sync". Nothing founder-authored is in the loop at all.
  #
  # The skeleton has gitignored this path since .gitignore:123 and has never
  # tracked it. Instances only carry it tracked because auto-commit.py classifies
  # it as `chore` exhaust and no filter stopped the commit -- which is exactly the
  # "one filter, past both" the comment above demands. Naming it here puts it past
  # both: the classifier can still propose it, and the chokepoint now declines.
  "q-system/.q-system/.claude-integrity-armed"
)
# Skeleton-managed plugin dirs are appended at run time from the SAME
# enumeration the sync itself uses (managed_plugin_names), never as a blanket
# "plugins" entry. The blanket version classified the WHOLE tree as system-owned
# and would have committed founder edits inside an instance-LOCAL plugin, which
# the sync does not manage (Codex review, PR #98 round 2). One enumeration, one
# meaning of "managed".
#
# Consequence, accepted deliberately: an ORPHANED plugin dir -- one an older
# skeleton shipped and a newer one dropped, e.g. plugins/memory-lifecycle -- is
# no longer covered, so it still blocks that instance. That is the right answer.
# An orphan is genuinely ambiguous (is it founder-adopted or dead weight?) and
# now gets NAMED in the run summary instead of silently skipped.
system_owned_paths_for_run() {
  local plugin_name
  printf '%s\n' "${SYSTEM_OWNED_PATHS[@]}"
  while IFS= read -r -d '' plugin_name; do
    printf 'plugins/%s\n' "$plugin_name"
  done < <(managed_plugin_names)
}
FAILED_NAMES=""

MODEL_SKIPPED_ROOT=""
MODEL_SKIPPED_PATHS=()

model_skip_scan() {
  local instance_root="$1" nested_git nested_rel
  [ "$MODEL_SKIPPED_ROOT" = "$instance_root" ] && return 0
  MODEL_SKIPPED_PATHS=()
  while IFS= read -r nested_git; do
    nested_rel="${nested_git#"$instance_root"/}"
    nested_rel="${nested_rel%/.git}"
    [ -n "$nested_rel" ] || continue
    [ "$nested_rel" != "$nested_git" ] || continue
    # Tracked-ness is the line, not nested-ness. A SUBMODULE is a gitlink in
    # this repo's index (mode 160000), so dropping it from the model makes git
    # report it DELETED and the dirty-tree guard refuses -- the instance can
    # never update. A separate project that merely lives under this path is
    # untracked, and skipping it is the whole point.
    #
    # Scar 2026-07-25: the exclusion shipped without this check and bricked
    # Alice, which carries three submodules under q-investigate/tools/.
    if git -C "$instance_root" ls-files --error-unmatch -- "$nested_rel" \
        >/dev/null 2>&1; then
      continue
    fi
    MODEL_SKIPPED_PATHS+=("$nested_rel")
  done < <(find "$instance_root" -mindepth 2 -maxdepth 5 -name .git -print 2>/dev/null)
  MODEL_SKIPPED_ROOT="$instance_root"
}

# Projection A of that one scan. It carries `.git` and the walk's projection
# does NOT, on purpose: the model receives .git by `cp -a` on the has-a-.git
# branch only, so the rsync must never copy it while the walk must still vet
# the instance's own .git -- a dangling link at .git/hooks/* is refused today
# and must stay refused. Collapsing the two into one list would either delete
# that refusal or leave them divergent, which is the defect this replaces.
# Projection B is MODEL_SKIPPED_PATHS itself, read directly by the walk.
model_rsync_excludes() {
  local instance_root="$1" nested_rel
  # Re-enters the one scan rather than trusting the caller to have run it, so
  # the projection cannot be built against a stale or unpopulated list. The
  # scan is cached per root, so this costs nothing on the second call.
  model_skip_scan "$instance_root"
  # BUILD CACHES ARE NOT STATE. The model exists to preview what the skeleton
  # sync would do, and the sync never touches these -- copying them is pure
  # cost. Measured 2026-08-04: the accountant instance carried an 8.7G
  # src-tauri/target tree, the copy hit "No space left on device" at 92% disk,
  # and the instance reported FAILED in --dry while the real run had updated it
  # fine. So --dry manufactured a false failure out of disk pressure alone.
  # Every path here is regenerable by its own toolchain and gitignored.
  MODEL_EXCLUDES=(--exclude=".git")
  # sp-f6733ee3. The comment above says "every path here is regenerable by its
  # own toolchain and gitignored". That is false for some instances, and the
  # exclusion list is the only thing that believed it. Measured 2026-08-10:
  # gtm-partner TRACKS 28 files under these names (build/index.html,
  # build/styles.css, a design-room template's build/art/, a released
  # dist/ tarball) and interview-coach tracks 1. Stripping a TRACKED file from
  # the model makes the model's git see it as deleted, so --dry reports a
  # deletion that the real sync would never perform.
  #
  # A fix that relocated its own bug: sp-b2f16971 (the model copied 8.7G of
  # caches) was closed by ADDING this list, and the list is what manufactures
  # the false deletions. So the test is not the name, it is whether git tracks
  # anything there. Untracked caches -- the 8.7G that motivated the list -- are
  # still stripped, which is the whole point of keeping the list at all.
  local instance_tracked tracked_nl cache_dir
  instance_tracked="$(git -C "$1" ls-files 2>/dev/null || true)"
  # Leading newline so a first-line match and a mid-path match use one pattern.
  # A `case` glob rather than `printf | grep -q`: grep -q closes the pipe on its
  # first match, the writer takes SIGPIPE, and pipefail reports 141 for the
  # whole pipeline -- which would silently invert this test.
  tracked_nl=$'\n'"$instance_tracked"
  for cache_dir in target node_modules .venv venv __pycache__ .next dist build .pytest_cache .mypy_cache .ruff_cache; do
    case "$tracked_nl" in
      *$'\n'"$cache_dir"/*|*"/$cache_dir"/*)
        # Tracked content lives here. Excluding it would fake a deletion.
        continue
        ;;
    esac
    MODEL_EXCLUDES+=(--exclude="$cache_dir/")
  done
  for nested_rel in ${MODEL_SKIPPED_PATHS[@]+"${MODEL_SKIPPED_PATHS[@]}"}; do
    MODEL_EXCLUDES+=(--exclude="/$nested_rel/")
  done
}

echo "=== Kipi System Update ==="
echo "Remote: $SKELETON_REMOTE"
echo "Branch: $SKELETON_BRANCH"
[ "$DRY_RUN" = "--dry-run" ] && echo "MODE: DRY RUN (no changes)"
echo ""

# Preflight: refuse to propagate if an enforcement hook is wired in the skeleton's
# runtime .claude/settings.json but missing from settings-template.json -- it would
# ship its SCRIPT to the fleet while the SWITCH never propagates (instances rebuild
# settings from the template only). Scar 2026-06-30: 8 hooks ran dead in 18/18
# instances exactly this way (lessons-validator, wiring-check, +6).
SYNC_CHECK="$SCRIPT_DIR/q-system/.q-system/scripts/settings-template-sync-check.py"
if [ -f "$SYNC_CHECK" ]; then
  if ! CLAUDE_PROJECT_DIR="$SCRIPT_DIR" python3 "$SYNC_CHECK" --check; then
    echo ""
    echo "ABORT: .claude/settings.json and settings-template.json are out of sync (above)."
    echo "Add the stranded hook(s) to settings-template.json before propagating,"
    echo "or kipi update would ship dead enforcement to every instance."
    exit 1
  fi
fi

# Preflight: refuse to fan a leaked instance fact out to every instance.
#
# NOT wrapped in `[ -f "$LEAK_GATE" ]`, unlike the settings check directly
# above. That guard turns a DELETED script into a green run, which is the exact
# failure this gate exists to prevent, one level up: the gate's own absence
# must stop the fleet, not wave it through. A leak caught after the fan-out is
# a post-mortem -- 23 repos already hold the fact, each in a commit.
LEAK_GATE="$SCRIPT_DIR/q-system/.q-system/scripts/propagation-leak-gate.py"
if [ ! -f "$LEAK_GATE" ]; then
  echo ""
  echo "ABORT: propagation leak gate missing at $LEAK_GATE"
  echo "It is fail-closed on purpose. Restore it or revert; do not proceed"
  echo "with 23 instances unchecked."
  exit 1
fi
# The gate reads the INDEX; this sync copies HEAD via `git archive`. Staging a
# fix without committing it decouples the two and HEAD wins, so the gate clears
# bytes nobody is propagating while the leak ships. Worse, a `git rm --cached`
# file has NO index entry at all and is never even enumerated. Refuse the
# divergence rather than scan the wrong tree.
if ! git -C "$SCRIPT_DIR" diff --cached --quiet HEAD -- q-system/ 2>/dev/null; then
  echo ""
  echo "ABORT: q-system/ is staged but not committed."
  echo "The leak gate scans the index and this sync copies HEAD, so they must"
  echo "agree. Commit or reset q-system/ before propagating."
  exit 1
fi

# Proof of EXECUTION, not proof of existence. `[ ! -f ]` above only closes the
# deleted case: a zero-byte .py is a valid program that exits 0, so a truncated
# or comment-only gate would pass with no output at all -- quieter, and likelier
# (interrupted write, bad merge, full disk), than deletion. Require the gate to
# state its own verdict before its exit code is believed.
# `if` form, not a bare assignment: under `set -e` a failing command
# substitution kills the script AT the assignment, so the gate's own abort
# message would never print and the run would die silent.
if LEAK_OUT="$(python3 "$LEAK_GATE" --check --repo-root "$SCRIPT_DIR" 2>&1)"; then
  LEAK_RC=0
else
  LEAK_RC=$?
fi
printf '%s\n' "$LEAK_OUT"
if ! printf '%s' "$LEAK_OUT" | grep -q "^propagation leak gate: "; then
  echo ""
  echo "ABORT: the propagation leak gate did not report a verdict."
  echo "It exists but did not run as a gate. Restore it or revert; do not"
  echo "proceed with 23 instances unchecked."
  exit 1
fi
if [ "$LEAK_RC" -ne 0 ]; then
  echo ""
  echo "ABORT: a fact absent from the propagation baseline would be copied into"
  echo "every instance (named above). Remove it, replace it with a placeholder,"
  echo "or re-baseline explicitly after a human reads each new entry."
  exit 1
fi

# Preflight: the bytes fanned out must be the bytes that were reviewed.
#
# q-system/ is copied with `git archive` from HEAD, and the two checks above
# refuse when the index and HEAD disagree. `.claude/` and `plugins/` get no
# such protection: they rsync from $SCRIPT_DIR -- the WORKING TREE, on whatever
# branch it is checked out on. Nothing asked which branch that was.
#
# Scar 2026-08-14 (sp-ea9c1628): kipi-system sat on sana/ask-728-plugin-parity
# holding an uncommitted partial forward-port of voiceloop/selector.py -- the
# nearest-length ranking without the anchor-survives fix Codex caught in #147
# and main already carried. A run from that state writes code strictly OLDER
# than main into every config-sync instance and prints PASS. Silent, plausible,
# and 23 repos wide; hence a preflight rather than a habit.
#
# Two halves, deliberately different in what they need:
#
#   DIRTY runs always. Staleness against HEAD needs no remote to be wrong, and
#   an untracked file under plugins/ rsyncs just as happily as a tracked one --
#   `git diff` is blind to it, so it is asked for by name.
#
#   BRANCH arms only when an `origin` remote exists. SKELETON_BRANCH names a
#   branch ON origin; a repo with no origin has no main to be stale against,
#   and every kipi-update fixture in q-system/.q-system/scripts/test/ is
#   exactly that repo. It announces the disarm rather than going quiet, because
#   a silent guard is indistinguishable from one that passed.
#
# Pinned by test-kipi-update-source-provenance.sh.
# SCOPED TO WHAT ACTUALLY RSYNCS, not to `.claude/` wholesale. The config sync
# copies .claude/{agents,output-styles,rules}/*.md and .claude/settings.json --
# nothing else under .claude/ ever reaches an instance. A wholesale check would
# abort on .claude/worktrees/ and settings.local.json, which protect nothing and
# would get the guard switched off. (The worktrees dir is ignored only in this
# clone's .git/info/exclude, so on a fresh clone the wholesale form fires on the
# repo's own worktree convention.) plugins/ stays whole: the syncer walks each
# managed plugin with `find`, so an untracked file inside one is copied too.
# IGNORED IS NOT ABSENT (Codex review of #149 round 3, major). `git status` hides
# ignored files by default, but rsync does not: the plugin copy excludes only
# .git/, __pycache__/, *.pyc, .venv/ and .pytest_cache/, so a gitignored
# plugins/<name>/.env goes to all 23 instances. That is not hypothetical --
# `.gitignore:3` is `*.env` and kipi-design's cip/generate.py reads a plugin-root
# .env for API keys. A guard that claims to cover what rsyncs has to look where
# rsync looks, so plugins/ is scanned with --ignored=matching and then filtered
# by the SAME five exclusions the rsync uses. Measured on this repo the day it
# was written: 0 such files, so the guard arrives green and fires on the next one.
#
# The .claude half is the mirror-image mistake, caught as a minor in the same
# round: it was recursive where the copy is a flat `*.md` glob, so a nested or
# non-md file raised an alarm nothing could act on. `:(glob)` makes `*` stop at
# the directory separator; a bare pathspec would let it match subdirectories and
# re-widen the very scope this narrows.
SYNC_SCOPE_DIRTY="$(
  {
    git -C "$SCRIPT_DIR" status --porcelain -- \
      ':(glob).claude/agents/*.md' \
      ':(glob).claude/output-styles/*.md' \
      ':(glob).claude/rules/*.md' \
      .claude/settings.json 2>/dev/null || true
    git -C "$SCRIPT_DIR" status --porcelain --ignored=matching -- plugins \
      2>/dev/null || true
  } | sed 's/^...//' \
    | grep -vE "$(plugin_copy_filter_regex)" || true
)"
if [ -n "$SYNC_SCOPE_DIRTY" ]; then
  echo ""
  echo "ABORT: the skeleton's .claude/ or plugins/ is not committed."
  echo "These rsync from the working tree, so every line below would reach all"
  echo "registered instances without ever having passed a review:"
  printf '%s\n' "$SYNC_SCOPE_DIRTY" | sed 's/^/  /'
  echo "Commit them, or restore them from ${SKELETON_BRANCH}, before propagating."
  exit 1
fi

if git -C "$SCRIPT_DIR" remote get-url origin >/dev/null 2>&1; then
  SKELETON_HEAD_BRANCH="$(git -C "$SCRIPT_DIR" symbolic-ref --short -q HEAD || true)"
  if [ "$SKELETON_HEAD_BRANCH" != "$SKELETON_BRANCH" ]; then
    echo ""
    echo "ABORT: the skeleton is not on $SKELETON_BRANCH."
    if [ -z "$SKELETON_HEAD_BRANCH" ]; then
      echo "  HEAD is detached."
    else
      echo "  HEAD is on $SKELETON_HEAD_BRANCH."
    fi
    echo ".claude/ and plugins/ rsync from this working tree, so a feature"
    echo "branch fans its unmerged -- or merely older -- copy to every instance."
    echo "Check out $SKELETON_BRANCH and pull before propagating."
    exit 1
  fi

  # THE NAME IS NOT THE COMMIT (Codex review of #149, major). Being ON main says
  # nothing about being AT main: a local main 15 commits behind origin passes a
  # name check and fans a reviewed-months-ago copy to 23 instances, which is the
  # exact failure this preflight exists to stop, one level up. It also catches
  # the mirror case -- local commits that were never pushed, so the bytes going
  # out were never reviewed by anyone.
  #
  # Measured 2026-08-14 on this very repo: the ask-728 checkout was 2 ahead and
  # 15 behind origin, carrying an unattended auto-commit that never left the
  # machine (rescued as PR #150).
  #
  # Fail closed when the comparison cannot be made. GIT_TERMINAL_PROMPT=0 is
  # exported at the top of this script, so an unreachable origin errors out
  # rather than hanging on credentials. Fanning to 23 repos on an unproven
  # source is worse than not fanning at all.
  if ! git -C "$SCRIPT_DIR" fetch origin "$SKELETON_BRANCH" --quiet 2>/dev/null; then
    echo ""
    echo "ABORT: could not fetch origin/$SKELETON_BRANCH."
    echo "Without it there is no way to prove this working tree matches what was"
    echo "reviewed. Fix connectivity, or propagate later; do not fan 23 repos"
    echo "from an unverified source."
    exit 1
  fi
  SKELETON_LOCAL_SHA="$(git -C "$SCRIPT_DIR" rev-parse HEAD 2>/dev/null || true)"
  SKELETON_REMOTE_SHA="$(
    git -C "$SCRIPT_DIR" rev-parse "refs/remotes/origin/$SKELETON_BRANCH" 2>/dev/null || true
  )"
  if [ -z "$SKELETON_LOCAL_SHA" ] || [ -z "$SKELETON_REMOTE_SHA" ]; then
    echo ""
    echo "ABORT: could not resolve HEAD or origin/$SKELETON_BRANCH to a commit."
    exit 1
  fi
  if [ "$SKELETON_LOCAL_SHA" != "$SKELETON_REMOTE_SHA" ]; then
    SKELETON_DRIFT="$(
      git -C "$SCRIPT_DIR" rev-list --left-right --count \
        "HEAD...refs/remotes/origin/$SKELETON_BRANCH" 2>/dev/null || printf '? ?'
    )"
    echo ""
    echo "ABORT: the skeleton is on $SKELETON_BRANCH but not AT origin/$SKELETON_BRANCH."
    echo "  local:  $SKELETON_LOCAL_SHA"
    echo "  origin: $SKELETON_REMOTE_SHA"
    echo "  ahead/behind: $SKELETON_DRIFT"
    echo "Ahead means bytes nobody reviewed; behind means bytes that were"
    echo "superseded. Either way the fleet would get something other than"
    echo "$SKELETON_BRANCH. Push or pull before propagating."
    exit 1
  fi
else
  echo "skeleton branch check: DISARMED (no origin remote; nothing to be stale against)"
fi

PASS=0
FAIL=0
SKIP=0
GATE_FAIL=""
UNDECLARED=""
MODEL_RUN=0
DRY_MODEL_ROOT=""
ARCHIVE_TMP=""
DRY_TMP=""

cleanup_dry_model() {
  if [ "${MODEL_RUN:-0}" = "1" ] && [ -n "${DRY_MODEL_ROOT:-}" ]; then
    cd "$SCRIPT_DIR"
    rm -r -- "$DRY_MODEL_ROOT"
    DRY_MODEL_ROOT=""
    MODEL_RUN=0
    # The isolated hooksPath pointed into the model that just went away.
    unset GIT_CONFIG_COUNT GIT_CONFIG_KEY_0 GIT_CONFIG_VALUE_0
  fi
}

cleanup_updater_temps() {
  if [ -n "${ARCHIVE_TMP:-}" ] && [ -d "$ARCHIVE_TMP" ]; then
    rm -r -- "$ARCHIVE_TMP"
    ARCHIVE_TMP=""
  fi
  if [ -n "${DRY_TMP:-}" ] && [ -d "$DRY_TMP" ]; then
    rm -r -- "$DRY_TMP"
    DRY_TMP=""
  fi
  if [ -n "${CHECKPOINT_DIR:-}" ] && [ -d "$CHECKPOINT_DIR" ]; then
    rm -r -- "$CHECKPOINT_DIR"
    CHECKPOINT_DIR=""
  fi
  clear_run_marker
  cleanup_dry_model
}

# Checkpoint and restore: a failed run must leave the instance as it found it.
#
# 24 places give up on an instance, and none of them recorded its state first,
# so any failure after the first write left debris that a human had to dig out
# by hand -- and, worse, that the dirty-tree guard then read as founder work,
# so EVERY later run refused too. One failure took the instance out of the
# fleet permanently. Scars: sp-5f2d2a63 (a failed staging left 43 files
# staged) and sp-e244e821 (a failed sync left tracked skeleton files modified).
#
# Restoring is exact, not lossy, because the dirty-tree guard has already
# proved the tree clean at checkpoint time: everything discarded here is
# something THIS run wrote. No hard reset and no clean subcommand is used.
CHECKPOINT_DIR=""
CHECKPOINT_TARGET=""
CHECKPOINT_PREFIX=""

# Is a rebase in flight in this instance?
#
# `--path-format=absolute` is not decoration: the plain `--git-path` form
# returns a RELATIVE path, which `[ -d ]` would then resolve against the
# SHELL's cwd instead of the instance -- correct only by accident, and only
# while the caller happens to have cd'd there.
instance_rebase_in_flight() {
  local target="$1" state resolved
  for state in rebase-merge rebase-apply; do
    resolved="$(
      git -C "$target" rev-parse --path-format=absolute --git-path "$state" \
        2>/dev/null || true
    )"
    if [ -n "$resolved" ] && [ -d "$resolved" ]; then
      return 0
    fi
  done
  return 1
}

# The untracked inventory, SCOPED to what this sync is allowed to write.
# Checkpoint and restore both call it, so their lists are comparable -- and,
# far more importantly, restore can never even propose deleting a path the
# sync was never permitted to touch. An unscoped inventory made restore delete
# files written into memory/ and output/ DURING the run (an instance
# pre-commit hook emitting a report is enough), which is unrecoverable: they
# are untracked, so git has no copy, and $SNAP only holds what existed before
# the rsync.
#
# `--others` without `--exclude-standard` on purpose: a gitignored file under
# the synced tree is still real state that rsync --delete would remove.
checkpoint_untracked_list() {
  local target="$1"
  [ -n "${CHECKPOINT_PREFIX:-}" ] || return 0
  ( cd "$target" && git ls-files -z --others -- \
      "$CHECKPOINT_PREFIX/" .claude/ plugins/ \
      $(pathspec_owned_excludes "$CHECKPOINT_PREFIX") 2>/dev/null )
}

checkpoint_instance() {
  local target="$1"
  CHECKPOINT_TARGET=""
  CHECKPOINT_PREFIX="$2"
  # Drop the previous instance's dir now rather than at EXIT; cleanup only ever
  # removed the last one, so a 23-instance run orphaned 22.
  if [ -n "${CHECKPOINT_DIR:-}" ] && [ -d "$CHECKPOINT_DIR" ]; then
    rm -r -- "$CHECKPOINT_DIR"
  fi
  CHECKPOINT_DIR="$(mktemp -d)" || return 1
  checkpoint_untracked_list "$target" > "$CHECKPOINT_DIR/untracked" || return 1
  # Whether a rebase was ALREADY in flight before this run touched anything.
  #
  # It is not enough to assume the zombie-rebase cleanup above already dealt
  # with it. That cleanup tests "$path/.git/rebase-merge" as a directory, which
  # is ENOTDIR when .git is a FILE -- a linked worktree -- so it silently does
  # nothing there. Meanwhile a `rebase -i` paused at `edit` or `break` leaves a
  # CLEAN index and worktree, so the dirty-tree guard passes and the run
  # proceeds with the founder's rebase still open. Aborting that would destroy
  # their work AND rewind this run's own landed commit. Restore clears only
  # what this run created.
  : > "$CHECKPOINT_DIR/inflight"
  if instance_rebase_in_flight "$target"; then
    printf 'rebase\n' > "$CHECKPOINT_DIR/inflight"
  fi
  CHECKPOINT_TARGET="$target"
}

restore_instance() {
  local target="${CHECKPOINT_TARGET:-}" uf
  local spec
  local -a restore_specs=()
  [ -n "$target" ] || return 0
  [ -d "$CHECKPOINT_DIR" ] || return 0
  # An interrupted rebase, first, because aborting one restores HEAD and the
  # worktree wholesale and everything below should run on that result.
  #
  # The mixed reset further down already clears MERGE_HEAD, CHERRY_PICK_HEAD
  # and REVERT_HEAD -- measured on git 2.54 across every conflicted state -- so
  # none of those need handling. A rebase directory is the one that SURVIVES a
  # reset.
  #
  # ONLY a rebase this run started. The checkpoint recorded whether one was
  # already open, and if it was, it is the founder's and it stays. Assuming
  # otherwise destroyed real work: the zombie-rebase cleanup above cannot see a
  # rebase in a linked worktree (it tests "$path/.git/rebase-merge" as a
  # directory, and there .git is a FILE), while a `rebase -i` paused at `edit`
  # leaves a clean tree that the dirty-tree guard passes -- so the founder's
  # open rebase reached this line untouched, and aborting it both discarded
  # their work and rewound the sync commit this run had just landed.
  #
  # If the abort cannot run, say so and leave it. Deleting git's own state by
  # hand is how a repo gets wrecked, and a human can finish what git could not.
  if instance_rebase_in_flight "$target" &&
      ! grep -qxF rebase "$CHECKPOINT_DIR/inflight" 2>/dev/null; then
    git -C "$target" rebase --abort 2>/dev/null ||
      echo "  WARN: a rebase this run started could not be aborted; the instance is left mid-rebase"
  fi
  # Untracked files the rsync --delete removed. No git verb can bring one back,
  # and the ONLY copy is the preservation snapshot under $SNAP -- which lives
  # inside ARCHIVE_TMP, so this has to happen before that is torn down. That
  # ordering is why abandon_instance owns both steps.
  if [ -n "${SNAP:-}" ] && [ -d "$SNAP/f" ] && [ -f "$SNAP/list" ]; then
    ( cd "$target" && while IFS= read -r -d '' uf; do
        if ! { [ -e "$uf" ] || [ -L "$uf" ]; } &&
            { [ -e "$SNAP/f/$uf" ] || [ -L "$SNAP/f/$uf" ]; }; then
          mkdir -p "$(dirname "$uf")" && cp -a "$SNAP/f/$uf" "$uf"
        fi
      done < "$SNAP/list" ) || true
  fi
  # Leave the instance CLEAN at whatever commit it reached -- do NOT rewind a
  # commit that landed. A landed commit is not damage: the tree is clean and
  # the next run proceeds normally. What actually took instances out of the
  # fleet was UNCOMMITTED debris -- a half-staged index (sp-5f2d2a63) or
  # modified tracked files (sp-e244e821) -- because the dirty-tree guard then
  # read it as founder work and refused forever.
  #
  # Rewinding was tried and is wrong: test-kipi-update-hook-contract.sh sets
  # HOOK_FAIL_ON=2 so the q-system commit lands and the CONFIG commit fails,
  # and it asserts the first commit survives. Undoing it also strands the
  # index against a HEAD it no longer matches, which manufactures the exact
  # dirty tree this function exists to prevent.
  # SCOPED to the sync's own write set (ASK-609), and this is load-bearing.
  # `checkout -- .` discards every unstaged tracked modification in the repo.
  # That was safe ONLY because the dirty-tree guard had just proved the whole
  # tree clean, so there was nothing of the founder's to discard. Once that
  # guard is scoped, an instance with founder edits outside the sync's reach
  # passes it legitimately -- and an unscoped checkout here would then delete
  # exactly the work the scoping was meant to stop blocking on. The two must
  # move together; the pathspec below is the same one the guard uses.
  # The restore itself takes index.lock (reset, checkout). An abandon caused
  # by a lock held past the bound would otherwise run these two silently into
  # the same lock, restore nothing, and leave this run's writes uncommitted:
  # dirty forever, refused by every later run (PR #314 review, round 1).
  # Wait the same bound again; if the writer is still there, say exactly what
  # was left behind instead of pretending the checkpoint was restored.
  if ! wait_for_index_lock "$target" "restore"; then
    echo "  ERROR: restore could NOT run: index.lock still held after ${LOCK_WAIT_S}s;" \
      "this instance keeps this run's uncommitted writes under $CHECKPOINT_PREFIX/, .claude/ and plugins/" \
      "until the lock clears and the tree is restored by hand" >&2
    return 1
  fi
  git -C "$target" reset -q HEAD -- "$CHECKPOINT_PREFIX/" .claude/ plugins/ \
    $(pathspec_owned_excludes "$CHECKPOINT_PREFIX") 2>/dev/null || true
  # `git checkout -- A B C` is ALL-OR-NOTHING. If ANY pathspec matches nothing
  # in the index it errors ("pathspec '.claude/' did not match any file(s)
  # known to git") and restores NONE of them -- while `git reset` above accepts
  # the same unmatched pathspec and returns 0. An instance that tracks no
  # .claude/ or plugins/ (a subtree instance that has never had a config sync
  # land is exactly that) therefore had its ENTIRE worktree restore silently
  # no-op: `2>/dev/null || true` hid the message and the exit code both, so the
  # index looked restored while the worktree kept the run's writes.
  #
  # That is what stranded instances: a failed run left `M q-system/tracked.md`
  # behind and every later run refused at the dirty-tree guard, reading the
  # updater's own debris as founder work. Measured 2026-08-13 (ASK-740): with
  # the unmatched specs passed, checkout rc=1 and the file stays modified; with
  # them dropped, rc=0 and the file is restored.
  #
  # Filtering by `ls-files` rather than by a directory test on purpose: what
  # checkout requires is a match in the INDEX, not a directory on disk.
  for spec in "$CHECKPOINT_PREFIX/" .claude/ plugins/; do
    if [ -n "$(git -C "$target" ls-files -- "$spec" 2>/dev/null)" ]; then
      restore_specs+=("$spec")
    fi
  done
  if [ "${#restore_specs[@]}" -gt 0 ]; then
    git -C "$target" checkout -q -- "${restore_specs[@]}" \
      $(pathspec_owned_excludes "$CHECKPOINT_PREFIX") 2>/dev/null || true
  fi
  # Finally, remove files this run created: untracked NOW, absent from the
  # checkpoint, and inside the sync's own scope. Never a recursive delete of a
  # directory this run was not observed to create.
  #
  # The set difference is computed once in python rather than by forking a grep
  # per file. The fork-per-file form was quadratic -- measured 83s on a 20k-file
  # instance against 1s before -- and it also could not match a path containing
  # a newline, because `grep -F` splits the PATTERN on newlines, so such a file
  # was deleted despite being IN the checkpoint. Splitting on NUL fixes both.
  checkpoint_untracked_list "$target" > "$CHECKPOINT_DIR/now" 2>/dev/null || true
  python3 - "$CHECKPOINT_DIR/untracked" "$CHECKPOINT_DIR/now" "$target" <<'PY' || true
import os
import sys

before = set(open(sys.argv[1], "rb").read().split(b"\0"))
root = sys.argv[3]
for record in open(sys.argv[2], "rb").read().split(b"\0"):
    if not record or record in before:
        continue
    candidate = os.path.join(root, os.fsdecode(record))
    try:
        if os.path.islink(candidate) or os.path.isfile(candidate):
            os.unlink(candidate)
    except OSError:
        pass
PY
}

# The single give-up path. Every one of the 24 sites routes through here, so
# restore-before-teardown is structural rather than 24 chances to forget it.
# Two sites record a failure and deliberately FALL THROUGH: a direct-clone
# whose merge needs manual resolve, and a failed archive export. Both still let
# the .claude/ and plugins/ config sync run, so the instance keeps receiving
# config updates even though its repo pull did not land. They must NOT abandon
# the instance -- doing so also tears down the dry-run model the config sync is
# still using. They get the counter alone, which is also what keeps the
# increment itself in exactly one place.
count_instance_failure() {
  FAIL=$((FAIL + 1))
  # NAME the instance, do not just count it. The summary reported "Failed: 6"
  # with no names, so nobody could see WHICH instances were drifting -- they sat
  # 2-6 prd-os versions behind for weeks and each run skipped a different subset
  # (measured 2026-08-04). A count is not a report.
  FAILED_NAMES="$FAILED_NAMES
    - ${name:-<unnamed>} (${path:-unknown path})"
}

abandon_instance() {
  local message="${1:-}"
  [ -n "$message" ] && echo "$message"
  restore_instance
  clear_run_marker
  if [ -n "${ARCHIVE_TMP:-}" ] && [ -d "$ARCHIVE_TMP" ]; then
    rm -r -- "$ARCHIVE_TMP"
    ARCHIVE_TMP=""
  fi
  cleanup_dry_model
  count_instance_failure
  echo ""
  return 0
}

worktree_digest() {
  python3 - "$1" <<'PY'
import hashlib
import os
import pathlib
import stat
import sys

root = pathlib.Path(sys.argv[1])
digest = hashlib.sha256()
for current, directories, files in os.walk(root, followlinks=False):
    directories[:] = sorted(name for name in directories if name != ".git")
    for name in sorted(directories + files):
        candidate = pathlib.Path(current, name)
        if candidate == root / ".git":
            continue
        relative = candidate.relative_to(root).as_posix()
        metadata = candidate.lstat()
        digest.update(relative.encode("utf-8", "surrogateescape") + b"\0")
        digest.update(f"{stat.S_IFMT(metadata.st_mode):o}:{stat.S_IMODE(metadata.st_mode):o}".encode() + b"\0")
        if stat.S_ISLNK(metadata.st_mode):
            digest.update(os.readlink(candidate).encode("utf-8", "surrogateescape"))
        elif stat.S_ISREG(metadata.st_mode):
            with candidate.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
        digest.update(b"\0")
print(digest.hexdigest())
PY
}

stage_q_system_sync() {
  local target="$1"
  local managed_prefix="$2"
  git -C "$target" add -u -- "$managed_prefix/" || return 1
  git -C "$SCRIPT_DIR" ls-tree -r --name-only -z HEAD -- q-system/ |
    python3 -c '
import os
import sys

prefix = sys.argv[1]
owned = sys.argv[2:]
for source in sys.stdin.buffer.read().split(b"\0"):
    if not source:
        continue
    relative = source.removeprefix(b"q-system/")
    # Skeleton paths under an instance-owned subtree are NOT synced, so adding
    # them stages a path that does not exist and the whole stage fails -- which
    # left the instance written-to but uncommitted.
    if any(relative.startswith(os.fsencode(o) + b"/") for o in owned):
        continue
    target = os.fsencode(prefix) + b"/" + relative
    sys.stdout.buffer.write(target + b"\0")
' "$managed_prefix" "${INSTANCE_OWNED_SUBTREES[@]}" |
    git -C "$target" add --pathspec-from-file=- --pathspec-file-nul
}

# Staging is not atomic: `git add -u` then a second add that can fail leaves the
# first one's work in the index. The updater then aborts, and EVERY later run
# aborts at the dirty-tree guard, because that guard reads `git diff --cached`.
# One interrupted run made an instance permanently un-updatable and a working
# tree checkout did not clear it, which made it easy to misdiagnose. Any staging
# failure unstages what it staged.
unstage_scope() {
  local target="$1"
  shift
  git -C "$target" reset -q -- "$@" 2>/dev/null || true
}

stage_config_sync() {
  local target="$1"
  local scope source relative plugin_name ignored_paths
  local -a plugin_paths=() stage_paths=()
  for scope in .claude plugins; do
    if [ -n "$(git -C "$target" ls-files -- "$scope/")" ]; then
      git -C "$target" add -u -- "$scope/" || return 1
    fi
  done
  if [ -f "$target/.claude/settings.json" ]; then
    git -C "$target" add -- .claude/settings.json || return 1
  fi
  for scope in agents rules output-styles; do
    if [ -d "$SCRIPT_DIR/.claude/$scope" ]; then
      while IFS= read -r -d '' source; do
        relative="${source#"$SCRIPT_DIR/"}"
        git -C "$target" add -- "$relative" || return 1
      done < <(
        find "$SCRIPT_DIR/.claude/$scope" -maxdepth 1 -type f \
          -name '*.md' -print0
      )
    fi
  done
  if [ -d "$SKELETON_PLUGIN_ROOT" ]; then
    # Rooted PER MANAGED PLUGIN, not at plugins/ wholesale. The stager and the
    # syncer now walk the same list, so the stager can no longer name a path
    # the syncer will not write -- which is what the old post-hoc [ -d ] filter
    # was patching around. See managed_plugin_names for the scar.
    # THE THIRD CONSUMER of PLUGIN_COPY_EXCLUDES, and the one that made the
    # duplication expensive rather than merely untidy (ASK-772). This walk had
    # its OWN hardcoded prune list -- .git, __pycache__, .pytest_cache, .venv,
    # *.pyc -- a third copy of the same value. Excluding `.env` from the rsync
    # without teaching the stager left it naming a path the syncer no longer
    # writes, and `git add` on a missing path is fatal:
    #
    #     fatal: pathspec 'plugins/demo/.env.local' did not match any files
    #     ERROR: config sync did not reach a complete committed state
    #
    # which is the exact class the comment above already warns about, arriving
    # from the one direction it did not cover. The find still prunes cheaply so
    # it never descends into a .venv; the shared regex is what decides.
    plugin_excl_re="$(plugin_copy_filter_regex)"
    while IFS= read -r -d '' plugin_name; do
      while IFS= read -r -d '' source; do
        relative="${source#"$SCRIPT_DIR/"}"
        # Matched on the path RELATIVE to the plugin dir, the same thing rsync
        # matches its --exclude patterns against. Matching the repo-relative path
        # would let a `.env` anywhere above the plugin root change the answer.
        case "${source#"$SKELETON_PLUGIN_ROOT/$plugin_name/"}" in
          *) printf '%s' "${source#"$SKELETON_PLUGIN_ROOT/$plugin_name/"}" \
               | grep -qE "$plugin_excl_re" && continue ;;
        esac
        plugin_paths+=("$relative")
      done < <(
        find "$SKELETON_PLUGIN_ROOT/$plugin_name" \
          \( -type d -name .git -o -type d -name __pycache__ \
             -o -type d -name .pytest_cache -o -type d -name .venv \) -prune -o \
          \( -type f -o -type l \) -print0
      )
    done < <(managed_plugin_names)
    # A path the INSTANCE ignores cannot be staged, and `git add` treats that
    # as an error, so ONE stray file in the skeleton fails the entire config
    # sync on every instance whose .gitignore covers its extension. Skip those
    # instead: a file the instance ignores was never going to be committed
    # there, and aborting the sync over it helps nobody.
    #
    # Scar 2026-07-25: the skeleton tracks
    # plugins/prd-os/scripts/export-fable-mirror.sh.remediation.bak -- a backup
    # committed by accident -- and ASK_AI_consultant's .gitignore line 62 is
    # `*.bak`. One file, whole fleet. check-ignore runs once over the batch
    # rather than per file.
    if [ "${#plugin_paths[@]}" -gt 0 ]; then
      ignored_paths="$(
        printf '%s\n' "${plugin_paths[@]}" |
          git -C "$target" check-ignore --stdin 2>/dev/null || true
      )"
      stage_paths=()
      for relative in "${plugin_paths[@]}"; do
        if [ -n "$ignored_paths" ] &&
            printf '%s\n' "$ignored_paths" | grep -Fxq -- "$relative"; then
          continue
        fi
        stage_paths+=("$relative")
      done
      if [ "${#stage_paths[@]}" -gt 0 ]; then
        git -C "$target" add -- "${stage_paths[@]}" || return 1
      fi
    fi
  fi
}

guarded_commit() {
  local target="$1"
  local message="$2"
  local guard_dir original_hooks configured hook index_path rc
  guard_dir="$(mktemp -d)"
  index_path="$(git -C "$target" rev-parse --git-path index)"
  cp "$index_path" "$guard_dir/index.before" || {
    rm -r -- "$guard_dir"
    return 1
  }
  git -C "$target" diff --cached --name-only -z > "$guard_dir/allowed"

  original_hooks=""
  if [ "$MODEL_RUN" != "1" ]; then
    configured="$(git -C "$target" config --path --get core.hooksPath || true)"
    if [ -n "$configured" ]; then
      case "$configured" in
        /*) original_hooks="$configured" ;;
        *) original_hooks="$target/$configured" ;;
      esac
    else
      original_hooks="$(
        git -C "$target" rev-parse --path-format=absolute --git-path hooks
      )"
    fi
  fi
  cat > "$guard_dir/hook-guard" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
hook_name="$(basename "$0")"
# Invoke the instance's hook by its REAL path. Running it through a renamed
# symlink (original-pre-commit) changed `basename "$0"` and pointed
# `dirname "$0"` at the guard dir, so dispatch-on-$0 hooks (lefthook, husky) and
# hooks that source a sibling (`. "$(dirname "$0")/common.sh"`) either
# misbehaved or hard-failed -- the active hook lost authority either way.
original="${GUARDED_ORIGINAL_HOOKS:-}"
if [ -n "$original" ] && [ -x "$original/$hook_name" ]; then
  "$original/$hook_name" "$@"
fi
case "$hook_name" in
  pre-commit|prepare-commit-msg|commit-msg)
    git diff --cached --name-only -z > "$GUARDED_HOOK_DIR/after"
    if ! cmp -s "$GUARDED_HOOK_DIR/allowed" "$GUARDED_HOOK_DIR/after"; then
      echo "ERROR: $hook_name changed the updater commit path set" >&2
      exit 1
    fi
    ;;
esac
SH
  chmod +x "$guard_dir/hook-guard"
  for hook in pre-commit prepare-commit-msg commit-msg post-commit post-rewrite; do
    ln -s hook-guard "$guard_dir/$hook" || {
      rm -r -- "$guard_dir"
      return 1
    }
  done

  set +e
  env -u GIT_CONFIG_PARAMETERS -u GIT_CONFIG_COUNT \
    GUARDED_HOOK_DIR="$guard_dir" \
    GUARDED_ORIGINAL_HOOKS="$original_hooks" \
    git -C "$target" -c core.hooksPath="$guard_dir" \
      commit --no-gpg-sign -m "$message" </dev/null | dry_filter
  # PIPESTATUS[0], not $?: with dry_filter on the end of the pipe, $? is sed's
  # status and a FAILED commit would read as success. sp-a4a933ad's tagging must
  # not cost the exit code it is printed next to.
  rc=${PIPESTATUS[0]}
  set -e
  if [ "$rc" -ne 0 ]; then
    cp "$guard_dir/index.before" "$index_path" || true
  fi
  rm -r -- "$guard_dir"
  return "$rc"
}

# A LIVE index.lock is another writer, not debris, and the answer is to wait.
#
# 2026-09-06 14:30, consulting: the q-system commit landed, then the config
# commit died seconds later on "Unable to create '.git/index.lock': File
# exists" and the whole instance was abandoned half-delivered (q-system
# committed, .claude/ written but uncommitted, plugins/ copied but never
# added or deleted). The holder was a peer session's `git status`, which
# refreshes the index under that lock for a fraction of a second. The stale
# lock deletion at the top of the instance loop covers a crashed writer that
# left a lock behind; it cannot cover a writer that is alive right now, and
# deleting THAT lock is how two writers corrupt one index. Captured as
# sp-523c1a25. So: every git command this run makes that takes the index
# lock (add, commit) first waits for the lock to be absent, bounded, and a
# commit that still dies on that exact error is retried a bounded number of
# times. Any other failure is returned unchanged on the first attempt.
# The default has to outlast the LONGEST known instance hold, not a typical
# one. On the same 2026-09-06 run the consulting instance's own Stop-hook
# auto-commit held the index lock through its 445 s pre-commit verify. A 120 s
# bound refuses that instance and leaves its tree half-delivered for manual
# repair, which is the failure this whole change exists to remove. 600 s
# clears 445 s with room. The tests set their own bound through the env var.
LOCK_WAIT_S="${KIPI_UPDATE_LOCK_WAIT_S:-600}"
LOCK_RETRY_MAX=3

index_lock_path() {
  local target="$1" lock
  lock="$(git -C "$target" rev-parse --path-format=absolute --git-path index.lock 2>/dev/null)" \
    || lock="$target/.git/index.lock"
  printf '%s\n' "$lock"
}

# $1 = instance path, $2 = the step name the log and the failure carry.
# Returns 1 only when the lock outlived the bound; a missing lock returns 0
# at once, so calling this before every index write costs nothing when the
# checkout is quiet.
wait_for_index_lock() {
  local target="$1" step="$2" lock waited=0
  lock="$(index_lock_path "$target")"
  while [ -e "$lock" ]; do
    if [ "$waited" -ge "$LOCK_WAIT_S" ]; then
      echo "  ERROR: index.lock held past ${LOCK_WAIT_S}s at $step; another git writer owns this checkout" >&2
      return 1
    fi
    if [ "$waited" -eq 0 ] || [ $((waited % 10)) -eq 0 ]; then
      echo "  waiting for index.lock at $step (${waited}s of ${LOCK_WAIT_S}s)"
    fi
    sleep 1
    waited=$((waited + 1))
  done
  return 0
}

# $1 = instance path, $2 = step name, $3.. = the commit command to run.
# Retries ONLY on the live-lock error text; every other failure returns on
# attempt 1 with its stderr intact, because a pre-commit refusal or a bad
# pathspec is not something waiting fixes (self-healing-retry.md rule 5).
retry_on_index_lock() {
  local target="$1" step="$2"
  shift 2
  local attempt=1 rc errf
  errf="$(mktemp)"
  while :; do
    if ! wait_for_index_lock "$target" "$step"; then
      rm -- "$errf"
      return 1
    fi
    if "$@" 2>"$errf"; then
      rc=0
    else
      rc=$?
    fi
    if [ "$rc" -eq 0 ]; then
      cat "$errf" >&2
      rm -- "$errf"
      return 0
    fi
    if [ "$attempt" -lt "$LOCK_RETRY_MAX" ] &&
        grep -qE "index\.lock': File exists|Unable to create .*index\.lock" "$errf"; then
      echo "  commit at $step hit a live index.lock (attempt $attempt of $LOCK_RETRY_MAX); waiting and retrying"
      attempt=$((attempt + 1))
      sleep 1
      continue
    fi
    cat "$errf" >&2
    rm -- "$errf"
    return "$rc"
  done
}

# The run marker: while one instance apply is in flight, <git-common-dir>/
# kipi-update.run holds this pid and the start time. The instance's own
# Stop-hook auto-commit (q-system/hooks/auto-commit.py) refuses to commit
# while a LIVE marker exists, so the updater's half-delivered files are not
# swept into the hook's generic commits mid-run (2026-09-06 14:33, consulting:
# "chore: update rules (10 files)" was the skeleton's rules, committed by the
# hook under its own name while the updater was still delivering; sp-9306036e).
# The common dir, not the worktree's git dir, so a linked worktree of the
# same checkout reads the same marker. Cleared on every exit path.
RUN_MARKER=""
RUN_MARKER_MAX_AGE_S="${KIPI_UPDATE_RUN_MARKER_MAX_AGE_S:-7200}"

# The marker is also the one-run-per-instance lock. A marker whose pid is
# alive and whose stamp is younger than the bound belongs to ANOTHER updater
# still applying this instance; writing over it would let two runs interleave
# on one index and let the first run's clear_run_marker strip the second's
# protection (PR #314 review, round 1). Returns 1 in that case; the caller
# abandons the instance. A dead pid or an old stamp is a crashed run's
# leftover and is replaced.
run_marker_is_live_foreign() {
  local marker="$1" pid stamp age
  [ -f "$marker" ] || return 1
  read -r pid stamp < "$marker" || return 1
  case "$pid" in ''|*[!0-9]*) return 1 ;; esac
  [ "$pid" != "$$" ] || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  age="$(python3 -c 'import calendar,sys,time
try:
    print(int(time.time() - calendar.timegm(time.strptime(sys.argv[1], "%Y-%m-%dT%H:%M:%SZ"))))
except Exception:
    print(-1)' "${stamp:-}" 2>/dev/null)" || age=-1
  [ "$age" -ge 0 ] && [ "$age" -le "$RUN_MARKER_MAX_AGE_S" ]
}
write_run_marker() {
  local target="$1" common
  common="$(git -C "$target" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" \
    || return 0
  if run_marker_is_live_foreign "$common/kipi-update.run"; then
    echo "  ERROR: another fleet update is applying this instance right now (pid $(cut -d' ' -f1 "$common/kipi-update.run")); refusing to run two at once" >&2
    return 1
  fi
  RUN_MARKER="$common/kipi-update.run"
  printf '%s %s\n' "$$" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$RUN_MARKER"
}
# Only this run's own marker is ever removed: the first field is the pid that
# wrote it, and a marker carrying any other pid is left for its owner.
clear_run_marker() {
  local owner
  if [ -n "${RUN_MARKER:-}" ] && [ -f "$RUN_MARKER" ]; then
    owner="$(cut -d' ' -f1 "$RUN_MARKER" 2>/dev/null || true)"
    if [ "$owner" = "$$" ]; then
      rm -- "$RUN_MARKER"
    fi
  fi
  RUN_MARKER=""
}

# One answer to "is this untracked file the founder's work, or this sync's own
# debris?". Two guards ask it -- the .claude/+plugins/ collision scan and the
# q-system collision scan -- and each used to answer with its own carve-out,
# neither knowing about the other's.
#
#   $1 = the file's path in the instance
#   $2 = the file the skeleton would write there, or "" when the caller has none
#   $3 = non-empty when the CALLER's own rsync clears build artifacts anyway
#
# Each argument is a piece of evidence the caller has and the predicate does
# not. Debris takes two forms and they do NOT apply to both callers equally:
# whether a build artifact is debris depends on what that caller's sync is
# about to do to it, so the caller says.
#
# NOT used by the tracked-tree guard further down. That one is
# `git diff --cached --quiet || git diff --quiet` over the WHOLE tree: it takes
# no path and no counterpart, so there is nothing to pass it. And excusing
# debris there would let a modified TRACKED .pyc reach `git add -u`, landing a
# founder edit inside the updater's own commit -- precisely what that guard
# exists to prevent. Measured, not assumed.
is_instance_wip() {
  local instance_file="$1" skeleton_file="$2" caller_clears_artifacts="$3"
  # A regenerable build artifact is not work -- but ONLY for a caller whose own
  # sync clears it regardless. The plugins rsync runs --delete-excluded with
  # exactly these filters, so refusing over one there would block the sync over
  # the very thing the sync is for. Scar 2026-07-25: this matched whenever the
  # plugin DIRECTORY existed in the skeleton, and the scan enumerates
  # gitignored files, so a single __pycache__ entry aborted the config sync on
  # 23 of 23 instances -- and with it .claude/, plugins/, and the 98MB .venv
  # deletion.
  #
  # The q-system rsync has NO --delete-excluded and none of these filters, so
  # there the same path is ordinary content. Excusing it would let the
  # skeleton's copy silently overwrite the instance's, and the post-rsync
  # restore only recovers files the rsync DELETED -- an overwritten one is
  # gone. Latent rather than live today only because the skeleton tracks
  # nothing under q-system/**/.venv/ or .pytest_cache/; that is not a property
  # to depend on.
  if [ -n "$caller_clears_artifacts" ]; then
    case "$instance_file" in
      */.git/*|*/__pycache__/*|*.pyc|*/.venv/*|*/.pytest_cache/*) return 1 ;;
    esac
  fi
  # Byte-identical is not work in progress: it is THIS sync's own output from a
  # run that died after the rsync and before the commit. Treating it as WIP
  # made one interrupted sync brick an instance permanently -- every later run
  # refused, and the only recovery was deleting files by hand. Observed on a
  # real run 2026-07-25: 40 residue files, all identical to the skeleton.
  # A caller that cannot name a counterpart passes "" and skips this test.
  if [ -n "$skeleton_file" ] && [ -f "$skeleton_file" ] &&
      [ -f "$instance_file" ] && cmp -s "$instance_file" "$skeleton_file"; then
    return 1
  fi
  # AN OLDER SKELETON BLOB IS ALSO NOT WORK (sp-940bcf47, measured 2026-08-14 PT).
  #
  # The byte-identical test above only recognises THIS sync's own output. An
  # untracked file written by an EARLIER sync, differing from the current
  # skeleton copy, looked like work-in-progress and refused the instance on
  # every run afterwards. one registered instance sat exactly there with an untracked
  # q-system/.q-system/scripts/merge-bypass-gate.py, and fleet-reach-audit.py
  # reported WOULD-SYNC for it the whole time because the audit does not model
  # this check. Real reach was 21 of 22 while the number on screen said 22.
  #
  # The exemption is EXACTLY as narrow as fleet-unblock's `commit` proof, and
  # for the same reason: a founder hand-edit does not produce bytes that collide
  # with a blob the skeleton itself once held at the same path. Anything the
  # skeleton never wrote there is still work and still refuses.
  #
  # Fail closed. The helper exits 2 when it cannot decide, and only exit 0 --
  # "the skeleton demonstrably shipped this blob here" -- excuses the file. A
  # missing helper therefore refuses, which is the behaviour before this change.
  local skeleton_repo_path="${4:-}"
  if [ -n "$skeleton_repo_path" ] && [ -f "$instance_file" ] &&
      [ -f "$SCRIPT_DIR/kipi-update-wip-check.py" ] &&
      python3 "$SCRIPT_DIR/kipi-update-wip-check.py" \
        --skeleton "$SCRIPT_DIR" --skeleton-path "$skeleton_repo_path" \
        --file "$instance_file" 2>/dev/null; then
    return 1
  fi
  return 0
}

config_source_manages() {
  local relative="$1"
  case "$relative" in
    .claude/settings.json)
      return 0
      ;;
    .claude/agents/*.md|.claude/rules/*.md|.claude/output-styles/*.md)
      [ -f "$SCRIPT_DIR/$relative" ]
      return
      ;;
    plugins/*/*)
      # Anything under a managed plugin dir is a candidate collision: the rsync
      # is --delete, so it removes instance files the skeleton does not carry.
      # Whether a given one is WIP or this sync's own debris is is_instance_wip's
      # call; this function answers only "does the skeleton manage this path?".
      is_managed_plugin_path "$relative"
      return
      ;;
  esac
  return 1
}

reject_untracked_config_collisions() {
  local target="$1"
  local relative counterpart
  while IFS= read -r -d '' relative; do
    # Byte-identical residue is this sync's own half-finished output, not the
    # founder's work -- the same carve-out the q-system guard already had. A
    # run that died after writing .claude/ and before committing left identical
    # untracked files here, and every later run then refused on them. That is
    # exactly how sp-5f2d2a63 bricked an instance at the other guard; this one
    # simply had not been given the carve-out yet.
    #
    # settings.json is the one managed path with no byte source: it is
    # GENERATED by kipi-settings-merge.py from settings-template.json, so the
    # skeleton's own copy is not what gets written there and comparing against
    # it would excuse a file this sync never produced.
    # THE HISTORICAL-BLOB EXEMPTION BELONGS HERE TOO (PR #185 review, major).
    #
    # sp-940bcf47 wired it into the q-system collision path only, so updater
    # residue under .claude/ or plugins/ from an EARLIER sync -- differing from
    # the current skeleton copy, so the byte-identical carve-out above misses it
    # -- still aborted the instance on every run. Same defect, same blast
    # radius, one call site further down. Wiring one and not the other is how a
    # carve-out gets a reputation for not working.
    #
    # The mapping is IDENTITY here: .claude/ and plugins/ live at the skeleton
    # root, so the instance's spelling of the path is the skeleton repo's too.
    # That is why the argument is passed per call site instead of derived inside
    # the helper -- the q-system path needs a q-system/ prefix and this one
    # must not have one.
    #
    # settings.json keeps its carve-out for BOTH checks. It is GENERATED by
    # kipi-settings-merge.py from settings-template.json, so no blob in skeleton
    # history is what belongs in an instance; excusing a file because the
    # skeleton once shipped that content would excuse a copy this sync never
    # produced and would never produce.
    case "$relative" in
      .claude/settings.json) counterpart=""; skeleton_rel="" ;;
      *) counterpart="$SCRIPT_DIR/$relative"; skeleton_rel="$relative" ;;
    esac
    if config_source_manages "$relative" &&
        is_instance_wip "$target/$relative" "$counterpart" clears-build-artifacts \
          "$skeleton_rel"; then
      echo "  ERROR: untracked WIP collides with managed config: $relative"
      return 1
    fi
  done < <(
    # UNTRACKED only, not --ignored. This guard exists to protect WORK from a
    # sync that would overwrite or --delete it. A file the instance itself
    # gitignores is, by its own declaration, not work; one real instance
    # returns 2569 ignored entries under these two dirs and the first of them
    # aborted the whole config block. Genuinely precious untracked state lives
    # under q-system/, which has its own snapshot-and-restore path.
    git -C "$target" ls-files -z --others --exclude-standard -- \
      .claude/ plugins/
  )
}

trap cleanup_updater_temps EXIT

while IFS='|' read -r name path prefix itype declared; do
  # Filter INSIDE the loop, not in the feed, so an --only name that matches
  # nothing is caught by the post-loop check rather than reading as an empty
  # registry.
  if [ -n "$ONLY" ] && [ "$name" != "$ONLY" ]; then
    continue
  fi
  echo "--- $name ($itype) ---"

  if [ ! -d "$path" ]; then
    echo "  SKIP: path $path does not exist"
    SKIP=$((SKIP + 1))
    echo ""
    continue
  fi

  # Standalone repos have no skeleton subtree; nothing to sync and the updater
  # must not auto-commit or rsync into them. (A null subtree_prefix used to
  # crash the registry parser below -- keep this guard before any mutation.)
  #
  # Receiving nothing is legitimate. Receiving nothing SILENTLY is not: this
  # branch printed one identical line either way, so `reddit-build-radar` sat in
  # the fleet's 24 governed instances with 0 skeleton capabilities -- no
  # token-guard, no .claude/rules/, no capability gate -- and every fleet-wide
  # claim about gates holding had an exception nobody could see (ASK-117). The
  # declaration is what separates a decision from an oversight, so an entry
  # without one is a run failure, not a skip.
  if [ "$itype" = "standalone" ] || [ -z "$prefix" ]; then
    if [ "$declared" = "declared" ]; then
      echo "  SKIP: declared not skeleton-managed (skeleton_managed=false)"
      SKIP=$((SKIP + 1))
    else
      echo "  UNDECLARED NON-PROPAGATING: registered as an instance but receives"
      echo "    no skeleton propagation, and nothing on record says that is intended."
      echo "    Add \"skeleton_managed\": false to its instance-registry.json entry"
      echo "    with a note, or give it a subtree_prefix so it actually syncs."
      UNDECLARED="$UNDECLARED $name"
      FAIL=$((FAIL + 1))
    fi
    echo ""
    continue
  fi

  MODEL_RUN=0
  DRY_MODEL_ROOT=""
  # Per-instance, not per-run. A stale CHECKPOINT_TARGET would let an early
  # bail on instance B restore against instance A's recorded state; a stale
  # SNAP would point restore at a torn-down directory.
  CHECKPOINT_TARGET=""
  CHECKPOINT_PREFIX=""
  # The checkpoint DIRECTORY too, not only the target. restore_instance returns
  # early on an empty target, so a bail before this instance's checkpoint
  # already restored nothing; clearing the directory as well makes that
  # structural rather than dependent on one guard line, and stops the
  # previous instance's snapshot outliving its iteration (PR #314 round 3).
  if [ -n "${CHECKPOINT_DIR:-}" ] && [ -d "$CHECKPOINT_DIR" ]; then
    rm -r -- "$CHECKPOINT_DIR"
  fi
  CHECKPOINT_DIR=""
  SNAP=""
  ORIGINAL_PATH="$path"
  ORIGINAL_HEAD=""
  if [ "$DRY_RUN" = "--dry-run" ]; then
    DRY_MODEL_ROOT="$(mktemp -d)"
    MODEL_RUN=1
    # Neutralize hooks for the WHOLE modeled iteration, not just the commit. A
    # direct-clone dry run runs fetch/pull/rebase/merge inside the model, which
    # fires pre-rebase, post-rewrite, post-merge and post-checkout out of the
    # COPIED .git (or an absolute core.hooksPath) -- production side effects
    # escaping a run that is supposed to change nothing. GIT_CONFIG_* env beats
    # local and worktree config, so it is the only scope the modeled repo cannot
    # override from inside; `git -c` still beats it, which is what keeps
    # guarded_commit authoritative.
    DRY_HOOKS_DIR="$DRY_MODEL_ROOT/no-hooks"
    if ! mkdir -p "$DRY_HOOKS_DIR"; then
      abandon_instance "  ERROR: could not create the isolated dry-run hooks directory" && continue
    fi
    unset GIT_CONFIG_PARAMETERS
    case "${GIT_CONFIG_COUNT:-}" in
      ''|*[!0-9]*) ;;
      *)
        if [ "$GIT_CONFIG_COUNT" -le 4096 ]; then
          INHERITED_CONFIG=0
          while [ "$INHERITED_CONFIG" -lt "$GIT_CONFIG_COUNT" ]; do
            unset "GIT_CONFIG_KEY_$INHERITED_CONFIG" \
              "GIT_CONFIG_VALUE_$INHERITED_CONFIG"
            INHERITED_CONFIG=$((INHERITED_CONFIG + 1))
          done
        fi
        ;;
    esac
    export GIT_CONFIG_COUNT=1
    export GIT_CONFIG_KEY_0=core.hooksPath
    export GIT_CONFIG_VALUE_0="$DRY_HOOKS_DIR"
    ORIGINAL_HEAD="$(git -C "$path" rev-parse HEAD 2>/dev/null || true)"
    if [ -z "$ORIGINAL_HEAD" ]; then
      abandon_instance "  ERROR: could not resolve production HEAD for dry-run model" && continue
    fi
    # Projection A. It re-enters the one scan itself, which also populates
    # MODEL_SKIPPED_PATHS -- projection B, read directly by the symlink walk
    # below and by the count on the next line.
    model_rsync_excludes "$path"
    if [ "${#MODEL_SKIPPED_PATHS[@]}" -gt 0 ]; then
      echo "  dry-run model: skipped ${#MODEL_SKIPPED_PATHS[@]} nested repositories (separate repos, not synced)"
    fi
    if ! python3 - "$path" ${MODEL_SKIPPED_PATHS[@]+"${MODEL_SKIPPED_PATHS[@]}"} <<'PY'
import os
import pathlib
import sys

# An escaping symlink is allowed ONLY when it resolves to an existing regular
# file. Such a link cannot leak a write: rsync and git replace the link itself
# rather than writing through it, which test-kipi-update-safety.sh asserts by
# checking the outside target is byte-identical after a dry run.
#
# Everything else that escapes is refused, for two different reasons:
#   - a DIRECTORY is a live path prefix a write can descend into
#   - a DANGLING target is worse, not better: nothing exists to replace, so a
#     mkdir -p or a redirect under it materialises the path OUTSIDE the model
#     (test-kipi-update-dry-final-state.sh plants exactly that shape)
#
# Scar 2026-07-25 (ASK_AI_consultant, fleet rollout): this walked the whole
# instance and refused on ANY escaping target, so every instance carrying a
# kipi-mcp virtualenv was unmodelable -- `.venv/bin/python -> /abs/python3.12`
# plus a relative `python3 -> python` that inherits the escape through the
# chain. That is the normal shape of every venv on disk and says nothing about
# update safety.
root = pathlib.Path(sys.argv[1]).resolve()
# Paths the model will not copy. A link inside one can never reach the model,
# so it cannot leak a write, and refusing on it would let rot in a SEPARATE
# repo block this instance forever. Scar 2026-07-25: personal-brand's broken
# canonical links refused cole-gtm, its parent, for a sync that never touches
# personal-brand at all.
skipped = {(root / arg).resolve(strict=False) for arg in sys.argv[2:]}
for current, directories, files in os.walk(root, followlinks=False):
    directories[:] = [
        name for name in directories
        if pathlib.Path(current, name).resolve(strict=False) not in skipped
    ]
    for name in directories + files:
        candidate = pathlib.Path(current, name)
        if not candidate.is_symlink():
            continue
        target = os.readlink(candidate)
        # is_file() follows the whole chain and is False for both a directory
        # and a dangling target, which is the line that matters. A link to a
        # real file is safe everywhere: rsync and git replace the link rather
        # than writing through it, so it cannot mutate what it points at.
        if candidate.is_file():
            continue
        # Not a file, so a write can descend into it or materialise it. It is
        # only safe if the whole chain is relative AND stays inside the
        # instance: relative hops follow the copy into the model, an absolute
        # hop keeps pointing at PRODUCTION even when it names a path inside
        # the instance -- which is the isolation break, not the escape.
        hop = candidate
        internal = True
        for _ in range(40):
            if not hop.is_symlink():
                break
            hop_target = os.readlink(hop)
            if os.path.isabs(hop_target):
                internal = False
                break
            hop = hop.parent / hop_target
            try:
                hop.resolve(strict=False).relative_to(root)
            except ValueError:
                internal = False
                break
        else:
            internal = False
        if internal:
            continue
        reason = "directory" if candidate.is_dir() else "dangling"
        print(f"unsafe {reason} symlink escapes the disposable model: {candidate.relative_to(root)} -> {target}", file=sys.stderr)
        raise SystemExit(1)
PY
    then
      abandon_instance "  ERROR: unsafe symlink prevents isolated dry-run modeling" && continue
    fi
    SOURCE_GIT_DIR="$(
      git -C "$path" rev-parse --path-format=absolute --git-common-dir \
        2>/dev/null || true
    )"
    SOURCE_WORKTREE_GIT_DIR="$(
      git -C "$path" rev-parse --path-format=absolute --git-dir \
        2>/dev/null || true
    )"
    if [ -n "$SOURCE_WORKTREE_GIT_DIR" ] &&
        { [ -f "$SOURCE_WORKTREE_GIT_DIR/MERGE_HEAD" ] ||
          [ -d "$SOURCE_WORKTREE_GIT_DIR/rebase-merge" ] ||
          [ -d "$SOURCE_WORKTREE_GIT_DIR/rebase-apply" ]; }; then
      abandon_instance "  ERROR: active merge or rebase cannot be modeled safely" && continue
    fi
    ORIGINAL_BRANCH="$(git -C "$path" symbolic-ref --short -q HEAD || true)"
    MODEL_SETUP_FAILED=0
    if [ -d "$path/.git" ]; then
      if ! mkdir -p "$DRY_MODEL_ROOT/instance" ||
          ! rsync -a --delete "${MODEL_EXCLUDES[@]}" "$path/" \
            "$DRY_MODEL_ROOT/instance/" ||
          ! cp -a "$path/.git" "$DRY_MODEL_ROOT/instance/.git"; then
        MODEL_SETUP_FAILED=1
      fi
    else
      if [ -z "$SOURCE_GIT_DIR" ] ||
          [ -z "$SOURCE_WORKTREE_GIT_DIR" ] ||
          ! git init --quiet "$DRY_MODEL_ROOT/instance" ||
          ! git -C "$DRY_MODEL_ROOT/instance" fetch --quiet --no-tags \
            "$SOURCE_GIT_DIR" "$ORIGINAL_HEAD"; then
        MODEL_SETUP_FAILED=1
      elif [ -n "$ORIGINAL_BRANCH" ]; then
        git -C "$DRY_MODEL_ROOT/instance" checkout --quiet \
          -B "$ORIGINAL_BRANCH" "$ORIGINAL_HEAD" ||
          MODEL_SETUP_FAILED=1
      else
        git -C "$DRY_MODEL_ROOT/instance" checkout --quiet \
          --detach "$ORIGINAL_HEAD" ||
          MODEL_SETUP_FAILED=1
      fi
      if [ "$MODEL_SETUP_FAILED" = "0" ] &&
          { ! cp "$SOURCE_GIT_DIR/config" \
              "$DRY_MODEL_ROOT/instance/.git/config" ||
            ! git -C "$DRY_MODEL_ROOT/instance" config --local \
              core.bare false ||
            ! rsync -a --delete "${MODEL_EXCLUDES[@]}" "$path/" \
              "$DRY_MODEL_ROOT/instance/"; }; then
        MODEL_SETUP_FAILED=1
      fi
      if [ "$MODEL_SETUP_FAILED" = "0" ] &&
          [ -f "$SOURCE_WORKTREE_GIT_DIR/index" ] &&
          ! cp "$SOURCE_WORKTREE_GIT_DIR/index" \
            "$DRY_MODEL_ROOT/instance/.git/index"; then
        MODEL_SETUP_FAILED=1
      fi
      if [ "$MODEL_SETUP_FAILED" = "0" ] &&
          [ -f "$SOURCE_WORKTREE_GIT_DIR/config.worktree" ] &&
          ! cp "$SOURCE_WORKTREE_GIT_DIR/config.worktree" \
            "$DRY_MODEL_ROOT/instance/.git/config.worktree"; then
        MODEL_SETUP_FAILED=1
      fi
      if [ "$MODEL_SETUP_FAILED" = "0" ] &&
          [ -f "$SOURCE_WORKTREE_GIT_DIR/info/sparse-checkout" ]; then
        mkdir -p "$DRY_MODEL_ROOT/instance/.git/info"
        cp "$SOURCE_WORKTREE_GIT_DIR/info/sparse-checkout" \
          "$DRY_MODEL_ROOT/instance/.git/info/sparse-checkout" ||
          MODEL_SETUP_FAILED=1
      fi
    fi
    if [ "$MODEL_SETUP_FAILED" != "0" ]; then
      abandon_instance "  ERROR: could not create disposable dry-run model" && continue
    fi
    if git -C "$DRY_MODEL_ROOT/instance" config --local \
        --get-all core.worktree >/dev/null 2>&1; then
      if ! git -C "$DRY_MODEL_ROOT/instance" config --local \
          --replace-all core.worktree "$DRY_MODEL_ROOT/instance"; then
        abandon_instance "  ERROR: could not isolate repository worktree config" && continue
      fi
    fi
    if [ -f "$DRY_MODEL_ROOT/instance/.git/config.worktree" ] &&
        git -C "$DRY_MODEL_ROOT/instance" config --worktree \
          --get-all core.worktree >/dev/null 2>&1; then
      if ! git -C "$DRY_MODEL_ROOT/instance" config --worktree \
          --replace-all core.worktree "$DRY_MODEL_ROOT/instance"; then
        abandon_instance "  ERROR: could not isolate linked-worktree config" && continue
      fi
    fi
    path="$DRY_MODEL_ROOT/instance"
    if [ "$itype" = "direct-clone" ]; then
      ORIGINAL_ORIGIN="$(git -C "$ORIGINAL_PATH" remote get-url origin 2>/dev/null || true)"
      case "$ORIGINAL_ORIGIN" in
        /*|*://*|*@*:*) ;;
        *)
          ORIGINAL_ORIGIN="$(
            python3 - "$ORIGINAL_PATH" "$ORIGINAL_ORIGIN" <<'PY'
import os
import sys
print(os.path.abspath(os.path.join(sys.argv[1], os.path.expanduser(sys.argv[2]))))
PY
          )"
          ;;
      esac
      if [ -z "$ORIGINAL_ORIGIN" ] ||
          ! git -C "$path" remote set-url origin "$ORIGINAL_ORIGIN"; then
        abandon_instance "  ERROR: could not configure isolated direct-clone origin" && continue
      fi
    fi
  fi

  if [ "$DRY_RUN" != "--dry-run" ] || [ "$MODEL_RUN" = "1" ]; then
    cd "$path"

    # Clean up stale git lock files from crashed processes
    for lockfile in "$path/.git/HEAD.lock" "$path/.git/index.lock" "$path/.git/AUTO_MERGE.lock"; do
      if [ -f "$lockfile" ]; then
        echo "  Removing stale lock: $(basename "$lockfile")"
        rm -f "$lockfile"
      fi
    done
    if ! write_run_marker "$path"; then
      abandon_instance "  ERROR: refusing to overlap another fleet update on this instance" && continue
    fi

    # Abort any zombie rebase/merge/cherry-pick
    if [ -d "$path/.git/rebase-merge" ] || [ -d "$path/.git/rebase-apply" ]; then
      echo "  Aborting zombie rebase..."
      git rebase --abort 2>/dev/null || true
    fi
    if [ -f "$path/.git/MERGE_HEAD" ]; then
      echo "  Aborting zombie merge..."
      git merge --abort 2>/dev/null || true
    fi

    # THE OTHER HALF OF THE UNTRACK BELOW, and it must run FIRST (sp-097d2e23).
    #
    # `git rm --cached` leaves the file on disk, UNTRACKED. In the skeleton that
    # is invisible, because root .gitignore has covered these paths since
    # .gitignore:123. No instance has ever had those lines: root .gitignore is
    # not in this script's sync set (q-system/, .claude/{agents,output-styles,
    # rules}/*.md, .claude/settings.json, plugins/). So on an instance the
    # untracked marker is REPORTED by git status, auto-commit.py classifies
    # q-system/.q-system/ as `chore` exhaust, and the next ordinary session
    # commits it straight back. The migration below would then have to run
    # again, and again, forever.
    #
    # That is not a prediction. SYSTEM_NEVER_COMMIT closes this script's own
    # commit path; the commit that re-added the marker to an instance at
    # 2026-08-14 14:22 carried auto-commit.py's subject ("chore: update system
    # infrastructure"), not this script's ("...before skeleton sync"). Two
    # writers, and the array only ever guarded one of them.
    #
    # Ignoring the path guards every writer at once -- this script, the Stop
    # hook, a stray `git add -A`, the founder's own commit -- because it works
    # at the layer all of them read. The stanza is PARSED from the skeleton's
    # own .gitignore, so adding a fourth never-commit path there reaches all 22
    # instances without touching this file.
    #
    # ADVISORY FOR THE UPDATE, A HARD PRECONDITION FOR THE UNTRACK
    # (PR #165 review round 6, major -- a defect in this block's first version).
    #
    # That version said: "an instance that cannot take the block is not a reason
    # to abandon an otherwise good update, and the untrack below still runs."
    # The first half is right and the second half is the bug. `git rm --cached`
    # leaves the marker on disk UNTRACKED; if the ignore rules are not in place
    # at that moment, git reports it and the next ordinary session's auto-commit
    # puts it straight back. So a failed block turned the untrack from a repair
    # into the exact regression the ordering exists to prevent -- and it would do
    # it again on every run, because the marker's one line is a timestamp the
    # tripwire rewrites on every arm.
    #
    # Leaving the marker TRACKED is the stable state. It is where 5 instances
    # already sit, the sync still works, and the next run can retry. Untracking
    # without ignoring is strictly worse than not untracking at all.
    #
    # So: the sync continues (advisory), the untrack does not (gated).
    GITIGNORE_BLOCK="$SCRIPT_DIR/kipi-update-gitignore-block.py"
    GITIGNORE_BLOCK_OK=0
    if [ -f "$GITIGNORE_BLOCK" ]; then
      if python3 "$GITIGNORE_BLOCK" --skeleton "$SCRIPT_DIR" --instance "$path"; then
        GITIGNORE_BLOCK_OK=1
      else
        echo "    WARN: could not write the .gitignore managed block; skipping the never-commit untrack so the marker is not left untracked AND unignored"
      fi
    else
      echo "    WARN: .gitignore block writer missing; skipping the never-commit untrack so the marker is not left untracked AND unignored"
    fi

    # ONE-TIME MIGRATION, and it must run BEFORE the block below (measured 2026-08-14, 6 instances).
    #
    # The chokepoint stops the baseline from BECOMING tracked. It does nothing for
    # the 6 instances where it already is: on those, preserve-scan rule 3 still
    # hands the committed copy to `rsync --delete` on the very next run. Untracking
    # is the only thing that moves them into the state the two healthy instances
    # are already in.
    #
    # Idempotent by construction: `ls-files --error-unmatch` is the test, so once
    # the path is untracked every later run skips it and this costs one git call.
    #
    # NEVER a working-tree delete. `git rm --cached` unstages the file and leaves
    # the instance's real baseline on disk, which is the whole point -- deleting it
    # would cause by hand the exact outage this is repairing.
    #
    # THE PATHSPEC TRAP, and it is the reason for the assert. `git commit -- <path>`
    # commits WORKTREE content and disregards the index, so the obvious
    #
    #     git rm --cached X && git commit -- X
    #
    # silently RE-ADDS X and undoes the untrack. The commit here therefore takes no
    # pathspec -- which is only safe because the index was proved to hold nothing
    # else, first by refusing outright when the founder has staged work (not ours to
    # package, same rule as the dirty guard below), then by asserting the staged set
    # is exactly this one path before committing.
    for sys_path in "${SYSTEM_NEVER_COMMIT[@]}"; do
      # Gated on the managed block being in place -- see the WARN above. A first
      # attempt at this guard used ${GITIGNORE_BLOCK_OK:+...} on the array, which
      # is wrong: the flag is 0 or 1 and "0" is non-empty, so it expanded on
      # failure exactly as before. Plain and readable beats clever here.
      [ "$GITIGNORE_BLOCK_OK" = "1" ] || continue
      git ls-files --error-unmatch -- "$sys_path" >/dev/null 2>&1 || continue
      if [ -n "$(git diff --cached --name-only 2>/dev/null)" ]; then
        say "  WARNING: $sys_path is tracked, but the index already holds staged work."
        say "           Leaving it. It will be deleted by this sync until it is untracked."
        continue
      fi
      # This untrack and its reset backouts are index writes too (PR #314
      # round 3); a lock held past the bound skips this path, with the error
      # printed, rather than failing the whole instance.
      wait_for_index_lock "$path" "untrack $sys_path" || continue
      if ! git rm --cached --quiet -- "$sys_path" 2>/dev/null; then
        say "  WARNING: could not untrack $sys_path"
        continue
      fi
      sys_staged="$(git diff --cached --name-only 2>/dev/null)"
      if [ "$sys_staged" != "$sys_path" ]; then
        say "  WARNING: staging $sys_path produced an unexpected index; backing out"
        git reset --quiet -q -- "$sys_path" >/dev/null 2>&1 || true
        continue
      fi
      if wait_for_index_lock "$path" "untrack commit" && git commit -q -m "chore: untrack instance-local $sys_path [no-issue: fleet updater instance-local untrack]

This file is instance-local (ASK-282) and gitignored by policy. While it was
tracked, the skeleton sync deleted it -- the skeleton once tracked the path and
then removed it, so preserve-scan correctly treats it as a propagating deletion.
The file itself is untouched on disk." 2>/dev/null; then
        say "  untracking instance-local file: $sys_path"
      else
        say "  WARNING: could not commit the untrack of $sys_path; backing out"
        git reset --quiet -q -- "$sys_path" >/dev/null 2>&1 || true
      fi
    done

    # Clear the system's OWN artifacts first, so the guard below judges founder
    # work only. Each path is committed individually and only if it is actually
    # dirty; nothing outside SYSTEM_OWNED_PATHS is ever touched here.
    sys_owned_dirty=()
    while IFS= read -r sys_path; do
      [ -n "$sys_path" ] || continue
      if ! git diff --quiet -- "$sys_path" 2>/dev/null ||
          ! git diff --cached --quiet -- "$sys_path" 2>/dev/null; then
        sys_owned_dirty+=("$sys_path")
      fi
    done < <(system_owned_paths_for_run)

    # Before anything is committed or written: which files this run would
    # overwrite carry content the skeleton never shipped (sp-1ad08728). Runs in
    # every mode, so the plain dry run, the fleet dry sweep's model run and the
    # apply all print the same lines.
    instance_ahead_preflight "$path" "$prefix" "$name"
    if [ "$REFUSE_INSTANCE_AHEAD" = "1" ] && [ "$INSTANCE_AHEAD_HITS" -gt 0 ]; then
      abandon_instance "  ERROR: instance is ahead of the skeleton on $INSTANCE_AHEAD_HITS file(s); refusing (--refuse-instance-ahead), nothing staged, nothing written" && continue
    fi

    # ASK-605. The list above is hand-maintained and names 3 paths. auto-commit.py's
    # classifier answers the SAME question -- "is this the system's own exhaust?" --
    # for the whole tree, and the two disagreed. `q-system/memory/open-loops.json`
    # is written by a background heartbeat, is `chore` to the classifier, was absent
    # from the list, and on 2026-08-10 left 4 of 7 instances permanently unsyncable:
    # dirty forever, so never synced, so never given the fix that would help.
    #
    # We shell the SKELETON's copy, never the instance's. A blocked instance is by
    # definition running stale code -- Alice's own pre-ASK-498 copy still had the
    # `chore: update project files` catch-all and swept 162 files of investigation
    # evidence when run there. The instance most in need of sweeping is the one whose
    # sweeper cannot be trusted, and this is how that circle breaks.
    #
    # `chore` only: content/feat are founder-authored and not the updater's to take.
    sys_classifier="$SCRIPT_DIR/q-system/hooks/auto-commit.py"
    if [ -f "$sys_classifier" ]; then
      while IFS= read -r sys_path; do
        [ -n "$sys_path" ] || continue
        # `:-` is not decoration. /bin/bash on macOS is 3.2.57, where `arr[*]`
        # on an EMPTY array is an unbound-variable error under `set -u` (bash
        # 4.4+ made it expand to nothing). The array is empty exactly when none
        # of the three hand-listed paths are dirty -- which is the case this
        # whole block was added to handle -- so the code written to unblock a
        # stuck instance aborted its sync instead. ASK-607, measured 2026-08-10.
        case " ${sys_owned_dirty[*]:-} " in *" $sys_path "*) continue ;; esac
        sys_owned_dirty+=("$sys_path")
      # -uall, not the default: plain --porcelain collapses untracked content into
      # the DIRECTORY ("q-system/"), which matches no classifier prefix, so every
      # untracked system file silently classified as nothing. Caught by running it
      # against a scratch repo rather than by reading it.
      done < <(git status --porcelain -uall 2>/dev/null | cut -c4- \
                 | python3 "$sys_classifier" --system-state 2>/dev/null)
    fi

    # THE CHOKEPOINT (measured 2026-08-14, 6 instances). Both feeders have now run; this is the only place
    # that can see everything either of them produced. See SYSTEM_NEVER_COMMIT for
    # why committing these paths is what gets them deleted.
    #
    # `${arr[@]+"${arr[@]}"}` and the explicit empty branch are not style. This is
    # /bin/bash 3.2 on macOS under `set -u`, where expanding an EMPTY array errors
    # out (ASK-607 aborted a sync exactly this way), and where
    # `arr=("${maybe_empty[@]:-}")` silently builds a ONE-element array holding the
    # empty string -- which would then be printed as a committed file and handed to
    # `git add ""`.
    if [ "${#sys_owned_dirty[@]}" -gt 0 ]; then
      sys_kept=()
      for sys_path in ${sys_owned_dirty[@]+"${sys_owned_dirty[@]}"}; do
        case " ${SYSTEM_NEVER_COMMIT[*]} " in
          *" $sys_path "*)
            say "  Leaving instance-local file uncommitted: $sys_path"
            ;;
          *) sys_kept+=("$sys_path") ;;
        esac
      done
      if [ "${#sys_kept[@]}" -eq 0 ]; then
        sys_owned_dirty=()
      else
        sys_owned_dirty=("${sys_kept[@]}")
      fi
    fi

    # sp-46c73c76. This read `[ "$DRY_RUN" != "1" ]`, and DRY_RUN is only ever ""
    # or the literal "--dry-run" (set at :22/:26) -- so the guard was ALWAYS true
    # and a --dry-run really did commit into live instances. Every other site in
    # this file already compares against "--dry-run" plus the MODEL_RUN escape
    # (a dry run operates on a throwaway clone, where writing is the point).
    # Found while extending this very block for ASK-605, which would have made a
    # "dry" run commit MORE.
    if [ "${#sys_owned_dirty[@]}" -gt 0 ] &&
        { [ "$DRY_RUN" != "--dry-run" ] || [ "$MODEL_RUN" = "1" ]; }; then
      say "  Committing ${#sys_owned_dirty[@]} system-written file(s) so they do not block the sync:"
      printf '    %s\n' "${sys_owned_dirty[@]}"
      # PATHSPEC-limited commit. `git commit` with no pathspec commits everything
      # ALREADY STAGED, so a founder with staged work would have had it swept into
      # this infra commit -- the exact thing the guard below exists to prevent,
      # reintroduced by the fix for it (Codex review, PR #98). With a pathspec,
      # only these paths are committed no matter what else sits in the index.
      #
      # THE ADD IS REQUIRED, AND IT IS SAFE (ASK-775). This block used to carry
      # "NO `git add`" as a rule, which quietly broke the whole carve-out: the
      # list MIXES tracked and untracked paths -- the classifier above pulls in
      # untracked machine exhaust on purpose -- and
      #
      #     git commit -- <tracked> <untracked>
      #     error: pathspec '<untracked>' did not match any file(s) known to git
      #
      # commits NOTHING. One untracked artifact therefore left the TRACKED
      # skeleton-owned dirt uncommitted too, and the guard below then refused the
      # instance over the very files this block had just announced it handled.
      # With `2>/dev/null || true` the failure was invisible while the
      # "Committing N system-written file(s)" line printed either way.
      #
      # Measured 2026-08-14, full dry sweep of 23 instances: 11 refusals, 10 of
      # them preceded by that announcement. One instance named 3 files, 2 of
      # them untracked, and refused with all 3 still dirty. (Instance NAMED in
      # the sweep log, not here: the skeleton ships to every instance, so an
      # instance name in a skeleton script is a propagation leak, which Gate 1
      # refuses. Learned the hard way on this very commit.)
      #
      # FILES, NEVER DIRECTORIES (Codex review of #151, major). "Pathspec-limited"
      # was not the safety I claimed it was: sys_owned_dirty carries DIRECTORY
      # entries -- `plugins/<name>` for every managed plugin, from
      # system_owned_paths_for_run -- and `git add <dir>` recursively stages every
      # untracked file beneath it. That includes untracked SOURCE a founder is
      # mid-edit on inside a managed plugin. Measured on this repo: 91 such paths
      # under plugins/kipi-core, 47 under plugins/prd-os.
      #
      # auto-commit.py:170 refuses source by extension precisely so the fleet
      # never commits founder code (ASK-712). Handing `git add` a directory walks
      # straight past that file-level decision. The fix for a silent commit
      # failure must not become a silent commit of the wrong thing.
      #
      # So each entry is expanded to the paths that are ACTUALLY dirty under it,
      # and every one of those is re-classified by the same auto-commit.py the
      # untracked loop above uses. A path the classifier will not call system
      # state is dropped here even though its parent directory is system-owned.
      # Without the classifier present we add nothing new -- the tracked entries
      # still stage, which is what unblocks the sync, and unclassifiable
      # untracked content is left for the guard below to refuse honestly.
      # TRACKED EDITS NEED A DIFFERENT TEST THAN UNTRACKED ONES (Codex review of
      # #151 round 2, major). `git add -u -- plugins/<name>` stages every tracked
      # modification under the directory, so a founder editing a .py inside a
      # managed plugin had it committed under a chore message.
      #
      # But the obvious fix -- run tracked files through auto-commit.py too --
      # breaks the thing this PR exists to fix. That classifier refuses source by
      # extension, and the file blocking 7 of the 11 instances is
      # plugins/prd-os/tests/test_judgment_compiler.py. Classify it and it is
      # refused, never committed, and the instance stays blocked forever.
      #
      # The distinguisher is not the extension, it is AUTHORSHIP, and the skeleton
      # can answer that directly: if the instance's working-tree content for a
      # managed-plugin file is byte-identical to the SKELETON's current content,
      # that content came from the fleet -- an earlier fanout wrote it and failed
      # to commit (ASK-728 did exactly this). Committing it records what is
      # already there. If it differs from the skeleton, someone local wrote it,
      # and it is not ours to take at any extension; it is left dirty so the guard
      # below refuses this instance and protects it.
      #
      # Fail-closed both ways: a file we cannot read on either side is treated as
      # founder work and left alone.
      sys_add_paths=()
      for sys_path in "${sys_owned_dirty[@]}"; do
        if [ -d "$path/$sys_path" ]; then
          # Tracked modifications: skeleton-content equality decides.
          while IFS= read -r dirty_rel; do
            [ -n "$dirty_rel" ] || continue
            # DELETIONS ARE AUTHORED TOO (Codex review of #151 round 3, major).
            # `cmp` needs both sides to exist, so a file the fleet DELETED read as
            # a local edit and blocked the instance permanently -- the very
            # deadlock this PR exists to break, reintroduced for the one case the
            # equality test could not express. The skeleton answers deletion the
            # same way it answers content: if the skeleton no longer ships the
            # file AND the instance no longer has it, the copy removed it and the
            # deletion is the fleet's to record. A file the skeleton still ships
            # is NOT this case -- someone local deleted it, and the sync will put
            # it back, so it stays a local edit.
            # THE INDEX IS A THIRD VERSION, AND `git add` DESTROYS IT (Codex
            # review of #151 round 4, major). Comparing only worktree-to-skeleton
            # misses this sequence: a founder STAGES an edit, a later fanout
            # overwrites the working tree with the skeleton's copy, the equality
            # test then says "fleet-written", and `git add` replaces the staged
            # blob with the skeleton content. The founder's staged work is gone,
            # with no diff left to show it ever existed.
            #
            # Every path here therefore has to clear the index before content is
            # even considered. NOT "index == skeleton", which would break the
            # whole fix: in the ordinary fanout case the index equals HEAD, the
            # instance is behind, so index != skeleton and every legitimate path
            # would be refused. The question is narrower -- is there a staged
            # CHANGE, and if so is that staged content itself the skeleton's?
            #
            #   no staged change          -> index is just HEAD, nothing to lose
            #   staged change == skeleton -> the fleet staged its own write
            #   staged change != skeleton -> founder work in the index. Leave it.
            # ONE index question, asked BEFORE any content or deletion reasoning
            # (Codex review of #151 round 5, blocker). Round 5 put the deletion
            # test first so a staged deletion by the fleet would not be misread --
            # and that ordering made deletion skip the index check entirely. A
            # founder stages an edit, the skeleton drops the file, the copy
            # removes it, and "absent from both" committed a deletion straight
            # over the staged blob. I introduced that hole while fixing round 4's.
            #
            # Ordering cannot resolve this, because the two cases need different
            # index facts. So the index is consulted once, up front, and the
            # question is precise:
            #
            #   no staged change            -> index is HEAD, nothing to lose
            #   staged change, NO index entry -> the fleet staged its own deletion
            #   staged change, entry == skeleton -> the fleet staged its own write
            #   staged change, entry != skeleton -> founder work. Stop here.
            staged_is_founders=0
            if ! git diff --cached --quiet -- "$dirty_rel" 2>/dev/null; then
              if git show ":$dirty_rel" >/dev/null 2>&1 &&
                  ! git show ":$dirty_rel" 2>/dev/null \
                      | cmp -s - "$SCRIPT_DIR/$dirty_rel" 2>/dev/null; then
                staged_is_founders=1
              fi
            fi
            if [ "$staged_is_founders" = "1" ]; then
              say "  keeping STAGED local edit, not the fleet's to commit: $dirty_rel"
            elif [ ! -e "$SCRIPT_DIR/$dirty_rel" ] && [ ! -e "$path/$dirty_rel" ]; then
              sys_add_paths+=("$dirty_rel")
            elif [ -f "$path/$dirty_rel" ] &&
                { { [ -f "$SCRIPT_DIR/$dirty_rel" ] &&
                    cmp -s "$SCRIPT_DIR/$dirty_rel" "$path/$dirty_rel"; } ||
                  fleet_authored_blob "$dirty_rel" "$path/$dirty_rel"; }; then
              # Current-skeleton equality first as the cheap path; the history
              # walk only runs when that fails, which on the real fleet is the
              # common case (instances hold an older fanout's bytes).
              sys_add_paths+=("$dirty_rel")
            else
              say "  keeping local edit, not the fleet's to commit: $dirty_rel"
            fi
          done < <(git diff --name-only -- "$sys_path" 2>/dev/null
                   git diff --cached --name-only -- "$sys_path" 2>/dev/null)
          # Untracked content: the classifier decides, as before.
          while IFS= read -r dirty_rel; do
            [ -n "$dirty_rel" ] || continue
            sys_add_paths+=("$dirty_rel")
          done < <(
            git status --porcelain -uall -- "$sys_path" 2>/dev/null \
              | grep '^??' | cut -c4- \
              | { if [ -f "$sys_classifier" ]; then
                    python3 "$sys_classifier" --system-state 2>/dev/null
                  else
                    # No classifier, no new untracked staging. `true` consumes
                    # stdin and emits nothing, which is the fail-closed answer.
                    true
                  fi; }
          )
          # The directory is deliberately NOT added to sys_add_paths. It was, in
          # round 2, "so tracked modifications are not dropped" -- and that single
          # line put the directory back into the commit pathspec, which is how the
          # founder-edit path survived the first fix. The expansion above is now
          # the ONLY way a path under a managed plugin reaches the commit.
          :
        else
          sys_add_paths+=("$sys_path")
        fi
      done
      if [ "${#sys_add_paths[@]}" -gt 0 ]; then
        git add -- "${sys_add_paths[@]}" 2>/dev/null || true
      fi
      # NO `git add -u -- "${sys_owned_dirty[@]}"` here. Round 2 had one, to catch
      # tracked-but-unstaged content, and `-u` scoped to a DIRECTORY stages every
      # tracked modification under it -- founder edits to a managed plugin
      # included. sys_add_paths already carries the tracked files that passed the
      # skeleton-equality test, and `git add` stages them whether or not they were
      # staged before, so nothing is lost by dropping this line.
      # `[no-issue: ...]` rather than --no-verify: the instance's commit-msg
      # gate wants a Linear id, and this is the sanctioned hatch that gets
      # LOGGED to linear-bypass.jsonl. Bypassing an instance's hooks wholesale
      # to land a commit in their repo is not ours to do.
      #
      # NOT SILENT ANY MORE. The old `2>/dev/null || true` is what let this run
      # for months: a carve-out that cannot fail loudly cannot be noticed when it
      # does. The run still continues on failure -- the guard below is the real
      # decision and it fails closed -- but it says what happened first.
      #
      # GUARDED ON NON-EMPTY, and this is not defensive padding. `git commit --`
      # with an EMPTY pathspec is not a no-op: it commits everything already
      # staged, which is precisely the founder-sweeping behaviour the PR #98 rule
      # exists to stop. sys_add_paths is empty exactly when every dirty path was
      # judged a local edit, i.e. the case where sweeping would be worst.
      if [ "${#sys_add_paths[@]}" -eq 0 ]; then
        say "  nothing to commit: every dirty system-owned path is a local edit"
      else
        # No command substitution around the commit. Inside one, the lock
        # wait's progress lines (the first wait AND every retry's) were
        # captured with the commit's stderr and printed only on failure, so a
        # two-minute wait was silent (PR #314 rounds 2 and 3). stdout reaches
        # the terminal as it happens; only stderr is kept for the warning.
        sys_errf="$(mktemp)"
        if ! retry_on_index_lock "$path" "system-state commit" git commit -q -m "chore: commit system-written state before skeleton sync [no-issue: fleet updater system-state commit]

These files are written by the fleet itself (sycophancy stamp, integrity
baseline, hook state, skeleton-shipped plugins). Committing them here keeps the
updater from being blocked by its own exhaust; founder work is never included
because this commit is pathspec-limited." -- "${sys_add_paths[@]}" 2>"$sys_errf"; then
          echo "  WARNING: the system-state commit FAILED; this instance will very"
          echo "  likely be refused below over dirt that is not founder work:"
          sed 's/^/    /' "$sys_errf"
        fi
        rm -- "$sys_errf"
      fi
    fi

    # Refuse tracked work in progress. The updater owns only its scoped sync
    # commits and must never package unrelated founder edits into an infra commit.
    #
    # SCOPED, not repo-wide (ASK-609). The sync writes exactly three things:
    # $prefix/ minus the instance-owned subtrees, .claude/, and plugins/. A
    # dirty file anywhere else is in a path this run is not permitted to write,
    # so it cannot be packaged into an infra commit and cannot be damaged.
    # Measured 2026-08-10: 182 dirty files across the four blocked instances,
    # ZERO of them reachable by the sync. Alice's 162 are investigation
    # evidence under q-investigate/. The guard was protecting an empty set and
    # charging four instances every future fix for it -- including the ASK-607
    # fix written to unblock stuck instances.
    #
    # Same pathspec as checkpoint_untracked_list, deliberately: that function
    # already carries the rule ("restore can never even propose deleting a path
    # the sync was never permitted to touch"). One scope, and the BLOCK
    # decision and the RESTORE decision must not be allowed to drift apart --
    # see restore_instance, which reduces its reset and checkout to this same
    # set. If they diverge, restore discards founder work the guard let past.
    if ! git diff --cached --quiet -- "$prefix/" .claude/ plugins/ \
          $(pathspec_owned_excludes "$prefix") 2>/dev/null ||
        ! git diff --quiet -- "$prefix/" .claude/ plugins/ \
          $(pathspec_owned_excludes "$prefix") 2>/dev/null; then
      if [ "$MODEL_RUN" = "1" ]; then
        echo "  Changes vs skeleton: blocked by dirty working tree"
      fi
      git status --short 2>/dev/null | sed 's/^/    /' || true
      abandon_instance "  ERROR: dirty working tree; refusing to commit unrelated work" && continue
    fi

    # Checkpoint HERE, not earlier, and the placement is the whole safety
    # argument: the guard directly above has just proved the tree clean, so
    # everything a later restore discards is something THIS run wrote. Against
    # a DIRTY checkpoint the restore's `git checkout -- .` would throw away the
    # founder's unstaged edits, which is the opposite of the point.
    if ! checkpoint_instance "$path" "$prefix"; then
      abandon_instance "  ERROR: could not checkpoint the instance; refusing to write" && continue
    fi
  fi

  # voicekit -> voiceloop, BEFORE the rsync that would strand the imports.
  #
  # sp-8d55455a. The skeleton renamed the voice package in cf6acdb4. plugins/
  # rsyncs with --delete, so the sync alone lands voiceloop/, removes voicekit/,
  # and cannot touch the code that imports it -- that code is instance-owned and
  # lives OUTSIDE plugins/ (consulting's q-consult/pipeline/voice.py puts
  # <repo>/plugins/kipi-core on sys.path and imports the package by name).
  # Measured 2026-08-30: 24 of 25 registered instances still carried the old
  # name, so this sync was armed to break the voice pipeline in every one.
  #
  # It runs HERE and the placement is the safety argument, the same one
  # checkpoint_instance makes directly above:
  #   * AFTER the dirty-tree guard, so the tree is proven clean and every change
  #     below is one THIS run made;
  #   * AFTER the checkpoint, so a later failure restores through the normal path;
  #   * BEFORE the rsync, so the package already answers to the new name when the
  #     skeleton's copy lands on top of it and --delete has nothing to strand.
  #
  # A migration is not a one-time script somebody remembers to run. An instance
  # that syncs next month without this step breaks in exactly the same way, so
  # it belongs in the update path or it does not exist.
  #
  # The helper commits its own work: it writes outside $prefix/, which the sync
  # commit below is pathspec-limited away from, and an uncommitted rewrite would
  # leave the instance permanently dirty and refused at this very guard forever.
  # Non-zero means it could not finish; abandoning is correct, because the
  # alternative is running the --delete rsync against imports it did not fix.
  VOICELOOP_MIGRATE="$SCRIPT_DIR/kipi-update-voiceloop-migrate.py"
  if [ -f "$VOICELOOP_MIGRATE" ] && [ -d "$path/plugins/kipi-core" ]; then
    if [ "$DRY_RUN" != "--dry-run" ] || [ "$MODEL_RUN" = "1" ]; then
      if ! python3 "$VOICELOOP_MIGRATE" --repo "$path" --apply; then
        abandon_instance "  ERROR: voiceloop migration failed; rsync not started" && continue
      fi
    else
      python3 "$VOICELOOP_MIGRATE" --repo "$path" | sed 's/^/  voiceloop: /' || true
    fi
  fi

  if [ "$itype" = "direct-clone" ]; then
    echo "  Direct clone - pulling from origin..."
    if [ "$DRY_RUN" != "--dry-run" ] || [ "$MODEL_RUN" = "1" ]; then
      if ! git fetch origin "$SKELETON_BRANCH" --quiet 2>/dev/null; then
        abandon_instance "  ERROR: fetch failed" && continue
      fi
      if git pull --rebase origin "$SKELETON_BRANCH" 2>&1; then
        echo "  OK"
        PASS=$((PASS + 1))
      else
        echo "  WARN: rebase failed, trying merge..."
        git rebase --abort 2>/dev/null || true
        if git merge origin/"$SKELETON_BRANCH" --no-edit 2>&1; then
          say "  OK (merged)"
          PASS=$((PASS + 1))
        else
          echo "  WARN: merge failed (needs manual resolve)"
          git merge --abort 2>/dev/null || true
          # No abandon: fall through so the config sync still runs.
          count_instance_failure
        fi
      fi
    fi
  else
    # Archive + rsync: fast, reliable, no history walking
    echo "  Syncing $prefix/ from skeleton..."
    if [ "$DRY_RUN" != "--dry-run" ] || [ "$MODEL_RUN" = "1" ]; then
      ARCHIVE_TMP=$(mktemp -d)
      if git -C "$SCRIPT_DIR" archive --format=tar HEAD -- q-system/ 2>/dev/null | tar -x -C "$ARCHIVE_TMP" 2>/dev/null; then
        # Snapshot untracked instance files before the destructive --delete.
        # `git ls-files --others` lists untracked files INCLUDING gitignored ones
        # (so it covers q-system/sources/ etc. that `git stash -u` would miss).
        # Lives inside ARCHIVE_TMP so the existing rm -rf cleans it -- no stash stack,
        # no extra cleanup, collision-safe.
        SNAP="$ARCHIVE_TMP/.snap"; mkdir -p "$SNAP/f"
        # Excluded from preservation: bytecode junk (regenerable) and the forbidden
        # nested $prefix/q-system/ shadow tree (a stale skeleton copy from the old
        # `git subtree add` creation path -- folder-structure.md bans it; restoring
        # it made the shadow tree immortal across updates).
        if ! ( cd "$path" && git ls-files -z --others -- "$prefix/" \
            $(pathspec_owned_excludes "$prefix") \
            ":(exclude)$prefix/q-system/" \
            ":(exclude)*.pyc" ":(exclude)*__pycache__*" 2>/dev/null ) > "$SNAP/list"; then
          abandon_instance "  ERROR: preservation snapshot inventory failed; rsync not started" && continue
        fi
        COLLISION=0
        while IFS= read -r -d '' uf; do
          relative="${uf#"$prefix/"}"
          if [ "$relative" = "$uf" ]; then
            continue
          fi
          source_path="$ARCHIVE_TMP/q-system/$relative"
          # No third argument: this rsync is a plain --delete with no filters,
          # so a build artifact here is content, not debris.
          # 4th arg: the path as the SKELETON REPO spells it. The archive is
          # `git archive HEAD` extracted with q-system/ inside, so a file the
          # instance keeps at <prefix>/<relative> is q-system/<relative> in the
          # skeleton. Passed per call site rather than derived inside the
          # helper, because the plugins call site maps differently.
          if { [ -e "$source_path" ] || [ -L "$source_path" ]; } &&
              is_instance_wip "$uf" "$source_path" "" "q-system/$relative"; then
            echo "  ERROR: untracked WIP collides with skeleton path: $uf"
            COLLISION=1
          fi
        done < "$SNAP/list"
        if [ "$COLLISION" != "0" ]; then
          abandon_instance && continue
        fi
        # Also preserve TRACKED instance-only files the --delete would remove. The
        # ls-files --others snapshot above only covers UNTRACKED files; a script the
        # instance COMMITTED inside the synced tree was deleted with no protection
        # (scar 2026-06-24: fractional-cxo income scanners died this way for 6 days).
        # The helper flags only files the skeleton NEVER tracked (genuinely instance-
        # added), so skeleton-intended deletions still propagate. It is a hard
        # precondition: missing or incomplete proof stops before rsync --delete.
        PRESERVE_SCAN="$SCRIPT_DIR/kipi-update-preserve-scan.py"
        if [ ! -f "$PRESERVE_SCAN" ]; then
          abandon_instance "  ERROR: preservation helper missing; rsync not started" && continue
        fi
        if ! python3 "$PRESERVE_SCAN" --skeleton-archive "$ARCHIVE_TMP" \
            --instance "$path" --prefix "$prefix" --skeleton-git "$SCRIPT_DIR" \
            --receipt "$SNAP/preservation-receipt.json" \
            > "$SNAP/tracked" 2>"$SNAP/warn"; then
          [ -s "$SNAP/warn" ] && cat "$SNAP/warn"
          abandon_instance "  ERROR: preservation helper failed; rsync not started" && continue
        fi
        if ! python3 - "$SNAP/preservation-receipt.json" "$SNAP/tracked" <<'PY'
import hashlib
import json
import pathlib
import sys

receipt_path = pathlib.Path(sys.argv[1])
output_path = pathlib.Path(sys.argv[2])
try:
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    output = output_path.read_bytes()
except (OSError, UnicodeError, json.JSONDecodeError):
    raise SystemExit(1)
expected_keys = {
    "candidate_count",
    "complete",
    "schema_version",
    "stdout_sha256",
}
if set(receipt) != expected_keys:
    raise SystemExit(1)
if receipt["schema_version"] != 1 or receipt["complete"] is not True:
    raise SystemExit(1)
if output and not output.endswith(b"\n"):
    raise SystemExit(1)
if receipt["candidate_count"] != len(output.splitlines()):
    raise SystemExit(1)
if receipt["stdout_sha256"] != hashlib.sha256(output).hexdigest():
    raise SystemExit(1)
PY
        then
          abandon_instance "  ERROR: preservation receipt incomplete or invalid; rsync not started" && continue
        fi
        [ -s "$SNAP/warn" ] && cat "$SNAP/warn"
        if [ -s "$SNAP/tracked" ]; then
          while IFS= read -r tf; do [ -n "$tf" ] && printf '%s\0' "$tf"; done \
            < "$SNAP/tracked" >> "$SNAP/list"
        fi
        if ! ( cd "$path" && while IFS= read -r -d '' uf; do
            mkdir -p "$SNAP/f/$(dirname "$uf")" &&
              cp -a "$uf" "$SNAP/f/$uf" 2>/dev/null || exit 1
          done < "$SNAP/list" ); then
          abandon_instance "  ERROR: preservation snapshot copy failed; rsync not started" && continue
        fi
        # Excludes are ANCHORED (leading /) to the transfer root. Unanchored
        # patterns also matched inside the nested q-system/q-system/ shadow copy
        # (protecting ITS memory/, canonical/, ...), so rsync could never delete
        # the shadow tree -- "not empty, cannot delete" on every update.
        # FAIL-CLOSED BACKSTOP (sp-737ce1ae, sp-10cf4f76). The excludes above
        # are ANCHORED to the transfer root, so they only protect the instance
        # when the destination IS its q-system dir. Reproduced 2026-08-05: with
        # a null `subtree_prefix` the destination is the instance ROOT, and an
        # instance still keeping its data under q-system/ has that data one
        # level below where the excludes point -- the dry run itemizes
        # `*deleting q-system/my-project/...` and nothing stops it.
        #
        # Re-anchoring the excludes fixes that variant; this catches the CLASS.
        # Any future layout, prefix, or registry drift that moves the
        # destination re-opens the same hole, and the failure mode is deleted
        # founder data with no error. So: ask rsync what it plans to delete,
        # and refuse if any of it is instance-owned at any depth.
        if ! rsync -ain --delete "$ARCHIVE_TMP/q-system/" "$path/$prefix/" \
            $(rsync_owned_excludes) 2>/dev/null \
            | python3 "$SCRIPT_DIR/kipi-update-deletion-guard.py"; then
          abandon_instance "  ERROR: q-system sync would delete instance-owned data; refusing" && continue
        fi
        if ! rsync -a --delete "$ARCHIVE_TMP/q-system/" "$path/$prefix/" \
            $(rsync_owned_excludes) 2>/dev/null; then
          abandon_instance "  ERROR: q-system sync failed" && continue
        fi
        # Restore any untracked file the rsync --delete removed (skeleton doesn't manage it).
        if ! ( cd "$path" && while IFS= read -r -d '' uf; do
            if ! { [ -e "$uf" ] || [ -L "$uf" ]; } && { [ -e "$SNAP/f/$uf" ] || [ -L "$SNAP/f/$uf" ]; }; then
              mkdir -p "$(dirname "$uf")" && cp -a "$SNAP/f/$uf" "$uf" && say "  restored untracked: $uf"
            fi
          done < "$SNAP/list" ); then
          abandon_instance "  ERROR: preserved-file restore failed" && continue
        fi
        rm -r -- "$ARCHIVE_TMP"
        ARCHIVE_TMP=""
        cd "$path"
        if ! wait_for_index_lock "$path" "q-system sync staging" ||
            ! stage_q_system_sync "$path" "$prefix" 2>/dev/null; then
          unstage_scope "$path" "$prefix/"
          abandon_instance "  ERROR: could not stage q-system sync" && continue
        fi
        CHANGES=$(git diff --cached --name-only 2>/dev/null | wc -l | tr -d ' ')
        if [ "$CHANGES" != "0" ]; then
          if ! retry_on_index_lock "$path" "q-system sync commit" guarded_commit "$path" \
              "chore: sync q-system from skeleton $(date +%Y-%m-%d) [no-issue: fleet updater skeleton sync]"; then
            abandon_instance "  ERROR: could not commit q-system sync" && continue
          fi
          say "  OK ($CHANGES files updated)"
        else
          say "  OK (already up to date)"
        fi
        PASS=$((PASS + 1))
      else
        rm -r -- "$ARCHIVE_TMP"
        ARCHIVE_TMP=""
        echo "  WARN: archive export failed"
        # No abandon: fall through so the config sync still runs.
        count_instance_failure
      fi
    else
      cd "$path"
      # Real itemized preview: rsync -ain --delete from the SAME `git archive HEAD`
      # source AND the same excludes the real run uses, so --dry cannot drift from
      # what a real run would change/delete.
      DRY_TMP=$(mktemp -d)
      if git -C "$SCRIPT_DIR" archive --format=tar HEAD -- q-system/ 2>/dev/null | tar -x -C "$DRY_TMP" 2>/dev/null; then
        CHANGED=$(rsync -ain --delete "$DRY_TMP/q-system/" "$path/$prefix/" \
          $(rsync_owned_excludes) 2>/dev/null)
        if [ -n "$CHANGED" ]; then
          echo "  Changes vs skeleton (run without --dry to apply):"
          echo "$CHANGED" | sed 's/^/    /'
        else
          echo "  Up to date"
        fi
        rm -r -- "$DRY_TMP"
        DRY_TMP=""
      else
        rm -r -- "$DRY_TMP"
        DRY_TMP=""
        echo "  WARN: archive export failed (dry)"
      fi
      PASS=$((PASS + 1))
    fi
  fi

  # Sync settings, agents, rules, output styles, and plugins
  if { [ "$DRY_RUN" != "--dry-run" ] || [ "$MODEL_RUN" = "1" ]; } &&
      [ -d "$path/.claude" ]; then
    echo "  Syncing .claude/ config..."
    CONFIG_FAILED=0
    if ! reject_untracked_config_collisions "$path"; then
      abandon_instance && continue
    fi

    # Rebuild settings.json from template (preserves instance customizations)
    if [ -f "$path/.claude/settings.json" ]; then
      # Merge lives in kipi-settings-merge.py (extracted 2026-07-02 so it is
      # testable: test-settings-merge.sh). Scar: the former inline heredoc
      # deduped hooks by exact command string, so a template command-form
      # change left BOTH forms in every instance — token-guard ran twice per
      # tool call and its counters doubled. The script dedupes by invoked
      # script basename; template form wins, instance-added hooks survive.
      if ! python3 "$SCRIPT_DIR/kipi-settings-merge.py" \
          "$SCRIPT_DIR/settings-template.json" \
          "$path/.claude/settings.json" 2>/dev/null; then
        echo "    ERROR: settings.json sync failed"
        CONFIG_FAILED=1
      fi

      # Path rewriting: previously this section doubled $CLAUDE_PROJECT_DIR/q-system/
      # to $CLAUDE_PROJECT_DIR/q-system/q-system/ for "subtree" instances. That logic
      # was wrong: the rsync above copies skeleton/q-system/* into instance/q-system/*,
      # so template paths like q-system/.q-system/scripts/X.py already point to the
      # correct file at instance/q-system/.q-system/scripts/X.py.
      # The doubled paths were silently no-ops via the `test -f ... || true` wrappers
      # in the hook commands, which is why this went undetected for a long time.
      # If you're reading this and considering re-adding sed rewriting, verify the
      # actual on-disk file structure of a subtree instance first.
    fi

    # Sync agents, output styles, rules
    if ! mkdir -p "$path/.claude/agents" "$path/.claude/output-styles" \
        "$path/.claude/rules"; then
      CONFIG_FAILED=1
    fi
    for config_kind in agents output-styles rules; do
      if compgen -G "$SCRIPT_DIR/.claude/$config_kind/*.md" >/dev/null &&
          ! cp "$SCRIPT_DIR"/.claude/"$config_kind"/*.md \
            "$path/.claude/$config_kind/" 2>/dev/null; then
        CONFIG_FAILED=1
      fi
    done

    # Sanction the .claude/ writes THIS update just made (ASK-291).
    #
    # SCAR, measured before rollout by probe_update_interaction.sh: Layer 2
    # (claude-integrity-tripwire.py --enforce) is wired PostToolUse on every
    # instance and AUTO-REVERTS unsanctioned .claude/ content. Everything above
    # this line rewrites .claude/ -- settings.json from the template, then
    # rules/, agents/, output-styles/. Without this call the next tool call in
    # the updated instance sees all of it as drift, quarantines it, and rolls the
    # update BACK. The updater already printed OK. Silent, and on 23 machines.
    #
    # A sanction and not an exclusion: `kipi update` propagates the skeleton's
    # git HEAD, which is the same reviewed provenance the tripwire's own
    # attributable() already treats as sanctioned. Excluding settings.json from
    # the watch set would hand back the whole hole. Phase 3 of the probe holds
    # the other end: a tamper AFTER this call is still caught.
    #
    # --register, NOT a blanket --baseline (review finding, PR #85). A blanket
    # re-baseline re-measures the WHOLE watch set, so any unrelated tamper that
    # happened to be sitting in .claude/ at that moment became sanctioned
    # content, fleet-wide, on every update. The applier's own docstring already
    # named that "the blinding version of this fix"; the updater was doing it.
    # The path list below is exactly what this run writes -- settings.json, every
    # .md copied above, and the two guard scripts the q-system rsync replaced --
    # so an unrelated file cannot ride along.
    #
    # THE WATCH SET IS NOT ONLY .claude/ (review finding, PR #85 round 14, MAJOR).
    # The list was written from the .claude/ half of it while the tripwire's
    # EXTRA_WATCHED has always held two files OUTSIDE .claude/: both guard
    # scripts, which the rsync at the top of this block rewrites on every update.
    # A fresh local commit is in no remote default branch, so head_is_reviewed()
    # is False and nothing absorbed them. Measured on a stand-in instance
    # (probe_round14_findings.sh phase 1): every tool call after a routine update
    # printed `SECURITY: unsanctioned .claude/ change -- 2 modified`, forever, on
    # 23 machines, until a human ran --baseline on each. An alarm nobody reads is
    # the same as no alarm, which is the failure mode both scripts' headers exist
    # to avoid.
    #
    # DERIVED FROM THE TRIPWIRE, NOT TRANSCRIBED: the paths come out of the
    # instance's own EXTRA_WATCHED, so adding a third watched file outside
    # .claude/ cannot leave this list behind.
    #
    # Best-effort by design: an instance that has not adopted the tripwire has no
    # script here, and a sanction failure must never abandon a good update.
    if [ -f "$path/q-system/.q-system/scripts/claude-integrity-tripwire.py" ]; then
      TRIPWIRE_WROTE=()
      [ -f "$path/.claude/settings.json" ] && TRIPWIRE_WROTE+=(".claude/settings.json")
      for config_kind in agents output-styles rules; do
        if compgen -G "$SCRIPT_DIR/.claude/$config_kind/*.md" >/dev/null; then
          for src in "$SCRIPT_DIR"/.claude/"$config_kind"/*.md; do
            TRIPWIRE_WROTE+=(".claude/$config_kind/$(basename "$src")")
          done
        fi
      done
      while IFS= read -r extra_rel; do
        [ -n "$extra_rel" ] || continue
        [ -f "$path/$extra_rel" ] && TRIPWIRE_WROTE+=("$extra_rel")
      done < <(python3 -c '
import importlib.util, sys
spec = importlib.util.spec_from_file_location("t", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print("\n".join(mod.EXTRA_WATCHED))
' "$path/q-system/.q-system/scripts/claude-integrity-tripwire.py" 2>/dev/null)
      KIPI_NOTIFY=/usr/bin/true python3 \
        "$path/q-system/.q-system/scripts/claude-integrity-tripwire.py" \
        --root "$path" --quiet \
        --register ${TRIPWIRE_WROTE[@]+"${TRIPWIRE_WROTE[@]}"} >/dev/null 2>&1 ||
        echo "    WARN: could not sanction .claude/ tripwire writes (next tool call may revert this update)"
    fi

    # Sync plugins (copy contents, not directory, to avoid plugins/plugins/ nesting).
    # rsync instead of rm -rf + cp -R: --delete-excluded strips embedded .git dirs
    # and bytecode from the instance copy. A symlinked skeleton plugin (e.g.
    # memory-lifecycle -> standalone repo) used to materialize WITH its .git,
    # leaving every instance permanently dirty on plugins/<name> in git status.
    if [ -d "$SKELETON_PLUGIN_ROOT" ]; then
      mkdir -p "$path/plugins"
      while IFS= read -r -d '' plugin_name; do
        # .venv/ is a uv-built virtualenv, not source: uv writes a
        # `.gitignore` of `*` inside it, pyvenv.cfg pins it to ONE machine's
        # Python (home = /Users/<name>/... macos-aarch64), and nothing
        # launches it -- plugins/kipi-core/.mcp.json runs `uv run`, which
        # rebuilds it from the tracked uv.lock (measured: 52 packages, 37ms).
        # It was 107MB of the 112MB plugin tree, copied into 23 instances
        # where it could never work. --delete-excluded also clears the stale
        # copies already there. Pairs with test-kipi-update-build-artifacts.sh.
        # Flags derived from PLUGIN_COPY_EXCLUDES, never hand-listed here: this
        # site and the preflight filter are the two consumers that must agree,
        # and a hand-listed copy is how a plugin-root .env shipped fleet-wide
        # (ASK-772). Word-splitting the generator output is intended -- every
        # pattern is a shell-safe token by construction.
        # shellcheck disable=SC2046
        if ! rsync -a --delete --delete-excluded \
            $(plugin_copy_rsync_flags) \
            "$SKELETON_PLUGIN_ROOT/$plugin_name/" \
            "$path/plugins/$plugin_name/" 2>/dev/null; then
          CONFIG_FAILED=1
        fi
      done < <(managed_plugin_names)
    fi

    # Commit the config sync. The updater used to commit only $prefix/, leaving
    # .claude/ and plugins/ permanently dirty in every instance repo.
    if git -C "$path" rev-parse --git-dir >/dev/null 2>&1; then
      if ! ( cd "$path" &&
        # The untrack below is this block's FIRST index write, so the wait sits
        # before it, not before the staging that follows (PR #314 round 2).
        wait_for_index_lock "$path" "config sync staging" &&
        if git ls-files --error-unmatch plugins/memory-lifecycle \
            >/dev/null 2>&1; then
          git rm -r -q --cached plugins/memory-lifecycle
        fi &&
        { stage_config_sync "$path" ||
            { unstage_scope "$path" .claude/ plugins/; false; }; } &&
        # THE COMMIT HALF NEEDS THE SAME UNWIND AS THE STAGING HALF (ASK-797).
        # unstage_scope was wired to stage_config_sync's failure only, so a
        # staging error unwound cleanly and a COMMIT error did not -- it left the
        # index fully staged and abandoned the instance. The comment on
        # unstage_scope already describes what that costs ("EVERY later run
        # aborts at the dirty-tree guard, because that guard reads `git diff
        # --cached`"); it just did not cover this exit.
        #
        # Measured 2026-08-14: 2 instances were carrying 10 staged additions each
        # under a plugin the skeleton had already dropped, byte-identical across
        # both repos, with clean worktrees. Nothing but this path produces that
        # shape, and no later run could clear it -- a worktree checkout does not
        # touch the index, so it looked like founder work forever.
        { if ! git diff --cached --quiet 2>/dev/null; then
            retry_on_index_lock "$path" "config sync commit" guarded_commit "$path" \
              "chore: sync .claude config + plugins from skeleton $(date +%Y-%m-%d) [no-issue: fleet updater skeleton sync]" ||
              { unstage_scope "$path" .claude/ plugins/; false; }
          fi; }
      ); then
        CONFIG_FAILED=1
      fi
    else
      CONFIG_FAILED=1
    fi

    if [ "$CONFIG_FAILED" != "0" ]; then
      abandon_instance "  ERROR: config sync did not reach a complete committed state" && continue
    fi

    echo "  Config synced"
    clear_run_marker
  fi

  # Post-sync capability gate (structure/wiring/data diff, no test execution —
  # the FULL per-instance run is fleet-capability-verify.py's job). This is the
  # deterministic instance-side call site: a skeleton-only artifact or missing
  # declared file goes loud HERE, at the moment it ships, not months later
  # (finding-2, prd-silent-absence-capability-gate-2026-07-23). Failures are
  # collected, not fatal per-instance, so one red instance cannot block the
  # fix from reaching the other 23; the run still exits non-zero at the end.
  GATE_SCRIPT="$path/q-system/.q-system/scripts/capability-gate.py"
  if [ -z "${DRY_RUN:-}" ]; then
    if [ -f "$GATE_SCRIPT" ]; then
      if python3 "$GATE_SCRIPT" --repo-root "$path" --check-only >"/tmp/kipi-gate-$$.log" 2>&1; then
        echo "  capability gate: GREEN"
      else
        echo "  capability gate: RED"
        tail -8 "/tmp/kipi-gate-$$.log" | sed 's/^/    /'
        GATE_FAIL="$GATE_FAIL $name"
      fi
      rm -f "/tmp/kipi-gate-$$.log"
    else
      # Post-sync and STILL no gate script = the sync itself failed to deliver
      # the fix. Silent skip here would be the disease this gate treats.
      echo "  capability gate: MISSING after sync"
      GATE_FAIL="$GATE_FAIL $name(missing-gate)"
    fi
  fi
  if [ "$MODEL_RUN" = "1" ]; then
    MODELED_DIFF="$(git -C "$path" diff --name-status "$ORIGINAL_HEAD" HEAD --)"
    MODELED_TREE="$(git -C "$path" rev-parse 'HEAD^{tree}')"
    MODELED_STATE="$(worktree_digest "$path")"
    if [ -n "$MODELED_DIFF" ]; then
      echo "  Changes vs skeleton (modeled final state):"
    else
      echo "  Up to date"
    fi
    echo "  MODELED_FINAL_DIFF_BEGIN $name"
    if [ -n "$MODELED_DIFF" ]; then
      printf '%s\n' "$MODELED_DIFF"
    fi
    echo "  MODELED_FINAL_DIFF_END $name"
    echo "  MODELED_FINAL_TREE $name $MODELED_TREE"
    echo "  MODELED_FINAL_STATE_SHA256 $name $MODELED_STATE"
    cleanup_dry_model
    path="$ORIGINAL_PATH"
  fi
  echo ""
done < <(python3 -c "
import json
d = json.load(open('$REGISTRY'))
for i in d['instances']:
    if 'status' in i and i['status'].startswith('merged'):
        continue
    t = i.get('type', 'subtree')
    prefix = i.get('subtree_prefix') or ''
    # Only an explicit false counts as a declaration. A missing key is the
    # reddit-build-radar state -- registered, receiving nothing, nobody on the
    # record for it -- and must not read the same as a deliberate opt-out.
    declared = 'declared' if i.get('skeleton_managed') is False else 'undeclared'
    print(i['name'] + '|' + i['path'] + '|' + prefix + '|' + t + '|' + declared)
")

if [ -n "$ONLY" ] && [ "$((PASS+FAIL+SKIP))" -eq 0 ]; then
  echo "ERROR: no registered instance named '$ONLY'" >&2
  exit 1
fi

echo "=== Summary ==="
echo "  Updated: $PASS"
echo "  Failed:  $FAIL"
if [ -n "$FAILED_NAMES" ]; then
  echo "  NOT UPDATED (still on their previous skeleton version):$FAILED_NAMES"
fi
echo "  Skipped: $SKIP"
if [ -n "${GATE_FAIL:-}" ]; then
  echo "  CAPABILITY GATE RED in:$GATE_FAIL"
fi
# Repeated here on purpose: the per-instance line sits inside a section a
# reader scrolls past, and the summary is what gets read.
if [ "$INSTANCE_AHEAD_TOTAL" -gt 0 ]; then
  echo "  INSTANCE AHEAD OF SKELETON ($INSTANCE_AHEAD_TOTAL file(s) whose instance content the skeleton never shipped; a sync overwrites them):$INSTANCE_AHEAD_REPORT"
fi
# In the summary, not only inline: a real run prints ~40 lines per instance and
# the summary is what gets read. An ungoverned instance that only appears on
# line 300 of 900 is still, in practice, silent.
if [ -n "${UNDECLARED:-}" ]; then
  echo "  UNDECLARED NON-PROPAGATING:$UNDECLARED"
fi

[ "$FAIL" -eq 0 ] && [ -z "${GATE_FAIL:-}" ] && exit 0 || exit 1
