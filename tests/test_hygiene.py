"""Code health checks. Each failure says how to fix it.

Agents copy what the code already does, so these checks stop a bad pattern before it spreads.
Some are absolute (no stray colours, no dead code). The rest are budgets in
tests/hygiene_budget.json that may only go down: when you improve a number, lower its budget in
the same commit so the gain is kept. Raising a budget needs a "Budget raised: <why>" line in the
commit message, which tools/check_commits.py enforces.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import hygiene  # noqa: E402

BUDGET = json.loads((ROOT / "tests" / "hygiene_budget.json").read_text())
NOW = hygiene.measure()


def test_colours_come_only_from_the_tokens():
    assert NOW["colours_outside_tokens"] == [], (
        "Colour values written outside :root in web/index.html:\n  " + "\n  ".join(NOW["colours_outside_tokens"])
        + "\nUse var(--token) for a colour that already has a job (surface, ink, pace, work, warn, wx). "
          "For a new job, add one token to :root with a comment saying what it is used for.")


def test_every_css_class_is_used():
    assert NOW["unused_classes"] == [], (
        "CSS classes nothing uses: " + ", ".join(NOW["unused_classes"])
        + "\nDelete their rules. Dead styles look like live patterns to the next change.")


def test_every_function_is_called():
    assert NOW["unused_functions"] == [], (
        "Functions nothing calls: " + ", ".join(NOW["unused_functions"])
        + "\nDelete them. When you remove a feature, remove its helpers, styles and tests with it.")


def test_no_note_comments():
    assert NOW["note_comments"] == [], (
        "TODO, FIXME, HACK or XXX notes at: " + ", ".join(NOW["note_comments"])
        + "\nDo the work now, or leave it out. A note excusing a shortcut teaches the next change to copy it.")


def test_no_copied_blocks():
    assert len(NOW["duplicate_blocks"]) <= BUDGET["duplicate_blocks"], (
        "Copied code (6 or more matching lines):\n  " + "\n  ".join(NOW["duplicate_blocks"])
        + "\nMove it into one function that both places call, as pickTrains() does for both screens.")


def test_page_stays_small_enough_to_read():
    assert NOW["page_lines"] <= BUDGET["page_lines"], (
        f"web/index.html has {NOW['page_lines']} lines; the limit is {BUDGET['page_lines']}. "
        "Move a self-contained part (styles, a screen, the rules) into its own file instead of raising the limit.")


@pytest.mark.parametrize("key,what,fix", [
    ("longest_function", "lines in the longest function",
     "Split it: move one clear step into its own named function. Longest now: {longest_functions}"),
    ("font_sizes", "different font sizes",
     "Use a size that already exists: {font_sizes}"),
    ("spacings", "different spacing values (padding, margin, gap)",
     "Use a spacing that already exists: {spacings}"),
])
def test_budget_only_goes_down(key, what, fix):
    now = len(NOW[key]) if isinstance(NOW[key], list) else NOW[key]
    hint = fix.format(**{k: v for k, v in NOW.items()})
    assert now <= BUDGET[key], f"{now} {what}; the budget is {BUDGET[key]}. {hint}"
    assert now == BUDGET[key], (
        f"Good: {now} {what}, under the budget of {BUDGET[key]}. "
        f'Lower "{key}" in tests/hygiene_budget.json to {now} so the gain is kept.')
