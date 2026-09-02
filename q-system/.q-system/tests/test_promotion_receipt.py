#!/usr/bin/env python3
"""RED FIRST. The promotion path (prd-lessons-rail-and-up-rail, Phase 4), one
slice per issue, all in this file. Every run uses two tmp trees (an instance
and a skeleton) built here; the live trees are never read or written.

Slice 1, issue lr-promote-path-containment (Codex finding-2 on the PRD): a
promoter with no containment would copy ../ or a symlink target out of the
instance and into the skeleton, which fans out to 25 instances.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent.parent
PROMOTE = ROOT / "kipi-promote.sh"
CLI = ROOT / "kipi"


CLIENTS = {"version": 1, "last_write": "2026-09-01", "clients": [
    # the producer's keys (consulting's clients.json), values invented
    {"name": "Northwind Traders", "slug": "northwind", "stage": "active", "tier": "b", "vertical": "x",
     "contact": "", "folder": "", "notes": "", "opened": "2026-01-01", "rate": 0, "rate_unit": "hr"},
    {"name": "Contoso Holdings", "slug": "contoso", "stage": "won", "tier": "a", "vertical": "y"},
]}


def _trees(tmp_path):
    inst = tmp_path / "instance"
    skel = tmp_path / "skeleton"
    (inst / "q-system" / "lessons").mkdir(parents=True)
    (inst / "q-system" / ".q-system" / "scripts").mkdir(parents=True)
    (inst / "q-consult" / "pipeline").mkdir(parents=True)
    (inst / "q-consult" / "my-project").mkdir(parents=True)
    (skel / "q-system" / "lessons").mkdir(parents=True)
    (inst / "q-system" / "lessons" / "general.md").write_text("---\ntitle: A general lesson\n---\nhow to do a thing\n")
    (inst / "q-consult" / "pipeline" / "voice.py").write_text("print('instance-owned')\n")
    (inst / "q-consult" / "my-project" / "clients.json").write_text(json.dumps(CLIENTS))
    (tmp_path / "outside.md").write_text("outside the instance\n")
    # the registry the scrub locates clients.json through: this instance's entry + a codename instance
    (tmp_path / "instance-registry.json").write_text(json.dumps({
        "skeleton": {"path": str(skel)},
        "instances": [{"name": "consulting", "path": str(inst), "instance_q_dir": "q-consult", "type": "subtree"},
                      {"name": "Example_Corp9", "path": str(tmp_path / "elsewhere"), "instance_q_dir": "q-gold", "type": "subtree"}]}))
    return inst, skel


def _promote(tmp_path, rel, unscrubbed=True, cwd=None):
    inst, skel = tmp_path / "instance", tmp_path / "skeleton"
    env = dict(os.environ, KIPI_PROMOTE_INSTANCE=str(inst), KIPI_PROMOTE_SKELETON=str(skel),
               KIPI_PROMOTE_REGISTRY=str(tmp_path / "instance-registry.json"))
    env.pop("KIPI_PROMOTE_UNSCRUBBED", None)  # never inherit the seam from the caller's shell
    if unscrubbed:
        env["KIPI_PROMOTE_UNSCRUBBED"] = "1"
    # timeout: a promoter that reads a fifo blocks forever; a hang is a failure, not a wait
    return subprocess.run(["/bin/bash", str(PROMOTE), rel], capture_output=True, text=True, env=env, cwd=cwd or inst, timeout=20)


def _nothing_copied(tmp_path):
    skel = tmp_path / "skeleton"
    files = [p for p in skel.rglob("*") if p.is_file()]
    assert files == [], f"refusal must copy nothing, found {files}"


@pytest.mark.parametrize("rel,why", [
    ("{inst}/q-system/lessons/general.md", "absolute, even when it points inside q-system"),
    ("/etc/hosts", "absolute"),
    ("q-system/../outside.md", "dot-dot"),
    ("q-system/./lessons/general.md", "dot segment"),
    ("q-consult/pipeline/voice.py", "outside q-system"),
    ("q-system/lessons", "directory"),
    ("q-system/lessons/missing.md", "no such file"),
])
def test_containment_refuses_bad_inputs(tmp_path, rel, why):
    inst, _ = _trees(tmp_path)
    r = _promote(tmp_path, rel.format(inst=inst))
    assert r.returncode == 2, (why, r.returncode, r.stderr)
    assert "refused" in r.stderr, r.stderr
    _nothing_copied(tmp_path)


def test_containment_refuses_a_symlinked_file_and_a_symlinked_parent(tmp_path):
    inst, skel = _trees(tmp_path)
    (inst / "q-system" / "lessons" / "link.md").symlink_to(tmp_path / "outside.md")
    r = _promote(tmp_path, "q-system/lessons/link.md")
    assert r.returncode == 2 and "refused: symlink on the path: q-system/lessons/link.md" in r.stderr, r.stderr
    (inst / "q-system" / "linked-dir").symlink_to(tmp_path)
    r = _promote(tmp_path, "q-system/linked-dir/outside.md")
    assert r.returncode == 2 and "refused: symlink on the path: q-system/linked-dir" in r.stderr, r.stderr
    _nothing_copied(tmp_path)


@pytest.mark.parametrize("rel,why", [
    ("q-system//lessons/general.md", "empty segment"),
    ("q-system/lessons/gen\neral.md", "newline"),
])
def test_empty_segments_and_newlines_are_refused_at_the_input(tmp_path, rel, why):
    _trees(tmp_path)
    r = _promote(tmp_path, rel)
    assert r.returncode == 2 and "refused" in r.stderr and "Traceback" not in r.stderr, (why, r.stderr)
    _nothing_copied(tmp_path)


def test_extra_arguments_fail_instead_of_half_succeeding(tmp_path):
    inst, skel = _trees(tmp_path)
    env = dict(os.environ, KIPI_PROMOTE_INSTANCE=str(inst), KIPI_PROMOTE_SKELETON=str(skel), KIPI_PROMOTE_UNSCRUBBED="1")
    r = subprocess.run(["/bin/bash", str(PROMOTE), "q-system/lessons/general.md", "/etc/passwd"], capture_output=True, text=True, env=env, cwd=inst, timeout=20)
    assert r.returncode == 2 and "usage" in r.stderr
    _nothing_copied(tmp_path)


def test_mode_bits_survive_the_copy(tmp_path):
    """Claude standard review: the fd copy wrote 644; a promoted hook script
    arrived non-executable and fanned out broken."""
    inst, skel = _trees(tmp_path)
    tool = inst / "q-system" / ".q-system" / "scripts" / "tool.sh"
    tool.write_text("#!/bin/bash\necho hi\n")
    tool.chmod(0o755)
    r = _promote(tmp_path, "q-system/.q-system/scripts/tool.sh")
    assert r.returncode == 0, r.stderr
    assert (skel / "q-system" / ".q-system" / "scripts" / "tool.sh").stat().st_mode & 0o777 == 0o755


def test_destination_uses_the_on_disk_casing(tmp_path):
    inst, skel = _trees(tmp_path)
    r = _promote(tmp_path, "q-system/Lessons/General.md")
    if r.returncode == 2:
        assert "no such file" in r.stderr, r.stderr  # case-sensitive filesystem: nothing to resolve
        return
    assert r.returncode == 0, r.stderr
    # exists() is case-insensitive here too, so compare the on-disk NAMES
    names = sorted(p.name for p in (skel / "q-system").iterdir())
    assert "lessons" in names and "Lessons" not in names, f"no second, differently-cased tree: {names}"
    assert [p.name for p in (skel / "q-system" / "lessons").iterdir()] == ["general.md"], "the on-disk casing, not the caller's"


def test_production_resolution_reads_the_registry_through_kipi_home(tmp_path):
    """Claude standard review: every test set KIPI_PROMOTE_SKELETON, so the
    registry read and the cwd default never ran."""
    inst, skel = _trees(tmp_path)
    home = tmp_path / "kipi-home"
    home.mkdir()
    # ONE registry serves both skeleton resolution and the scrub roster: the fixture's
    (home / "instance-registry.json").write_text((tmp_path / "instance-registry.json").read_text())
    env = {k: v for k, v in os.environ.items() if not k.startswith("KIPI_PROMOTE")}
    env.update(KIPI_HOME=str(home), KIPI_PROMOTE_UNSCRUBBED="1")
    r = subprocess.run(["/bin/bash", str(PROMOTE), "q-system/lessons/general.md"], capture_output=True, text=True, env=env, cwd=inst, timeout=20)
    assert r.returncode == 0, r.stderr
    assert (skel / "q-system" / "lessons" / "general.md").exists()
    (home / "instance-registry.json").write_text("{not json")
    r = subprocess.run(["/bin/bash", str(PROMOTE), "q-system/lessons/general.md"], capture_output=True, text=True, env=env, cwd=inst, timeout=20)
    assert r.returncode == 2 and "skeleton" in r.stderr, "an unreadable registry refuses, never guesses"


def test_containment_refuses_a_fifo(tmp_path):
    inst, _ = _trees(tmp_path)
    os.mkfifo(inst / "q-system" / "lessons" / "pipe.md")
    r = _promote(tmp_path, "q-system/lessons/pipe.md")
    assert r.returncode == 2 and "regular file" in r.stderr, r.stderr
    _nothing_copied(tmp_path)


def test_a_plain_relative_q_system_path_copies_to_the_same_relative_path(tmp_path):
    inst, skel = _trees(tmp_path)
    r = _promote(tmp_path, "q-system/lessons/general.md")
    assert r.returncode == 0, r.stderr
    assert (skel / "q-system" / "lessons" / "general.md").read_text() == (inst / "q-system" / "lessons" / "general.md").read_text()
    (inst / "q-system" / ".q-system" / "scripts" / "new-tool.py").write_text("print('general')\n")
    r = _promote(tmp_path, "q-system/.q-system/scripts/new-tool.py")
    assert r.returncode == 0 and (skel / "q-system" / ".q-system" / "scripts" / "new-tool.py").exists(), "parents are created"


def test_without_the_unscrubbed_seam_containment_passes_but_nothing_is_copied(tmp_path):
    """The containment slice can never ship as a working promoter on its own."""
    _trees(tmp_path)
    r = _promote(tmp_path, "q-system/lessons/general.md", unscrubbed=False)
    assert r.returncode == 3 and "nothing copied" in r.stderr, (r.returncode, r.stderr)
    _nothing_copied(tmp_path)


def test_unscrubbed_seam_is_ignored_outside_pytest(tmp_path):
    inst, skel = _trees(tmp_path)
    env = dict(os.environ, KIPI_PROMOTE_INSTANCE=str(inst), KIPI_PROMOTE_SKELETON=str(skel), KIPI_PROMOTE_UNSCRUBBED="1",
               KIPI_PROMOTE_REGISTRY=str(tmp_path / "instance-registry.json"))
    env.pop("PYTEST_CURRENT_TEST", None)
    r = subprocess.run(["/bin/bash", str(PROMOTE), "q-system/lessons/general.md"], capture_output=True, text=True, env=env, cwd=inst)
    assert r.returncode == 3, "the seam only opens under pytest"
    _nothing_copied(tmp_path)


def test_destination_chain_with_a_symlink_is_refused_and_nothing_lands_outside(tmp_path):
    """Codex adversarial: mkdir/cp followed a symlinked destination directory."""
    inst, skel = _trees(tmp_path)
    outside = tmp_path / "outside-skeleton"
    outside.mkdir()
    (skel / "q-system" / "lessons").rmdir()
    (skel / "q-system" / "lessons").symlink_to(outside)
    r = _promote(tmp_path, "q-system/lessons/general.md")
    assert r.returncode == 2 and "contained copy failed" in r.stderr, (r.returncode, r.stderr)
    assert list(outside.iterdir()) == [], "nothing may land through the symlink"


def test_the_copy_is_the_containment_not_a_precheck_plus_cp():
    """Codex adversarial: validate-then-cp is a race. The copy walks both chains
    with O_NOFOLLOW relative to directory fds, so a swapped component fails."""
    src = PROMOTE.read_text()
    assert "O_NOFOLLOW" in src and "dir_fd=" in src
    import re
    assert not re.search(r"(?m)^\s*cp\s", src), "no plain cp invocation anywhere"


def test_the_seam_also_requires_a_temp_rooted_instance():
    """Codex adversarial: PYTEST_CURRENT_TEST alone is anyone's to set."""
    src = PROMOTE.read_text()
    assert "/private/var/folders/*" in src and '[ "$_tmp_rooted" != "1" ]' in src


