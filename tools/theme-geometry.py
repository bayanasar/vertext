#!/usr/bin/env python3
"""On a page in vertext-theme, the page's table of contents stands under the
text, at any window height.

A horizontal page's TOC stands beside the text however wide the window is.
The theme set the vertical page's TOC strip at the window's bottom edge, and
the text stops at its measure (`vertext-column-chars:` cells, 34 by default),
so a taller window opened a gap between the two: at 1600x2200 the text ended
at 638px and the strip began at 1921px. The region now runs no deeper than
the text needs, and the strip is pinned under the region.

Two pages through Quarto, the theme and the binary, each at three window
sizes: a page with no section sidebar, and a book's chapter under its chapter
strip. At each size the strip must begin under the text's last column, no
further than CLEARANCE below it, and end inside the window; where the window
has room, a column must keep its whole measure.

Quarto is not on the CI runners, so this runs where Quarto is, as
`examples/test-extension.sh` does.

Usage
-----
    cargo build --release -p vertext-cli
    python3 tools/theme-geometry.py --quarto PATH [--chrome PATH] [--stylesheet SCSS]
"""

import argparse
import functools
import http.server
import importlib.util
import json
import os
import pathlib
import queue
import shutil
import subprocess
import sys
import tempfile
import threading

ROOT = pathlib.Path(__file__).resolve().parent.parent
BINARY = ROOT / "target" / "release" / "vertext"


def _load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_bg = _load("browser_golden", "browser-golden.py")

CELL = 18
CHARS = 34
# The gap the theme keeps between a column's end and the region's (2rem), the
# wrapper's border and padding, and the rounding of a line to the cell.
CLEARANCE = 64
SIZES = [(1280, 700), (1600, 1600), (1600, 2200)]
PARA = "鬱鬱澗底松，離離山上苗。以彼徑寸莖，蔭此百尺條。世冑躡高位，英俊沉下僚。地勢使之然，由來非一朝。" * 2
SECTIONS = "".join(f"## {h}\n\n{PARA}\n\n{PARA}\n\n" for h in ["第一節", "第二節", "第三節"])
FORMAT = "format:\n  vertext-theme-html:\n    theme: [cosmo, vertext-theme.scss]\n"
PAGES = {
    "page": {
        "_quarto.yml": "project:\n  type: default\nlang: zh-Hant\n",
        "page.qmd": f"---\ntitle: \"目錄位置\"\n{FORMAT}---\n\n{SECTIONS}",
    },
    "book": {
        "_quarto.yml": ("project:\n  type: book\nlang: zh-Hant\nbook:\n  title: \"試驗書\"\n"
                        f"  chapters:\n    - index.qmd\n    - chapter.qmd\n{FORMAT}"),
        "index.qmd": f"# 前言\n\n{PARA}\n",
        "chapter.qmd": f"# 目錄位置\n\n{SECTIONS}",
    },
}
OPENED = {"page": "page.html", "book": "_book/chapter.html"}

MEASURE = """<script>
window.addEventListener('load', () => document.fonts.ready.then(() => setTimeout(() => {
  const columns = [...document.querySelectorAll('main .vertext-column')]
    .filter(c => c.textContent.trim());
  const strip = document.querySelector('#quarto-margin-sidebar');
  const s = strip && strip.getBoundingClientRect();
  fetch('/result', { method: 'POST', body: JSON.stringify({
    window: innerHeight,
    textEnd: Math.max(...columns.map(c => c.getBoundingClientRect().bottom)),
    measure: Math.max(...columns.map(c => parseFloat(getComputedStyle(c).height))),
    strip: s && s.height ? [s.top, s.bottom] : null,
  }) });
}, 500)));
</script>"""


