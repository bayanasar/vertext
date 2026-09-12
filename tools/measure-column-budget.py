#!/usr/bin/env python3
"""Measure what column length each mode actually gives, in a real browser.

Not a gate. Issue #26 asks for a measurement before anyone changes the number,
because changing it moves every page already rendered — kele's pixel seal
included — and the current `34em` has no provenance: it was written down and
never touched, not measured and not taken from a standard.

What differs between the modes is one declaration, and both live in the filter
rather than in vertext.css:

    document   --vertext-column-height: var(--vertext-column-theme-height,
                                            calc(100vh - 12rem))
    page       --vertext-column-height: var(--vertext-column-theme-height, 34em)

`vertext.css` then spends it as `.vertext-column { height: … }`, so in vertical
writing this is the length of a line: it decides at which character a sentence
turns the column, which is the rhythm a reader's eye moves in. This script
renders the same source through the real binary in both modes, at several
viewport sizes, and reports the resolved length and how many characters fit.

Usage
-----
    cargo build --release -p vertext-cli
    python3 tools/measure-column-budget.py
    python3 tools/measure-column-budget.py --viewport 1280x800

Needs a Chrome; searches ~/.cache/puppeteer, or pass --chrome.
"""

import argparse
import json
import pathlib
import re
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
BINARY = ROOT / "target" / "release" / "vertext"
FILTER = ROOT / "extensions" / "vertext" / "vertext.lua"
STYLESHEET = ROOT / "extensions" / "vertext" / "vertext.css"

# Sizes worth reporting rather than a sweep: a laptop, a desktop, a tall window
# and a portrait tablet. The question is whether the length tracks the window at
# all, and four points answer it.
VIEWPORTS = [(1280, 800), (1920, 1080), (1280, 2000), (768, 1024)]

# One sample, fixed here so two runs are comparable. The first line is the
# golden the README already uses; the rest gives the columns something long
# enough to turn.
SAMPLE = (
    "山川异域，风月同天。寄诸佛子，共结来缘。\n\n"
    "ᠮᠣᠩᠭᠣᠯ ᠤᠨ ᠲᠡᠦᠬᠡ ᠶᠢ ᠪᠢᠴᠢᠭᠰᠡᠨ ᠨᠣᠮ\n\n"
    "垂直排版的行長不是美學偏好，而是閱讀的節奏：它決定一句話在第幾個字轉欄，"
    "也就決定了讀者的眼睛多久往旁邊跳一次。橫排裏這個量由行寬承擔，直排裏由欄高承擔。"
)


# A second, deliberately boring input, for the "how many characters fit" half.
# The sample above cannot answer it: its punctuation is rotated into its own
# spans, which sit at a different physical x, so grouping characters by column
# position fragments on every comma. One repeated upright ideograph has no such
# seams, and 400 of them are longer than any column measured here.
PROBE = "垂" * 400


def find_chrome(given):
    if given:
        return pathlib.Path(given)
    found = sorted((pathlib.Path.home() / ".cache" / "puppeteer")
                   .glob("chrome/*/chrome-linux64/chrome"))
    if not found:
        sys.exit("no chrome found -- pass --chrome")
    return found[-1]


def mode_style(mode):
    """The mode's stylesheet, taken out of the filter by its id.

    Same source as examples/test-column-budget.js reads, and for the same
    reason: these two declarations do not exist anywhere else, so a measurement
    that invented them would be measuring a fixture.
    """
    lua = FILTER.read_text(encoding="utf-8")
    found = re.search(r'<style id="vertext-%s-mode">([\s\S]*?)</style>' % mode, lua)
    if not found:
        sys.exit(f"no <style id=\"vertext-{mode}-mode\"> in the filter")
    return found.group(1)


