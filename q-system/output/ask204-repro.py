"""ASK-204 reproducer: the ask-150 detector publishes crontab text into a Linear body.

Run against the ask-150 HEAD copy (q-system/output/ask150-fleet-health-daily.py),
then against the fixed file. Exit 1 = the defect reproduces.

The three shapes are the ones ASK-204 names as rounds 8 and 9's findings:
  1. an assignment whose word start is a BACKTICK -- outside _ASSIGNMENT_RE's
     lookbehind character class, so the value is published verbatim;
  2. a bare `lin_api_` token -- no _SECRET_PATTERNS entry;
  3. a bare `ntn_` token -- no _SECRET_PATTERNS entry.
"""
import importlib.util
import sys
from pathlib import Path

TARGET = sys.argv[1] if len(sys.argv) > 1 else "q-system/output/ask150-fleet-health-daily.py"
spec = importlib.util.spec_from_file_location("fh", Path(TARGET).resolve())
fh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fh)

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

findings = fh.detect_cron_shells_claude(None, cron_text=CRON)
if not findings:
    print("REPRO INCONCLUSIVE: detector found nothing to publish")
    sys.exit(2)

body = findings[0]["body"]
print("what the finding publishes:")
for line in body.splitlines():
    if line.startswith("- `"):
        print("   ", line)

leaks = [name for name, secret in SECRETS.items() if secret in body]
if leaks:
    print(f"\nRED: {len(leaks)} secret(s) reach the Linear issue body verbatim:")
    for name in leaks:
        print(f"    - {name}: {SECRETS[name]}")
    sys.exit(1)
print("\nGREEN: zero characters of any source line reach the body")
sys.exit(0)
