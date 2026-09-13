#!/usr/bin/env python3
"""The caret host in examples/wasm, driven in a real browser (#12, #13).

The source map in vertext-core is only worth its API if something puts a caret
with it. examples/wasm/caret.html does: a textarea is the document, the wasm
module renders it vertically, a click on a glyph moves the textarea caret to
that character, and moving the textarea caret outlines the slot. Its
`?selftest` mode clicks every grapheme of every slot through the browser's own
hit test (`caretRangeFromPoint`) and moves the caret onto every slot, then
reports; this script serves the page, runs it headless and fails on any finding.

The Mongolian run in the page is the case that matters: one slot, and a click
between two of its letters has to land between those letters, not at the start
of the run. Shown red by fixing the grapheme index at 0.

Usage
-----
    cargo build --release -p vertext-wasm --target wasm32-unknown-unknown
    python3 tools/wasm-caret.py [--chrome PATH]
"""

import argparse
import functools
import html
import http.server
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import threading

ROOT = pathlib.Path(__file__).resolve().parent.parent
WASM = ROOT / "target" / "wasm32-unknown-unknown" / "release" / "vertext_wasm.wasm"
FONT = ROOT / "goldens" / "fonts" / "NotoSansMongolian-Regular.ttf"


def find_chrome(given):
    if given:
        return pathlib.Path(given)
    found = sorted((pathlib.Path.home() / ".cache" / "puppeteer")
                   .glob("chrome*/*/chrome*-linux64/chrome*"))
    found = [f for f in found if f.is_file() and f.name in ("chrome", "chrome-headless-shell")]
    if not found:
        sys.exit("no chrome found -- pass --chrome")
    return found[-1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chrome")
    args = ap.parse_args()
    if not WASM.exists():
        sys.exit(f"no wasm at {WASM} -- cargo build --release -p vertext-wasm "
                 f"--target wasm32-unknown-unknown")
    chrome = find_chrome(args.chrome)

    work = pathlib.Path(tempfile.mkdtemp(prefix="vertext-caret-"))
    for source in (ROOT / "examples" / "wasm" / "caret.html",
                   ROOT / "examples" / "wasm" / "vertext.mjs",
                   ROOT / "extensions" / "vertext" / "vertext.css", WASM, FONT):
        shutil.copy(source, work / source.name)
    # The pinned face under the family the shipped stylesheet asks for, as the
    # browser golden does, so the run is laid out in the font the goldens use.
    page = work / "caret.html"
    page.write_text(page.read_text(encoding="utf-8").replace(
        "</head>", f'<style>@font-face {{ font-family: "Noto Sans Mongolian"; '
                   f'src: url("{FONT.name}"); }}</style>\n</head>', 1), encoding="utf-8")

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    handler = functools.partial(Quiet, directory=str(work))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/caret.html?selftest"
    try:
        done = subprocess.run(
            [str(chrome), "--headless", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
             "--window-size=1280,900", "--virtual-time-budget=30000", "--dump-dom", url],
            capture_output=True, text=True, timeout=180)
    finally:
        server.shutdown()
    found = re.search(r'<pre id="selftest">([^<]*)</pre>', done.stdout)
    if not found:
        sys.exit(f"the page reported nothing\n{done.stderr[-1500:]}")
    result = json.loads(html.unescape(found.group(1)))
    if result["failed"] or not result["clicks"] or not result["follows"]:
        print(f"FAIL: {result['failed']} finding(s) over {result['clicks']} clicks "
              f"and {result['follows']} caret moves")
        for line in result["fails"]:
            print("  " + line)
        return 1
    print(f"PASS: {result['clicks']} clicks on graphemes land the textarea caret on "
          f"that character, and {result['follows']} caret moves outline their slot")
    return 0


if __name__ == "__main__":
    sys.exit(main())