def test_unresolvable_skeleton_refuses(tmp_path):
    inst, _ = _trees(tmp_path)
    env = dict(os.environ, KIPI_PROMOTE_INSTANCE=str(inst), KIPI_PROMOTE_SKELETON=str(tmp_path / "nowhere"))
    r = subprocess.run(["/bin/bash", str(PROMOTE), "q-system/lessons/general.md"], capture_output=True, text=True, env=env, cwd=inst)
    assert r.returncode == 2 and "skeleton" in r.stderr


def test_cli_registers_promote(tmp_path):
    src = CLI.read_text()
    assert "kipi promote" in src and "kipi-promote.sh" in src
    h = subprocess.run(["/bin/bash", str(CLI), "help"], capture_output=True, text=True)
    assert "promote" in h.stdout, h.stdout[-500:]
    # the dispatch itself, not the help text: `kipi promote` must reach the promoter
    inst, skel = _trees(tmp_path)
    env = dict(os.environ, KIPI_PROMOTE_INSTANCE=str(inst), KIPI_PROMOTE_SKELETON=str(skel))
    r = subprocess.run(["/bin/bash", str(CLI), "promote", "q-system/lessons/missing.md"], capture_output=True, text=True, env=env, cwd=inst, timeout=20)
    assert r.returncode == 2 and "kipi promote: refused: no such file" in r.stderr, (r.returncode, r.stderr[-300:], r.stdout[-300:])


