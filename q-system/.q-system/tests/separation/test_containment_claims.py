import json
import re
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[4]
PARENT_PRD = (
    REPO_ROOT
    / ".prd-os/prds/prd-skeleton-data-containment-2026-07-24.md"
)
UPDATER_ISSUE = (
    REPO_ROOT / ".prd-os/issues/fcu-dry-run-final-state.md"
)
UPDATER = REPO_ROOT / "kipi-update.sh"
RECEIPTS = REPO_ROOT / ".prd-os/receipts.jsonl"
REGISTRY = REPO_ROOT / "instance-registry.json"
DEPENDENCY_ID = "fcu-dry-run-final-state"
DEPENDENCY_PRD = "prd-fail-closed-fleet-updater-2026-07-24"


def frontmatter_value(path, key):
    content = path.read_text(encoding="utf-8")
    frontmatter = content.split("---", 2)[1]
    match = re.search(rf"^{re.escape(key)}:\s*(.+)$", frontmatter, re.M)
    assert match is not None
    return match.group(1).strip()


def verified_dependency_receipt():
    if frontmatter_value(UPDATER_ISSUE, "status") != "closed":
        return None

    for line in RECEIPTS.read_text(encoding="utf-8").splitlines():
        receipt = json.loads(line)
        if (
            receipt.get("issue_id") == DEPENDENCY_ID
            and receipt.get("prd_id") == DEPENDENCY_PRD
            and receipt.get("verified_at")
            and receipt.get("reviewed_at")
            and receipt.get("findings_triaged_at")
            and receipt.get("closed_at")
            and receipt.get("commit_sha")
        ):
            commit = receipt["commit_sha"]
            if re.fullmatch(r"[0-9a-f]{40}", commit) and subprocess.run(
                ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
            ).returncode == 0:
                return receipt
    return None


def propagation_contract(prd):
    match = re.search(
        r"^4\. Treat update propagation.+?(?=^5\.)",
        prd,
        re.M | re.S,
    )
    assert match is not None
    return match.group(0)


def logical_lines(script):
    """Join backslash-continued shell lines into one logical command each.

    A regex anchored on the invocation's surface form breaks the moment the
    command is reformatted. This one broke exactly that way: the real sync grew
    an `if ! ` prefix and per-line `--exclude` continuations, so the locator
    found nothing and the propagation evidence went unchecked while the gate
    read RED for a formatting change rather than a missing exclude.
    """
    joined = []
    pending = ""
    for raw in script.splitlines():
        # The backslash must be the LAST character. `\` followed by a space is
        # not a continuation in sh, and treating it as one would let a
        # separately executed line supply the excludes this gate looks for.
        if raw.endswith("\\"):
            pending += raw[:-1].strip() + " "
            continue
        joined.append((pending + raw.strip()).strip())
        pending = ""
    if pending:
        joined.append(pending.strip())
    return joined


def shell_commands(script):
    """Executable command segments: comments dropped, ; && || split apart."""
    for line in logical_lines(script):
        if line.startswith("#"):
            continue
        for segment in re.split(r";|&&|\|\|", line):
            segment = segment.strip()
            if segment:
                yield segment


def normalize_operand(token):
    """`"${ARCHIVE_TMP}"/q-system/` and `"$ARCHIVE_TMP/q-system/"` are the same path."""
    token = token.replace('"', "").replace("'", "")
    return re.sub(r"\$\{(\w+)\}", r"$\1", token)


# rsync has to be in COMMAND position, not inside an echo or a string. An
# unrecognized prefix makes the search find nothing and the gate fail loudly,
# which is the safe direction.
COMMAND_POSITION = re.compile(
    r"^(?:!\s+|if\s+|then\s+|else\s+|elif\s+|while\s+|until\s+|do\s+"
    r"|\w+=\$\(\s*|\$\(\s*|\(\s*)*rsync\s+(?P<arguments>.*)$"
)


# rsync options whose value is a SEPARATE argument. Without this the value of
# `--filter '- /tmp/'` would be mistaken for the source path and the gate would
# fail on a perfectly valid refactor.
VALUE_OPTIONS = {
    "--exclude", "--include", "--filter", "-f", "--exclude-from",
    "--include-from", "--files-from", "-e", "--rsh", "--chmod",
    "--compare-dest", "--copy-dest", "--link-dest", "--log-file",
    "--out-format", "--password-file", "--partial-dir", "--temp-dir", "-T",
    "--timeout", "--bwlimit", "--max-size", "--min-size", "--block-size",
    "-B", "--modify-window", "--backup-dir", "--suffix", "--rsync-path",
    "--sockopts", "--iconv", "--info", "--debug", "--outbuf",
}


