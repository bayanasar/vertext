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
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
BINARY = ROOT / "target" / "release" / "vertext"
SHIM = ROOT / "tools" / "quarto-shim.lua"
STYLESHEET = ROOT / "extensions" / "vertext" / "vertext.css"
# The Mongolian face ships beside the stylesheet, which names it by a relative
# URL; it is copied next to the stylesheet here as Quarto copies it.
MONGOLIAN = STYLESHEET.parent / "NotoSansMongolian-Regular.ttf"

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
    # A Latin face, with no vertical metrics, for a body whose stack puts a
    # Latin face first, as Bootstrap's and Quarto's do.
    "Noto Sans": (
        "https://github.com/notofonts/notofonts.github.io/raw/noto-monthly-release-2026.10.01/"
        "fonts/NotoSans/unhinted/ttf/NotoSans-Regular.ttf",
        "f3961a9cde016d41a4879aecda1474d3a36d6bf54fa0e4643de029cc2248b0e8"),
}

PROSE = "山川异域，风月同天。寄诸佛子，共结来缘。" * 12

MEASURE = """
<script>
document.fonts.ready.then(() => {
  const root = getComputedStyle(document.documentElement);
  const cell = parseFloat(root.getPropertyValue('--vertext-cell'));
  const columns = [...document.querySelectorAll('.vertext-column')]
    .filter(c => c.textContent.trim());
  // A column's slots in order: its children, and the slots inside a span
  // that keeps a box and its marks on one line.
  const slotsOf = c => [...c.children]
    .flatMap(e => e.classList.contains('vertext-nobreak') ? [...e.children] : [e]);
  // What a reader who selects a whole column and copies it gets.
  const copied = c => {
    const range = document.createRange();
    range.selectNodeContents(c);
    const selection = getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    const text = selection.toString();
    selection.removeAllRanges();
    return text;
  };
  // The centre of every upright character in the first column, across the
  // line axis: one distinct value per line of the paragraph.
  const centres = [...(columns[0] ? columns[0].querySelectorAll('.vertext-upright') : [])]
    .map(s => { const r = s.getBoundingClientRect(); return (r.left + r.right) / 2; });
  const result = {
    cell,
    lineGap: parseFloat(root.getPropertyValue('--vertext-line-gap')),
    // Every slot of the first column, by kind, with the centre of its line.
    items: (columns[0] ? slotsOf(columns[0]) : []).map(e => {
      const r = e.getBoundingClientRect();
      return [e.className, (r.left + r.right) / 2];
    }),
    heights: columns.map(c => parseFloat(getComputedStyle(c).height)),
    centres,
    // Each column's slots, as text and the centre of their line.
    slots: columns.map(c => slotsOf(c).map(e => {
      const r = e.getBoundingClientRect();
      return [e.textContent, Math.round((r.left + r.right) / 2)];
    })),
    copied: columns.map(copied),
    // Each column's slots with their kind, their extent along the line and
    // the centre of their line.
    spans: columns.map(c => slotsOf(c).map(e => {
      const r = e.getBoundingClientRect();
      return [e.className.replace('vertext-', ''), e.textContent, r.top, r.bottom,
              Math.round((r.left + r.right) / 2)];
    })),
    // Where each column begins and ends along the line.
    ends: columns.map(c => { const r = c.getBoundingClientRect(); return [r.top, r.bottom]; }),
    // How far each column's slots run past its end, along the line.
    overrun: columns.map(c => {
      const end = c.getBoundingClientRect().bottom;
      return Math.max(0, ...slotsOf(c).map(e => e.getBoundingClientRect().bottom - end));
    }),
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


class Raw(str):
    """Text as a wasm or Dart host hands it to the renderer. Through pandoc a
    doubled space would arrive as one, so the strip of this text comes from
    the binary itself, set in the page pandoc and the filter build."""


def page(pandoc, work, name, text, meta, body_faces, stylesheet="vertext.css"):
    """A document through the real filter, set the way a Quarto page sets it:
    `body_faces` are the body's font stack, and `stylesheet` the stylesheet
    the page links."""
    source = work / f"{name}.md"
    front = "".join(f"{key}: {value}\n" for key, value in meta.items())
    written = "永" if isinstance(text, Raw) else text
    source.write_text(f"---\nvertext: true\n{front}---\n\n{written}\n", encoding="utf-8")
    env = dict(os.environ, PATH=f"{BINARY.parent}:{os.environ['PATH']}")
    done = subprocess.run([pandoc, "-s", "-f", "markdown", "-t", "html", "--wrap=none",
                           "--metadata", f"title={name}", f"--lua-filter={SHIM}",
                           str(source)], capture_output=True, text=True, env=env, timeout=120)
    if done.returncode != 0:
        sys.exit(f"pandoc failed:\n{done.stderr[-2000:]}")
    head, _, rest = done.stdout.partition("<body>")
    body, _, tail = rest.partition("</body>")
    if isinstance(text, Raw):
        flags = (["--progression", meta["vertext-progression"]]
                 if "vertext-progression" in meta else [])
        strip = subprocess.run([str(BINARY), "html", *flags], input=text, capture_output=True,
                               text=True, check=True, timeout=120).stdout.strip()
        if body.count('<div class="vertext"') != 1:
            sys.exit(f"{name}: the page has no single strip to replace")
        body = re.sub(r'<div class="vertext".*</div>', lambda _: strip, body, count=1,
                      flags=re.S)
    faces = "".join(f'@font-face {{ font-family: "{f}"; src: url("{p.name}"); }}\n'
                    for f, p in FONTS_IN_WORK.items())
    stack = ", ".join(f'"{f}"' for f in body_faces)
    head = head.replace("</head>", f'<link rel="stylesheet" href="{stylesheet}">\n'
                        f'<style>{faces}body {{ font-family: {stack}; }}</style>\n'
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


def line_pitch(kinds):
    """Every line of the first paragraph is one pitch from the next, the cell
    plus the declared gap, whatever kind of slot fills it. The upright marks
    carry the pitch as their line height; a line holding only Mongolian runs
    or only Latin words has no upright mark in it, so those slots must carry
    it too. `kinds` are the slot classes whose centres mark the lines."""
    def check(m, where):
        cell = m["cell"]
        pitch = cell * (1 + m["lineGap"])
        centres = sorted(x for cls, x in m["items"]
                         if any(f"vertext-{kind}" in cls.split() for kind in kinds))
        lines = []
        for x in centres:
            if lines and x - lines[-1][-1] < cell / 4:
                lines[-1].append(x)
            else:
                lines.append([x])
        lines = [sum(line) / len(line) for line in lines]
        if len(lines) < 3:
            return [f"{where}: the first paragraph has {len(lines)} line(s) of "
                    f"{'/'.join(kinds)}; the pitch needs at least three"]
        apart = [b - a for a, b in zip(lines, lines[1:])]
        off = [d for d in apart if abs(d - pitch) > 0.5]
        if off:
            return [f"{where}: lines {', '.join(f'{d:.1f}' for d in apart)}px apart; "
                    f"the pitch is {pitch:.1f}px"]
        m["gap"] = (m.get("gap", "") + f"{len(lines)} lines {pitch:.1f}px apart").strip()
        return []
    return check


def marks_together(m, where):
    """CLReq 5.1.1.3: two question or exclamation marks used together take one
    character's space. Along the line that is one cell; across it, no wider
    than the line."""
    cell, pitch = m["cell"], m["cell"] * 1.5
    fails = []
    if len(m["combined"]) != 4:
        fails.append(f"{where}: {len(m['combined'])} paired marks, expected 4")
    for width, height in m["combined"]:
        if abs(height - cell) > 0.5 or width > pitch + 0.5:
            fails.append(f"{where}: a pair takes {width:.1f}x{height:.1f}px, "
                         f"not one {cell}px cell")
    if not fails:
        m["gap"] = (m.get("gap", "") + f"{len(m['combined'])} pairs one cell each").strip()
    return fails


TOGETHER = "真的？！不会吧！！谁？？？真的?!"

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
# one of them exactly where the second line begins. CLReq 6.1.1's basic rule,
# with the characters from CLReq's tables of marks: the pause and stop marks;
# the closing quotation marks, brackets and title marks; and the connector
# marks, interpuncts and solidi. A lone `—` is a connector; two are a dash,
# which may begin a line. CLReq's text on the connector mark gives `~` beside
# `～` as Taiwan's second form, and `－` is the range mark this repository sets
# between numbers.
PROHIBITED = ("、，。．；：！？"
              "」』”’〞〟）］｝〕】〗〉》"
              "～〜~-–—－·・‧/／")


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
OPENING = "「『“‘〝（［｛〔【〖〈《"


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


# The same rules beside a slot the browser sets as one box -- a Latin word, a
# number, a Mongolian run -- where a line may otherwise break on either side
# of the box. Its length along the line depends on the face, so each probe is
# placed 1 to 8 cells from the end of the first line (an opening mark 1 to 3),
# and at one of those the box fills the line and the mark has to go somewhere.
BOX_CLOSING = ["sayin，", "sayin。", "sayin）", "sayin！？", "50%。", "2026」", "ᠮᠣᠩᠭᠣᠯ，",
               "ᠮᠣᠩᠭᠣᠯ》",
               # A pair around a box: 1 cell from the end its opening mark
               # ends the line, a few further its closing mark would begin
               # the next.
               "〝sayin〞", "〝sayin〟", "“sayin”", "‘sayin’", "［sayin］", "｛sayin｝",
               "〔sayin〕", "【sayin】", "〖sayin〗", "〈sayin〉",
               "2000～2010", "1990~2000", "1990－2000", "sayin〜", "sayin~", "sayin-",
               "sayin–", "sayin—", "sayin·", "sayin・", "sayin‧", "sayin/", "sayin／"]
BOX_OPENING = ["（sayin）", "「50%」", "《ᠮᠣᠩᠭᠣᠯ》"]
BOX_PROBES = ([(probe, k) for probe in BOX_CLOSING for k in range(1, 9)]
              + [(probe, k) for probe in BOX_OPENING for k in range(1, 4)])


def beside_boxes(n):
    return "\n\n".join("永" * (n - k) + probe + "永永永" for probe, k in BOX_PROBES)


def lines_of(column, cell):
    """A column's slots as lines, in reading order: a new line wherever the
    centre moves by more than half a cell. A box's centre may sit a pixel off
    the line's, or a Mongolian run's by its stem shift, so equal centres do
    not mark a line here."""
    lines, previous = [], None
    for text, x in column:
        if previous is None or abs(x - previous) > cell / 2:
            lines.append([])
        lines[-1].append(text)
        previous = x
    return lines


def no_mark_beside_a_box_breaks(m, where):
    """CLReq 6.1.1 beside a Latin word, a number and a Mongolian run: no
    mark that may not begin a line begins one and no opening mark ends one.
    And the text a reader copies from each column is the paragraph as
    written. Each probe must reach a line edge at one of its distances at
    least -- the second line beginning inside it, or with the slot just
    before it -- or the probe proves nothing: a face or a stylesheet that
    makes the box shorter would leave every placement inside the first line,
    and the rules would hold by never being asked."""
    fails = []
    cell = m["cell"]
    n = round(m["heights"][0] / cell) if m["heights"] else 0
    if len(m["slots"]) != len(BOX_PROBES):
        return [f"{where}: {len(m['slots'])} columns for {len(BOX_PROBES)} probes"]
    reached = set()
    for (probe, k), column, copied in zip(BOX_PROBES, m["slots"], m["copied"]):
        at = f"{where}: `{probe}` {k} cell(s) from the end"
        lines = lines_of(column, cell)
        # The probe's slots follow the n - k Han before it and precede the
        # three after it. The line may also break one slot early: a `“` holds
        # to both sides, so the Han before it goes to the next line with it.
        if len(lines) > 1 and n - k - 1 <= len(lines[0]) < len(column) - 3:
            reached.add(probe)
        for line in lines[1:]:
            if line[0] in set(PROHIBITED) | {"？！", "！？", "？？", "！！"}:
                fails.append(f"{at}: a line begins with `{line[0]}`")
        for line in lines[:-1]:
            if line[-1] in OPENING:
                fails.append(f"{at}: a line ends with `{line[-1]}`")
        written = "永" * (n - k) + probe + "永永永"
        if copied != written:
            fails.append(f"{at}: copying the column gives {copied!r}")
    fails += [f"{where}: `{probe}` never reached a line edge"
              for probe in dict.fromkeys(probe for probe, _ in BOX_PROBES)
              if probe not in reached]
    if not fails:
        m["gap"] = (m.get("gap", "") + f"{len(BOX_PROBES)} probes beside a box hold, "
                    f"each reaching a line edge, and copy as written").strip()
    return fails


# A run of one connector mark, interpunct or solidus, twice as long as the
# column, between Han. The renderer holds a run's first mark to the slot
# before it and no more, so a run longer than the column breaks inside it
# rather than running past the column's end.
RUNS = "～〜~-–—－·・‧/／"


def runs(n):
    # Escaped where Markdown would read a run: `~~` as strikeout, `--` as a dash.
    return "\n\n".join("永" * 5 + ("\\" * (mark in "~-") + mark) * (2 * n) + "永" * 5
                       for mark in RUNS)


def no_run_overruns(m, where):
    """No slot of a run runs past the end of its column, and each column
    copies as written."""
    fails = []
    n = round(m["heights"][0] / m["cell"]) if m["heights"] else 0
    if len(m["slots"]) != len(RUNS):
        return [f"{where}: {len(m['slots'])} columns for {len(RUNS)} runs"]
    for mark, copied, overrun in zip(RUNS, m["copied"], m["overrun"]):
        if overrun > 0.5:
            fails.append(f"{where}: a run of `{mark}` runs {overrun:.0f}px past the column's end")
        written = "永" * 5 + mark * (2 * n) + "永" * 5
        if copied != written:
            fails.append(f"{where}: copying the run of `{mark}` gives {copied!r}")
    if not fails:
        m["gap"] = (m.get("gap", "") + f"no run of {RUNS} runs past a column's end, "
                    f"and each copies as written").strip()
    return fails


# Bichig alone, in its own progression: no upright mark on any line.
BICHIG = "ᠮᠣᠩᠭᠣᠯ ᠪᠢᠴᠢᠭ " * 24


def short_latin(n):
    """A Han line, then about two and a half lines of short Latin words, then
    Han again: still a vertical paragraph (3n Han characters outvote 2n
    words), with whole lines that hold nothing but Latin. The words are
    narrower than a cell, so their lines are exactly one pitch wide."""
    words = ("of in to is at by on or an a " * n).split()[:2 * n]
    return "永" * n + " ".join(words) + "永" * (2 * n)


# Prose whose lines break at word spaces: Chinese with romanized words, as the
# lesson pages have them; bichig of words of every length, in two orders, so
# that the lines end at different distances from the column's end; and bichig
# with Han words in it. And bichig with doubled spaces, which only a host that
# hands the renderer its text as it is can give.
SPACED_CHINESE = ("“sayin baina uu”是问候语，意思是“你好”。回答时说 sayin baina 即可。"
                  "表示感谢说 bayarlalaa ，告别时说 bayartai 。" * 6)
WORDS = ("ᠮᠣᠩᠭᠣᠯ ᠪᠢᠴᠢᠭ ᠦᠨ ᠬᠡᠯᠡ ᠪᠣᠯ ᠡᠪᠦᠭᠡ ᠡᠮᠡᠭᠡ ᠬᠦᠮᠦᠨ ᠦ ᠭᠠᠵᠠᠷ ᠣᠯᠠᠨ ᠨᠣᠮ ᠢᠷᠡᠬᠦ ᠦᠵᠡᠬᠦ "
         "ᠮᠣᠷᠢ ᠲᠠᠪᠤᠨ ᠬᠣᠶᠠᠷ ᠭᠤᠷᠪᠠ ᠳᠥᠷᠪᠡ ᠨᠢᠭᠡ ᠪᠢᠳᠡᠨ ᠡᠭᠦᠳᠡ ᠨᠠᠢᠮᠠ ᠰᠠᠶᠢᠨ ᠤᠷᠲᠤ ᠬᠣᠲᠠ "
         "ᠡᠨᠡ ᠲᠡᠷᠡ ᠶᠠᠭᠤ ᠮᠢᠨᠦ ᠴᠢᠨᠦ ᠪᠠᠭᠰᠢ ᠨᠣᠮᠤᠳ ᠤᠰᠤᠨ ᠠᠷᠪᠠ ᠶᠢᠰᠦ ᠨᠣᠬᠠᠢ ᠮᠣᠷᠢᠰ ᠳᠡᠭᠦᠦ "
         "ᠡᠭᠡᠴᠢ ᠢᠳᠡᠬᠦ ᠠᠶᠢᠯ ᠣᠬᠣᠷ ᠥᠭᠬᠦ ᠦᠭᠡᠢ ᠨᠠᠳᠠ ᠪᠠᠲᠤ ᠬᠡᠳᠦᠨ ᠵᠢᠵᠢᠭ").split()
SPACED_BICHIG = "\n\n".join(
    [" ".join(WORDS[i:] + WORDS[:i]) + "᠃" for i in (0, 17)]
    + [" ".join(w if i % 7 else f"{w} 蒙古文字" for i, w in enumerate(WORDS)) + "᠃"])
DOUBLED = Raw("  ".join(WORDS[:20]) + " " + " ".join(WORDS[20:]) + "᠃")


def lines_with_kinds(spans, cell):
    """A column's slots as lines, as `lines_of` makes them, each slot as its
    kind, text and extent along the line."""
    lines, previous = [], None
    for kind, text, top, bottom, x in spans:
        if previous is None or abs(x - previous) > cell / 2:
            lines.append([])
        lines[-1].append((kind, text, top, bottom))
        previous = x
    return lines


def no_line_begins_with_a_space(text):
    """No line begins with a word space, and each column copies as written. A
    line that broke before a space would begin with it, and its first word
    would stand half a cell down from the head of the line (MLReq 7.2: the
    words at a paragraph's upper boundary align). The page must break at a
    space somewhere, a line ending in one or the next beginning with one, or
    the check proves nothing."""
    def check(m, where):
        fails, breaks = [], 0
        paragraphs = text.split("\n\n")
        if len(m["spans"]) != len(paragraphs):
            return [f"{where}: {len(m['spans'])} columns for {len(paragraphs)} paragraphs"]
        for spans, copied, written in zip(m["spans"], m["copied"], paragraphs):
            lines = lines_with_kinds(spans, m["cell"])
            for line in lines[1:]:
                if line[0][0] == "space":
                    fails.append(f"{where}: a line begins with a space, before "
                                 f"{''.join(t for _, t, _, _ in line[1:4])!r}")
            breaks += sum(a[-1][0] == "space" or b[0][0] == "space"
                          for a, b in zip(lines, lines[1:]))
            if copied != written:
                fails.append(f"{where}: copying a column gives {copied[:40]!r}…, "
                             f"not {written[:40]!r}…")
        if not breaks:
            fails.append(f"{where}: no line broke at a space")
        if not fails:
            m["gap"] = (m.get("gap", "") + f"{breaks} breaks at a space, no line "
                        f"beginning with one, and every column copies as written").strip()
        return fails
    return check


def set_lines(m, where, justify):
    """Each column's lines, checked as justified where `justify(c)` says
    column `c` is, and as not justified elsewhere. Either way every line
    begins at the head of its column and a Han character is one cell
    (MLReq 7.3.4: no space is added between Han). Justified (MLReq 7.2),
    every line but the last ends at the column's end, its last slot that is
    not a space there (a space after it hangs past the end and is not
    stretched), and a line's other spaces are one width, no narrower than
    half a cell. Any other space, a paragraph's last line's among them, is
    half a cell, whatever face the page sets it in. Where some column is
    justified, lines that all happened to fill it would prove nothing, so
    some spaces must have grown."""
    fails, justified_lines, stretched, plain = [], 0, 0, 0
    cell = m["cell"]
    for c, (spans, (top, bottom)) in enumerate(zip(m["spans"], m["ends"])):
        lines = lines_with_kinds(spans, cell)
        for i, line in enumerate(lines):
            at = f"{where}: column {c}, line {i}"
            words = [s for s in line if s[0] != "space"]
            last = max(j for j, s in enumerate(line) if s[0] != "space")
            spaces = [s[3] - s[2] for s in line[:last] if s[0] == "space"]
            widths = sorted({round(s, 1) for s in spaces})
            if abs(line[0][2] - top) > 0.5:
                fails.append(f"{at} begins {line[0][2] - top:.1f}px from the column's head")
            for kind, text, start, end in words:
                if kind == "upright" and abs(end - start - cell) > 0.1:
                    fails.append(f"{at}: `{text}` is {end - start:.1f}px, not one cell")
            if justify(c) and i < len(lines) - 1:
                justified_lines += 1
                if abs(words[-1][3] - bottom) > 0.5:
                    fails.append(f"{at} ends {bottom - words[-1][3]:.1f}px from the column's end")
                if spaces and max(spaces) - min(spaces) > 0.1:
                    fails.append(f"{at}: its spaces are {widths}px")
                if spaces and min(spaces) < cell / 2 - 0.1:
                    fails.append(f"{at}: a space is {min(spaces):.1f}px, under half a cell")
                stretched += any(s > cell / 2 + 1 for s in spaces)
                continue
            plain += len(spaces)
            if any(abs(s - cell / 2) > 0.1 for s in spaces):
                fails.append(f"{at}{', the last,' if justify(c) else ''} has spaces of "
                             f"{widths}px, not half a cell")
    if any(justify(c) for c in range(len(m["spans"]))) and not stretched:
        fails.append(f"{where}: no line's spaces grew, so nothing was justified")
    if not fails:
        m["gap"] = (m.get("gap", "") + (f"; {justified_lines} lines justified at their "
                    f"spaces, {stretched} of them stretched," if justified_lines else ";")
                    + f" {plain} other spaces half a cell").strip("; ")
    return fails


def justified(m, where):
    """Every column justified: a page of Mongolian paragraphs."""
    return set_lines(m, where, lambda c: True)


def not_justified(m, where):
    """No column justified: a page of Chinese, which CLReq 6.2.2 would adjust
    in an order of its own."""
    return set_lines(m, where, lambda c: False)


# Slots set as inline text, which a browser may space apart when it justifies
# a line. A Mongolian run, a Latin word and a number are boxes.
TEXT_KINDS = {"upright", "neutral", "vform", "corner", "combine"}


def justified_without_text_justify(m, where):
    """As a browser that does not apply `text-justify` sets the page (#108):
    a column of bichig alone, whose only text is its spaces, is justified
    still, and a column with Han in it is not, so that nothing is added
    between the Han (MLReq 7.3.4). The page must hold both kinds."""
    kinds = [{s[0] for s in spans} for spans in m["spans"]]
    plain = [not k & TEXT_KINDS for k in kinds]
    if all(plain) or not any(plain):
        return [f"{where}: no column of each kind, bichig alone and with Han"]
    return set_lines(m, where, lambda c: plain[c])


def without_text_justify(css):
    """The stylesheet as a browser that does not know `text-justify` reads it:
    every `@supports (text-justify: ...)` false, and the property dropped.
    Comments go first, as they name the property too."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    css = re.sub(r"@supports\s*\(\s*text-justify\s*:[^)]*\)", "@supports (not (display: block))",
                 css)
    return re.sub(r"text-justify\s*:[^;}]*;?", "", css)