# ---- slice 2, issue lr-promote-scrub-source (Codex finding-3 on the PRD) -------

@pytest.mark.parametrize("planted,why", [
    ("Northwind Traders", "client name"),
    ("contoso", "client slug"),
    ("Assaf", "tripwire term"),
    ("/Users/someone/x", "tripwire path"),
    ("Example_Corp9", "instance codename from the registry"),
])
def test_client_name_refused(tmp_path, planted, why):
    inst, _ = _trees(tmp_path)
    (inst / "q-system" / "lessons" / "general.md").write_text(f"---\ntitle: t\n---\nlearned this with {planted} last week\n")
    r = _promote(tmp_path, "q-system/lessons/general.md")
    assert r.returncode == 2 and "refused" in r.stderr and "client data" in r.stderr, (why, r.stderr)
    _nothing_copied(tmp_path)


def test_clients_file_missing_refuses_and_names_the_path(tmp_path):
    inst, _ = _trees(tmp_path)
    (inst / "q-consult" / "my-project" / "clients.json").unlink()
    r = _promote(tmp_path, "q-system/lessons/general.md")
    assert r.returncode == 2 and "clients file missing" in r.stderr and "q-consult/my-project/clients.json" in r.stderr, r.stderr
    _nothing_copied(tmp_path)


