#!/usr/bin/env python3
"""Where each pause or stop mark's ink lands in its character frame.

CLReq 2.1.2 and appendix A: the pause and stop marks (、，。．；：！？) keep the
direction of a character in vertical writing, so none of them turns. In the
Mainland style they sit in the upper-right corner of their frame; in Taiwan
and Hong Kong they sit in its centre. A CJK face carries that placement in
its vertical forms, so the style is the face's: a Mainland face puts the marks
in the corner, a Taiwan or Hong Kong face centres them. vertext's part is to
leave them alone, never turn them, and not override the face.

One thing measured here and deliberately not asserted: a face that serves
every region does not always switch with the language. Noto Sans CJK SC under
`zh-TW` centres `！` and `？` and still sets `、，。．；：` in the Mainland corner.
Its `locl` covers the one and not the other. Forcing the centre by switching
`vert` off does not help: Chrome then draws the vertical presentation forms,
which sit in the corner whatever the language. A Taiwan page wants a Taiwan
face.

For each mark and each style this sets `口<mark>口` exactly as the binary
renders it, with the shipped stylesheet and a pinned face (Noto Sans SC for
the Mainland, TC for the centred style), at a 96px cell, and screenshots it in
headless Chrome. The frame of the mark is known without asking the page: along
the line it is the second cell from the column's top, and across the line it
is centred on the ink of the `口` beside it, which is drawn centred in its
em square. The mark's ink is then located in that frame, as fractions from
the frame's left and top edges, and checked against its style:

  * Mainland: the ink to the right of centre, and a short mark's ink in the
    upper half (GB/T 15834: below the character it follows, to the right);
  * centred: the ink's centre within 15% of the frame's centre;
  * either: a colon's two dots one above the other (its ink taller than wide),
    since a turned colon lays them side by side.

Run with --report to print every measurement instead of judging it.

Usage
-----
    cargo build --release -p vertext-cli
    python3 tools/punctuation-ink.py [--chrome PATH] [--fonts DIR] [--report]
"""

import argparse
import importlib.util
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
BINARY = ROOT / "target" / "release" / "vertext"
STYLESHEET = ROOT / "extensions" / "vertext" / "vertext.css"


def _load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_bg = _load("browser_golden", "browser-golden.py")
_pg = _load("page_geometry", "page-geometry.py")

CELL = 96
MARKS = "、，。．；：！？"
# (style, lang attribute or None, face)
STYLES = [
    ("mainland", None, "Noto Sans SC"),
    ("mainland", "zh-CN", "Noto Sans CJK SC"),
    ("centred", "zh-TW", "Noto Sans TC"),
    ("centred", "zh-HK", "Noto Sans TC"),
    ("centred", "zh-Hant", "Noto Sans TC"),
]
BOX_W, BOX_H = 3 * CELL, 4 * CELL
TOP = CELL // 2


def column_html(text):
    done = subprocess.run([str(BINARY), "html"], input=text, capture_output=True,
                          text=True, check=True)
    return done.stdout


def build(fonts, extra_css="", hide_marks=False):
    cells = []
    for style, lang, face in STYLES:
        for mark in MARKS:
            cells.append((style, lang, face, mark, column_html(f"口{mark}口")))
    # Relative, so the page loads its faces the same way from file:// for the
    # screenshot and over http for the report of which faces loaded.
    faces = "".join(f'@font-face {{ font-family: "{f}"; src: url("{p.name}"); }}\n'
                    for f, p in fonts.items())
    body = "".join(
        f'<div class="box"{f" lang={lang}" if lang else ""} '
        f'style="font-family: &quot;{face}&quot;">{html}</div>'
        for _, lang, face, _, html in cells)
    page = f"""<!doctype html><meta charset="utf-8">
<style>
{faces}
{STYLESHEET.read_text(encoding="utf-8")}
:root {{ --vertext-cell: {CELL}px; }}
html, body {{ margin: 0; padding: 0; background: #fff; color: #000; }}
body {{ display: grid; grid-template-columns: repeat({len(MARKS)}, {BOX_W}px); }}
.box {{ position: relative; width: {BOX_W}px; height: {BOX_H}px; overflow: hidden; }}
.box .vertext {{ position: absolute; top: {TOP}px; right: 0; padding: 0; border: 0;
                 gap: 0; min-block-size: 0; overflow: visible; }}
{".vertext-column > :nth-child(2) { visibility: hidden; }" if hide_marks else ""}
{extra_css}
</style>
{body}
<script>
document.fonts.ready.then(() => fetch('result', {{ method: 'POST', body: JSON.stringify(
  [...document.fonts].filter(f => f.status === 'loaded').map(f => f.family)) }}));
</script>
"""
    return cells, page


def ink(rows, blank, channels, x0, y0, x1, y1):
    """The bounding box of the pixels that differ between the shot with the
    marks and the shot with them hidden, in [x0, x1) x [y0, y1). Everything
    else on the page is identical in the two, so this is the mark alone."""
    xs, ys = [], []
    for y in range(max(0, y0), min(len(rows), y1)):
        a, b = rows[y], blank[y]
        for x in range(max(0, x0), x1):
            k = x * channels
            if a[k:k + 3] != b[k:k + 3] and min(a[k:k + 3]) < 160:
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    return min(xs), min(ys), max(xs) + 1, max(ys) + 1


