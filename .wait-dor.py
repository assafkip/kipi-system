"""Wait for the kickstarted com.kipi.linear-dor run to finish, then print proof."""
import pathlib
import re
import subprocess
import time

LABEL = "com.kipi.linear-dor"
DEADLINE = time.time() + 900


def snapshot():
    r = subprocess.run(["launchctl", "list", LABEL], capture_output=True, text=True)
    pid = re.search(r'"PID"\s*=\s*(\d+)', r.stdout)
    last = re.search(r'"LastExitStatus"\s*=\s*(-?\d+)', r.stdout)
    return (pid.group(1) if pid else None), (last.group(1) if last else None)


while time.time() < DEADLINE:
    pid, last = snapshot()
    if pid is None:
        break
    time.sleep(10)

pid, last = snapshot()
print(f"running_pid={pid}  LastExitStatus={last}")
for name in ("linear-dor.out", "linear-dor.err"):
    p = pathlib.Path.home() / ".config" / "kipi" / name
    if not p.exists():
        print(f"== {name}: STILL MISSING")
        continue
    body = p.read_text()
    print(f"== {name} ({p.stat().st_size} bytes)")
    print(body[-1200:] or "(empty)")
state = pathlib.Path.home() / ".config" / "kipi" / "linear-dor-state.json"
print("== state:", state.read_text() if state.exists() else "MISSING")
