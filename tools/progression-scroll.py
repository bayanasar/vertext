#!/usr/bin/env python3
"""A document opens at its first column, in either progression (#52).

Columns advance right-to-left for CJK (`vertical-rl`) and left-to-right for
traditional Mongolian (`vertical-lr`). In document mode the content region is
a scroller, and its writing mode decides where the scroll starts: the right
edge under `vertical-rl`, the left edge under `vertical-lr`. A region that
does not follow the declared progression still renders every column in the
right order -- it just opens at the end of the text, with the first column
scrolled out of view. Nothing about that looks broken until someone tries to
start reading.

For each progression this renders a document long enough to overflow through
pandoc, the real filter and the binary, sets it in the structure Quarto gives
a page (`main.content`) with the filter's own document-mode style and the
shipped stylesheet, opens it in headless Chrome, and requires that the first
column is inside the viewport on load while the text as a whole overflows it.
Shown red by writing `vertical-rl` back into the document-mode region: the
`lr` document then opens with its first column off the left edge.

The page POSTs its measurements back and this waits for them in real time; a
virtual-time budget does not wait for fonts (see tools/wasm-caret.py).

Usage
-----
    cargo build --release -p vertext-cli
    python3 tools/progression-scroll.py [--pandoc PATH] [--chrome PATH]
"""

import argparse
import functools
import http.server
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
SHIM = ROOT / "tools" / "quarto-shim.lua"
STYLESHEET = ROOT / "extensions" / "vertext" / "vertext.css"
FONT = ROOT / "goldens" / "fonts" / "NotoSansMongolian-Regular.ttf"
WINDOW = (900, 700)

TEXT = {
    "rl": "山川异域，风月同天。寄诸佛子，共结来缘。",
    "lr": "ᠮᠣᠩᠭᠣᠯ\u202fᠤᠨ ᠪᠢᠴᠢᠭ ᠪᠣᠯ ᠡᠷᠲᠡ ᠦᠶ\u180eᠡ\u202fᠡᠴᠡ ᠤᠯᠠᠮᠵᠢᠯᠠᠭᠰᠠᠨ ᠪᠢᠴᠢᠭ ᠮᠥᠨ᠃",
}

MEASURE = """
<script>
document.fonts.ready.then(() => {
  const region = document.querySelector('main.content');
  const columns = [...document.querySelectorAll('.vertext-column')]
    .filter(c => c.textContent.trim());
  const box = c => { const r = c.getBoundingClientRect(); return [r.left, r.right]; };
  const result = {
    writingMode: getComputedStyle(region).writingMode,
    scrollWidth: region.scrollWidth,
    clientWidth: region.clientWidth,
    viewport: innerWidth,
    first: box(columns[0]),
    last: box(columns[columns.length - 1]),
    columns: columns.length,
  };
  fetch('result', { method: 'POST', body: JSON.stringify(result) });
});
</script>
"""


def find_chrome(given):
    if given:
        return pathlib.Path(given)
    found = sorted((pathlib.Path.home() / ".cache" / "puppeteer")
                   .glob("chrome*/*/chrome*-linux64/chrome*"))
    found = [f for f in found if f.is_file() and f.name in ("chrome", "chrome-headless-shell")]
    if not found:
        sys.exit("no chrome found -- pass --chrome")
    return found[-1]


def page(pandoc, progression, work):
    """The rendered document, set the way a Quarto page sets it."""
    source = work / f"doc-{progression}.md"
    paragraphs = "\n\n".join(TEXT[progression] * 3 for _ in range(30))
    source.write_text(f"---\nvertext: true\nvertext-progression: {progression}\n---\n\n"
                      f"{paragraphs}\n", encoding="utf-8")
    env = dict(os.environ, PATH=f"{BINARY.parent}:{os.environ['PATH']}")
    done = subprocess.run([pandoc, "-s", "-f", "markdown", "-t", "html", "--wrap=none",
                           "--metadata", "title=progression", f"--lua-filter={SHIM}",
                           str(source)], capture_output=True, text=True, env=env, timeout=120)
    if done.returncode != 0:
        sys.exit(f"pandoc failed:\n{done.stderr[-2000:]}")
    out = done.stdout
    if 'id="vertext-document-mode"' not in out:
        sys.exit(f"{progression}: the filter emitted no document-mode style")
    head, _, rest = out.partition("<body>")
    body, _, tail = rest.partition("</body>")
    head = head.replace("</head>", '<link rel="stylesheet" href="vertext.css">\n'
                        f'<style>@font-face {{ font-family: "Noto Sans Mongolian"; '
                        f'src: url("{FONT.name}"); }}</style>\n</head>', 1)
    return (f'{head}<body><main class="content" id="quarto-document-content">'
            f'{body}</main>{MEASURE}</body>{tail}')


def measure(chrome, work, name, window=WINDOW):
    """Open `name` from `work` in headless Chrome and wait for its POST."""
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
    profile = tempfile.mkdtemp(prefix="vertext-progression-profile-")
    browser = subprocess.Popen(
        [str(chrome), "--headless", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
         f"--window-size={window[0]},{window[1]}", f"--user-data-dir={profile}",
         f"http://127.0.0.1:{server.server_address[1]}/{name}"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        return reports.get(timeout=120)
    except queue.Empty:
        return None
    finally:
        browser.kill()
        browser.wait()
        server.shutdown()
        shutil.rmtree(profile, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pandoc", default="pandoc")
    ap.add_argument("--chrome")
    args = ap.parse_args()
    if not BINARY.exists():
        sys.exit(f"no binary at {BINARY} -- cargo build --release -p vertext-cli")
    chrome = find_chrome(args.chrome)

    work = pathlib.Path(tempfile.mkdtemp(prefix="vertext-progression-"))
    shutil.copy(STYLESHEET, work / STYLESHEET.name)
    shutil.copy(FONT, work / FONT.name)
    fails, lines = [], []
    for progression, mode in (("rl", "vertical-rl"), ("lr", "vertical-lr")):
        name = f"page-{progression}.html"
        (work / name).write_text(page(args.pandoc, progression, work), encoding="utf-8")
        m = measure(chrome, work, name)
        if m is None:
            fails.append(f"{progression}: the page reported nothing within 120s")
            continue
        left, right = m["first"]
        if m["scrollWidth"] <= m["clientWidth"]:
            fails.append(f"{progression}: the text does not overflow the region "
                         f"({m['scrollWidth']} <= {m['clientWidth']}), so this proves nothing")
        if m["writingMode"] != mode:
            fails.append(f"{progression}: the region is {m['writingMode']}, not {mode}")
        if right <= 0 or left >= m["viewport"]:
            fails.append(f"{progression}: the first column opens at x={left:.0f}..{right:.0f}, "
                         f"outside the {m['viewport']}px viewport; the last is at "
                         f"x={m['last'][0]:.0f}")
        lines.append(f"{progression}: {m['columns']} columns in a {m['clientWidth']}px region "
                     f"scrolling {m['scrollWidth']}px; the first opens at x={left:.0f}")
    shutil.rmtree(work, ignore_errors=True)
    for line in fails:
        print("FAIL: " + line)
    if fails:
        return 1
    print("PASS: in both progressions a document that overflows opens at its first column")
    for line in lines:
        print("      " + line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