def test_instance_without_a_registry_entry_refuses(tmp_path):
    inst, _ = _trees(tmp_path)
    (tmp_path / "instance-registry.json").write_text(json.dumps({"skeleton": {"path": str(tmp_path / "skeleton")}, "instances": []}))
    r = _promote(tmp_path, "q-system/lessons/general.md")
    assert r.returncode == 2 and "no registry entry" in r.stderr, r.stderr
    _nothing_copied(tmp_path)


def test_scrub_roster_comes_from_production_sources_not_an_env_list():
    src = PROMOTE.read_text()
    assert "KIPI_SCRUB_TERMS" not in src
    assert "codenames_from_registry" in src and "client_terms" in src and "tripwire_terms" in src
    assert "tripwire-terms.txt" in src


def test_push_tripwire_is_single_sourced():
    push = (ROOT / "kipi-push-upstream.sh").read_text()
    assert 'grep -ril "KTLYST\\|ktlyst' not in push, "the inline list must be gone"
    assert "tripwire-terms.txt" in push
    sys.path.insert(0, str(ROOT / "q-system" / ".q-system" / "scripts"))
    import lessons_scrub
    terms = lessons_scrub.tripwire_terms(ROOT / "q-system" / ".q-system" / "scripts" / "tripwire-terms.txt")
    assert terms == ["KTLYST", "ktlyst", "CISO", "re-breach", "Assaf", "/Users/"], "the same six terms the inline grep carried"


