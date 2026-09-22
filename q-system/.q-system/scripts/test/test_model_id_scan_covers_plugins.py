#!/usr/bin/env python3
"""Pins the plugins/ model-ID scan (ASK-1904, from spillover sp-e86a9a9f).

Gate 1.1b reads `.claude/agents/*.md` frontmatter only. `model-allocation.md`
says model IDs live ONLY in agent frontmatter and the paired validator tables,
but nothing enforced that outside `.claude/agents/`, so
`plugins/kipi-core/voiceloop/critic.py:115-116` pinned two IDs where no check
could see them. A retired ID there ships fleet-wide green.

Nine contracts, each with a negative case so a no-op implementation fails:

1. A retired ID planted in a temp plugin tree is a violation naming the file.
2. The same tree with an allowlisted ID is clean (the scan is not "always red").
3. The derivation has a floor: scanning the LIVE plugins/ tree finds the pins it
   claims to cover. A scan whose regex stopped matching would read green, and
   every check built on it would be a silent no-op.
4. The live tree is GREEN. A gate red on its own population on day one gets
   switched off, and a gate that is off protects nothing.
5. The registered exceptions are bound to the (path, id) PAIR, not to the path.
   A different out-of-allowlist ID at a registered path is still a violation.
6. An ID inside a URL is not a pin (the kipi-mcp tests use
   `https://example.com/claude-sonnet-5` as fixture data).
7. An ID inside a prose comment line is not a pin (`revise.py:292` names an ID
   while explaining why it is not hardcoded).
8. The allowlist is DERIVED from MODEL_TIERS, not restated. Mutating MODEL_TIERS
   changes the verdict, which is what proves the two are actually coupled.
9. The check is WIRED: validate-separation.py's main() calls the scanner. A
   function nothing calls is not a gate.
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
VALIDATOR = REPO_ROOT / "validate-separation.py"

# A genuinely retired ID: superseded generation, not in any current tier.
RETIRED_ID = "claude-3-opus-20240229"

FAILURES: list[str] = []


def load_validator():
    spec = importlib.util.spec_from_file_location("kipi_validate_separation", VALIDATOR)
    if spec is None or spec.loader is None:
        raise SystemExit("cannot load validate-separation.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok   {label}")
        return
    FAILURES.append(label)
    print(f"  FAIL {label}" + (f"\n         {detail}" if detail else ""))


def plugin_tree(tmp: Path, relpath: str, body: str) -> Path:
    """Build a temp repo root holding one plugin file, and return that root."""
    target = tmp / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body)
    return tmp


def main() -> int:
    mod = load_validator()
    scan = getattr(mod, "plugin_model_id_violations", None)
    if scan is None:
        print("  FAIL validate-separation.py has no plugin_model_id_violations()")
        print("test_model_id_scan_covers_plugins.py: FAIL (1)")
        return 1

    # 1 + 2: a retired ID is red, an allowlisted ID is green, same shape of file.
    with tempfile.TemporaryDirectory() as td:
        root = plugin_tree(
            Path(td), "plugins/kipi-core/fake/pin.py", f'MODEL = "{RETIRED_ID}"\n'
        )
        red = scan(str(root))
        check(
            "a retired ID in plugins/ is a violation",
            len(red) == 1 and "pin.py" in red[0] and RETIRED_ID in red[0],
            f"got {red!r}",
        )

    with tempfile.TemporaryDirectory() as td:
        root = plugin_tree(
            Path(td), "plugins/kipi-core/fake/pin.py", 'MODEL = "claude-sonnet-5"\n'
        )
        check(
            "an allowlisted ID in plugins/ is clean",
            scan(str(root)) == [],
            f"got {scan(str(root))!r}",
        )

    # 3: the floor. The scan must actually FIND the pins it covers on the live
    # tree; an empty parse would make every check above a no-op that reads green.
    found = getattr(mod, "plugin_model_id_pins", None)
    if found is None:
        check("plugin_model_id_pins() exists (the derivation's floor)", False)
    else:
        pins = found(str(REPO_ROOT))
        critic_pins = [p for p in pins if p[0].endswith("voiceloop/critic.py")]
        check(
            "the live scan finds critic.py's two pins",
            len(critic_pins) == 2
            and {p[1] for p in critic_pins} == {"claude-sonnet-5", "claude-haiku-4-5"},
            f"got {critic_pins!r}",
        )
        check("the live scan finds pins at all (non-empty derivation)", len(pins) >= 2)

    # 4: calibration. Green on its own population today.
    live = scan(str(REPO_ROOT))
    check("the live plugins/ tree is green", live == [], f"got {live!r}")

    # 5: an exception is bound to (path, id), never to the path alone.
    exceptions = getattr(mod, "PLUGIN_PIN_EXCEPTIONS", None)
    check("PLUGIN_PIN_EXCEPTIONS is declared", isinstance(exceptions, (set, frozenset)))
    if isinstance(exceptions, (set, frozenset)) and exceptions:
        exempt_path, exempt_id = sorted(exceptions)[0]
        with tempfile.TemporaryDirectory() as td:
            root = plugin_tree(Path(td), exempt_path, f'M = "{exempt_id}"\n')
            check(
                "the registered (path, id) pair is exempt",
                scan(str(root)) == [],
                f"got {scan(str(root))!r}",
            )
        with tempfile.TemporaryDirectory() as td:
            root = plugin_tree(Path(td), exempt_path, f'M = "{RETIRED_ID}"\n')
            mutated = scan(str(root))
            check(
                "a DIFFERENT out-of-allowlist ID at an exempt path is still a violation",
                len(mutated) == 1 and RETIRED_ID in mutated[0],
                f"got {mutated!r}",
            )

    # 6: an ID inside a URL is fixture data, not a pin.
    with tempfile.TemporaryDirectory() as td:
        root = plugin_tree(
            Path(td),
            "plugins/kipi-core/fake/t.py",
            f'URL = "https://example.com/{RETIRED_ID}"\n',
        )
        check(
            "an ID inside a URL is not a pin",
            scan(str(root)) == [],
            f"got {scan(str(root))!r}",
        )

    # 7: an ID named in a prose comment is not a pin.
    with tempfile.TemporaryDirectory() as td:
        root = plugin_tree(
            Path(td),
            "plugins/kipi-core/fake/t.py",
            f"# we used to run {RETIRED_ID} here and it was wrong\n",
        )
        check(
            "an ID inside a comment line is not a pin",
            scan(str(root)) == [],
            f"got {scan(str(root))!r}",
        )

    # 8: the allowlist is derived from MODEL_TIERS, not restated beside it.
    with tempfile.TemporaryDirectory() as td:
        root = plugin_tree(
            Path(td), "plugins/kipi-core/fake/pin.py", 'MODEL = "claude-sonnet-5"\n'
        )
        before = scan(str(root))
        saved = mod.MODEL_TIERS["sonnet"]
        mod.MODEL_TIERS["sonnet"] = {"claude-sonnet-99"}
        after = scan(str(root))
        mod.MODEL_TIERS["sonnet"] = saved
        check(
            "the verdict follows MODEL_TIERS (derived, not restated)",
            before == [] and len(after) == 1,
            f"before={before!r} after={after!r}",
        )

    # 9: wired into the gate, not merely defined.
    source = VALIDATOR.read_text()
    check(
        "validate-separation.py calls plugin_model_id_violations()",
        source.count("plugin_model_id_violations(") >= 2,
        "defined but never called",
    )

    print()
    print("test_model_id_scan_covers_plugins.py")
    if FAILURES:
        print(f"test_model_id_scan_covers_plugins.py: FAIL ({len(FAILURES)})")
        return 1
    print("test_model_id_scan_covers_plugins.py: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
