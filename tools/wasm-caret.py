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

The page also has to refuse a module from another release (#46). The .wasm and
vertext.mjs travel as two files, and either can be the stale one, so the page
is loaded three more times: with the glue's WIRE_VERSION changed by one digit,
with the version string inside the .wasm changed by one digit, and with the
version export renamed away, which is what a module from before the handshake
looks like. Each time `load()` must refuse, and the page must name both sides.

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
WASM = ROOT / "target" / "wasm32-unknown-unknown" / "release" / "vertext_wasm.wasm"
FONT = ROOT / "goldens" / "fonts" / "NotoSansMongolian-Regular.ttf"

# The release archive's builder: its version reader and the module's name.
_spec = importlib.util.spec_from_file_location("wasm_archive", ROOT / "tools" / "wasm-archive.py")
archive = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(archive)
MODULE = archive.MODULE_NAME


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
                   ROOT / "extensions" / "vertext" / "vertext.css", FONT):
        shutil.copy(source, work / source.name)
    # Under the name the release archive gives it, so the page is exercised the
    # way a host that took both files from the release would serve them.
    shutil.copy(WASM, work / MODULE)
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

    fails = refusals(chrome, work)
    for line in fails:
        print("FAIL: " + line)
    if fails:
        return 1
    print(f"PASS: {result['clicks']} clicks on graphemes land the textarea caret on "
          f"that character, and {result['follows']} caret moves outline their slot")
    print("      and the page refuses, naming both sides, when the glue or the "
          "module is from another release or the module predates the handshake")
    return 0


def other(version):
    """`version` with its first digit changed, so its length stays the same."""
    return ("9" if version[0] != "9" else "8") + version[1:]


def refusals(chrome, work):
    """Load the page against a mismatched pair three ways; each must refuse."""
    glue = (work / "vertext.mjs").read_text(encoding="utf-8")
    # The same reader the release archive uses, so the two cannot disagree
    # about which version the crate declares.
    crate, wire = archive.versions()
    if not (wire and crate):
        return ["could not read the glue's WIRE_VERSION or the crate version"]
    module = WASM.read_bytes()
    if module.count(crate.encode()) != 1 or b"vertext_version" not in module:
        return [f"the module should carry {crate} exactly once and export vertext_version, "
                f"or the patched modules below are not the cases they claim to be"]

    cases = [
        ("the glue speaks another version", [other(wire), crate],
         "vertext.mjs", glue.replace(f"WIRE_VERSION = '{wire}'", f"WIRE_VERSION = '{other(wire)}'").encode()),
        ("the module is another version", [other(crate), wire],
         MODULE, module.replace(crate.encode(), other(crate).encode())),
        ("the module predates the handshake", ["before the version handshake", wire],
         MODULE, module.replace(b"vertext_version", b"vertext_versioX")),
    ]
    fails = []
    for name, wanted, file, content in cases:
        case = pathlib.Path(tempfile.mkdtemp(prefix="vertext-caret-refuse-"))
        shutil.copytree(work, case, dirs_exist_ok=True)
        (case / file).write_bytes(content)
        result = run_page(chrome, case, "?selftest")
        if result is None or "refused" not in result:
            fails.append(f"{name}: the page did not refuse: {result}")
            continue
        missing = [w for w in wanted if w not in result["refused"]]
        if missing:
            fails.append(f"{name}: the refusal does not say {missing}: {result['refused']!r}")
    return fails


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
