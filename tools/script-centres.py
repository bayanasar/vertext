#!/usr/bin/env python3
"""Where Han, Latin and digits sit across a line, against the Mongolian stem.

MLReq 7.3.2-7.3.4: in a line that mixes scripts, the Han characters' centre
line, and half the text height of Latin and digits, align with the Mongolian
centre line -- the stem the letters of a word hang from. That stem is a line,
not a box edge, so it is found in the pixels: the column of the line where a
Mongolian word has the most ink, since every letter joins along it.

Each line here is laid out by the binary as one strip, set with the shipped
stylesheet, the golden Mongolian face and a pinned CJK face at a 48px cell, in
both progressions. The page colours each script apart (Mongolian red, Han
blue, Latin and digits green), one screenshot is taken, and for each line the
stem and each other script's ink centre are located. Offsets are reported as
a fraction of the cell, positive towards the right of the page, and each must
be within 0.05 of a cell. The stem is not at the centre of a Mongolian run's
box: the stylesheet moves the run by `--vertext-mongolian-stem-shift` to put it
there, and removing that shift puts every line about 0.16 of a cell out.

Usage
-----
    cargo build --release -p vertext-cli
    python3 tools/script-centres.py [--chrome PATH] [--fonts DIR] [--report]
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
MONGOLIAN = ROOT / "goldens" / "fonts" / "NotoSansMongolian-Regular.ttf"


def _load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_bg = _load("browser_golden", "browser-golden.py")
_pg = _load("page_geometry", "page-geometry.py")

CELL = 48
# How far a centre may sit off the stem, as a fraction of the cell: about 2px
# at 48px, which is the stem stroke's own half width in this face.
TOLERANCE = 0.05
BOX_W, BOX_H = 4 * CELL, 16 * CELL
# One line each. The Mongolian words are long enough that the stem is the
# densest column by a wide margin.
LINES = [
    ("rl", "汉字ᠮᠣᠩᠭᠣᠯ汉字"),
    ("rl", "汉字ᠪᠢᠴᠢᠭ汉字"),
    ("lr", "ᠮᠣᠩᠭᠣᠯ汉字ᠪᠢᠴᠢᠭ"),
    ("lr", "ᠮᠣᠩᠭᠣᠯ abc ᠪᠢᠴᠢᠭ"),
    ("lr", "ᠮᠣᠩᠭᠣᠯ 2026 ᠪᠢᠴᠢᠭ"),
    ("rl", "汉字 abc 汉字ᠮᠣᠩᠭᠣᠯ"),
]
COLOURS = {"mongolian": (255, 0, 0), "upright": (0, 0, 255), "latin": (0, 160, 0)}


def strip(text, progression):
    args = [str(BINARY), "html"] + (["--progression", "lr"] if progression == "lr" else [])
    return subprocess.run(args, input=text, capture_output=True, text=True, check=True).stdout


def build(fonts, extra_css=""):
    faces = (f'@font-face {{ font-family: "Noto Sans Mongolian"; src: url("{MONGOLIAN.as_uri()}"); }}\n'
             f'@font-face {{ font-family: "Noto Sans SC"; src: url("{fonts["Noto Sans SC"].as_uri()}"); }}\n')
    colours = "".join(f".vertext-{k} {{ color: rgb{v}; }}\n" for k, v in COLOURS.items())
    body = "".join(f'<div class="box">{strip(text, p)}</div>' for p, text in LINES)
    return f"""<!doctype html><meta charset="utf-8">
<style>
{faces}
{STYLESHEET.read_text(encoding="utf-8")}
:root {{ --vertext-cell: {CELL}px; }}
html, body {{ margin: 0; padding: 0; background: #fff; font-family: "Noto Sans SC"; }}
body {{ display: grid; grid-template-columns: repeat({len(LINES)}, {BOX_W}px); }}
.box {{ position: relative; width: {BOX_W}px; height: {BOX_H}px; overflow: hidden; }}
.box .vertext {{ position: absolute; top: 0; left: 0; right: 0; padding: 0; border: 0;
                 justify-content: center; min-block-size: 0; overflow: visible; }}
{colours}
{extra_css}
</style>
{body}
"""


def near(pixel, colour):
    return all(abs(a - b) < 90 for a, b in zip(pixel, colour)) and pixel != (255, 255, 255)


def locate(rows, channels, index):
    """(stem x, {script: ink centre x}) in one line's box, page pixels."""
    x0 = index * BOX_W
    counts = {k: {} for k in COLOURS}
    for y in range(min(BOX_H, len(rows))):
        line = rows[y]
        for x in range(x0, x0 + BOX_W):
            p = tuple(line[x * channels:x * channels + 3])
            if min(p) > 200:
                continue
            for k, c in COLOURS.items():
                if near(p, c):
                    counts[k][x] = counts[k].get(x, 0) + 1
    if not counts["mongolian"]:
        return None, {}
    # The stem is a stroke with a width: take the run of columns around the
    # densest one that keep at least 80% of its ink, and its centre.
    red = counts["mongolian"]
    peak = max(red, key=red.get)
    lo = hi = peak
    while red.get(lo - 1, 0) >= 0.8 * red[peak]:
        lo -= 1
    while red.get(hi + 1, 0) >= 0.8 * red[peak]:
        hi += 1
    centres = {k: (min(v) + max(v) + 1) / 2 for k, v in counts.items() if v and k != "mongolian"}
    return (lo + hi + 1) / 2, centres


def main():
    global CELL, BOX_W, BOX_H
    ap = argparse.ArgumentParser()
    ap.add_argument("--chrome")
    ap.add_argument("--fonts", default=str(pathlib.Path.home() / ".cache" / "vertext-fonts"))
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--cell", type=int, default=CELL)
    ap.add_argument("--css", default="", help="extra CSS, for experiments")
    args = ap.parse_args()
    CELL, BOX_W, BOX_H = args.cell, 4 * args.cell, 16 * args.cell
    if not BINARY.exists():
        sys.exit(f"no binary at {BINARY} -- cargo build --release -p vertext-cli")
    chrome = _bg.find_chrome(args.chrome)
    fonts = _pg.fetch_fonts(pathlib.Path(args.fonts))
    work = pathlib.Path(tempfile.mkdtemp(prefix="vertext-centres-"))
    page, png = work / "centres.html", work / "centres.png"
    page.write_text(build(fonts, args.css), encoding="utf-8")
    _bg.shoot(chrome, page, png, len(LINES) * BOX_W, BOX_H)
    _, _, rows, channels = _bg.read_png(png)
    fails, report = [], []
    for i, (progression, text) in enumerate(LINES):
        stem, centres = locate(rows, channels, i)
        if stem is None or not centres:
            fails.append(f"{progression} {text}: a script drew no ink")
            continue
        parts = ", ".join(f"{k} {(c - stem) / CELL:+.2f}" for k, c in centres.items())
        report.append(f"{progression} {text}: {parts}")
        for k, c in centres.items():
            if abs(c - stem) / CELL > TOLERANCE:
                fails.append(f"{progression} {text}: the {k} centre is {(c - stem) / CELL:+.2f} "
                             f"of a cell off the Mongolian stem")
    if args.keep:
        print(f"left in {work}")
    else:
        shutil.rmtree(work, ignore_errors=True)
    if args.report:
        print("\n".join(report))
        return 0
    for f in fails:
        print("FAIL: " + f)
    if fails:
        return 1
    print(f"PASS: in {len(LINES)} mixed lines, both progressions, the Han and Latin centres "
          f"sit within {TOLERANCE} of a {CELL}px cell of the Mongolian stem")
    for line in report:
        print("      " + line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
