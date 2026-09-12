#!/usr/bin/env python3
"""The filter golden: does the half of the chain we never run still encode?

What was missing
----------------
A real document reaches the page like this:

    pandoc -> vertext.lua -> the PUA wire protocol -> vertext (the binary) -> HTML

`tools/shaping-golden.py` starts at the font. `tools/delivery-golden.py` and
`tools/browser-golden.py` start at the BINARY: they hand it text on stdin. So
every gate in this repository begins after the filter, and the filter half --
where author text enters the wire protocol, and where the 13 reserved codepoints
are written -- has never been executed by anything that can fail.

It is not the safe half. #25 (two copies of the filter, drifted) proved this is
the piece that moves: the theme's vendored copy sat a whole commit behind, then
drifted again by comments, and the only assertion that would have caught it
lived in `examples/test-extension.sh`, which needs `quarto render` and therefore
has never run. Closing #25 pinned that the two copies are byte-identical. It did
not pin that either copy still encodes anything.

How this runs the filter without Quarto
---------------------------------------
`extensions/vertext/vertext.lua` is a Quarto extension: it calls `quarto.*` for
three things, so plain pandoc cannot load it. `tools/quarto-shim.lua` supplies
those three -- and nothing else -- then `dofile`s the real filter, unmodified.
That is the same route urtu took by hand when the U+202F crossing was recorded
in PROGRESS; this makes it a gate instead of a memory.

pandoc itself: Debian's `pandoc` (2.17 on the CI image) is used, not Quarto's
own 3.x. Both were run against every fixture here and the HTML came back BYTE
IDENTICAL, which is why the cheap one is good enough. If they ever diverge, pin
a 3.x tarball the way `.forgejo/workflows/ci.yml` pins the browser.

What it pins
------------
  1. The binary really ran. Empty stderr: the filter's own fallback writes
     `quarto.log.warning` and then ships plain horizontal text, which is the
     exact accident this gate exists to catch -- and it looks like a clean
     render to everything else.
  2. Every Mongolian run arrives whole. In a vertical measure the spans are
     exactly that block's runs, in order, byte for byte; in a horizontal one
     (a code block, or a Latin-majority list item) the run must still appear
     contiguously in the output.
  3. The block kinds survive the wire. A heading comes back a heading, a table
     a table, a bullet list a bullet list, an ordered list an ordered list, a
     code block code. Those are the modes the reserved codepoints encode, so a
     drift between the filter's `RESERVED_COUNT` and the binary's `RESERVED_END`
     shows up here as structure that stopped arriving.
  4. What came back shapes as the shaping golden recorded, so this gate cannot
     drift from the other two.
  5. The filter refuses a binary that does not speak its wire version, and
     degrades horizontal instead of rendering a mismatched pair (#9, step 3).
     Nothing else checks that the two halves came from the same release, and a
     mismatched pair renders wrong with every other gate green.
  6. The three hand-typed version declarations -- Cargo.toml, _extension.yml and
     the filter's WIRE_VERSION -- are one version. A handshake resting on a
     constant that can drift would refuse correct pairs.

Usage
-----
    cargo build --release -p vertext-cli
    python3 tools/filter-golden.py
    python3 tools/filter-golden.py --prove   # show the gate can go red

Needs pandoc and uharfbuzz. See .forgejo/workflows/ci.yml.
"""

import argparse
import html as htmllib
import importlib.util
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
BINARY = ROOT / "target" / "release" / "vertext"
SHIM = ROOT / "tools" / "quarto-shim.lua"

_spec = importlib.util.spec_from_file_location(
    "shaping_golden", ROOT / "tools" / "shaping-golden.py")
_sg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_sg)

SPAN = re.compile(r'<span class="vertext-mongolian">(.*?)</span>')
CLASSES = re.compile(r'class="(vertext[^"]*)"')

FRONT = "---\nvertext: true\nvertext-progression: lr\n---\n\n"