# Counting `textContent.length` per column measures how the SOURCE was
# chunked, not how the page reads: one `.vertext-column` holds a whole strip
# and the browser wraps inside it. What issue #26 asks for is how many
# characters fit before the text turns, so walk the characters with a Range
# and group them by their position on the block axis -- in vertical writing a
# wrap moves the glyph sideways, so a change in `x` IS the turn.
MEASURE = """
function visualLines(el) {
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  const groups = [];
  let node;
  while ((node = walker.nextNode())) {
    for (let i = 0; i < node.length; i++) {
      if (/\\s/.test(node.data[i])) continue;
      const range = document.createRange();
      range.setStart(node, i);
      range.setEnd(node, i + 1);
      const rect = range.getBoundingClientRect();
      if (!rect.width && !rect.height) continue;
      const key = Math.round(rect.x);
      const last = groups[groups.length - 1];
      if (last && last.key === key) last.count++;
      else groups.push({ key, count: 1 });
    }
  }
  return groups;
}
const columns = [...document.querySelectorAll('.vertext-column')];
const style = getComputedStyle(document.body);
const perColumn = columns.map(visualLines);
const out = {
  declared: style.getPropertyValue('--vertext-column-height').trim(),
  rootFontSize: parseFloat(getComputedStyle(document.documentElement).fontSize),
  bodyFontSize: parseFloat(style.fontSize),
  viewport: [window.innerWidth, window.innerHeight],
  columns: columns.length,
  heights: columns.map(c => Math.round(c.getBoundingClientRect().height * 10) / 10),
  // The longest run of characters that sat at one block-axis position, i.e.
  // the fullest visual column on the page, and how many turns happened.
  longestLine: Math.max(0, ...perColumn.flat().map(g => g.count)),
  visualLines: perColumn.reduce((n, g) => n + g.length, 0),
};
document.body.setAttribute('data-measured', JSON.stringify(out));
"""


def measure(chrome, mode, html, width, height, work, tag="sample"):
    page = work / f"{mode}-{tag}-{width}x{height}.html"
    page.write_text(f"""<meta charset="utf-8">
<style>
{STYLESHEET.read_text(encoding="utf-8")}
</style>
<style>
{mode_style(mode)}
</style>
{html}
<script>{MEASURE}</script>
""", encoding="utf-8")
    done = subprocess.run(
        [str(chrome), "--headless", "--disable-gpu", "--no-sandbox",
         "--force-device-scale-factor=1", "--hide-scrollbars",
         f"--window-size={width},{height}", "--dump-dom", page.as_uri()],
        capture_output=True, text=True, timeout=180)
    found = re.search(r'data-measured="([^"]*)"', done.stdout)
    if not found:
        raise SystemExit(f"no measurement came back for {mode} {width}x{height}:\n"
                         f"{done.stderr[-1500:]}")
    import html as htmllib
    return json.loads(htmllib.unescape(found.group(1)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chrome")
    ap.add_argument("--binary", default=str(BINARY))
    ap.add_argument("--viewport", action="append",
                    help="WIDTHxHEIGHT, repeatable; replaces the default set")
    args = ap.parse_args()

    chrome = find_chrome(args.chrome)
    binary = pathlib.Path(args.binary)
    if not binary.exists():
        sys.exit(f"no binary at {binary} -- cargo build --release -p vertext-cli")

    viewports = VIEWPORTS
    if args.viewport:
        viewports = [tuple(int(n) for n in v.lower().split("x")) for v in args.viewport]

    rendered, probes = {}, {}
    for mode, flags in (("document", []), ("page", ["--page"])):
        for label, text, into in (("sample", SAMPLE, rendered),
                                  ("probe", PROBE, probes)):
            done = subprocess.run([str(binary), *flags], input=text,
                                  capture_output=True, text=True)
            if done.returncode != 0:
                sys.exit(f"binary failed in {mode} mode on the {label}: "
                         f"{done.stderr.strip()}")
            into[mode] = done.stdout

    work = pathlib.Path(tempfile.mkdtemp(prefix="vertext-measure-"))
    print(f"{'viewport':>11}  {'inner h':>7}  {'mode':<9} {'declared':<32} "
          f"{'column px':>9} {'chars/col':>10} {'px/char':>8}")
    print("-" * 93)
    rows = []
    for width, height in viewports:
        for mode in ("document", "page"):
            m = measure(chrome, mode, rendered[mode], width, height, work)
            p = measure(chrome, mode, probes[mode], width, height, work,
                        tag="probe")
            longest = max(m["heights"]) if m["heights"] else 0
            fits = p["longestLine"]
            rows.append((width, height, mode, longest, fits))
            print(f"{width}x{height:<5}  {m['viewport'][1]:>7}  {mode:<9} "
                  f"{m['declared'][:31]:<32} {longest:>9} "
                  f"{fits:>10} {round(longest / fits, 1) if fits else 0:>8}")

    doc = {(w, h): px for w, h, mode, px, _ in rows if mode == "document"}
    page = {(w, h): px for w, h, mode, px, _ in rows if mode == "page"}
    print()
    print(f"document mode spans {min(doc.values())}px to {max(doc.values())}px "
          f"across these {len(doc)} windows.")
    print(f"page mode is {'constant at %spx' % next(iter(set(page.values()))) if len(set(page.values())) == 1 else 'NOT constant: %s' % sorted(set(page.values()))}"
          f" — it owns the whole viewport and ignores it.")
    print(f"      pages left in {work}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