# A body that sets Latin first: a space is then the Latin face's, which has
# no vertical metrics, unless the stylesheet sizes the space itself.
LATIN_FIRST = {"body": ["Noto Sans", "Noto Sans SC"]}


CASES = [
    # name, text (or a builder given the column's cells), metadata, window,
    # the faces that must load (the first is the body's), checks, and options:
    # `body`, the body's font stack instead; `stylesheet`, a change to the
    # stylesheet the page links
    ("document-short", PROSE, {}, (900, 700), ["Noto Sans SC"], [whole_cells, line_gap]),
    ("page-short", PROSE, {"vertext-page": "true"}, (900, 500), ["Noto Sans SC"],
     [whole_cells, line_gap]),
    ("marks-together", TOGETHER, {}, (900, 700), ["Noto Sans SC"], [marks_together]),
    ("number-affixes", affixes, {}, (900, 700), ["Noto Sans SC"], [numbers_keep_affixes]),
    ("line-start", line_start, {}, (900, 700), ["Noto Sans SC"], [no_mark_starts_a_line]),
    ("line-end", line_end, {}, (900, 700), ["Noto Sans SC"], [no_mark_ends_a_line]),
    ("beside-a-box", beside_boxes, {}, (900, 700),
     ["Noto Sans SC", "Vertext Noto Sans Mongolian"], [no_mark_beside_a_box_breaks]),
    ("runs", runs, {}, (900, 700), ["Noto Sans SC"], [no_run_overruns]),
    ("bichig-lines", BICHIG, {"vertext-progression": "lr"}, (900, 700),
     ["Noto Sans SC", "Vertext Noto Sans Mongolian"], [line_pitch(["mongolian"])]),
    ("latin-lines", short_latin, {}, (900, 700), ["Noto Sans SC"],
     [line_pitch(["latin", "upright"])]),
    ("spaces-chinese", SPACED_CHINESE, {}, (900, 700), ["Noto Sans SC"],
     [no_line_begins_with_a_space(SPACED_CHINESE), not_justified]),
    ("spaces-bichig", SPACED_BICHIG, {"vertext-progression": "lr"}, (900, 700),
     ["Noto Sans SC", "Vertext Noto Sans Mongolian"],
     [no_line_begins_with_a_space(SPACED_BICHIG), justified]),
    ("doubled-spaces", DOUBLED, {"vertext-progression": "lr"}, (900, 700),
     ["Noto Sans SC", "Vertext Noto Sans Mongolian"],
     [no_line_begins_with_a_space(DOUBLED), justified]),
    # The same, in a body whose font stack puts a Latin face first, as
    # Bootstrap's and Quarto's do.
    ("spaces-chinese-latin-first", SPACED_CHINESE, {}, (900, 700), ["Noto Sans", "Noto Sans SC"],
     [no_line_begins_with_a_space(SPACED_CHINESE), not_justified], LATIN_FIRST),
    ("spaces-bichig-latin-first", SPACED_BICHIG, {"vertext-progression": "lr"}, (900, 700),
     ["Noto Sans", "Noto Sans SC", "Vertext Noto Sans Mongolian"],
     [no_line_begins_with_a_space(SPACED_BICHIG), justified], LATIN_FIRST),
    ("doubled-spaces-latin-first", DOUBLED, {"vertext-progression": "lr"}, (900, 700),
     ["Noto Sans", "Vertext Noto Sans Mongolian"],
     [no_line_begins_with_a_space(DOUBLED), justified], LATIN_FIRST),
    # The bichig again, as Safari or a Chrome before 145 sets it.
    ("spaces-bichig-no-text-justify", SPACED_BICHIG, {"vertext-progression": "lr"}, (900, 700),
     ["Noto Sans SC", "Vertext Noto Sans Mongolian"],
     [no_line_begins_with_a_space(SPACED_BICHIG), justified_without_text_justify],
     {"stylesheet": without_text_justify}),
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
    shutil.copy(MONGOLIAN, work / MONGOLIAN.name)
    for family, path in fonts.items():
        shutil.copy(path, work / path.name)
        FONTS_IN_WORK[family] = path
    fails, lines = [], []
    measured = {}
    for name, text, meta, window, families, checks, *options in CASES:
        options = options[0] if options else {}
        body = options.get("body", families[:1])
        stylesheet = STYLESHEET.name
        if "stylesheet" in options:
            stylesheet = f"{name}.css"
            (work / stylesheet).write_text(options["stylesheet"](
                STYLESHEET.read_text(encoding="utf-8")), encoding="utf-8")
        if callable(text):
            # Measure the column this window and mode give, then build for it.
            key = (window, tuple(sorted(meta.items())))
            if key not in measured:
                probe = _ps.measure(chrome, work, page(args.pandoc, work, f"{name}-probe",
                                                       PROSE, meta, families[:1]), window)
                measured[key] = probe and round(max(probe["heights"]) / probe["cell"])
            if not measured[key]:
                fails.append(f"{name}: the probe page reported no column")
                continue
            cells = measured[key]
            text, checks = text(cells), [built_for(cells), *checks]
        m = _ps.measure(chrome, work, page(args.pandoc, work, name, text, meta, body,
                                           stylesheet), window)
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
          "the lines of a paragraph sit within CLReq's usual gap, and one pitch "
          "apart when they hold only Mongolian or only Latin, marks used "
          "together share a cell, a number keeps its sign and unit, no "
          "closing mark starts a line or opening mark ends one, no run of "
          "one mark runs past a column's end, no line begins with a word space, "
          "a space is half a cell whatever face the body puts first, and a "
          "Mongolian paragraph is justified at its spaces, one with Han in it "
          "only where the browser applies `text-justify`")
    for line in lines:
        print("      " + line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