def dark(rows, channels, x0, y0, x1, y1):
    """The bounding box of dark pixels, for the reference character."""
    xs = [x for y in range(max(0, y0), min(len(rows), y1))
          for x in range(max(0, x0), x1)
          if min(rows[y][x * channels:x * channels + 3]) < 128]
    if not xs:
        return None
    return min(xs), max(xs) + 1


def measure(rows, blank, channels, index):
    bx, by = (index % len(MARKS)) * BOX_W, (index // len(MARKS)) * BOX_H
    # The first 口 occupies the first cell of the line; its ink fixes the
    # centre of the frames across the line.
    ref = dark(rows, channels, bx, by + TOP, bx + BOX_W, by + TOP + CELL)
    if ref is None:
        return None, "the reference character drew nothing"
    fx0, fy0 = (ref[0] + ref[1]) / 2 - CELL / 2, by + TOP + CELL
    got = ink(rows, blank, channels, bx, by, bx + BOX_W, by + BOX_H)
    if got is None:
        return None, "the mark drew nothing"
    x0, y0, x1, y1 = got
    return {
        "cx": ((x0 + x1) / 2 - fx0) / CELL,
        "cy": ((y0 + y1) / 2 - fy0) / CELL,
        "w": (x1 - x0) / CELL,
        "h": (y1 - y0) / CELL,
    }, None


def judge(style, mark, m):
    fails = []
    # GB/T 15834, which CLReq follows for the Mainland: the marks sit below the
    # character they follow, to the right. A short mark (、，。．) therefore
    # sits in the upper-right quarter of its own frame; a full-height one
    # (；：！？) can only be to the right.
    if style == "mainland" and m["cx"] < 0.6:
        fails.append(f"ink centre at ({m['cx']:.2f}, {m['cy']:.2f}), not to the right")
    if style == "mainland" and m["h"] < 0.5 and m["cy"] >= 0.5:
        fails.append(f"ink centre at ({m['cx']:.2f}, {m['cy']:.2f}), not in the upper half")
    if style == "centred" and not (abs(m["cx"] - 0.5) <= 0.15 and abs(m["cy"] - 0.5) <= 0.15):
        fails.append(f"ink centre at ({m['cx']:.2f}, {m['cy']:.2f}), not at the centre")
    if mark == "：" and not m["h"] > m["w"]:
        fails.append(f"the dots lie side by side ({m['w']:.2f} wide, {m['h']:.2f} tall): "
                     f"the colon turned")
    return fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chrome")
    ap.add_argument("--fonts", default=str(pathlib.Path.home() / ".cache" / "vertext-fonts"))
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--css", default="", help="extra CSS, for experiments")
    args = ap.parse_args()
    if not BINARY.exists():
        sys.exit(f"no binary at {BINARY} -- cargo build --release -p vertext-cli")
    chrome = _bg.find_chrome(args.chrome)
    fonts = _pg.fetch_fonts(pathlib.Path(args.fonts))

    work = pathlib.Path(tempfile.mkdtemp(prefix="vertext-punctuation-"))
    for path in fonts.values():
        shutil.copy(path, work / path.name)
    shots = []
    for hide in (False, True):
        cells, html = build(fonts, args.css, hide)
        page, png = work / f"marks{int(hide)}.html", work / f"marks{int(hide)}.png"
        page.write_text(html, encoding="utf-8")
        _bg.shoot(chrome, page, png, len(MARKS) * BOX_W, len(STYLES) * BOX_H)
        shots.append(_bg.read_png(png))
    (width, height, rows, channels), (_, _, blank, _) = shots

    fails, report = [], []
    # Ink alone cannot tell the pinned faces from any other CJK face that
    # happens to be installed: the marks would land somewhere and be judged.
    # So the same page, served, reports which of its faces actually loaded.
    loaded = _pg._ps.measure(chrome, work, "marks0.html",
                             (len(MARKS) * BOX_W, len(STYLES) * BOX_H))
    for face in dict.fromkeys(face for _, _, face in STYLES):
        if loaded is None or face not in loaded:
            fails.append(f"{face} did not load ({loaded}), so the ink measured is "
                         f"not that face's")
    for i, (style, lang, face, mark, _) in enumerate(cells):
        where = f"{mark} {style} ({lang or 'no lang'}, {face})"
        m, problem = measure(rows, blank, channels, i)
        if problem:
            fails.append(f"{where}: {problem}")
            continue
        report.append(f"{where}: centre ({m['cx']:.2f}, {m['cy']:.2f}), "
                      f"{m['w']:.2f} x {m['h']:.2f} of the frame")
        fails += [f"{where}: {f}" for f in judge(style, mark, m)]
    if args.keep:
        print(f"page and screenshot left in {work}")
    else:
        shutil.rmtree(work, ignore_errors=True)
    if args.report:
        print("\n".join(report))
        return 0
    for f in fails:
        print("FAIL: " + f)
    if fails:
        return 1
    print(f"PASS: none of the {len(MARKS)} pause and stop marks turns, and each sits "
          f"where its style puts it, in {len(STYLES)} language settings")
    return 0


if __name__ == "__main__":
    sys.exit(main())
