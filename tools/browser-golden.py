#!/usr/bin/env python3
"""The browser golden: does a real browser actually join what we deliver?

Why this is a third gate
------------------------
`tools/shaping-golden.py` proves the FONT joins, by shaping strings with
HarfBuzz directly. `tools/delivery-golden.py` proves the ENGINE hands the font
a whole word, by taking the text back out of the binary's HTML. Neither has
ever asked a browser to draw anything, and a browser is what readers use.

The obvious rig does not work, and the reason is worth stating so nobody builds
it twice. Measuring geometry cannot tell joined from isolated with this font:
every letter of Noto Sans Mongolian carries the same vertical advance in every
positional form, so across all 168 runs in the golden the joined advance sum
equals the per-character isolated sum, and the only advances the golden holds
are 0 and 1000. A height measurement is identical whether the browser joined
anything or not.

So this gate compares INK. Each run is rendered twice through the real
stylesheet and the real binary output: once normally, and once with
`font-feature-settings: "init" 0, "medi" 0, "fina" 0` — the browser-side form of
the `--prove` the other two gates run on every build, because those three
features ARE joining. Then the two screenshots are compared cell by cell.

  a run of two or more letters MUST differ    -- the browser joined it
  a run of exactly one letter MUST NOT differ -- the rig is discriminating,
                                                 not merely noisy

Thirteen of the corpus runs are a single letter, which is what makes the second
assertion free. A rig that reports a difference everywhere proves nothing.

LETTERS, counted by `_sg.letters()`, not codepoints. A run is lifted from the
lessons with whatever rides along inside it -- sentence punctuation, the vowel
separator, a variation selector -- and none of those takes a positional form.
Counting codepoints would file a one-letter run under "must change", and it
would not change, and this gate would blame the browser for it.

No --prove here, and that is deliberate
---------------------------------------
The other two gates carry one because they compare against RECORDED
expectations: if the recording were wrong, or the comparison stopped happening,
every run would still be green, so they re-establish on every build that they
can still go red. This gate is a differential experiment — it compares two
renders of the same page taken minutes apart — and its negative control runs
every time: the single-letter runs that MUST NOT change are the proof that the
rig discriminates. Adding a `--prove` would be adding a second copy of an
assertion this gate already makes on every run. (urtu, reviewing #31.)

What it does not prove
----------------------
That the shapes are the right ones for a reader. This gate says the browser
applied contextual forms to what we delivered; the shaping golden says those
forms are the ones the font intends. Whether a page reads as writing rather
than as marks in the right places is layer 3 of #7, and it is a person.

Usage
-----
    cargo build --release -p vertext-cli
    python3 tools/browser-golden.py
    python3 tools/browser-golden.py --keep   # leave the pages and PNGs behind

Needs a Chrome. Point --chrome at it, or let it search ~/.cache/puppeteer.
No Python packages: the PNG is decoded with zlib from the standard library.
"""

import argparse
import importlib.util
import json
import pathlib
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
BINARY = ROOT / "target" / "release" / "vertext"
STYLESHEET = ROOT / "extensions" / "vertext" / "vertext.css"

_spec = importlib.util.spec_from_file_location(
    "shaping_golden", ROOT / "tools" / "shaping-golden.py")
_sg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_sg)

# Cells are fixed so that one clipped run cannot shift every cell after it and
# report the whole grid as different. The longest corpus run is 11 characters.
FONT_PX = 32
CELL_W, CELL_H = 72, 480
COLUMNS = 24

# Disabling these three features IS a non-joining font, which is exactly what
# tools/shaping-golden.py --prove relies on. Same lever, applied in the browser.
JOINING_OFF = 'font-feature-settings: "init" 0, "medi" 0, "fina" 0;'


def find_chrome(given):
    if given:
        return pathlib.Path(given)
    cache = pathlib.Path.home() / ".cache" / "puppeteer"
    found = sorted(cache.glob("chrome/*/chrome-linux64/chrome"))
    if not found:
        sys.exit("no chrome found -- npx @puppeteer/browsers install chrome@stable, "
                 "or pass --chrome")
    return found[-1]


def version(chrome):
    """What the browser says it is.

    Asked rather than inferred from the path: under ~/.cache/puppeteer the
    version is the grandparent directory, and an unzipped chrome-for-testing in
    /tmp makes that same expression print "tmp". This line is part of the
    evidence the gate leaves behind, so it should come from the binary.
    """
    done = subprocess.run([str(chrome), "--version"], capture_output=True,
                          text=True)
    return done.stdout.strip() or f"{chrome} (no --version)"


