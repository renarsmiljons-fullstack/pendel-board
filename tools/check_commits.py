"""Rules every commit must follow. CI runs this on each pushed commit.

1. A commit whose subject starts with "tidy:" changes structure only. It may not touch the tests
   or the screenshot baselines, so the unchanged tests prove nothing visible changed. It may edit
   the health checks themselves: tests/test_hygiene.py, tests/hygiene_budget.json, tools/hygiene.py.
2. A budget in tests/hygiene_budget.json may only go down. Raising one needs a line
   "Budget raised: <why>" in the commit message, so it is a visible decision, never a quiet one.

Usage: python tools/check_commits.py <first commit to check>^..<last commit>  (default HEAD^..HEAD)
"""
from __future__ import annotations

import json
import subprocess
import sys

BUDGET = "tests/hygiene_budget.json"
CHECKS = {BUDGET, "tests/test_hygiene.py", "tools/hygiene.py"}


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def budget_at(rev: str) -> dict:
    try:
        return json.loads(git("show", f"{rev}:{BUDGET}"))
    except subprocess.CalledProcessError:
        return {}


def problems(sha: str) -> list[str]:
    message = git("log", "-1", "--format=%B", sha)
    subject = message.splitlines()[0]
    files = git("diff-tree", "--no-commit-id", "--name-only", "-r", "--root", sha).split()
    found = []
    if subject.lower().startswith("tidy:"):
        touched = [f for f in files if f.startswith("tests/") and f not in CHECKS]
        if touched:
            found.append(
                f"'{subject}' is a tidy commit but changes {', '.join(touched)}.\n"
                "  A tidy commit must leave tests and screenshots alone; that is how it proves nothing visible changed.\n"
                "  Split it: commit the structural change as tidy:, and the test or screenshot change separately.")
    if BUDGET in files and "Budget raised:" not in message:
        before, after = budget_at(f"{sha}^"), budget_at(sha)
        raised = [f"{k} {before[k]} -> {v}" for k, v in after.items() if k in before and v > before[k]]
        if raised:
            found.append(
                f"'{subject}' raises budgets: {', '.join(raised)}.\n"
                "  Budgets only go down. Fix the code instead (split the function, reuse a size or spacing),\n"
                "  or, if raising is truly right, add a line 'Budget raised: <why>' to the commit message.")
    return found


def main(spec: str) -> int:
    shas = git("rev-list", "--reverse", spec).split()
    found = [p for sha in shas for p in problems(sha)]
    for p in found:
        print(p, end="\n\n")
    if not found:
        print(f"Commit rules: {len(shas)} commit(s) checked, all fine.")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "HEAD^..HEAD"))