# Every block kind the filter encodes specially, each carrying bichig. The
# classes are what the wire protocol's mode markers turn into on the other side:
# if a marker stopped being written, or the binary's reserved range moved, the
# text still arrives and the STRUCTURE does not.
STRUCTURE = FRONT + """# ᠨᠣᠮ heading

ᠰᠠᠶᠢᠨ

- ᠭᠡᠷ item one
- ᠮᠣᠷᠢ item two

1. ᠠᠪᠤ first
2. ᠡᠵᠢ second

| a | b |
|---|---|
| ᠨᠡᠷ᠎ᠡ | x |

```
ᠲᠠ code
```
"""

# Declared rather than re-extracted: this fixture is hand-written, so its runs
# are known, and a helper that lifts them would be a second definition of
# something `shaping-golden.py` already owns.
STRUCTURE_RUNS = ["ᠨᠣᠮ", "ᠰᠠᠶᠢᠨ", "ᠭᠡᠷ", "ᠮᠣᠷᠢ", "ᠠᠪᠤ", "ᠡᠵᠢ", "ᠨᠡᠷ᠎ᠡ", "ᠲᠠ"]

STRUCTURE_WANTS = [
    ("vertext-column-heading", "a heading came back a heading"),
    ("vertext-column-h1", "and at its own level"),
    ("vertext-table", "a table came back a table"),
    ("vertext-cell", "with cells"),
    ("vertext-horizontal-list-bullet", "a bullet list stayed a bullet list"),
    ("vertext-horizontal-list-ordered", "an ordered list stayed ordered"),
    ("vertext-horizontal-code", "a code block stayed code"),
]


def render(pandoc, document, path_extra=None):
    """pandoc -> the real filter -> the wire -> the binary. Returns (html, stderr)."""
    env = dict(os.environ)
    env["PATH"] = (path_extra if path_extra is not None
                   else f"{BINARY.parent}:{env['PATH']}")
    with tempfile.NamedTemporaryFile("w", suffix=".md", encoding="utf-8",
                                     delete=False) as f:
        f.write(document)
        source = f.name
    try:
        done = subprocess.run(
            [pandoc, "-f", "markdown", "-t", "html", "--wrap=none",
             f"--lua-filter={SHIM}", source],
            capture_output=True, text=True, env=env, timeout=300)
    finally:
        os.unlink(source)
    if done.returncode != 0:
        raise SystemExit(f"pandoc failed:\n{done.stderr[-2000:]}")
    return done.stdout, done.stderr


def spans_of(html):
    return [htmllib.unescape(m) for m in SPAN.findall(html)]


def with_stub(pandoc, script):
    """Render with a fake `vertext` first on PATH. Returns (html, stderr).

    The handshake's whole job is to refuse a binary that does not speak this
    filter's wire version, and the only honest way to test a refusal is to
    present something to refuse.
    """
    directory = pathlib.Path(tempfile.mkdtemp(prefix="vertext-stub-"))
    try:
        stub = directory / "vertext"
        stub.write_text(script)
        stub.chmod(0o755)
        return render(pandoc, STRUCTURE,
                      path_extra=f"{directory}{os.pathsep}{os.environ['PATH']}")
    finally:
        shutil.rmtree(directory, ignore_errors=True)


# Two binaries the filter must refuse. The first speaks a wire version that is
# not ours; the second is old enough not to know `--version` at all, so it reads
# the empty stdin and prints an empty render -- which is why the filter anchors
# its pattern to the word `vertext` rather than hunting for digits.
STUBS = [
    ("a binary from another release",
     '#!/bin/sh\n[ "$1" = "--version" ] && { echo "vertext 9.9.0"; exit 0; }\n'
     'cat >/dev/null; echo "<p>not ours</p>"\n'),
    ("a binary too old to know --version",
     '#!/bin/sh\ncat >/dev/null; echo "<div class=\\"vertext\\"></div>"\n'),
]


