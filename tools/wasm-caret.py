#!/usr/bin/env python3
"""The caret host in examples/wasm, driven in a real browser (#12, #13).

The source map in vertext-core is only worth its API if something puts a caret
with it. examples/wasm/caret.html does: a textarea is the document, the wasm
module renders it vertically, a click on a glyph moves the textarea caret to
that character, and moving the textarea caret outlines the slot. Its
`?selftest` mode clicks every grapheme of every slot through the browser's own
hit test (`caretRangeFromPoint`) and moves the caret onto every slot, then
POSTs a report; this script serves the page, runs it headless, waits for that
report and fails on any finding.

It waits in real time rather than dumping the DOM after a virtual-time budget:
virtual time does not wait for the font or the wasm compile, and the dump came
back before `document.fonts.ready` had resolved in about one run in five.

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
import http.server
import json
import pathlib
import queue
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

    result = run_page(chrome, work, "?selftest")
    if result is None:
        sys.exit("the page reported nothing within 120s")
    if result["failed"] or not result["clicks"] or not result["follows"]:
        print(f"FAIL: {result['failed']} finding(s) over {result['clicks']} clicks "
              f"and {result['follows']} caret moves")
        for line in result["fails"]:
            print("  " + line)
        return 1
    print(f"PASS: {result['clicks']} clicks on graphemes land the textarea caret on "
          f"that character, and {result['follows']} caret moves outline their slot")
    return 0


def run_page(chrome, work, query):
    """Serve `work`, open caret.html with `query` headless, and return the JSON
    the page POSTs to `selftest`, or None if nothing arrives in time."""
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
    url = f"http://127.0.0.1:{server.server_address[1]}/caret.html{query}"
    profile = tempfile.mkdtemp(prefix="vertext-caret-profile-")
    browser = subprocess.Popen(
        [str(chrome), "--headless", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
         "--window-size=1280,900", f"--user-data-dir={profile}", url],
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


if __name__ == "__main__":
    sys.exit(main())
