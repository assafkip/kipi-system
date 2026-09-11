"""Arctic Shift is the fleet's only Reddit transport. Import from here.

    import sys
    from pathlib import Path
    sys.path.insert(0, str(<repo root> / "plugins" / "kipi-core"))
    from reddit_arctic import transport

`bootstrap.locate()` finds that path for a caller that does not want to hardcode
it. The module lives beside `voiceloop` for the reason recorded in
`voiceloop/voice_ref.py`: a caller that does not travel with its engine is not
wired, it is wired on one machine.
"""
from reddit_arctic.transport import (  # noqa: F401
    ARCTIC_BASE,
    DEFAULT_MAX_ITEMS,
    DEFAULT_TIMEOUT,
    MAX_LIMIT,
    PULLPUSH_BASE,
    RETIRED_ACTOR,
    USER_AGENT,
    RedditFetchFailed,
    arctic_url,
    author_items,
    author_url,
    comments,
    comments_url,
    coverage,
    fetch_posts,
    normalize,
    pullpush_url,
    recent,
    search,
    thread,
)

__all__ = [
    "ARCTIC_BASE", "PULLPUSH_BASE", "USER_AGENT", "RETIRED_ACTOR",
    "DEFAULT_TIMEOUT", "DEFAULT_MAX_ITEMS", "MAX_LIMIT",
    "RedditFetchFailed",
    "arctic_url", "pullpush_url", "fetch_posts",
    "comments_url", "comments", "author_url", "author_items",
    "normalize", "recent", "search", "thread", "coverage",
]
