#!/usr/bin/env python3
"""CLReq geometry of a rendered page, measured in a browser.

Some of what CLReq asks of a page is only true or false once a browser has
laid it out with a real font: whether a column is a whole number of
characters long, how far apart the lines of a paragraph sit. This renders
documents through pandoc, the real filter and the binary, sets each the way a
Quarto page sets it (the filter's own mode style plus the shipped
stylesheet), opens it in headless Chrome with a pinned CJK face, and checks
the measurements against the requirement each one is named after.

A CJK face is required, not optional: without one Chrome draws tofu, whose
advance is not the 18px cell, and every count comes out wrong. The faces are
Noto Sans SC and TC from notofonts/noto-cjk at a pinned tag, fetched once into
--fonts and checked against their sha256.

The page POSTs its measurements back and this waits for them in real time
(see tools/wasm-caret.py for why not a virtual-time budget).

Usage
-----
    cargo build --release -p vertext-cli
    python3 tools/page-geometry.py [--pandoc PATH] [--chrome PATH] [--fonts DIR]
"""

import argparse
import hashlib
import importlib.util
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
BINARY = ROOT / "target" / "release" / "vertext"
SHIM = ROOT / "tools" / "quarto-shim.lua"
STYLESHEET = ROOT / "extensions" / "vertext" / "vertext.css"

_spec = importlib.util.spec_from_file_location(
    "progression_scroll", ROOT / "tools" / "progression-scroll.py")
_ps = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ps)

NOTO = "https://github.com/notofonts/noto-cjk/raw/Sans2.004/Sans/SubsetOTF"
FONTS = {
    "Noto Sans SC": (f"{NOTO}/SC/NotoSansSC-Regular.otf",
                     "faa6c9df652116dde789d351359f3d7e5d2285a2b2a1f04a2d7244df706d5ea9"),
    "Noto Sans TC": (f"{NOTO}/TC/NotoSansTC-Regular.otf",
                     "5bab0cb3c1cf89dde07c4a95a4054b195afbcfe784d69d75c340780712237537"),
    # One face for every region, choosing its forms by the text's language.
    "Noto Sans CJK SC": (
        "https://github.com/notofonts/noto-cjk/raw/Sans2.004/Sans/OTF/"
        "SimplifiedChinese/NotoSansCJKsc-Regular.otf",
        "2c76254f6fc379fddfce0a7e84fb5385bb135d3e399294f6eeb6680d0365b74b"),
}

PROSE = "山川异域，风月同天。寄诸佛子，共结来缘。" * 12

MEASURE = """
<script>
document.fonts.ready.then(() => {
  const cell = parseFloat(getComputedStyle(document.documentElement)
    .getPropertyValue('--vertext-cell'));
  const columns = [...document.querySelectorAll('.vertext-column')]
    .filter(c => c.textContent.trim());
  // The centre of every upright character in the first column, across the
  // line axis: one distinct value per line of the paragraph.
  const centres = [...(columns[0] ? columns[0].querySelectorAll('.vertext-upright') : [])]
    .map(s => { const r = s.getBoundingClientRect(); return (r.left + r.right) / 2; });
  const result = {
    cell,
    heights: columns.map(c => parseFloat(getComputedStyle(c).height)),
    centres,
    // Each column's slots, as text and the centre of their line.
    slots: columns.map(c => [...c.children].map(e => {
      const r = e.getBoundingClientRect();
      return [e.textContent, Math.round((r.left + r.right) / 2)];
    })),
    combined: [...document.querySelectorAll('.vertext-combine')]
      .map(e => { const r = e.getBoundingClientRect(); return [r.width, r.height]; }),
    fonts: [...document.fonts].filter(f => f.status === 'loaded').map(f => f.family),
  };
  fetch('result', { method: 'POST', body: JSON.stringify(result) });
});
</script>
"""


def fetch_fonts(directory):
    """Each pinned face in `directory`, downloaded once and checked."""
    directory.mkdir(parents=True, exist_ok=True)
    paths = {}
    for family, (url, digest) in FONTS.items():
        path = directory / url.rsplit("/", 1)[1]
        if not path.exists():
            with urllib.request.urlopen(url, timeout=120) as response:
                path.write_bytes(response.read())
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != digest:
            sys.exit(f"{path} is not the pinned {family}: sha256 {actual}")
        paths[family] = path
    return paths


def page(pandoc, work, name, text, meta, family):
    """A document through the real filter, set the way a Quarto page sets it."""
    source = work / f"{name}.md"
    front = "".join(f"{key}: {value}\n" for key, value in meta.items())
    source.write_text(f"---\nvertext: true\n{front}---\n\n{text}\n", encoding="utf-8")
    env = dict(os.environ, PATH=f"{BINARY.parent}:{os.environ['PATH']}")
    done = subprocess.run([pandoc, "-s", "-f", "markdown", "-t", "html", "--wrap=none",
                           "--metadata", f"title={name}", f"--lua-filter={SHIM}",
                           str(source)], capture_output=True, text=True, env=env, timeout=120)
    if done.returncode != 0:
        sys.exit(f"pandoc failed:\n{done.stderr[-2000:]}")
    head, _, rest = done.stdout.partition("<body>")
    body, _, tail = rest.partition("</body>")
    faces = "".join(f'@font-face {{ font-family: "{f}"; src: url("{p.name}"); }}\n'
                    for f, p in FONTS_IN_WORK.items())
    head = head.replace("</head>", '<link rel="stylesheet" href="vertext.css">\n'
                        f'<style>{faces}body {{ font-family: "{family}"; }}</style>\n'
                        '</head>', 1)
    html = (f'{head}<body><main class="content" id="quarto-document-content">'
            f'{body}</main>{MEASURE}</body>{tail}')
    (work / f"{name}.html").write_text(html, encoding="utf-8")
    return f"{name}.html"


