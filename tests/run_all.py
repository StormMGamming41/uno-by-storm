"""Runs every test file; fails if any exits badly or prints a FAIL line. Used by the cloud build."""
import os, subprocess, sys
here = os.path.dirname(os.path.abspath(__file__))
names = ["test_desktop", "test_profiles", "test_touch", "test_present", "test_cards",
         "test_clipboard", "test_check_display", "test_orientation"]
bad = []
for n in names:
    p = subprocess.run([sys.executable, os.path.join(here, n + ".py")], cwd=here,
                       capture_output=True, text=True, timeout=600)
    text = p.stdout + p.stderr
    failed = p.returncode != 0 or "FAIL" in text or "Traceback" in text
    passed = sum(1 for l in text.splitlines() if l.startswith("PASS"))
    print(f"{'FAIL' if failed else 'ok  '} {n}  ({passed} PASS lines)")
    if failed:
        bad.append(n); print(text[-1500:])
sys.exit(1 if bad else 0)