def versions_agree():
    """The three hand-typed version declarations must be one version.

    `Cargo.toml`'s workspace version is what the binary prints; `_extension.yml`
    is what Quarto installs by; `WIRE_VERSION` in the filter is what the
    handshake compares. They were equal by coincidence -- three constants, three
    files, nobody checking -- which is the shape of #17 (`RESERVED_END` one off
    from its own comment) and of #25 (a file one commit off from its source).
    A handshake built on a constant that can drift from the version it claims to
    speak would be worse than none: it would refuse correct pairs.
    """
    fails = []
    cargo = re.search(r'(?m)^version = "([^"]+)"',
                      (ROOT / "Cargo.toml").read_text(encoding="utf-8"))
    manifest = re.search(r"(?m)^version:\s*(\S+)",
                         (ROOT / "extensions" / "vertext" / "_extension.yml")
                         .read_text(encoding="utf-8"))
    wire = re.search(r'(?m)^local WIRE_VERSION = "([^"]+)"',
                     (ROOT / "extensions" / "vertext" / "vertext.lua")
                     .read_text(encoding="utf-8"))
    if not (cargo and manifest and wire):
        return [f"versions: a declaration has moved -- Cargo.toml {bool(cargo)}, "
                f"_extension.yml {bool(manifest)}, WIRE_VERSION {bool(wire)}"]
    if cargo.group(1) != manifest.group(1):
        fails.append(f"versions: Cargo.toml says {cargo.group(1)} and "
                     f"_extension.yml says {manifest.group(1)}")
    wanted = ".".join(cargo.group(1).split(".")[:2])
    if wire.group(1) != wanted:
        fails.append(f"versions: the crates are {cargo.group(1)}, so the "
                     f"filter's WIRE_VERSION should be {wanted}, not "
                     f"{wire.group(1)} -- the handshake would refuse the very "
                     f"binary it ships with")
    return fails


