"""Guards the bypass_check quote-handling contract (orig sp-f597e213).

History: a `_strip_surrounding_quote_pair` helper once truncated bypass_check
commands that legitimately end in a quote (e.g. `grep -rnE 'foo'`). The fix
removed quote-stripping entirely, so the helper no longer exists; this test was
recovered as a dead import during the client-b-wiring-sweep and rewritten to guard
the SAME concern against current code: `_parse_yaml_block` must preserve a
bypass_check value verbatim, including inner/trailing quotes, never truncating.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import json

from issue_runner import _parse_yaml_block, _decode_bypass_check


def test_bypass_check_with_inner_quotes_is_preserved():
    block = "bypass_check: ! grep -rnE 'build_synthetic_seed|_SYN_'\n"
    parsed = _parse_yaml_block(block)
    assert parsed["bypass_check"] == "! grep -rnE 'build_synthetic_seed|_SYN_'"


def test_bypass_check_trailing_quote_not_truncated():
    block = "bypass_check: pytest tests -k 'evidence'\n"
    parsed = _parse_yaml_block(block)
    assert parsed["bypass_check"] == "pytest tests -k 'evidence'"
    assert parsed["bypass_check"].endswith("'")


def test_bypass_check_plain_command_preserved():
    block = "bypass_check: pytest tests/test_x.py -q\n"
    parsed = _parse_yaml_block(block)
    assert parsed["bypass_check"] == "pytest tests/test_x.py -q"


# --- _decode_bypass_check: the gate-command serialization boundary (sp-8e9a12b8) ---
# prd_split writes the frontmatter value via json.dumps; _decode_bypass_check is
# the symmetric json.loads read that must yield an sh-VALID command.

def test_nested_double_quotes_round_trip_sh_valid():
    cmd = 'python3 -c "import sys; sys.exit(0)"'
    serialized = json.dumps(cmd)  # what prd_split stores in the spec
    decoded = _decode_bypass_check(serialized)
    assert decoded == cmd
    assert "\\" not in decoded


def test_single_quoted_arg_not_truncated():
    cmd = "grep -rnE 'build_synthetic_seed|_SYN_'"
    decoded = _decode_bypass_check(json.dumps(cmd))
    assert decoded == cmd
    assert decoded.endswith("'")


def test_bare_single_quoted_value_pair_stripped():
    assert _decode_bypass_check("'pytest -k evidence'") == "pytest -k evidence"


def test_bare_command_unchanged():
    assert _decode_bypass_check("pytest tests/test_x.py -q") == "pytest tests/test_x.py -q"


def test_empty_value():
    assert _decode_bypass_check("") == ""
    assert _decode_bypass_check("   ") == ""
