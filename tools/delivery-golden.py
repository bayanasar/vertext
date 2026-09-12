#!/usr/bin/env python3
"""The delivery golden: does the ENGINE hand the font a whole word?

Why this is a separate gate from tools/shaping-golden.py
--------------------------------------------------------
The shaping golden proves the font joins. It shapes the corpus strings
directly -- there is no binary anywhere in that chain:

    entries.update({f"corpus:{r}": shape(font, hb, r) for r in corpus["runs"]})

So if `Slot::MongolianRun` were split in two by some later change, or U+202F
were treated as a word break again, the font would still join the raw string
perfectly and that gate would stay green from end to end. What reaches the page
would be two spans, each shaped on its own: the stem's last letter in FINAL
form, the suffix's first in INITIAL form, where the genitive requires one word.

Real glyphs, real font, valid HTML, and the grammar severed. That is the exact
failure this project exists to prevent, and it lives between the engine and the
font -- which is to say, in the one place neither the unit tests nor the shaping
golden looks.

What this pins
--------------
For every golden string that is a single unbroken run, the binary's HTML must
carry it in exactly ONE `vertext-mongolian` span, byte for byte, and the text
taken back OUT of that span must shape to what the golden recorded. The
comparison is against the shaping golden's own expectations, so the two gates
cannot drift apart: this one asks whether the engine delivered the string that
one already proved joins.

The four `-space`/`spaced-` cases are excluded on purpose. They contain a plain
U+0020, which is a word break, so they SHOULD arrive as several spans -- they
are the shaping golden's negative controls, not runs.

Usage
-----
    cargo build --release -p vertext-cli
    python3 tools/delivery-golden.py
    python3 tools/delivery-golden.py --prove    # show the gate can go red

Needs uharfbuzz, same venv as the shaping golden. See .forgejo/workflows/ci.yml.
"""

import argparse
import hashlib
import html as htmllib
import importlib.util
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
BINARY = ROOT / "target" / "release" / "vertext"

# One definition of `shape()` and of the font path, not two. These two gates
# compare against the same expectations, so a second copy of the shaping call
# is a second thing to keep in step -- and this repository has already paid for
# a filter that existed in two copies. The hyphen in the filename is why this
# goes through importlib rather than a plain import.
_spec = importlib.util.spec_from_file_location(
    "shaping_golden", ROOT / "tools" / "shaping-golden.py")
_sg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_sg)

SPAN = re.compile(r'<span class="vertext-mongolian">(.*?)</span>')


def texts_from_golden(golden):
    """Every golden entry that is one unbroken run, as {key: text}."""
    out = {}
    for name, text in _sg.CASES:
        if " " not in text:
            out[name] = text
    for run in golden["corpus"]["runs"]:
        if " " not in run:
            out[f"corpus:{run}"] = run
    return out


def deliver(binary, text):
    """Run the real binary and return the Mongolian spans it emitted."""
    done = subprocess.run([str(binary), "--progression", "lr"],
                          input=text, capture_output=True, text=True)
    if done.returncode != 0:
        raise SystemExit(f"binary failed on {text!r}: {done.stderr.strip()}")
    return [htmllib.unescape(m) for m in SPAN.findall(done.stdout)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--binary", default=str(BINARY))
    ap.add_argument("--prove", action="store_true",
                    help="show the golden can go red: shape each run as though "
                         "the engine had split it at every character")
    args = ap.parse_args()

    try:
        import uharfbuzz as hb
    except ImportError:
        sys.exit("needs uharfbuzz:  python3 -m venv .venv && "
                 ".venv/bin/pip install uharfbuzz")

    if not _sg.GOLDEN.exists():
        sys.exit("no shaping golden yet -- run tools/shaping-golden.py --update")
    import json
    golden = json.loads(_sg.GOLDEN.read_text(encoding="utf-8"))

    digest = hashlib.sha256(_sg.FONT.read_bytes()).hexdigest()
    if golden["font"]["sha256"] != digest:
        print(f"FONT CHANGED: golden {golden['font']['sha256'][:12]} vs file "
              f"{digest[:12]} -- every expectation here is void")
        return 1

    blob = hb.Blob.from_file_path(str(_sg.FONT))
    face = hb.Face(blob)
    font = hb.Font(face)

    was = golden.get("shaper", {}).get("harfbuzz")
    now = hb.version_string()
    if was and was != now:
        print(f"note: harfbuzz {was} when the golden was written, {now} now. "
              f"Any diff below may be the shaper, not the font.\n")

    wanted = texts_from_golden(golden)

    if args.prove:
        # The failure this gate exists for is a run arriving in pieces. Simulate
        # exactly that: shape each character on its own and concatenate, which
        # is what the font sees when the engine emits one span per character.
        # Every run of two or more letters must diff. A rig that cannot produce
        # the failure is not evidence that the failure is gone.
        blind, checked = [], 0
        for name, text in wanted.items():
            want = golden["shaped"].get(name)
            # Letters, not codepoints: see _sg.letters(). A one-letter run
            # cannot be split, so it carries no information here either way.
            if want is None or _sg.letters(text) < 2:
                continue
            checked += 1
            split = [g for ch in text for g in _sg.shape(font, hb, ch)]
            if split == want:
                blind.append(name)
        if blind:
            print(f"FAIL: split per character, yet these still match the "
                  f"golden: {blind[:5]}")
            print("      the gate cannot see the failure it exists for")
            return 1
        sample = "ᠨᠣᠮ"
        print(f"PROVEN: shaped one character at a time, all {checked} multi-letter "
              f"runs diff from the golden.")
        print(f"        split:  "
              f"{' '.join(g['g'] for ch in sample for g in _sg.shape(font, hb, ch))}")
        print(f"        golden: "
              f"{' '.join(g['g'] for g in golden['shaped']['joined-nom'])}")
        return 0

    binary = pathlib.Path(args.binary)
    if not binary.exists():
        sys.exit(f"no binary at {binary} -- cargo build --release -p vertext-cli")

    fails = []
    for name, text in sorted(wanted.items()):
        spans = deliver(binary, text)
        if len(spans) != 1:
            fails.append(f"{name}: the engine split this run into {len(spans)} "
                         f"spans\n     want one: {text!r}\n     got: {spans!r}")
            continue
        if spans[0] != text:
            fails.append(f"{name}: the span text is not the input\n"
                         f"     want {text!r}\n     got  {spans[0]!r}")
            continue
        want = golden["shaped"].get(name)
        if want is None:
            fails.append(f"{name}: delivered, but not in the shaping golden")
            continue
        got = _sg.shape(font, hb, spans[0])
        if got != want:
            fails.append(f"{name}: what the engine delivered shapes differently\n"
                         f"     want {' '.join(g['g'] for g in want)}\n"
                         f"     got  {' '.join(g['g'] for g in got)}")

    if fails:
        print(f"FAIL: {len(fails)} of {len(wanted)} runs\n")
        for f in fails[:20]:
            print("  " + f)
        return 1

    joint = wanted.get("suffix-202f")
    print(f"PASS: {len(wanted)} runs reach the page in one span and shape as "
          f"the golden recorded")
    print(f"      binary {binary.relative_to(ROOT) if binary.is_relative_to(ROOT) else binary}, "
          f"font {digest[:12]}")
    if joint:
        print(f"      the U+202F joint survives delivery: {joint!r} -> one span")
    return 0


if __name__ == "__main__":
    sys.exit(main())
