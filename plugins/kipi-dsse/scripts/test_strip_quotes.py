"""Guards the bypass_check quote-handling contract (orig sp-f597e213).

History: a `_strip_surrounding_quote_pair` helper once truncated bypass_check
commands that legitimately end in a quote (e.g. `grep -rnE 'foo'`). The fix
removed quote-stripping entirely, so the helper no longer exists; this test was
recovered as a dead import during the qep-wiring-sweep and rewritten to guard
the SAME concern against current code: `_parse_yaml_block` must preserve a
bypass_check value verbatim, including inner/trailing quotes, never truncating.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from issue_runner import _parse_yaml_block


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
