"""ASK-204 reproducer: does a cron finding publish crontab TEXT into a Linear body?

    python3 q-system/output/ask204-repro.py             # the shipped detector -> GREEN
    python3 q-system/output/ask204-repro.py --legacy    # the ask-150 output channel -> RED
    python3 q-system/output/ask204-repro.py --self-test # asserts all three exit codes
    python3 q-system/output/ask204-repro.py <path>      # any other copy of the detector

Exit 0 = GREEN (nothing leaked), 1 = RED (the defect reproduces), 2 = INCONCLUSIVE
(the target could not be loaded, or the detector found nothing to publish).

Both halves run FROM THIS BRANCH (PR #19 review, minor 3). The default target used
to be `q-system/output/ask150-fleet-health-daily.py`, which is not on the branch:
the RED half was unreproducible by anyone reading the PR, and the resulting
FileNotFoundError exited 1 -- the same code as "the defect reproduces". So the
default is now the file this branch actually ships, a missing target exits 2, and
`--legacy` reconstructs the OLD OUTPUT CHANNEL (publish the line, not its number)
over the shipped detector, which is the whole of what ASK-204 changed.

The three shapes are rounds 8 and 9 of #11's review:
  1. an assignment whose word start is a BACKTICK -- outside _ASSIGNMENT_RE's
     lookbehind character class, so the value was published verbatim;
  2. a bare `lin_api_` token -- no _SECRET_PATTERNS entry;
  3. a bare `ntn_` token -- no _SECRET_PATTERNS entry.
"""
import importlib.util
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TARGET = REPO_ROOT / "q-system/.q-system/scripts/fleet-health-daily.py"

SECRETS = {
    "backtick-word-start assignment": "lin_api_backtickleak",
    "bare Linear token": "lin_api_bareleak",
    "bare Notion token": "ntn_barenotionleak",
}
CRON = (
    "0 3 * * * bash -lc '`LINEAR_API_KEY=lin_api_backtickleak claude -p sweep`'\n"
    "0 4 * * * claude -p 'sweep' --header lin_api_bareleak\n"
    "0 5 * * * claude -p 'sweep' --header ntn_barenotionleak\n"
)


def load(target):
    """The detector under test, or exit 2. A target that will not load is
    INCONCLUSIVE, never RED -- an exit-code wrapper cannot tell those apart."""
    path = Path(target).resolve()
    if not path.is_file():
        print(f"INCONCLUSIVE: no such target: {path}")
        sys.exit(2)
    try:
        spec = importlib.util.spec_from_file_location("fh", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001
        print(f"INCONCLUSIVE: {path} did not load: {type(exc).__name__}: {exc}")
        sys.exit(2)
    return module


def legacy_body(fh):
    """The body the ask-150 ARCHITECTURE built: the offending lines themselves.

    Same detector, old output channel. That is the honest reconstruction -- ASK-204
    never changed what is detected, only what the finding carries -- and it keeps
    the RED half runnable without a copy of the deleted file on the branch.
    """
    numbers = fh.offending_cron_lines(CRON)
    lines = CRON.splitlines()
    return "\n".join(f"- `{lines[n - 1]}`" for n in numbers)


def self_test():
    """Assert all three exit codes, so this script cannot go one-sided again."""
    cases = [
        ("--legacy", 1, "the old output channel reproduces the leak"),
        (str(DEFAULT_TARGET), 0, "the shipped detector publishes no source text"),
        (str(REPO_ROOT / "q-system/output/does-not-exist.py"), 2,
         "a missing target is INCONCLUSIVE, not RED"),
    ]
    bad = []
    for arg, want, label in cases:
        res = subprocess.run([sys.executable, __file__, arg],
                             capture_output=True, text=True)
        got = res.returncode
        print(f"  {'ok ' if got == want else 'FAIL'}: {label} (exit {got}, want {want})")
        if got != want:
            bad.append(f"{arg}: exit {got}, want {want}\n{res.stdout}{res.stderr}")
    if bad:
        print("\nSELF-TEST FAILED:")
        for line in bad:
            print(f"  - {line}")
        return 1
    print("\nSELF-TEST PASS: RED, GREEN and INCONCLUSIVE all reachable from this branch")
    return 0


def main(argv):
    if "--self-test" in argv:
        return self_test()
    legacy = "--legacy" in argv
    positional = [a for a in argv if not a.startswith("--")]
    fh = load(positional[0] if positional else DEFAULT_TARGET)

    if legacy:
        body = legacy_body(fh)
        print("what the ask-150 output channel publishes:")
    else:
        findings = fh.detect_cron_shells_claude(None, cron_text=CRON)
        if not findings:
            print("INCONCLUSIVE: detector found nothing to publish")
            return 2
        body = findings[0]["body"]
        print("what the finding publishes:")
    for line in body.splitlines():
        if line.startswith("- "):
            print("   ", line)

    leaks = [name for name, secret in SECRETS.items() if secret in body]
    if leaks:
        print(f"\nRED: {len(leaks)} secret(s) reach the Linear issue body verbatim:")
        for name in leaks:
            print(f"    - {name}: {SECRETS[name]}")
        return 1
    print("\nGREEN: zero characters of any source line reach the body")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
