#!/usr/bin/env python3
"""Where Mongolian, Han, Latin and digits sit across a line.

MLReq 7.3.1: Mongolian is aligned to a baseline that runs down the centre of
the writing. 7.3.2-7.3.4: in a line that mixes scripts, the Han characters'
centre line, and half the text height of Latin and digits, align with that
Mongolian centre line -- the stem the letters of a word hang from. That stem is
a line, not a box edge, so it is found in the pixels: the column of the line
where a Mongolian word has the most ink, since every letter joins along it.

Each line here is laid out by the binary as one strip and set the way it
ships: the stylesheet and the Mongolian face from extensions/vertext, copied
side by side as Quarto copies them, plus a pinned CJK face, in both
progressions and at two cells. The page colours each script apart (Mongolian
red, Han blue, Latin and digits green) and one screenshot is taken. The same
page, served, reports which faces loaded and where each line's box is, so a
fallback face cannot pass for the shipped one. For each line:

  * the stem sits on the centre of the line's box (7.3.1);
  * the ink centre of every other script sits on the stem (7.3.2-7.3.4);
  * every script the line was written with drew ink, so a script that
    silently stops drawing cannot leave the line passing on the others.

Offsets are a fraction of the cell, positive towards the right of the page,
and each must be within 0.05 of a cell. The stem is not at the centre of a
Mongolian run's box: the stylesheet moves the run by
`--vertext-mongolian-stem-shift` to put it there, and removing that shift puts
every line about 0.16 of a cell out.

Usage
-----
    cargo build --release -p vertext-cli
    python3 tools/script-centres.py [--chrome PATH] [--fonts DIR] [--cell N ...] [--report]
"""

import argparse
import importlib.util
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
BINARY = ROOT / "target" / "release" / "vertext"
SHIPPED = ROOT / "extensions" / "vertext"
SHIPPED_FILES = ["vertext.css", "NotoSansMongolian-Regular.ttf"]
SHIPPED_FACE = "Vertext Noto Sans Mongolian"


def _load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_bg = _load("browser_golden", "browser-golden.py")
_pg = _load("page_geometry", "page-geometry.py")

# At 48px the tolerance is about 2px, the stem stroke's own half width in this
# face. At 24px it is a little over a pixel, so that cell is a check on the
# shift's scaling as much as on the face.
CELLS = (48, 24)
TOLERANCE = 0.05
# One line each, and the scripts besides Mongolian it must show. The Mongolian
# words are long enough that the stem is the densest column by a wide margin.
LINES = [
    ("rl", "汉字ᠮᠣᠩᠭᠣᠯ汉字", {"upright"}),
    ("rl", "汉字ᠪᠢᠴᠢᠭ汉字", {"upright"}),
    ("lr", "ᠮᠣᠩᠭᠣᠯ汉字ᠪᠢᠴᠢᠭ", {"upright"}),
    ("lr", "ᠮᠣᠩᠭᠣᠯ abc ᠪᠢᠴᠢᠭ", {"latin"}),
    ("lr", "ᠮᠣᠩᠭᠣᠯ 2026 ᠪᠢᠴᠢᠭ", {"latin"}),
    ("rl", "汉字 abc 汉字ᠮᠣᠩᠭᠣᠯ", {"upright", "latin"}),
    ("rl", "汉字 2026 汉字ᠮᠣᠩᠭᠣᠯ", {"upright", "latin"}),
    ("rl", "ᠮᠣᠩᠭᠣᠯ ᠪᠢᠴᠢᠭ", set()),
    ("lr", "ᠮᠣᠩᠭᠣᠯ ᠪᠢᠴᠢᠭ", set()),
]
COLOURS = {"mongolian": (255, 0, 0), "upright": (0, 0, 255), "latin": (0, 160, 0)}

# The page stays black until this load has the shipped face and the CJK one,
# so a screenshot taken in any other face has no stem to find.
REPORT = """<div id="unproven"></div>
<script>
document.fonts.ready.then(() => {
  const fonts = [...document.fonts].map(f => [f.family, f.status]);
  const loaded = fonts.filter(([, status]) => status === 'loaded').map(([family]) => family);
  if (FACES.every(f => loaded.includes(f))) {
    document.getElementById('unproven').remove();
  }
  fetch('result', { method: 'POST', body: JSON.stringify({
    fonts,
    lines: [...document.querySelectorAll('.box')].map(b => {
      const c = b.querySelector('.vertext-column');
      if (!c) return null;
      const r = c.getBoundingClientRect();
      return (r.left + r.right) / 2;
    }),
  }) });
});
</script>""".replace("FACES", json.dumps([SHIPPED_FACE, "Noto Sans SC"]))


def strip(text, progression):
    args = [str(BINARY), "html"] + (["--progression", "lr"] if progression == "lr" else [])
    return subprocess.run(args, input=text, capture_output=True, text=True, check=True).stdout


