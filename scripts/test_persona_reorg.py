#!/usr/bin/env python3
"""Unit tests for persona-reorg.py's hardened rewriter + single-source map.

Covers PRD reorg-stale-ref-remediation findings 6/7/8. PURE-FUNCTION ONLY — no
filesystem walks or writes (the fable-discipline lint blocks tests that touch a
live data path; the cross-project sweep is exercised separately via --remediate
--dry, not here). Run: python3 scripts/test_persona_reorg.py  (exit 0 = pass)."""
import importlib.util as ilu
import os
import sys

_PR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "persona-reorg.py")
_spec = ilu.spec_from_file_location("persona_reorg", _PR)
pr = ilu.module_from_spec(_spec)
_spec.loader.exec_module(pr)

HOME = os.path.expanduser("~")
FAILS = []


def check(name, cond):
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if not cond:
        FAILS.append(name)


# --- finding-7: rewriter covers all four path-prefix forms + .mjs/.cjs ----------
old = f"{HOME}/projects/cheapcheck"
new = f"{HOME}/projects/micro-saas/projects/cheapcheck"

forms = pr.path_forms(old)
check("path_forms yields absolute form", old in forms)
check("path_forms yields ~ form", "~/projects/cheapcheck" in forms)
check("path_forms yields $HOME form", "$HOME/projects/cheapcheck" in forms)
check("path_forms yields ${HOME} form", "${HOME}/projects/cheapcheck" in forms)
check("path_forms yields $PROJECTS form", "$PROJECTS/cheapcheck" in forms)
check("old/new path_forms same length (zip aligns)",
      len(pr.path_forms(old)) == len(pr.path_forms(new)))

# a fixture body holding EVERY form (this is what .mjs/.sh/.py files looked like)
body = "\n".join([
    f'const A = "{old}/webapp";',              # absolute (the .mjs case)
    f'B=~/projects/cheapcheck/pipeline',        # ~
    f'C="$HOME/projects/cheapcheck/q-design"',  # $HOME
    f'D=${{HOME}}/projects/cheapcheck/x',       # ${HOME}
    f'E=$PROJECTS/cheapcheck/y',                # $PROJECTS
])
out, n = pr.rewrite_all_forms(body, old, new)
check("rewrite_all_forms rewrote all 5 form occurrences", n == 5)
# negative self-test: NO old form survives (the whole point of the reorg scar)
check("negative self-test: absolute old gone", old not in out)
check("negative self-test: ~ old gone", "~/projects/cheapcheck/" not in out)
check("negative self-test: $HOME old gone", "$HOME/projects/cheapcheck" not in out)
check("negative self-test: ${HOME} old gone", "${HOME}/projects/cheapcheck" not in out)
check("negative self-test: $PROJECTS old gone", "$PROJECTS/cheapcheck" not in out)
check("new nested path present after rewrite", "micro-saas/projects/cheapcheck" in out)

# a ref ALREADY at the new nested path must not be double-rewritten
already = f'X = "{new}/webapp"'
out2, n2 = pr.rewrite_all_forms(already, old, new)
check("already-migrated path untouched (no double rewrite)", n2 == 0 and out2 == already)

check(".mjs in SELFREF_EXTS", ".mjs" in pr.SELFREF_EXTS)
check(".cjs in SELFREF_EXTS", ".cjs" in pr.SELFREF_EXTS)

# --- finding-7: distinct backup namespace so passes don't clobber each other ---
import inspect
sig = inspect.signature(pr._bak)
check("_bak takes a suffix param (distinct remediation namespace)",
      "suffix" in sig.parameters)

# --- finding-6/3: single-source map derived from PERSONAS, incl. src_sub --------
m = pr.build_oldnew_map()
check("build_oldnew_map returns non-empty abspath map", len(m) > 0 and
      all(k.startswith(HOME) and v.startswith(HOME) for k, v in m.items()))
# a src_sub move (ktlyst-hub/event_coordinator) must be representable by full path
ec_old = f"{HOME}/projects/ktlyst-hub/event_coordinator"
check("src_sub old path present in map (finding-3)", ec_old in m)
check("src_sub maps under cole-gtm/projects", m.get(ec_old, "").endswith(
      "cole-gtm/projects/event_coordinator"))
# interview-coach re-home reflected (single source == reality)
ic_old = f"{HOME}/projects/interview-coach-public"
check("interview-coach-public maps to micro-saas (re-home reflected)",
      m.get(ic_old, "").endswith("micro-saas/projects/interview-coach-public"))

# --- finding-8: the cross-project remediation entrypoint exists + is dry-safe ---
check("remediate_cross_project is callable", callable(pr.remediate_cross_project))
check("remediate_cross_project defaults to dry (apply kwarg)",
      inspect.signature(pr.remediate_cross_project).parameters["apply"].default is False)

print()
if FAILS:
    print(f"FAIL: {len(FAILS)} check(s) failed: {FAILS}")
    sys.exit(1)
print("PASS: all rewriter + map checks green.")
sys.exit(0)
