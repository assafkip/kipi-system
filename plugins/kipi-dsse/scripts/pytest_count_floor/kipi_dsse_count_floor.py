"""pytest plugin that issue_runner loads for its own check runs only (ASK-3829, sp-dae00232).

WHY. pytest prints its summary line ("2 passed in 0.01s") only at verbosity -1 or higher.
chief's pyproject addopts carry -q and every split spec's check carries -q too, so those runs sat
at -2. pytest then prints no summary, not even on a failure, and verify refused every chief issue
with "the runner printed no count this could read". Three specs were patched by amendment, one at
a time. This raises verbosity to -1 when it is lower and leaves it alone otherwise, so a check
that already printed a count prints exactly what it printed before.

It is a floor on output, not a source of counts: the count verify reads is still pytest's own
summary line.

It takes its own name out of PYTEST_PLUGINS on import. A pytest that a test starts in a
subprocess then does not inherit a plugin name whose directory that test may have dropped from
PYTHONPATH, which would stop that inner pytest before it collected anything.
"""
import os

NAME = "kipi_dsse_count_floor"

_listed = [p.strip() for p in os.environ.get("PYTEST_PLUGINS", "").split(",") if p.strip()]
if NAME in _listed:
    _rest = [p for p in _listed if p != NAME]
    if _rest:
        os.environ["PYTEST_PLUGINS"] = ",".join(_rest)
    else:
        os.environ.pop("PYTEST_PLUGINS", None)


def pytest_configure(config):
    if getattr(config.option, "verbose", 0) < -1:
        config.option.verbose = -1