def build(cell, cjk, extra_css=""):
    box_w, box_h = 4 * cell, 16 * cell
    colours = "".join(f".vertext-{k} {{ color: rgb{v}; }}\n" for k, v in COLOURS.items())
    body = "".join(f'<div class="box">{strip(text, p)}</div>' for p, text, _ in LINES)
    return f"""<!doctype html><meta charset="utf-8">
<link rel="stylesheet" href="vertext.css">
<style>
@font-face {{ font-family: "Noto Sans SC"; src: url("{cjk.name}"); }}
:root {{ --vertext-cell: {cell}px; }}
html, body {{ margin: 0; padding: 0; background: #fff; font-family: "Noto Sans SC"; }}
body {{ display: grid; grid-template-columns: repeat({len(LINES)}, {box_w}px); }}
.box {{ position: relative; width: {box_w}px; height: {box_h}px; overflow: hidden; }}
.box .vertext {{ position: absolute; top: 0; left: 0; right: 0; padding: 0; border: 0;
                 justify-content: center; min-block-size: 0; overflow: visible; }}
#unproven {{ position: fixed; inset: 0; background: #000; }}
{colours}
{extra_css}
</style>
{body}
{REPORT}
"""


def near(pixel, colour):
    return all(abs(a - b) < 90 for a, b in zip(pixel, colour)) and pixel != (255, 255, 255)


def locate(rows, channels, index, box_w, box_h):
    """(stem x, {script: ink centre x}) in one line's box, page pixels."""
    x0 = index * box_w
    counts = {k: {} for k in COLOURS}
    for y in range(min(box_h, len(rows))):
        line = rows[y]
        for x in range(x0, x0 + box_w):
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


def run(chrome, cjk, cell, work, extra_css):
    """Fails and report lines for every line at one cell."""
    box_w, box_h = 4 * cell, 16 * cell
    page, png = work / f"centres-{cell}.html", work / f"centres-{cell}.png"
    page.write_text(build(cell, cjk, extra_css), encoding="utf-8")
    served = _pg._ps.measure(chrome, work, page.name, (len(LINES) * box_w, box_h))
    if served is None:
        return [f"{cell}px: the page reported nothing within 120s"], []
    loaded = {family for family, status in served["fonts"] if status == "loaded"}
    if SHIPPED_FACE not in loaded:
        return [f"{cell}px: the shipped face, {SHIPPED_FACE}, did not load "
                f"({served['fonts']}), so the stems measured are another face's"], []
    with _bg.serve(work) as base:
        _bg.shoot(chrome, f"{base}/{page.name}", png, len(LINES) * box_w, box_h)
    _, _, rows, channels = _bg.read_png(png)
    if min(rows[0][:3]) < 200:
        return [f"{cell}px: the screenshot was taken before its faces loaded, "
                f"or without them"], []
    fails, report = [], []
    for i, (progression, text, scripts) in enumerate(LINES):
        where = f"{cell}px {progression} {text}"
        stem, centres = locate(rows, channels, i, box_w, box_h)
        if stem is None:
            fails.append(f"{where}: the Mongolian drew no ink")
            continue
        missing = sorted(scripts - set(centres))
        if missing:
            fails.append(f"{where}: {', '.join(missing)} drew no ink")
        centres["line"] = served["lines"][i]
        parts = ", ".join(f"{k} {(c - stem) / cell:+.2f}" for k, c in centres.items())
        report.append(f"{where}: {parts}")
        for k, c in centres.items():
            if abs(c - stem) / cell > TOLERANCE:
                against = "the line's centre" if k == "line" else f"the {k} centre"
                fails.append(f"{where}: {against} is {(c - stem) / cell:+.2f} "
                             f"of a cell off the Mongolian stem")
    return fails, report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chrome")
    ap.add_argument("--fonts", default=str(pathlib.Path.home() / ".cache" / "vertext-fonts"))
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--cell", type=int, action="append", help="a cell in px; repeatable")
    ap.add_argument("--css", default="", help="extra CSS, for experiments")
    args = ap.parse_args()
    if not BINARY.exists():
        sys.exit(f"no binary at {BINARY} -- cargo build --release -p vertext-cli")
    chrome = _bg.find_chrome(args.chrome)
    cjk = _pg.fetch_fonts(pathlib.Path(args.fonts))["Noto Sans SC"]
    work = pathlib.Path(tempfile.mkdtemp(prefix="vertext-centres-"))
    for name in SHIPPED_FILES:
        shutil.copy(SHIPPED / name, work / name)
    shutil.copy(cjk, work / cjk.name)
    fails, report = [], []
    cells = args.cell or CELLS
    for cell in cells:
        f, r = run(chrome, cjk, cell, work, args.css)
        fails += f
        report += r
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
    print(f"PASS: in {len(LINES)} lines, both progressions, at "
          f"{' and '.join(f'{c}px' for c in cells)} cells in the shipped face, the "
          f"Mongolian stem sits on the line's centre and the Han and Latin centres "
          f"on the stem, within {TOLERANCE} of a cell")
    for line in report:
        print("      " + line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
