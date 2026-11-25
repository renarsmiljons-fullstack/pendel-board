"""No text on the board may be cut off.

The Pi renders with DejaVu Sans, which is wider than Inter, and real dates and sun times are longer
than the ones in the fixtures. So each check uses the Pi's font, the panel sizes, and the longest
weekday and month names.
"""
from __future__ import annotations

import pytest

from test_home import BASE, t, wx

SIZES = {"panel": {"width": 1067, "height": 600}, "landscape": {"width": 1024, "height": 600}}

# Every element that holds text must sit inside the screen and inside every box that contains it:
# its section, a panel that hides overflow, or anything else that clips.
CLIPPED = r"""() => {
  const W = innerWidth, bad = [];
  for (const el of document.querySelectorAll('body *')) {
    if (!el.getClientRects().length) continue;
    if (![...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())) continue;
    const range = document.createRange(); range.selectNodeContents(el);
    const r = range.getBoundingClientRect();
    if (!r.width) continue;
    const what = (el.id ? '#' + el.id : el.tagName.toLowerCase() + '.' + [...el.classList].join('.'))
      + ' "' + el.textContent.trim().slice(0, 40) + '"';
    if (r.left < -1 || r.right > W + 1) { bad.push(what + ' leaves the screen'); continue; }
    for (let a = el.parentElement; a && a !== document.body; a = a.parentElement) {
      const s = getComputedStyle(a);
      if (a.tagName !== 'SECTION' && s.overflowX === 'visible') continue;
      const b = a.getBoundingClientRect();
      if (r.left < b.left - 1 || r.right > b.right + 1) {
        bad.push(what + ' sticks out of ' + (a.id ? '#' + a.id : a.tagName.toLowerCase() + '.' + a.className));
        break;
      }
    }
  }
  return bad;
}"""

LONGEST = """() => {
  DAYS.fill('Wednesday'); MONTHS.fill('September');
  document.body.style.fontFamily = 'DejaVu Sans'; render(); fitClock();
}"""


@pytest.mark.parametrize("size", SIZES)
@pytest.mark.parametrize("view,at,weather", [
    ("home", "05:50", "kallhall_dry"),   # before sunrise: "Sunrise 08:03"
    ("home", "20:08", "kallhall_dry"),   # after sunset: "Sunrise 08:05 tomorrow", the longest sun line
    ("home", "05:50", "bergen_rain"),
    ("home", "05:50", "kiruna_snow"),
    ("home", "05:50", None),             # weather down
    ("trains", "05:50", "kallhall_dry"),
    ("trains", "06:30", "bergen_rain"),
])
def test_no_text_is_cut_off_in_the_pis_font(open_board, size, view, at, weather):
    board = open_board(BASE, t(at), view=view, orientation="landscape", weather=wx(weather, sun=True) if weather else None)
    board.page.set_viewport_size(SIZES[size])
    board.page.evaluate(LONGEST)
    board.page.wait_for_timeout(200)
    bad = board.page.evaluate(CLIPPED)
    assert not bad, "Cut-off text. Make it fit its box at this size in DejaVu Sans:\n" + "\n".join(bad)