FONTS_IN_WORK = {}


def built_for(cells):
    """The paragraphs below put a mark exactly where a line ends, which holds
    only if the column is as many cells long as the text was built for. A
    column of another length moves the mark off the break, and the check then
    passes without having asked anything."""
    def check(m, where):
        heights = set(m["heights"])
        if heights != {cells * m["cell"]}:
            return [f"{where}: built for {cells}-cell columns, but the columns are "
                    f"{sorted(heights)}px of a {m['cell']}px cell"]
        return []
    return check


def whole_cells(m, where):
    """CLReq 7.1.1.5: a line is a whole number of characters long. The window
    is chosen so that the space is NOT a whole number of cells; a column that
    is not capped proves nothing, so that is a failure too."""
    fails = []
    cell, heights = m["cell"], m["heights"]
    if not heights:
        return [f"{where}: no column on the page"]
    for h in set(heights):
        if abs(h / cell - round(h / cell)) > 0.01:
            fails.append(f"{where}: a column is {h}px, {h / cell:.2f} cells of {cell}px")
    if max(heights) >= 34 * cell:
        fails.append(f"{where}: the columns are not capped ({max(heights)}px), "
                     f"so this window proves nothing")
    return fails


def line_gap(m, where):
    """CLReq 7.1.1.5: the gap between the lines of a paragraph is commonly 50%
    to 100% of the character frame, and does not exceed the font size. The
    gap is the pitch between adjacent line centres less the frame (the cell).
    A paragraph that does not wrap has no gap to measure, so that fails."""
    cell = m["cell"]
    lines = sorted({round(c * 2) / 2 for c in m["centres"]})
    if len(lines) < 3:
        return [f"{where}: the first paragraph has {len(lines)} line(s); "
                f"the gap needs at least three"]
    pitches = sorted(b - a for a, b in zip(lines, lines[1:]))
    pitch = pitches[len(pitches) // 2]
    gap = (pitch - cell) / cell
    m["gap"] = f"lines {pitch:.1f}px apart, a gap of {gap:.0%} of the frame"
    if not 0.5 - 0.01 <= gap <= 1.0 + 0.01:
        return [f"{where}: lines {pitch:.1f}px apart, a gap of {gap:.0%} of the "
                f"{cell}px frame; CLReq's usual range is 50% to 100%"]
    return []


def marks_together(m, where):
    """CLReq 5.1.1.3: two question or exclamation marks used together take one
    character's space. Along the line that is one cell; across it, no wider
    than the line."""
    cell, pitch = m["cell"], m["cell"] * 1.5
    fails = []
    if len(m["combined"]) != 3:
        fails.append(f"{where}: {len(m['combined'])} paired marks, expected 3")
    for width, height in m["combined"]:
        if abs(height - cell) > 0.5 or width > pitch + 0.5:
            fails.append(f"{where}: a pair takes {width:.1f}x{height:.1f}px, "
                         f"not one {cell}px cell")
    if not fails:
        m["gap"] = (m.get("gap", "") + f"{len(m['combined'])} pairs one cell each").strip()
    return fails


TOGETHER = "真的？！不会吧！！谁？？？"

# Each paragraph leaves the end of its first line just room for the number and
# not its suffix, or for the prefix and not its number, so the break has to go
# somewhere: between the two, or before both. `n` is the column's length in
# cells, measured before the text is built.
AFFIXED = [("50", "%"), ("30", "℃"), ("¥", "100"), ("-", "5")]


def affixes(n):
    return "\n\n".join("永" * (n - 1) + a + b + "永永" for a, b in AFFIXED)


def numbers_keep_affixes(m, where):
    """CLReq 6.1.2.2: a number and its prefix or suffix (`50%`, `¥100`, `30℃`)
    are not separated across lines."""
    fails = []
    for (a, b), column in zip(AFFIXED, m["slots"]):
        texts = [t for t, _ in column]
        joined = a + b
        lines = {}
        for text, x in column:
            lines.setdefault(x, "")
            lines[x] += text
        if any(joined in line for line in lines.values()):
            continue
        if not any(joined in "".join(texts[i:i + 2]) for i in range(len(texts))):
            fails.append(f"{where}: `{joined}` is not in the column at all: {texts[-6:]}")
            continue
        fails.append(f"{where}: `{a}` and `{b}` sit on different lines: "
                     + " / ".join(line[-4:] for line in lines.values()))
    if not fails:
        m["gap"] = (m.get("gap", "") + f"{len(AFFIXED)} affixed numbers whole").strip()
    return fails

# A full first line, then marks that may not start a line: each paragraph puts
# one of them exactly where the second line begins.
PROHIBITED = "、，。．；：！？）」』》"


def line_start(n):
    return "\n\n".join("永" * n + mark + "永永" for mark in PROHIBITED)


def no_mark_starts_a_line(m, where):
    """CLReq 6.1.1: a closing or pause mark does not begin a line."""
    fails = []
    for mark, column in zip(PROHIBITED, m["slots"]):
        lines = {}
        for text, x in column:
            lines.setdefault(x, []).append(text)
        for x, line in lines.items():
            if line and line[0] in PROHIBITED:
                fails.append(f"{where}: a line begins with `{line[0]}`")
    if not fails:
        m["gap"] = (m.get("gap", "") + f"no line begins with any of {PROHIBITED}").strip()
    return fails


# And the other end: an opening mark placed in the last cell of the first line.
OPENING = "（「『《"


def line_end(n):
    return "\n\n".join("永" * (n - 1) + mark + "永永永" for mark in OPENING)


def no_mark_ends_a_line(m, where):
    """CLReq 6.1.1: an opening bracket or quotation mark does not end a line."""
    fails = []
    for column in m["slots"]:
        lines = {}
        for text, x in column:
            lines.setdefault(x, []).append(text)
        ordered = [lines[x] for x in sorted(lines, reverse=True)]
        for line in ordered[:-1]:
            if line and line[-1] in OPENING:
                fails.append(f"{where}: a line ends with `{line[-1]}`")
    if not fails:
        m["gap"] = (m.get("gap", "") + f"no line ends with any of {OPENING}").strip()
    return fails


CASES = [
    # name, text (or a builder given the column's cells), metadata, window,
    # the faces that must load (the first is the body's), checks
    ("document-short", PROSE, {}, (900, 700), ["Noto Sans SC"], [whole_cells, line_gap]),
    ("page-short", PROSE, {"vertext-page": "true"}, (900, 500), ["Noto Sans SC"],
     [whole_cells, line_gap]),
    ("marks-together", TOGETHER, {}, (900, 700), ["Noto Sans SC"], [marks_together]),
    ("number-affixes", affixes, {}, (900, 700), ["Noto Sans SC"], [numbers_keep_affixes]),
    ("line-start", line_start, {}, (900, 700), ["Noto Sans SC"], [no_mark_starts_a_line]),
    ("line-end", line_end, {}, (900, 700), ["Noto Sans SC"], [no_mark_ends_a_line]),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pandoc", default="pandoc")
    ap.add_argument("--chrome")
    ap.add_argument("--fonts", default=str(pathlib.Path.home() / ".cache" / "vertext-fonts"))
    args = ap.parse_args()
    if not BINARY.exists():
        sys.exit(f"no binary at {BINARY} -- cargo build --release -p vertext-cli")
    chrome = _ps.find_chrome(args.chrome)
    fonts = fetch_fonts(pathlib.Path(args.fonts))

    work = pathlib.Path(tempfile.mkdtemp(prefix="vertext-geometry-"))
    shutil.copy(STYLESHEET, work / STYLESHEET.name)
    for family, path in fonts.items():
        shutil.copy(path, work / path.name)
        FONTS_IN_WORK[family] = path
    fails, lines = [], []
    measured = {}
    for name, text, meta, window, families, checks in CASES:
        if callable(text):
            # Measure the column this window and mode give, then build for it.
            key = (window, tuple(sorted(meta.items())))
            if key not in measured:
                probe = _ps.measure(chrome, work, page(args.pandoc, work, f"{name}-probe",
                                                       PROSE, meta, families[0]), window)
                measured[key] = probe and round(max(probe["heights"]) / probe["cell"])
            if not measured[key]:
                fails.append(f"{name}: the probe page reported no column")
                continue
            cells = measured[key]
            text, checks = text(cells), [built_for(cells), *checks]
        m = _ps.measure(chrome, work, page(args.pandoc, work, name, text, meta, families[0]),
                        window)
        if m is None:
            fails.append(f"{name}: the page reported nothing within 120s")
            continue
        missing = [f for f in families if f not in m["fonts"]]
        if missing:
            fails.append(f"{name}: {', '.join(missing)} did not load ({m['fonts']}), so "
                         f"nothing here measured a real glyph")
            continue
        for check in checks:
            fails += check(m, name)
        lines.append(f"{name} at {window[0]}x{window[1]}: columns "
                     f"{sorted(set(m['heights']))}px of a {m['cell']}px cell"
                     + (f"; {m['gap']}" if "gap" in m else ""))
    shutil.rmtree(work, ignore_errors=True)
    for line in fails:
        print("FAIL: " + line)
    if fails:
        return 1
    print("PASS: every column on a short window is a whole number of cells long, "
          "the lines of a paragraph sit within CLReq's usual gap, marks used "
          "together share a cell, a number keeps its sign and unit, and no "
          "closing mark starts a line or opening mark ends one")
    for line in lines:
        print("      " + line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
