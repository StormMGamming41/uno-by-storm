"""
Reads a failed Buildozer log and prints the part that explains WHY it failed.

Buildozer prints "Command failed ... The error might be hidden in the log above" followed by a long
dump of environment variables; the real cause is further up. This finds the first lines that look like
a cause (Python tracebacks, compiler errors, missing modules, anything mentioning Cython...) and shows
them with the lines around them, then the end of the log with the environment dump removed.

    python ci/explain_failure.py build.log
"""
import re
import sys

path = sys.argv[1] if len(sys.argv) > 1 else "build.log"
try:
    raw = open(path, errors="replace").read().splitlines()
except OSError as problem:
    sys.exit(f"cannot read {path}: {problem}")

ENV_DUMP = re.compile(r"^#\s+[A-Za-z_][A-Za-z_0-9]* = ")          # "#     PATH = '...'"
lines = [(n, text) for n, text in enumerate(raw) if not ENV_DUMP.match(text)]

# strongest first; each is (label, pattern)
CAUSES = [
    ("Python traceback", re.compile(r"Traceback \(most recent call last\)")),
    ("missing Python module", re.compile(r"No module named|ModuleNotFoundError|ImportError")),
    ("Cython", re.compile(r"cython", re.I)),
    ("compiler error", re.compile(r"\berror:|fatal error|undefined reference|ld: error|CMake Error")),
    ("failed step", re.compile(r"\bERROR\b|FAILED|Error \d+|returned non-zero|No such file")),
]
print(f"Log: {path}, {len(raw)} lines ({len(raw) - len(lines)} lines of environment dump hidden)\n")
print("What it was building:")
for n, text in lines:
    if "--requirements=" in text or "requirements =" in text:
        print("  " + text.strip()[:200]); break
for n, text in lines:
    if "python-for-android" in text.lower() and ("version" in text.lower() or "branch" in text.lower()):
        print("  " + text.strip()[:200]); break
print()

shown = []                                  # line numbers already covered, so blocks don't repeat
CONTEXT = 14
found = 0
for label, pattern in CAUSES:
    hits = [(n, t) for n, t in lines if pattern.search(t) and "Command failed" not in t]
    if not hits:
        continue
    print(f"=== {label}: {len(hits)} matching line(s); the first ===")
    n = hits[0][0]
    if any(abs(n - s) < CONTEXT for s in shown):
        print("  (already shown above)\n")
        continue
    shown.append(n)
    found += 1
    block = [t for i, t in lines if n - CONTEXT <= i <= n + CONTEXT]
    print("\n".join("  " + t[:220] for t in block))
    print()
    if found >= 3:
        break

if not found:
    print("No line in this log looks like a cause. Is the log complete (buildozer -v, log_level = 2)?\n")
print("=== the last 30 lines (environment dump removed) ===")
print("\n".join("  " + t[:220] for _, t in lines[-30:]))
