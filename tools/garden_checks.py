"""Garden checks: measures how tidy the board's code is.

tests/test_garden.py compares these numbers with tests/garden_budget.json on every commit,
and tools/garden.py prints them as the gardening list. Run `python tools/garden_checks.py` to see them.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "web" / "index.html"
CODE_DIRS = ("web", "pi", "tools")


def page_parts(text: str | None = None) -> dict:
    s = text if text is not None else PAGE.read_text()
    css = s[s.index("<style>") + 7: s.index("</style>")]
    root_end = css.index("}", css.index(":root")) + 1
    return {"all": s, "css": css, "root": css[:root_end], "css_rules": css[root_end:],
            "markup": s[s.index("</style>"): s.index("<script>")],
            "js": s[s.index("<script>") + 8: s.index("</script>")]}


def strip_comments(code: str) -> str:
    code = re.sub(r"/\*.*?\*/", "", code, flags=re.S)
    return re.sub(r"(?<![:\\'\"])//[^\n]*", "", code)


def colours_outside_tokens(p: dict) -> list[str]:
    """Colour values written anywhere except the :root token list."""
    pattern = r"#[0-9a-fA-F]{3,8}\b|\b(?:rgb|rgba|hsl|hsla)\("
    found = []
    for name in ("css_rules", "markup", "js"):
        for m in re.finditer(pattern, strip_comments(p[name])):
            if name == "markup" and m.group().startswith("#") and not re.search(r"[0-9]", m.group()):
                continue  # an id like "#band" inside markup text, not a colour
            found.append(f"{m.group()} in the page's {name.replace('_rules', '')}")
    return found


def css_classes(p: dict) -> set[str]:
    css = re.sub(r"\{[^{}]*\}", "{}", strip_comments(p["css_rules"]))  # selectors only
    css = re.sub(r"@media[^{]*\{", "", css)
    return set(re.findall(r"\.([a-zA-Z][\w-]*)", css))


def unused_classes(p: dict) -> list[str]:
    """CSS classes that no markup, script or test ever uses."""
    users = p["markup"] + p["js"] + "".join(f.read_text() for f in (ROOT / "tests").glob("*.py"))
    return sorted(c for c in css_classes(p) if not re.search(r"(?<![\w-])" + re.escape(c) + r"(?![\w-])", users))


def functions(js: str) -> dict[str, int]:
    """Named functions in the page's script and their length in lines."""
    out = {}
    for m in re.finditer(r"^\s*(?:async\s+)?function\s+(\w+)\s*\(", js, flags=re.M):
        depth, i = 0, js.index("{", m.end())
        start_line = js.count("\n", 0, m.start())
        while True:
            c = js[i]
            depth += c == "{"
            depth -= c == "}"
            if depth == 0:
                break
            i += 1
        out[m.group(1)] = js.count("\n", 0, i) - start_line + 1
    return out


def unused_functions(p: dict) -> list[str]:
    js = strip_comments(p["js"])
    tests = "".join(f.read_text() for f in (ROOT / "tests").glob("*.py"))
    return sorted(name for name in functions(js)
                  if len(re.findall(r"\b" + name + r"\b", js)) < 2 and not re.search(r"\b" + name + r"\b", tests))


def note_comments() -> list[str]:
    """TODO, FIXME, HACK and XXX notes. A note is a promise nobody keeps; fix it or leave it out."""
    found = []
    for d in CODE_DIRS:
        for f in (ROOT / d).rglob("*"):
            if f.is_file() and f.suffix in (".html", ".py", ".sh", ".js", ".css") and f != Path(__file__).resolve():
                for n, line in enumerate(f.read_text().splitlines(), 1):
                    if re.search(r"\b(TODO|FIXME|HACK|XXX)\b", line):
                        found.append(f"{f.relative_to(ROOT)}:{n}")
    return found


def font_sizes(p: dict) -> list[str]:
    return sorted(set(re.findall(r"font-size:\s*([\d.]+px)", p["css_rules"] + p["js"])), key=lambda v: float(v[:-2]))


def spacings(p: dict) -> list[str]:
    values = set()
    for m in re.finditer(r"(?:padding|margin|gap)[\w-]*:\s*([^;}]+)", p["css_rules"]):
        values.update(re.findall(r"(?<![\w.-])(\d+(?:\.\d+)?)px", m.group(1)))
    return sorted(values, key=float)


def duplicate_blocks(window: int = 6) -> list[str]:
    """Runs of 6 or more matching code lines found in two places, across web/, pi/ and tools/."""
    seen: dict[tuple, list[str]] = defaultdict(list)
    for d in CODE_DIRS:
        for f in (ROOT / d).rglob("*"):
            if not f.is_file() or f.suffix not in (".html", ".py", ".sh", ".js"):
                continue
            lines = [(n, re.sub(r"\s+", " ", l).strip()) for n, l in enumerate(f.read_text().splitlines(), 1)]
            lines = [(n, l) for n, l in lines if len(l) > 3 and l not in ("}", "});", "};", ")", "]", "fi", "done")]
            for i in range(len(lines) - window + 1):
                chunk = tuple(l for _, l in lines[i:i + window])
                seen[chunk].append(f"{f.relative_to(ROOT)}:{lines[i][0]}")
    places = sorted({tuple(v) for v in seen.values() if len(v) > 1})
    merged, last = [], None
    for p in places:  # overlapping windows of one copied block count once
        if last and all(_near(a, b) for a, b in zip(p, last)):
            last = p
            continue
        merged.append(" and ".join(p))
        last = p
    return merged


def _near(a: str, b: str) -> bool:
    fa, la = a.rsplit(":", 1)
    fb, lb = b.rsplit(":", 1)
    return fa == fb and abs(int(la) - int(lb)) <= 6


def measure(text: str | None = None) -> dict:
    p = page_parts(text)
    fns = functions(strip_comments(p["js"]))
    return {
        "colours_outside_tokens": colours_outside_tokens(p),
        "unused_classes": unused_classes(p),
        "unused_functions": unused_functions(p),
        "note_comments": note_comments(),
        "page_lines": p["all"].count("\n") + 1,
        "longest_function": max(fns.values()),
        "longest_functions": Counter(fns).most_common(5),
        "font_sizes": font_sizes(p),
        "spacings": spacings(p),
        "duplicate_blocks": duplicate_blocks(),
    }


if __name__ == "__main__":
    json.dump(measure(), sys.stdout, indent=2)
    print()
