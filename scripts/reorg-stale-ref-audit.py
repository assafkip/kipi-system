#!/usr/bin/env python3
"""reorg-stale-ref-audit.py — reproducer + acceptance gate for the fleet
persona-reorg stale-reference remediation (see q-system/output/plans/ +
.prd-os PRD reorg-stale-ref-remediation).

WHY THIS EXISTS (scar, 2026-07-06): persona-reorg.py's self-ref rewriter only
rewrote the absolute `/Users/...` path form, skipped `.mjs`/`.cjs`, and never
touched cross-project refs (project A -> moved-project B). Result (classified by
this audit): 41 stale refs in executable/config files that gate, plus 56 in
prose/regenerating state that do not (97 actionable; an earlier pre-classification
grep counted ~99) — a broken MCP config, a git hook, self-ref shell scripts,
launcher catalogs, orphaned plugin-install records.

Deterministic contract:
  - Scans the fleet for references to any OLD (pre-reorg) top-level path.
  - Buckets known-acceptable noise (rollback manifests, fleet-synced vendored
    copies, session-history cache, dated point-in-time records, .bak backups,
    a pre-existing wrong-user ref) away from actionable findings.
  - EXITS NON-ZERO if any stale ref remains in an EXECUTABLE/CONFIG file (the
    class that breaks at runtime). Prose (.md/.txt) + regenerating daemon state
    are reported as informational and do NOT gate.

Usage: python3 scripts/reorg-stale-ref-audit.py [--all]
  --all : also list the informational (prose/state) findings.
"""
import os, re, sys, subprocess

HOME = os.path.expanduser("~")
PROJ = os.path.join(HOME, "projects")

# SINGLE SOURCE of the old->new mapping (finding-6): imported from the reorg tool
# itself so the audit cannot drift from the actual move definitions. Keyed by
# PROJECTS-relative OLD path — "vc-signals", but also "ktlyst-hub/event_coordinator"
# for src_sub moves, which a flat name-only dict could not represent (finding-3).
import importlib.util as _ilu
_PR_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "persona-reorg.py")
_spec = _ilu.spec_from_file_location("persona_reorg", _PR_PATH)
_pr = _ilu.module_from_spec(_spec); _spec.loader.exec_module(_pr)
_OLDNEW_ABS = _pr.build_oldnew_map()            # old_abs -> new_abs (the reorg map)
NEWLOC = {}          # old PROJECTS-rel path -> new PROJECTS-rel location (for reports)
_NEWABS = {}         # old PROJECTS-rel path -> new abspath (for existence check)
for _o, _n in _OLDNEW_ABS.items():
    _orel = _o[len(PROJ) + 1:]
    NEWLOC[_orel] = (_n[len(PROJ) + 1:] + "/") if _n.startswith(PROJ + os.sep) else _n
    _NEWABS[_orel] = _n
# founder-signal-engine was moved into cole-gtm then archived (RULE-2026-07-06-A
# note); its reorg-map target intentionally does not exist on disk.
ARCHIVED_OK = {"founder-signal-engine"}
NAMES = sorted(NEWLOC, key=len, reverse=True)
alts = "|".join(re.escape(n) for n in NAMES)
# The reorg operated on THIS user's home. A `/Users/<other>/projects/...` absolute
# ref is a pre-existing artifact from a prior machine (this box is single-user; the
# other-user path does not even resolve) — the PRD non-goal'd it and it is tracked
# separately as spillover. Scope the gate's absolute form to the current user so a
# pre-existing wrong-user ref cannot hold the gate red forever.
CURRENT_USER = os.path.basename(HOME)
CONTENT_PAT = re.compile(
    rf"(?:/Users/{re.escape(CURRENT_USER)}|~|\$HOME|\$\{{HOME\}}|\$PROJECTS)"
    rf"/projects/({alts})(?:[/\"'\s):]|$)")

# Executable / runtime-config files: a stale ref here BREAKS something -> gates.
GATING_EXT = {".sh", ".py", ".mjs", ".cjs", ".js", ".ts", ".plist", ".yml",
              ".yaml", ".toml", ".cfg", ".env", ".zsh", ".bash"}
GATING_BASENAME = {".mcp.json", "mcp.json", "hooks.json", "lefthook.yml",
                   "installed_plugins.json", "products.json", "build-manifest.json",
                   # widened (finding-5): package/build/shell config that also runs
                   "package.json", "Makefile", "Dockerfile", ".env.local",
                   ".zshrc", ".bashrc", ".zprofile"}


def _has_shebang(fp):
    """An extensionless file that starts with #! is an executable script -> gates
    (finding-5). Cheap: only called on files that already matched a stale ref."""
    try:
        with open(fp, "rb") as f:
            return f.read(2) == b"#!"
    except OSError:
        return False

# Vendored plugin dirs: an instance copy re-syncs from the skeleton on `kipi
# update`, so a stale ref there is churn, not a durable break — only the skeleton
# copy under kipi-system/ gates. The reorg tooling holds old paths as data/fixtures.
_VENDORED_SEG = ("/plugins/prd-os/", "/plugins/kipi-core/", "/plugins/kipi-ops/",
                 "/plugins/kipi-design/")
_SKELETON = os.path.join(PROJ, "kipi-system")
_TOOLING = {"persona-reorg.py", "reorg-stale-ref-audit.py", "test_persona_reorg.py"}


