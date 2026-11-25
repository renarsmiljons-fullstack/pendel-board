# Working on this repo

This board hangs by a front door and is changed mostly by AI agents. The code is their memory:
they copy what they find. So CI enforces the habits that keep it healthy. These notes say why.

## Every commit

- Run `python -m pytest -q` before you push. It takes about 20 minutes.
- Change structure or behaviour in a commit, never both. A structure-only commit starts with `tidy:`
  and may not touch tests or screenshots. CI checks this with `tools/check_commits.py`.
- Before you write new code, look for code to reuse. Colours come from the tokens in `:root`.
  "Which train is yours" comes from `pickTrains()`.
- When you remove a feature, remove its styles, helpers and tests too.
- `tests/test_garden.py` fails on stray colours, dead code, TODO notes, copied blocks and growing
  budgets. Its message says the fix. Fix the code. Don't raise the budget.

## The garden gate

After 10 code commits, CI blocks everything except a `tidy:` commit that lowers a budget in
`tests/garden_budget.json` or adds a check. `python tools/garden.py report` shows where to look.

## When you are corrected

Turn the correction into a check, so no agent makes the mistake again. A line in this file is the
weakest fix. A test is stronger. Code that makes the mistake impossible is strongest.