def read_png(path):
    """(width, height, rows) for an 8-bit RGB/RGBA PNG. Enough for a screenshot."""
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path} is not a PNG")
    pos, idat, width = 8, [], None
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        if kind == b"IHDR":
            width, height, depth, colour = struct.unpack(">IIBB", body[:10])
            if depth != 8 or colour not in (2, 6):
                raise ValueError(f"unsupported PNG: depth {depth}, colour {colour}")
            channels = 3 if colour == 2 else 4
        elif kind == b"IDAT":
            idat.append(body)
        elif kind == b"IEND":
            break
        pos += 12 + length
    if width is None:
        raise ValueError(f"{path} has no IHDR")

    raw = zlib.decompress(b"".join(idat))
    stride = width * channels
    rows, previous = [], bytearray(stride)
    at = 0
    for _ in range(height):
        filt = raw[at]
        line = bytearray(raw[at + 1:at + 1 + stride])
        at += 1 + stride
        for i in range(stride):
            left = line[i - channels] if i >= channels else 0
            up = previous[i]
            corner = previous[i - channels] if i >= channels else 0
            if filt == 1:
                line[i] = (line[i] + left) & 0xFF
            elif filt == 2:
                line[i] = (line[i] + up) & 0xFF
            elif filt == 3:
                line[i] = (line[i] + (left + up) // 2) & 0xFF
            elif filt == 4:
                p = left + up - corner
                pa, pb, pc = abs(p - left), abs(p - up), abs(p - corner)
                best = left if (pa <= pb and pa <= pc) else (up if pb <= pc else corner)
                line[i] = (line[i] + best) & 0xFF
            elif filt != 0:
                raise ValueError(f"unknown PNG filter {filt}")
        rows.append(bytes(line))
        previous = line
    return width, height, rows, channels


def cell_ink(rows, channels, column, row, width):
    """The bytes of one grid cell, as a single blob to compare."""
    x0, y0 = column * CELL_W, row * CELL_H
    out = []
    for y in range(y0, min(y0 + CELL_H, len(rows))):
        line = rows[y]
        out.append(line[x0 * channels:min((x0 + CELL_W), width) * channels])
    return b"".join(out)


def build_page(cells, extra_css):
    stylesheet = STYLESHEET.read_text(encoding="utf-8")
    font = (ROOT / "goldens" / "fonts" / "NotoSansMongolian-Regular.ttf").as_uri()
    body = "".join(f'<div class="cell">{html}</div>' for _, html in cells)
    return f"""<meta charset="utf-8">
<style>
/* The vendored face, registered under the family the real stylesheet already
   asks for first, so the cascade below is the shipped one and not a fixture.
   Pinning it matters for the same reason the shaping golden checksums it: a
   different Mongolian font is a different set of glyphs. */
@font-face {{ font-family: "Noto Sans Mongolian"; src: url("{font}"); }}
{stylesheet}
html, body {{ margin: 0; padding: 0; background: #fff; }}
body {{ display: grid; grid-template-columns: repeat({COLUMNS}, {CELL_W}px); }}
/* Fixed cells with the overflow clipped: one long run must not be able to
   shift every cell after it and report the whole grid as changed. */
.cell {{ width: {CELL_W}px; height: {CELL_H}px; overflow: hidden; }}
.cell .vertext {{ font-size: {FONT_PX}px; }}
{extra_css}
</style>
{body}
"""


def shoot(chrome, page, png, width, height):
    # --disable-dev-shm-usage is not boilerplate: a container gets a 64MB
    # /dev/shm by default, and at that size this grid (1728x3360) does not fail,
    # it HANGS -- measured inside azura-ci:latest, where the same shot is 1.0s
    # with the flag and still running at 120s without it. The gate's own 300s
    # timeout then reports a timeout rather than a cause. Writing the shared
    # memory to /tmp instead costs nothing here and is what lets this run
    # anywhere but a developer's host.
    done = subprocess.run(
        [str(chrome), "--headless", "--disable-gpu", "--no-sandbox",
         "--disable-dev-shm-usage",
         "--force-device-scale-factor=1", "--hide-scrollbars",
         f"--window-size={width},{height}", f"--screenshot={png}", page.as_uri()],
        capture_output=True, text=True, timeout=300)
    if not png.exists():
        raise SystemExit(f"chrome produced no screenshot:\n{done.stderr[-2000:]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chrome")
    ap.add_argument("--binary", default=str(BINARY))
    ap.add_argument("--keep", action="store_true",
                    help="leave the generated pages and screenshots in place")
    args = ap.parse_args()

    chrome = find_chrome(args.chrome)
    binary = pathlib.Path(args.binary)
    if not binary.exists():
        sys.exit(f"no binary at {binary} -- cargo build --release -p vertext-cli")
    golden = json.loads(_sg.GOLDEN.read_text(encoding="utf-8"))

    texts = {n: t for n, t in _sg.CASES if " " not in t}
    texts.update({f"corpus:{r}": r for r in golden["corpus"]["runs"] if " " not in r})
    names = sorted(texts)

    cells = []
    for name in names:
        done = subprocess.run([str(binary), "--progression", "lr"],
                              input=texts[name], capture_output=True, text=True)
        if done.returncode != 0:
            sys.exit(f"binary failed on {name}: {done.stderr.strip()}")
        cells.append((name, done.stdout))

    rows_needed = (len(cells) + COLUMNS - 1) // COLUMNS
    width, height = COLUMNS * CELL_W, rows_needed * CELL_H

    work = pathlib.Path(tempfile.mkdtemp(prefix="vertext-browser-"))
    try:
        shots = {}
        for label, extra in (("joined", ""),
                             ("isolated", f".vertext-mongolian {{ {JOINING_OFF} }}")):
            page = work / f"{label}.html"
            page.write_text(build_page(cells, extra), encoding="utf-8")
            png = work / f"{label}.png"
            shoot(chrome, page, png, width, height)
            shots[label] = read_png(png)

        (w1, h1, r1, c1), (w2, h2, r2, c2) = shots["joined"], shots["isolated"]
        if (w1, h1, c1) != (w2, h2, c2):
            sys.exit(f"the two screenshots differ in shape: {w1}x{h1} vs {w2}x{h2}")

        blank, blind, noisy, wordless = [], [], [], []
        white = None
        for index, (name, _) in enumerate(cells):
            column, row = index % COLUMNS, index // COLUMNS
            a = cell_ink(r1, c1, column, row, w1)
            b = cell_ink(r2, c2, column, row, w2)
            if white is None:
                white = bytes([0xFF]) * len(a)
            if a == white:
                blank.append(name)
                continue
            letters = _sg.letters(texts[name])
            if letters == 0:
                # Neither assertion applies, so such a run would go through
                # this gate unexamined. It cannot come from today's corpus,
                # whose every entry carries a letter -- but extract()'s range
                # is the whole block and _sg.LETTERS is only the part of it
                # that joins, so the two can part company on a re-extract.
                # Say so rather than pass quietly.
                wordless.append(name)
                continue
            if letters >= 2 and a == b:
                blind.append(name)
            if letters == 1 and a != b:
                noisy.append(name)

        if blank:
            print(f"FAIL: {len(blank)} cells rendered nothing at all: {blank[:5]}")
            print("      an empty cell compares equal to an empty cell; the gate "
                  "would pass for the wrong reason")
            return 1
        if blind:
            print(f"FAIL: joining disabled, yet these {len(blind)} runs render "
                  f"identically: {blind[:5]}")
            print("      the browser is not applying the joining features")
            return 1
        if noisy:
            print(f"FAIL: single-letter runs changed too: {noisy[:5]}")
            print("      a rig that differs everywhere is not discriminating")
            return 1
        if wordless:
            print(f"FAIL: {len(wordless)} runs carry no letter that can take a "
                  f"positional form: {wordless[:5]}")
            print("      neither assertion applies to them, so this gate would "
                  "not be looking at them")
            print("      widen tools/shaping-golden.py's LETTERS, or drop the "
                  "entries from the corpus")
            return 1

        multi = sum(1 for n in names if _sg.letters(texts[n]) >= 2)
        single = len(names) - multi
        print(f"PASS: chrome draws joined forms. {multi} multi-letter runs all "
              f"change when init/medi/fina are off, and all {single} "
              f"single-letter runs do not.")
        print(f"      {version(chrome)}, {w1}x{h1} at {FONT_PX}px, "
              f"font {golden['font']['sha256'][:12]}")
        return 0
    finally:
        if args.keep:
            print(f"      pages and screenshots left in {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