def test_push_script_fails_closed_without_the_term_list(tmp_path):
    """An instance whose fan-out lost tripwire-terms.txt must not push unscanned."""
    inst = tmp_path / "inst"
    (inst / "q-system").mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=inst, check=True)  # the script refuses outside a repo first
    import shutil
    shutil.copy(ROOT / "kipi-push-upstream.sh", inst / "kipi-push-upstream.sh")
    r = subprocess.run(["/bin/bash", "kipi-push-upstream.sh"], capture_output=True, text=True, cwd=inst, timeout=60,
                       env=dict(os.environ, KIPI_SKELETON_REMOTE=str(tmp_path / "no-remote")))
    assert r.returncode == 1 and "tripwire term list missing" in r.stdout + r.stderr, (r.returncode, r.stdout[-300:], r.stderr[-300:])


def test_push_script_blocks_a_planted_term(tmp_path):
    """Codex (issue 8, blocker): the joined pattern ran under basic grep, where
    '|' is literal, so the first version matched nothing at all."""
    import shutil
    inst = tmp_path / "inst"
    (inst / "q-system" / ".q-system" / "scripts").mkdir(parents=True)
    (inst / "q-system" / "lessons").mkdir()
    subprocess.run(["git", "init", "-q"], cwd=inst, check=True)
    shutil.copy(ROOT / "kipi-push-upstream.sh", inst / "kipi-push-upstream.sh")
    shutil.copy(ROOT / "q-system" / ".q-system" / "scripts" / "tripwire-terms.txt", inst / "q-system" / ".q-system" / "scripts" / "tripwire-terms.txt")
    (inst / "q-system" / "lessons" / "leak.md").write_text("learned this with assaf last week\n")  # lower-case: the grep is -i
    env = dict(os.environ, KIPI_SKELETON_REMOTE=str(tmp_path / "no-remote"))
    r = subprocess.run(["/bin/bash", "kipi-push-upstream.sh"], capture_output=True, text=True, cwd=inst, timeout=60, env=env)
    out = r.stdout + r.stderr
    assert r.returncode == 1 and "Instance-specific content found" in out and "leak.md" in out, (r.returncode, out[-400:])
    (inst / "q-system" / "lessons" / "leak.md").write_text("nothing instance-specific here\n")
    r = subprocess.run(["/bin/bash", "kipi-push-upstream.sh"], capture_output=True, text=True, cwd=inst, timeout=60, env=env)
    assert "No instance-specific content detected" in r.stdout + r.stderr, "the clean case passes the tripwire (and fails later, on the remote)"


def test_a_two_letter_slug_is_still_scrubbed(tmp_path):
    inst, _ = _trees(tmp_path)
    data = json.loads((inst / "q-consult" / "my-project" / "clients.json").read_text())
    data["clients"].append({"name": "AI Co", "slug": "ai"})
    (inst / "q-consult" / "my-project" / "clients.json").write_text(json.dumps(data))
    (inst / "q-system" / "lessons" / "general.md").write_text("---\ntitle: t\n---\nthe ai account taught us this\n")
    r = _promote(tmp_path, "q-system/lessons/general.md")
    assert r.returncode == 2 and "client data" in r.stderr, r.stderr


def test_scrub_helpers_read_the_producers_shapes(tmp_path):
    sys.path.insert(0, str(ROOT / "q-system" / ".q-system" / "scripts"))
    import lessons_scrub
    inst, _ = _trees(tmp_path)
    reg = tmp_path / "instance-registry.json"
    assert lessons_scrub.clients_file_for_instance(reg, inst) == str(inst / "q-consult" / "my-project" / "clients.json")
    assert lessons_scrub.clients_file_for_instance(reg, tmp_path / "unknown") is None
    assert lessons_scrub.client_terms(inst / "q-consult" / "my-project" / "clients.json") == ["Northwind Traders", "northwind", "Contoso Holdings", "contoso"]
    assert lessons_scrub.codenames_from_registry(reg) == ["Example_Corp9"], "generic lowercase names are not codenames"