def shell_tokens(text):
    """Split on UNQUOTED whitespace only.

    shlex is not usable here: it ends a token at a closing quote, so
    `"${ARCHIVE_TMP}"/q-system/` came back as `"${ARCHIVE_TMP}"` and the source
    operand no longer matched. A word is one token even when only part of it is
    quoted, which is exactly how the shell reads it.
    """
    tokens = []
    current = ""
    quote = None
    for char in text:
        if quote is not None:
            current += char
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
            current += char
        elif char.isspace():
            if current:
                tokens.append(current)
                current = ""
        else:
            current += char
    if current:
        tokens.append(current)
    return tokens


def rsync_tokens(segment):
    """Arguments of an rsync invocation in command position, or None."""
    match = COMMAND_POSITION.match(segment)
    if match is None:
        return None
    return shell_tokens(match.group("arguments"))


def rsync_source_operand(segment):
    """First positional operand of an rsync invocation, or None.

    rsync reads its FIRST operand and writes the last, so checking position
    keeps a destination path from passing as proof that the command reads it.
    """
    tokens = rsync_tokens(segment)
    if tokens is None:
        return None
    skip_value = False
    for token in tokens:
        if skip_value:
            skip_value = False
            continue
        if token.startswith("-") and token != "-":
            skip_value = token in VALUE_OPTIONS
            continue
        return normalize_operand(token)
    return None


def rsync_flags(segment):
    """Long options plus every letter of the short bundles: -ain -> -a -i -n."""
    flags = set()
    for token in rsync_tokens(segment) or []:
        if token.startswith("--"):
            flags.add(token.split("=", 1)[0])
        elif token.startswith("-") and len(token) > 1:
            flags.update("-" + letter for letter in token[1:])
    return flags


def rsync_excludes(segment):
    """Excluded paths, whichever of the four spellings rsync accepts is used."""
    values = set()
    tokens = rsync_tokens(segment) or []
    for index, token in enumerate(tokens):
        value = None
        if token.startswith("--exclude="):
            value = token.split("=", 1)[1]
        elif token == "--exclude" and index + 1 < len(tokens):
            value = tokens[index + 1]
        if value is not None:
            values.add(normalize_operand(value).rstrip("/"))
    return values


def rsync_command(updater, source):
    """The single rsync invocation that READS `source`, however it is written.

    Exactly one is required: two would make the assertions below ambiguous
    about which invocation actually carries the excludes.
    """
    wanted = normalize_operand(source)
    matches = [
        segment
        for segment in shell_commands(updater)
        if rsync_source_operand(segment) == wanted
    ]
    assert len(matches) == 1, (
        f"expected exactly one rsync invocation reading {source}, "
        f"found {len(matches)}"
    )
    return matches[0]


def assert_storage_classification(contract):
    assert "storage separation breach, not proof of observed propagation" in contract


def assert_preventive_contract(contract):
    assert "Treat update propagation as preventive hardening." in contract
    assert "Block propagation proof on closed issue" in contract
    assert DEPENDENCY_ID in contract

    approved_negative = (
        "storage separation breach, not proof of observed propagation"
    )
    remaining_contract = contract.replace(approved_negative, "")
    proof_terms = (
        "observed",
        "confirmed",
        "proven",
        "verified",
        "demonstrated",
        "reproduced",
    )
    for term in proof_terms:
        assert re.search(
            rf"(?i)\b{term}\b.{{0,100}}\bpropagat\w*"
            rf"|\bpropagat\w*.{{0,100}}\b{term}\b",
            remaining_contract,
        ) is None
    assert re.search(
        r"(?i)\bpropagated\s+(?:to|across|into)\b|\bfleet\s+proof\b",
        remaining_contract,
    ) is None


def assert_updater_evidence():
    updater = UPDATER.read_text(encoding="utf-8")
    real_command = rsync_command(updater, '"$ARCHIVE_TMP/q-system/"')
    dry_command = rsync_command(updater, '"$DRY_TMP/q-system/"')

    # Assert the BEHAVIOUR, not the spelling: `--archive` and `-a`, `-ain` and
    # `-a -i -n`, `--exclude=X` and `--exclude X` all mean the same thing, and a
    # gate that only knows one spelling reports RED for a rename.
    real_flags = rsync_flags(real_command)
    assert "-a" in real_flags or "--archive" in real_flags
    assert "--delete" in real_flags
    assert "/canonical" in rsync_excludes(real_command)

    dry_flags = rsync_flags(dry_command)
    assert "-a" in dry_flags or "--archive" in dry_flags
    assert "--delete" in dry_flags
    assert "-n" in dry_flags or "--dry-run" in dry_flags
    assert "-i" in dry_flags or "--itemize-changes" in dry_flags
    assert "/canonical" in rsync_excludes(dry_command)

    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    managed_direct_clones = [
        instance["name"]
        for instance in registry["instances"]
        if instance.get("type") == "direct-clone"
    ]
    assert managed_direct_clones == []


