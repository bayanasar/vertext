#!/usr/bin/env python3
"""Every bracket, quote and pause or stop mark takes one cell along the column,
in Chrome and in Firefox, whatever kerning the page asks for, alone or beside
another mark.

CLReq 6.3.2: a mark between characters usually occupies one em. Whether to
narrow it is a style; many Taiwan publications do not. vertext narrows none
(CONFORMANCE 6.3.2), and its column lengths count cells on that basis.

The faces carry proportional vertical metrics for these marks (`vpal`), half a
cell for most of them. HarfBuzz leaves that feature off unless asked. Firefox
140 turns it on under `font-kerning: normal`, which pandoc's standalone
template sets on the body, so on such a page Noto Sans SC set `说「好` with the
bracket in half a cell, and `，` and `。` too, where Chrome set one cell each.
The stylesheet now turns kerning off for the cells. Chrome does not do this,
so this gate has to run in Firefox to be able to fail.

Chrome narrows on its own instead: by default (`text-spacing-trim: normal`)
Chrome 152 set one of two adjacent marks in half a cell, the first in `」，`
and `）、`, the opening bracket in `」「` and `。「`, on either page. Firefox
140 trims neither, so this half of the gate can fail only in Chrome. The
stylesheet now asks for `text-spacing-trim: space-all` on the cells.

Each mark is set between two Han characters, `口<mark>口`, and so is each pair
of marks, exactly as the binary renders it, with the shipped stylesheet and a
pinned face, twice: on a plain page, and under the body rule of pandoc's
template. The page reports every slot's extent along the column, and each must
be one cell to within half a pixel.

Usage
-----
    cargo build --release -p vertext-cli
    python3 tools/cell-advance.py [--chrome PATH] [--firefox PATH] [--fonts DIR]
"""

import argparse
import functools
import http.server
import importlib.util
import json
import pathlib
import queue
import shutil
import subprocess
import sys
import tempfile
import threading

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

CELL = 48
MARKS = "「」『』（）《》〈〉【】〔〕“”‘’、，。．；：！？"
# Two marks side by side, of the kinds CLReq 3.1.6 lists as adjacent: a
# closing bracket before a pause or stop mark and after one, two closing or
# two opening brackets, a closing bracket or a pause or stop mark before an
# opening bracket.
PAIRS = ["」，", "」。", "）、", "』；", "。」", "，」", "！」", "』」", "）」",
         "「『", "（「", "」「", "）（", "。「", "，（", "：「"]