def acceptable_noise(fp):
    if fp.endswith((".persona-reorg.bak", ".remediation.bak")): return True
    if "persona-reorg-manifest" in fp: return True          # rollback record
    if os.path.basename(fp) in _TOOLING: return True        # reorg tooling: holds old paths as data
    if any(v in fp for v in _VENDORED_SEG) and not fp.startswith(_SKELETON + os.sep):
        return True                                         # instance vendored copy: re-syncs
    if "/kipi-mcp/" in fp: return True                      # fleet-synced vendored (incl. skeleton)
    if "/.claude/projects/" in fp or "/.claude/paste-cache/" in fp: return True
    if "/.claude/todos/" in fp or "/.claude/history" in fp: return True
    if "/.claude/plugins/marketplaces/" in fp or "/.claude/plugins/cache/" in fp: return True  # re-synced clone
    if "/worktrees/" in fp or "/.playwright-mcp/" in fp: return True
    # dated point-in-time records (a day's render/distribution log)
    if re.search(r"/(distribution|platform|launch)/.*20\d\d-\d\d-\d\d", fp): return True
    if re.search(r"oneoff_run_\d", fp): return True
    for seg in ("/output/", "/runs/", "/evidence/", "/investigations/", "/sessions/",
                "/memory/archives/", "/_archive", "/audits/", "/logs/", "/.prd-os/",
                "/drafts/", "/.git/", "node_modules/"):
        if seg in fp + "/": return True
    return False

def is_gating(fp):
    base = os.path.basename(fp)
    _, ext = os.path.splitext(fp)
    if ext in GATING_EXT or base in GATING_BASENAME:
        return True
    return ext == "" and _has_shebang(fp)      # extensionless executable script

INC = ("--include=*.py","--include=*.sh","--include=*.js","--include=*.ts","--include=*.mjs",
       "--include=*.cjs","--include=*.json","--include=*.md","--include=*.plist",
       "--include=*.yaml","--include=*.yml","--include=*.toml","--include=*.cfg",
       "--include=*.txt","--include=*.env")
EXC = ("--exclude-dir=node_modules","--exclude-dir=.git","--exclude-dir=.next",
       "--exclude-dir=.venv","--exclude-dir=venv","--exclude-dir=__pycache__",
       "--exclude-dir=dist","--exclude-dir=build","--exclude-dir=_codex-worktrees",
       "--exclude-dir=worktrees")

def scan():
    roots = [PROJ, os.path.join(HOME, ".claude"),
             os.path.join(HOME, "Library", "LaunchAgents"),
             os.path.join(HOME, ".ktlyst"), os.path.join(HOME, ".config", "kipi")]
    roots = [r for r in roots if os.path.exists(r)]
    grep_pat = r"(/Users/[^/]+|~|\$\{?HOME\}?|\$PROJECTS)/projects/(" + alts + r")([/\"'\s):]|$)"
    out = subprocess.run(["grep", "-rInE", grep_pat, *roots, *INC, *EXC],
                         capture_output=True, text=True, timeout=300).stdout
    gating, prose = [], []
    for ln in out.splitlines():
        parts = ln.split(":", 2)
        if len(parts) < 3: continue
        fp, lno, content = parts
        m = CONTENT_PAT.search(content)
        if not m: continue
        if acceptable_noise(fp): continue
        rec = (fp, lno, m.group(1), content.strip())
        (gating if is_gating(fp) else prose).append(rec)
    return gating, prose

def main():
    show_all = "--all" in sys.argv
    gating, prose = scan()
    def dump(recs, title):
        print(f"\n{'='*70}\n{title}: {len(recs)}\n{'='*70}")
        byf = {}
        for fp, lno, nm, content in recs:
            byf.setdefault(fp, []).append((lno, nm, content))
        for fp in sorted(byf):
            print(f"\n  {fp.replace(HOME, '~')}")
            for lno, nm, content in byf[fp][:10]:
                print(f"    L{lno}  [{nm} -> {NEWLOC[nm]}]  {content[:110]}")
            if len(byf[fp]) > 10:
                print(f"    ... +{len(byf[fp])-10} more")
    dump(gating, "GATING — stale refs in executable/config (MUST be 0)")
    if show_all or prose:
        dump(prose, "INFORMATIONAL — prose/state (fix, but does not gate)")
    # finding-2: prove remediation TARGETS EXIST, not merely that old strings are
    # gone. Without this, a rewrite to a wrong/nonexistent new path passes green
    # while the launcher/MCP/hook still fails. Every reorg-map target must resolve
    # on disk (except the intentionally-archived allowlist).
    missing = [(o, a) for o, a in _NEWABS.items()
               if os.path.basename(o.rstrip("/")) not in ARCHIVED_OK
               and not os.path.exists(a)]
    if missing:
        print(f"\n{'='*70}\nDANGLING MAP TARGETS — reorg new path absent on disk: "
              f"{len(missing)}\n{'='*70}")
        for o, a in sorted(missing):
            print(f"  {o}  ->  {a.replace(HOME,'~')}  [MISSING]")
    print(f"\n{'='*70}")
    if gating or missing:
        print(f"FAIL: {len(gating)} gating stale ref(s) across "
              f"{len({r[0] for r in gating})} file(s); "
              f"{len(missing)} dangling map target(s).")
        sys.exit(1)
    print(f"PASS: 0 gating stale refs, all reorg targets exist. "
          f"({len(prose)} informational prose/state refs remain.)")
    sys.exit(0)

if __name__ == "__main__":
    main()