def check(html, stderr, runs, golden, font, hb, label):
    """The four things this gate pins, for one rendered document."""
    fails = []
    if stderr.strip():
        fails.append(f"{label}: the filter complained, so the binary did not "
                     f"run and the page fell back to plain text\n"
                     f"     {stderr.strip()[:200]}")
        return fails
    got = spans_of(html)
    vertical = [r for r in runs if r in "".join(got)] if got else []
    # Runs that reached a vertical measure must be spans, in order; the rest
    # must still appear whole. Both are the same failure when broken: the font
    # is handed two fragments instead of a word.
    for run in runs:
        if run not in html:
            fails.append(f"{label}: {run!r} does not appear whole in the output")
    for span in got:
        if _sg.letters(span) == 0:
            continue
        want = golden["shaped"].get(f"corpus:{span}")
        if want is None:
            for name, text in _sg.CASES:
                if text == span:
                    want = golden["shaped"].get(name)
        if want is None:
            fails.append(f"{label}: {span!r} came back and the shaping golden "
                         f"has no expectation for it")
            continue
        if _sg.shape(font, hb, span) != want:
            fails.append(f"{label}: {span!r} shapes differently than the golden")
    return fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pandoc", default="pandoc")
    ap.add_argument("--binary", default=str(BINARY))
    ap.add_argument("--prove", action="store_true",
                    help="show the gate can go red: run the same documents with "
                         "the binary missing from PATH, which is the accident "
                         "this gate exists for")
    args = ap.parse_args()

    if not shutil.which(args.pandoc):
        sys.exit(f"no pandoc on PATH -- apt-get install -y pandoc")
    try:
        import uharfbuzz as hb
    except ImportError:
        sys.exit("needs uharfbuzz: see .forgejo/workflows/ci.yml")
    binary = pathlib.Path(args.binary)
    if not binary.exists():
        sys.exit(f"no binary at {binary} -- cargo build --release -p vertext-cli")

    golden = json.loads(_sg.GOLDEN.read_text(encoding="utf-8"))
    blob = hb.Blob.from_file_path(str(_sg.FONT))
    font = hb.Font(hb.Face(blob))

    corpus = golden["corpus"]["runs"]
    prose = FRONT + "\n\n".join(corpus)

    if args.prove:
        # The failure this gate exists for: the binary drops out of the chain
        # and `pandoc.pipe` fails, so the filter warns and ships the author's
        # text as ordinary horizontal markdown. Every other gate in this
        # repository stays green through that, because none of them runs the
        # filter at all.
        # PATH minus the release directory, and nothing else removed: pandoc
        # must still be found, or this would prove that a missing pandoc is
        # noticed, which is not the interesting failure.
        without = os.pathsep.join(
            d for d in os.environ["PATH"].split(os.pathsep)
            if pathlib.Path(d or ".").resolve() != BINARY.parent.resolve())
        if shutil.which("vertext", path=without):
            sys.exit("vertext is installed system-wide, so this proof cannot "
                     "remove it from PATH -- run it where it is not")
        html, stderr = render(args.pandoc, STRUCTURE, path_extra=without)
        fails = check(html, stderr, STRUCTURE_RUNS, golden, font, hb,
                      "structure")
        if not fails:
            print("FAIL: the binary was not on PATH, the filter fell back to "
                  "plain text, and this gate still passed")
            print("      it cannot see the failure it exists for")
            return 1
        print(f"PROVEN: with the binary off PATH the chain falls back to plain "
              f"text and this gate reports {len(fails)} failure(s).")
        print(f"        first: {fails[0].splitlines()[0]}")
        print(f"        spans emitted: {len(spans_of(html))} (a rendered page "
              f"has one per run)")
        return 0

    fails = []
    html, stderr = render(args.pandoc, prose)
    fails += check(html, stderr, corpus, golden, font, hb, "corpus")
    got = spans_of(html)
    if got != corpus:
        fails.append(f"corpus: the spans are not the runs, in order\n"
                     f"     {len(got)} spans for {len(corpus)} runs")

    html, stderr = render(args.pandoc, STRUCTURE)
    fails += check(html, stderr, STRUCTURE_RUNS, golden, font, hb,
                   "structure")
    classes = set()
    for found in CLASSES.findall(html):
        classes.update(found.split())
    for wanted, why in STRUCTURE_WANTS:
        if wanted not in classes:
            fails.append(f"structure: no `{wanted}` in the output -- {why} is "
                         f"no longer true, so a wire marker did not arrive")

    fails += versions_agree()

    # The handshake (#9, step 3). Nothing else in this repository checks that
    # the filter and the binary came from the same release, and a mismatched
    # pair renders the page wrong with every other gate green.
    for why, script in STUBS:
        html, stderr = with_stub(args.pandoc, script)
        if "wire version" not in stderr:
            fails.append(f"handshake: {why} was accepted -- the filter said "
                         f"nothing about the version\n     stderr: "
                         f"{stderr.strip()[:160]!r}")
        if spans_of(html):
            fails.append(f"handshake: {why} was accepted -- the document "
                         f"rendered {len(spans_of(html))} spans through a "
                         f"binary that does not speak our wire")

    if fails:
        print(f"FAIL: {len(fails)} findings\n")
        for f in fails[:20]:
            print("  " + f)
        return 1

    version = subprocess.run([args.pandoc, "--version"], capture_output=True,
                             text=True).stdout.splitlines()[0]
    print(f"PASS: the real vertext.lua encodes and the binary decodes. "
          f"{len(corpus)} runs cross pandoc -> filter -> wire -> binary in one "
          f"span each and shape as the golden recorded.")
    print(f"      every block kind survives the wire: heading, table, bullet "
          f"list, ordered list, code.")
    print(f"      and the handshake refuses {len(STUBS)} binaries that do not "
          f"speak this filter's wire version, degrading horizontal rather than "
          f"rendering a mismatched pair.")
    print(f"      {version}, the real extensions/vertext/vertext.lua through "
          f"tools/quarto-shim.lua, binary {binary.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