ITEMS = list(MARKS) + PAIRS
ROWS = -(-len(ITEMS) // len(MARKS))
# (lang attribute or None, face)
FACES = [
    (None, "Noto Sans SC"),
    ("zh-CN", "Noto Sans CJK SC"),
    ("zh-Hant", "Noto Sans TC"),
]
# The body rule of pandoc's standalone template (styles.html), the part of it
# that reaches shaping.
PANDOC_BODY = "text-rendering: optimizeLegibility; font-kerning: normal;"
LEGS = [("plain page", ""), ("pandoc's font-kerning: normal", PANDOC_BODY)]
WINDOW = (len(MARKS) * 2 * CELL, len(LEGS) * len(FACES) * ROWS * 5 * CELL)


def column_html(text):
    done = subprocess.run([str(BINARY), "html"], input=text, capture_output=True,
                          text=True, check=True)
    return done.stdout


def build(fonts):
    faces = "".join(f'@font-face {{ font-family: "{f}"; src: url("{p.name}"); }}\n'
                    for f, p in fonts.items())
    rows = []
    for leg, rule in LEGS:
        cells = "".join(
            f'<div class="box" data-leg="{leg}" data-face="{face}" data-mark="{item}"'
            f'{f" lang={lang}" if lang else ""} style="font-family: &quot;{face}&quot;">'
            f'{column_html(f"口{item}口")}</div>'
            for lang, face in FACES for item in ITEMS)
        rows.append(f'<div class="leg" style="{rule}">{cells}</div>')
    return f"""<!doctype html><meta charset="utf-8">
<style>
{faces}
{STYLESHEET.read_text(encoding="utf-8")}
:root {{ --vertext-cell: {CELL}px; }}
html, body {{ margin: 0; padding: 0; background: #fff; color: #000; }}
.leg {{ display: grid; grid-template-columns: repeat({len(MARKS)}, {2 * CELL}px); }}
.box {{ position: relative; width: {2 * CELL}px; height: {5 * CELL}px; overflow: hidden; }}
.box .vertext {{ position: absolute; top: 0; right: 0; padding: 0; border: 0;
                 gap: 0; min-block-size: 0; overflow: visible; }}
</style>
{"".join(rows)}
<script>
document.fonts.ready.then(() => {{
  const cells = [...document.querySelectorAll('.box')].map(box => ({{
    leg: box.dataset.leg, face: box.dataset.face, mark: box.dataset.mark,
    slots: [...box.querySelectorAll('.vertext-column span')]
      .filter(s => !s.classList.contains('vertext-nobreak'))
      .map(s => [s.textContent, s.className, s.getBoundingClientRect().height]),
  }}));
  // Firefox names a loaded family with its quotes, Chrome without.
  const loaded = [...document.fonts].filter(f => f.status === 'loaded')
    .map(f => f.family.replace(/^"|"$/g, ''));
  fetch('result', {{ method: 'POST', body: JSON.stringify(
    {{ browser: navigator.userAgent, loaded, cells }}) }});
}});
</script>
"""


def measure(kind, browser, work, name):
    """Open `name` from `work` in `browser` and wait for the page's report."""
    reports = queue.Queue()

    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            self.send_response(204)
            self.end_headers()
            reports.put(json.loads(body))

    handler = functools.partial(Handler, directory=str(work))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    profile = tempfile.mkdtemp(prefix=f"vertext-cell-advance-{kind}-")
    url = f"http://127.0.0.1:{server.server_address[1]}/{name}"
    size = f"{WINDOW[0]},{WINDOW[1]}"
    if kind == "chrome":
        command = [str(browser), "--headless", "--no-sandbox", "--disable-gpu",
                   "--disable-dev-shm-usage", "--hide-scrollbars",
                   f"--window-size={size}", f"--user-data-dir={profile}", url]
    else:
        command = [str(browser), "--headless", "--no-remote", "--profile", profile,
                   f"--window-size={size}", url]
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
    try:
        return reports.get(timeout=120)
    except queue.Empty:
        return None
    finally:
        process.kill()
        process.wait()
        server.shutdown()
        shutil.rmtree(profile, ignore_errors=True)


def problems(report):
    fails = []
    for face in dict.fromkeys(face for _, face in FACES):
        if face not in report["loaded"]:
            fails.append(f"{face} did not load ({report['loaded']}), so the advances "
                         f"measured are not that face's")
    for cell in report["cells"]:
        where = f"{cell['mark']} in {cell['face']}, {cell['leg']}"
        if [text for text, _, _ in cell["slots"]] != ["口", *cell["mark"], "口"]:
            fails.append(f"{where}: the column is not one slot a character: "
                         f"{cell['slots']}")
            continue
        for text, kind, advance in cell["slots"]:
            if abs(advance - CELL) > 0.5:
                fails.append(f"{where}: {text} ({kind}) takes {advance / CELL:.2f} "
                             f"of a cell")
    return fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chrome")
    ap.add_argument("--firefox", help="also run in this Firefox")
    ap.add_argument("--fonts", default=str(pathlib.Path.home() / ".cache" / "vertext-fonts"))
    args = ap.parse_args()
    if not BINARY.exists():
        sys.exit(f"no binary at {BINARY} -- cargo build --release -p vertext-cli")
    browsers = [("chrome", _bg.find_chrome(args.chrome))]
    if args.firefox:
        browsers.append(("firefox", pathlib.Path(args.firefox)))
    fonts = _pg.fetch_fonts(pathlib.Path(args.fonts))

    work = pathlib.Path(tempfile.mkdtemp(prefix="vertext-cell-advance-"))
    try:
        for path in fonts.values():
            shutil.copy(path, work / path.name)
        (work / "marks.html").write_text(build(fonts), encoding="utf-8")
        fails, ran = [], []
        for kind, browser in browsers:
            report = measure(kind, browser, work, "marks.html")
            if report is None:
                fails.append(f"{kind}: the page never reported")
                continue
            ran.append(report["browser"].rsplit(") ", 1)[-1])
            fails += [f"{kind}: {f}" for f in problems(report)]
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if fails:
        print(f"FAIL: {len(fails)} problem(s)")
        for f in fails:
            print(f"  {f}")
        sys.exit(1)
    print(f"PASS: each of {len(MARKS)} marks, and each mark of {len(PAIRS)} adjacent "
          f"pairs, takes one cell between two Han characters in {len(FACES)} faces, on "
          f"a plain page and under font-kerning: normal, in " + " and ".join(ran))


if __name__ == "__main__":
    main()