# ---- slice 3, issue lr-promote-receipt-hash-binding (Codex finding-1 on the PRD) ----
# A receipt that names only a path blesses whatever is later written at that path.
# The receipt binds the git blob hash of the promoted content; the lessons guard in
# kipi-push-upstream.sh passes a divergent lesson only when the skeleton's receipt
# file (read at FETCH_HEAD) carries a done row whose blob equals the instance's blob.

RECEIPTS_REL = "q-system/.q-system/promotions.jsonl"


def _git(cwd, *args):
    return subprocess.run(["git", "-c", "user.email=t@t.t", "-c", "user.name=t", "-c", "commit.gpgsign=false", *args],
                          cwd=cwd, capture_output=True, text=True, check=True).stdout


def _repos(tmp_path, receipts=None):
    """A bare skeleton with one clone (the skeleton working tree) and one instance clone.
    Both start with the same lesson; the instance then diverges. FETCH_HEAD in the
    instance points at the skeleton's main, which is where the guard reads receipts."""
    import shutil
    bare = tmp_path / "skel.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    skel = tmp_path / "skeleton"
    _git(tmp_path, "clone", "-q", str(bare), str(skel))
    (skel / "q-system" / "lessons").mkdir(parents=True)
    (skel / "q-system" / ".q-system" / "scripts").mkdir(parents=True)
    (skel / "q-system" / "lessons" / "a.md").write_text("---\ntitle: A\n---\noriginal body\n")
    # a second lesson keeps the instance's lessons dict non-empty after a.md is
    # deleted; the guard skips everything when it is empty (captured, sp below)
    (skel / "q-system" / "lessons" / "b.md").write_text("---\ntitle: B\n---\nanother body\n")
    (skel / "q-system" / ".q-system" / "promotions.jsonl").write_text("".join(json.dumps(r) + "\n" for r in (receipts or [])))
    shutil.copy(ROOT / "q-system" / ".q-system" / "scripts" / "tripwire-terms.txt", skel / "q-system" / ".q-system" / "scripts" / "tripwire-terms.txt")
    _git(skel, "add", "-A"); _git(skel, "commit", "-qm", "seed"); _git(skel, "push", "-q", "origin", "HEAD:main")
    inst = tmp_path / "inst"
    _git(tmp_path, "clone", "-q", "-b", "main", str(bare), str(inst))
    shutil.copy(ROOT / "kipi-push-upstream.sh", inst / "kipi-push-upstream.sh")
    (inst / "instance-registry.json").write_text('{"instances":[{"name":"foo","type":"subtree"}]}\n')
    return bare, skel, inst


def _blob(path):
    return subprocess.run(["git", "hash-object", str(path)], capture_output=True, text=True, check=True).stdout.strip()


def _push(inst, bare):
    return subprocess.run(["/bin/bash", "kipi-push-upstream.sh"], capture_output=True, text=True, cwd=inst, timeout=120,
                          env=dict(os.environ, KIPI_SKELETON_REMOTE=str(bare)))


def _diverge(inst, body="a promoted change\n"):
    (inst / "q-system" / "lessons" / "a.md").write_text("---\ntitle: A\n---\n" + body)
    _git(inst, "commit", "-qam", "diverge")
    return _blob(inst / "q-system" / "lessons" / "a.md")


def _add_receipt(skel, bare, row):
    with open(skel / "q-system" / ".q-system" / "promotions.jsonl", "a") as fh:
        fh.write(json.dumps(row) + "\n")
    _git(skel, "commit", "-qam", "receipt"); _git(skel, "push", "-q", "origin", "HEAD:main")


def _row(blob, status="done", path="q-system/lessons/a.md"):
    return {"path": path, "blob": blob, "from_instance": "inst", "decided_by": "sana", "scrub": "clean", "status": status, "at": "2026-09-02T00:00:00+0000"}


def test_no_receipt_refused(tmp_path):
    bare, skel, inst = _repos(tmp_path)
    _diverge(inst)
    r = _push(inst, bare)
    assert r.returncode == 1 and "lessons/ differs from skeleton: lessons/a.md" in r.stdout + r.stderr, r.stdout + r.stderr


