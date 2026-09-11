"""Find `plugins/kipi-core` from anywhere in a repo, so no caller hardcodes it.

Every consumer of the transport lives at a different depth: a q-system script,
a pipeline package, a cole-gtm gtm/scripts file, a kipi-mcp module inside a
src/ layout. A relative `parents[N]` is correct in exactly one of those and
silently wrong in the rest, which is the class of bug `voice_ref.py` records:
a caller that does not travel with its engine is wired on one machine.

Usage, from any depth:

    from reddit_arctic.bootstrap import load
    transport = load()

or, when the package is not importable yet (the usual case, because finding it
is the whole problem):

    import importlib.util, pathlib, sys
    for parent in pathlib.Path(__file__).resolve().parents:
        cand = parent / "plugins" / "kipi-core"
        if (cand / "reddit_arctic").is_dir():
            sys.path.insert(0, str(cand)); break
    from reddit_arctic import transport

`plugin_root()` below is that loop, kept in one place for callers that CAN
already import the package.
"""
from __future__ import annotations

import sys
from pathlib import Path


def plugin_root(start: Path | str | None = None) -> Path:
    """The nearest `plugins/kipi-core` at or above `start`.

    Walks UP rather than reading an env var: the fleet has one skeleton and many
    instances, each carrying its own vendored copy, and a caller must get the
    copy that shipped with it. An env var would let a stale export point an
    instance at another instance's plugin, which is exactly the cross-instance
    reach `test_boundary.py` forbids.
    """
    here = Path(start or __file__).resolve()
    if here.is_file():
        here = here.parent
    for parent in [here, *here.parents]:
        cand = parent / "plugins" / "kipi-core"
        if (cand / "reddit_arctic").is_dir():
            return cand
        # the module may already BE inside plugins/kipi-core
        if parent.name == "kipi-core" and (parent / "reddit_arctic").is_dir():
            return parent
    raise RuntimeError(
        "no plugins/kipi-core/reddit_arctic at or above %s. The Reddit transport "
        "ships with the kipi-core plugin; run `kipi update` in this instance."
        % here)


def load(start: Path | str | None = None):
    """Import and return the transport module, putting the plugin on sys.path."""
    root = plugin_root(start)
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from reddit_arctic import transport
    return transport