def test_no_unproven_propagation_claim():
    prd = PARENT_PRD.read_text(encoding="utf-8")
    contract = propagation_contract(prd)

    assert_storage_classification(contract)
    assert_updater_evidence()
    receipt = verified_dependency_receipt()
    if receipt is None:
        assert_preventive_contract(contract)

        with pytest.raises(AssertionError):
            assert_preventive_contract(
                contract + "\nPropagation to every fleet instance is proven."
            )


def test_storage_and_propagation_have_distinct_evidence_labels():
    contract = propagation_contract(PARENT_PRD.read_text(encoding="utf-8"))

    assert_storage_classification(contract)
    if verified_dependency_receipt() is None:
        assert_preventive_contract(contract)


def test_current_updater_excludes_canonical_in_real_and_dry_paths():
    assert_updater_evidence()


SOURCE = '"$ARCHIVE_TMP/q-system/"'
ONE_LINE = (
    'rsync -a --delete "$ARCHIVE_TMP/q-system/" "$path/" '
    '--exclude="/my-project/" --exclude="/canonical/" 2>/dev/null'
)
GUARDED = (
    'if ! rsync -a --delete "$ARCHIVE_TMP/q-system/" "$path/" \\\n'
    '    --exclude="/my-project/" \\\n'
    '    --exclude="/canonical/" 2>/dev/null; then'
)
CAPTURED = (
    'CHANGED=$(rsync -a --delete "$ARCHIVE_TMP/q-system/" "$path/" \\\n'
    '  --exclude="/canonical/" 2>/dev/null)'
)


BRACED = (
    'rsync -a --delete "${ARCHIVE_TMP}"/q-system/ "$path/" '
    '--exclude="/canonical/" 2>/dev/null'
)
SPELLED_OUT = (
    'rsync --archive --delete "$ARCHIVE_TMP/q-system/" "$path/" '
    "--exclude /canonical/ 2>/dev/null"
)
# An option whose value is a separate argument, sitting before the source.
FILTERED = (
    "rsync -a --filter '- /tmp/' --delete \"$ARCHIVE_TMP/q-system/\" \"$path/\" "
    '--exclude="/canonical/" 2>/dev/null'
)


def test_rsync_locator_is_format_proof_and_still_has_teeth():
    """The locator must find the command in any shell form AND still fail loudly.

    A locator that quietly matches nothing turns this whole gate into a
    formatting check. These fixtures keep both halves honest: reformatting must
    not break it, and a dropped exclude, a vanished command, or text that only
    LOOKS like the command must.
    """
    for form in (ONE_LINE, GUARDED, CAPTURED, BRACED, SPELLED_OUT, FILTERED):
        assert "/canonical" in rsync_excludes(rsync_command(form, SOURCE))

    dropped = GUARDED.replace('    --exclude="/canonical/" \\\n', "").replace(
        '--exclude="/canonical/" ', ""
    )
    assert "/canonical" not in rsync_excludes(rsync_command(dropped, SOURCE))

    # Equivalent spellings must read as equivalent, not as a regression.
    assert rsync_flags(SPELLED_OUT) >= {"--archive", "--delete"}
    assert rsync_flags('rsync -ain --delete "$ARCHIVE_TMP/q-system/" "$p/"') >= {
        "-a", "-i", "-n", "--delete"
    }

    # Nothing that is not an executed rsync reading that source may count.
    for impostor in (
        'echo "no rsync here"',
        f"# {ONE_LINE}",
        f'echo "{ONE_LINE}"',
        'rsync -a --delete "$other/" "$ARCHIVE_TMP/q-system/" 2>/dev/null',
    ):
        with pytest.raises(AssertionError):
            rsync_command(impostor, SOURCE)

    # A backslash followed by a space does not continue the command, so the
    # exclude on the next line belongs to something else.
    not_continued = (
        'rsync -a --delete "$ARCHIVE_TMP/q-system/" "$path/" 2>/dev/null \\ \n'
        '--exclude="/canonical/"'
    )
    assert '--exclude="/canonical/"' not in rsync_command(not_continued, SOURCE)

    with pytest.raises(AssertionError):
        rsync_command(ONE_LINE + "\n" + CAPTURED, SOURCE)
    with pytest.raises(AssertionError):
        rsync_command(ONE_LINE + " ; " + CAPTURED, SOURCE)