def test_stale_receipt_refused(tmp_path):
    """The receipt was for an earlier content; the file changed after it."""
    bare, skel, inst = _repos(tmp_path)
    old = _diverge(inst, "the promoted body\n")
    _add_receipt(skel, bare, _row(old))
    _diverge(inst, "edited again after the receipt\n")
    r = _push(inst, bare)
    assert r.returncode == 1 and "lessons/ differs from skeleton: lessons/a.md" in r.stdout + r.stderr, r.stdout + r.stderr


def test_matching_done_receipt_passes_the_lessons_guard(tmp_path):
    bare, skel, inst = _repos(tmp_path)
    blob = _diverge(inst)
    _add_receipt(skel, bare, _row(blob))
    r = _push(inst, bare)
    out = r.stdout + r.stderr
    assert "lessons/ differs" not in out and "skeleton-authored" not in out, out
    assert "promotion receipt honoured: lessons/a.md" in out, out


def test_a_pending_receipt_does_not_pass(tmp_path):
    """Only status done counts: a pending row (issue 10 writes one before the
    copy) must never bless a divergent lesson."""
    bare, skel, inst = _repos(tmp_path)
    blob = _diverge(inst)
    _add_receipt(skel, bare, _row(blob, status="pending"))
    r = _push(inst, bare)
    assert r.returncode == 1 and "lessons/ differs from skeleton: lessons/a.md" in r.stdout + r.stderr, r.stdout + r.stderr


def test_deletion_and_uncommitted_edits_stay_refused_even_with_a_receipt(tmp_path):
    bare, skel, inst = _repos(tmp_path)
    blob = _diverge(inst)
    _add_receipt(skel, bare, _row(blob))
    (inst / "q-system" / "lessons" / "a.md").write_text("uncommitted\n")
    r = _push(inst, bare)
    assert r.returncode == 1 and "uncommitted change under lessons/" in r.stdout + r.stderr
    _git(inst, "checkout", "-q", "--", "q-system/lessons/a.md")
    _git(inst, "rm", "-q", "q-system/lessons/a.md"); _git(inst, "commit", "-qm", "delete")
    r = _push(inst, bare)
    assert r.returncode == 1 and "lessons/ deleted vs skeleton" in r.stdout + r.stderr


def test_promote_writes_a_receipt_bound_to_the_blob(tmp_path):
    inst, skel = _trees(tmp_path)
    r = _promote(tmp_path, "q-system/lessons/general.md")
    assert r.returncode == 0, r.stderr
    rows = [json.loads(l) for l in (skel / RECEIPTS_REL).read_text().splitlines()]
    assert len(rows) == 1
    row = rows[0]
    assert row["path"] == "q-system/lessons/general.md" and row["blob"] == _blob(inst / "q-system" / "lessons" / "general.md")
    assert row["status"] == "done" and row["scrub"].startswith("clean") and row["from_instance"] == str(inst.resolve())
    assert row["decided_by"] == os.environ.get("USER") and row["at"]


def test_promote_decided_by_flag(tmp_path):
    inst, skel = _trees(tmp_path)
    env = dict(os.environ, KIPI_PROMOTE_INSTANCE=str(inst), KIPI_PROMOTE_SKELETON=str(skel), KIPI_PROMOTE_UNSCRUBBED="1",
               KIPI_PROMOTE_REGISTRY=str(tmp_path / "instance-registry.json"))
    r = subprocess.run(["/bin/bash", str(PROMOTE), "--decided-by", "sana", "q-system/lessons/general.md"], capture_output=True, text=True, env=env, cwd=inst, timeout=20)
    assert r.returncode == 0, r.stderr
    assert json.loads((skel / RECEIPTS_REL).read_text().splitlines()[-1])["decided_by"] == "sana"


def test_this_file_runs_its_own_tests_under_python3():
    if os.environ.get("KIPI_SELFTEST_INNER"):
        pytest.skip("inner run")
    env = dict(os.environ, KIPI_SELFTEST_INNER="1")
    ok = subprocess.run([sys.executable, __file__], capture_output=True, text=True, env=env)
    assert ok.returncode == 0 and "passed" in ok.stdout, ok.stdout[-600:]
    none = subprocess.run([sys.executable, __file__, "-k", "no_such_test_zzz"], capture_output=True, text=True, env=env)
    assert none.returncode != 0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", *sys.argv[1:]]))