def render(quarto, work, name, stylesheet):
    site = work / name
    (site / "_extensions").mkdir(parents=True)
    shutil.copytree(ROOT / "extensions" / "vertext-theme", site / "_extensions" / "vertext-theme")
    shutil.copytree(ROOT / "extensions" / "vertext", site / "_extensions" / "vertext")
    shutil.copy(stylesheet, site / "vertext-theme.scss")
    for file, text in PAGES[name].items():
        (site / file).write_text(text, encoding="utf-8")
    env = dict(os.environ, PATH=f"{BINARY.parent}:{pathlib.Path(quarto).parent}:{os.environ['PATH']}")
    done = subprocess.run([str(quarto), "render", "--quiet"], cwd=site, env=env,
                          capture_output=True, text=True, timeout=600)
    if done.returncode != 0:
        sys.exit(f"{name}: quarto render failed:\n{done.stderr[-2000:]}")
    page = site / OPENED[name]
    page.write_text(page.read_text(encoding="utf-8").replace("</body>", MEASURE + "</body>"),
                    encoding="utf-8")
    return site


def measure(chrome, site, page, size):
    reports = queue.Queue()

    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            self.send_response(204)
            self.end_headers()
            reports.put(json.loads(body))

    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(Handler, directory=str(site)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    profile = tempfile.mkdtemp(prefix="vertext-theme-geometry-")
    process = subprocess.Popen(
        [str(chrome), "--headless", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage",
         "--hide-scrollbars", f"--window-size={size[0]},{size[1]}", f"--user-data-dir={profile}",
         f"http://127.0.0.1:{server.server_address[1]}/{page}"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        return reports.get(timeout=120)
    except queue.Empty:
        return None
    finally:
        process.kill()
        process.wait()
        server.shutdown()
        shutil.rmtree(profile, ignore_errors=True)


def problems(name, size, m):
    where = f"{name} at {size[0]}x{size[1]}"
    if m is None:
        return [f"{where}: the page never reported"]
    if not m["strip"]:
        return [f"{where}: no TOC strip on the page"]
    fails = []
    top, bottom = m["strip"]
    gap = top - m["textEnd"]
    if not 0 <= gap <= CLEARANCE:
        fails.append(f"{where}: the TOC strip begins {gap:.0f}px under the text's end, "
                     f"want 0 to {CLEARANCE}px (text ends at {m['textEnd']:.0f}px, "
                     f"the window at {m['window']}px)")
    if bottom > m["window"] + 0.5:
        fails.append(f"{where}: the TOC strip ends at {bottom:.0f}px, past the window's "
                     f"{m['window']}px")
    if size[1] >= 1600 and abs(m["measure"] - CHARS * CELL) > 0.5:
        fails.append(f"{where}: a column is {m['measure']:.0f}px long, not its whole "
                     f"measure of {CHARS * CELL}px")
    return fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quarto", required=True)
    ap.add_argument("--chrome")
    ap.add_argument("--stylesheet", default=str(ROOT / "extensions" / "vertext-theme" /
                                                "vertext-theme.scss"),
                    help="the theme's scss to render with (to prove the gate on another)")
    args = ap.parse_args()
    if not BINARY.exists():
        sys.exit(f"no binary at {BINARY} -- cargo build --release -p vertext-cli")
    chrome = _bg.find_chrome(args.chrome)
    quarto = shutil.which(args.quarto)
    if not quarto:
        sys.exit(f"no quarto at {args.quarto}")
    args.quarto = pathlib.Path(quarto).resolve()
    work = pathlib.Path(tempfile.mkdtemp(prefix="vertext-theme-geometry-"))
    fails, seen = [], []
    try:
        for name in PAGES:
            site = render(args.quarto, work, name, args.stylesheet)
            for size in SIZES:
                m = measure(chrome, site, OPENED[name], size)
                fails += problems(name, size, m)
                if m and m["strip"]:
                    seen.append(f"{name} {size[0]}x{size[1]}: text ends {m['textEnd']:.0f}, "
                                f"strip {m['strip'][0]:.0f}-{m['strip'][1]:.0f}, "
                                f"window {m['window']}")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if fails:
        print(f"FAIL: {len(fails)} problem(s)")
        for f in fails:
            print(f"  {f}")
        sys.exit(1)
    print(f"PASS: on a page and on a book's chapter in vertext-theme, at {len(SIZES)} window "
          f"heights, the TOC strip begins within {CLEARANCE}px under the text and ends inside "
          f"the window, and a window with room keeps the whole measure")
    for line in seen:
        print(f"      {line}")


if __name__ == "__main__":
    main()
