"""The garden gate. CI runs this on every push to main.

After GATE code commits (commits that touch web/, pi/ or tools/, apart from tidy commits) since
the last gardening, CI fails every commit except a tidy commit that improves the code's health:
it lowers a budget in tests/hygiene_budget.json, or adds a check to tests/test_hygiene.py or
tools/hygiene.py. When that tidy commit passes, CI moves the garden-report tag to it and the
count starts again.

Usage:
  python tools/garden.py check   exit 1, with the gardening list, when the gate is closed for HEAD
  python tools/garden.py report  print the gardening list
  python tools/garden.py done    exit 0 when HEAD is a tidy commit that clears the gate
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hygiene  # noqa: E402

GATE = 10
TAG = "garden-report"
CODE = ["web", "pi", "tools"]
HEALTH = ["tests/hygiene_budget.json", "tests/test_hygiene.py", "tools/hygiene.py"]


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout.strip()


def anchor() -> str:
    """The last gardening: the garden-report tag, or the commit that added this gate."""
    try:
        return git("rev-parse", f"{TAG}^{{commit}}")
    except subprocess.CalledProcessError:
        return git("log", "--diff-filter=A", "--format=%H", "-1", "--", "tools/garden.py")


def code_commits(base: str, head: str = "HEAD") -> list[str]:
    out = git("log", "--format=%h %s", f"{base}..{head}", "--", *CODE)
    return [line for line in out.splitlines() if line and not line.split(" ", 1)[1].lower().startswith("tidy:")]


def is_tidy(rev: str = "HEAD") -> bool:
    return git("log", "-1", "--format=%s", rev).lower().startswith("tidy:")


def improves_health(rev: str = "HEAD") -> bool:
    files = git("diff-tree", "--no-commit-id", "--name-only", "-r", rev).split()
    if any(f in files for f in HEALTH[1:]):
        return True
    if HEALTH[0] in files:
        before = json.loads(git("show", f"{rev}^:{HEALTH[0]}"))
        after = json.loads(git("show", f"{rev}:{HEALTH[0]}"))
        return any(after.get(k, v) < v for k, v in before.items())
    return False


def report(count: int) -> str:
    now = hygiene.measure()
    budget = json.loads(Path(hygiene.ROOT, HEALTH[0]).read_text())
    longest = ", ".join(f"{name} ({lines} lines)" for name, lines in now["longest_functions"])
    return f"""Garden gate: {count} code commits since the last gardening (limit {GATE}).

Before more features land, make one tidy commit that leaves the code healthier.
Its subject starts with "tidy:", it changes no tests or screenshots, and it either
lowers a budget in tests/hygiene_budget.json or adds a check to tests/test_hygiene.py.

Where to look:
  Longest functions: {longest}. Budget {budget['longest_function']} lines.
  Font sizes in use: {len(now['font_sizes'])} (budget {budget['font_sizes']}): {', '.join(now['font_sizes'])}
  Spacings in use: {len(now['spacings'])} (budget {budget['spacings']}): {', '.join(now['spacings'])} px
  web/index.html: {now['page_lines']} lines (limit {budget['page_lines']})
  Anything you had to correct twice since the last gardening: turn it into a check.

Pick the change that makes the next feature easiest. Run the full test suite before pushing."""


def main(cmd: str) -> int:
    base = anchor()
    count = len(code_commits(base))
    if cmd == "report":
        print(report(count))
        return 0
    if cmd == "done":
        return 0 if is_tidy() and improves_health() else 1
    if count < GATE:
        print(f"Garden gate open: {count} of {GATE} code commits since the last gardening.")
        return 0
    if is_tidy() and improves_health():
        print("Garden gate: this tidy commit clears the gate.")
        return 0
    print(report(count))
    if is_tidy():
        print("\nThis tidy commit doesn't lower a budget or add a check yet, so the gate stays closed.")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "check"))
