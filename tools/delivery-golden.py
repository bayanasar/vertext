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

And what this pins IN CONTEXT
-----------------------------
Those 168 strings arrive with no neighbours: `extract()` lifts Mongolian
codepoints out of the lessons and strips them, and this gate then feeds each one
to the binary as a whole document. All of that together says only that a LONE
run is not cut -- while the engine's error-prone place is the other one. Both #4
and #3 were adjacency defects: a transliteration pair whose correct direction
flipped with writing order, and two scripts hard against each other where the
later one lost a slot. A regression that split a run only in the `ᠰᠠᠶᠢᠨ(sayin)`
shape would pass all 168.

So the second half of this gate takes whole lines -- ten picked by hand from the
lessons with a reason each, three built for the shapes kele does not contain --
and asserts that the Mongolian spans the binary emits are EXACTLY the runs in
that line, in order, byte for byte. Nothing split, nothing merged, nothing
dropped, nothing reordered. Then every run that carries letters is shaped and
compared to the expectation the golden already holds for it, so the lines bring
context and not one new answer for a human to eyeball.

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
# The horizontal path marks its runs with a class of its own, because the
# vertical one also carries writing-mode and would stand them upright (#35).
INLINE = re.compile(r'<span class="vertext-mongolian-inline">(.*?)</span>')


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


def lines_from_golden(golden):
    """Whole lines -- kele's, frozen in the golden, plus the constructed ones.

    Each carries the layout path it must take. That is pinned rather than
    discovered because the strong assertion below only applies to one of them:
    a measure whose Latin outweighs its vertical script lays out HORIZONTALLY
    and emits no `vertext-mongolian` span at all, so a change that sent every
    line down that path would leave this gate green while checking nothing.
    """
    out = {}
    for entry in golden["corpus"].get("lines", []):
        out[f"{entry['file']}:{entry['line']}"] = (entry["text"],
                                                   entry.get("path", "vertical"))
    for name, path, text in _sg.LINE_CASES:
        out[f"line-case:{name}"] = (text, path)
    return out


def expectation(golden, run):
    """What the shaping golden recorded for this run, wherever it recorded it.

    A run lifted from a line is usually a corpus entry, because the corpus was
    extracted from those same files. The constructed lines use runs the CASES
    list holds instead -- `ᠮᠣᠩᠭᠣᠯ` is `stem-alone` there and in no corpus entry.
    """
    want = golden["shaped"].get(f"corpus:{run}")
    if want is not None:
        return want
    for name, text in _sg.CASES:
        if text == run:
            return golden["shaped"].get(name)
    return None


def render(binary, text):
    """Run the real binary and return its HTML."""
    done = subprocess.run([str(binary), "--progression", "lr"],
                          input=text, capture_output=True, text=True)
    if done.returncode != 0:
        raise SystemExit(f"binary failed on {text!r}: {done.stderr.strip()}")
    return done.stdout


def deliver(binary, text):
    """Run the real binary and return the Mongolian spans it emitted."""
    return [htmllib.unescape(m) for m in SPAN.findall(render(binary, text))]


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
        # The line layer needs its own proof, and did not have one: everything
        # above shapes runs, and `--prove` used to return before the lines were
        # reached at all. So the run layer re-established on every build that it
        # could go red, while the line layer rested on one manual experiment.
        #
        # Its assertion is sequence equality against `runs_in(text)`, so what has
        # to be shown is that the sequence would reject a split. No binary and no
        # font needed: mutilate the expectation the way an engine would and
        # require the comparison to notice.
        lines, blind_lines, proved = lines_from_golden(golden), [], 0
        for name, (text, _) in sorted(lines.items()):
            want = _sg.runs_in(text)
            if not want:
                blind_lines.append(f"{name}: no runs at all, so its assertion "
                                   f"is vacuous")
                continue
            index = next((i for i, r in enumerate(want) if len(r) >= 2), None)
            if index is None:
                continue          # nothing in it a split could even apply to
            split = want[:index] + [want[index][:1], want[index][1:]] + want[index + 1:]
            proved += 1
            if split == want:
                blind_lines.append(f"{name}: a run split in two compares equal "
                                   f"to the line's own runs")
        if blind_lines:
            print("FAIL: the line layer cannot see the failure it exists for")
            for line in blind_lines[:10]:
                print("  " + line)
            return 1

        sample = "ᠨᠣᠮ"
        print(f"PROVEN: shaped one character at a time, all {checked} multi-letter "
              f"runs diff from the golden;")
        print(f"        and across {proved} of {len(lines)} lines, a run split in "
              f"two is rejected by the sequence comparison.")
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

    # The same question asked where the answer is harder: in a line, with
    # neighbours. The assertion is sequence equality -- the Mongolian spans the
    # binary emitted, against the runs the line contains, in order and byte for
    # byte. A split shows up as an extra span, a merge as a missing one, and a
    # dropped separator as a run that does not match its own source text.
    lines = lines_from_golden(golden)
    in_context, horizontal = 0, 0
    for name, (text, path) in sorted(lines.items()):
        html = render(binary, text)
        spans = [htmllib.unescape(m) for m in SPAN.findall(html)]
        want = _sg.runs_in(text)
        took = "horizontal" if "vertext-horizontal" in html else "vertical"
        if took != path:
            fails.append(f"{name}: laid out {took}, and this line is pinned "
                         f"{path}\n     line {text[:70]!r}")
            continue
        if took == "horizontal":
            # This path carries no `vertext-mongolian` span -- the run is not a
            # slot here, it stays in the line. It does carry
            # `vertext-mongolian-inline`, which exists so the stylesheet can give
            # it a face that joins: without it the bichig on this path rendered
            # in a browser fallback and did not change at all when init/medi/fina
            # were switched off (#35).
            #
            # So the same assertion as the vertical path, against that class: the
            # marked runs must be exactly this line's runs, in order, byte for
            # byte. A mid-run tag splits one into two and the font is handed two
            # words where the author wrote one.
            horizontal += 1
            inline = [htmllib.unescape(m) for m in INLINE.findall(html)]
            if inline != want:
                fails.append(f"{name}: horizontal, and the marked runs are not "
                             f"this line's runs\n     want {want!r}\n"
                             f"     got  {inline!r}")
            for run in want:
                if run not in html:
                    fails.append(f"{name}: horizontal, and {run!r} does not "
                                 f"appear whole in the output")
            continue
        if spans != want:
            fails.append(f"{name}: the spans are not the runs of this line\n"
                         f"     line {text[:70]!r}\n"
                         f"     want {want!r}\n"
                         f"     got  {spans!r}")
            continue
        for span in spans:
            if _sg.letters(span) == 0:
                # A lone punctuation mark takes no positional form, so there is
                # nothing to shape and nothing to compare -- that one is a real
                # skip, and lines do contain them. A run of Todo or Sibe letters
                # would land here too and be skipped just as quietly, which is
                # not the same thing at all: tools/browser-golden.py already
                # fails loudly on that, and two tools giving one situation two
                # treatments is a trap with someone's afternoon in it.
                if _sg.letters_beyond_our_range(span):
                    fails.append(
                        f"{name}: {span!r} carries letters this gate does not "
                        f"count, so it would go through unexamined\n"
                        f"     widen tools/shaping-golden.py's LETTERS, or drop "
                        f"the line")
                continue
            in_context += 1
            exp = expectation(golden, span)
            if exp is None:
                fails.append(f"{name}: {span!r} came back in context, and the "
                             f"shaping golden has no expectation for it")
                continue
            got = _sg.shape(font, hb, span)
            if got != exp:
                fails.append(f"{name}: in context, {span!r} shapes differently\n"
                             f"     want {' '.join(g['g'] for g in exp)}\n"
                             f"     got  {' '.join(g['g'] for g in got)}")

    if fails:
        print(f"FAIL: {len(fails)} findings over {len(wanted)} runs and "
              f"{len(lines)} lines\n")
        for f in fails[:20]:
            print("  " + f)
        return 1

    joint = wanted.get("suffix-202f")
    print(f"PASS: {len(wanted)} runs reach the page in one span and shape as "
          f"the golden recorded, and {in_context} more do so inside "
          f"{len(lines) - horizontal} whole lines, with their neighbours")
    print(f"      {horizontal} more line(s) lay out horizontally as pinned, "
          f"where the runs are marked inline so they keep a face that joins")
    print(f"      binary {binary.relative_to(ROOT) if binary.is_relative_to(ROOT) else binary}, "
          f"font {digest[:12]}")
    if joint:
        print(f"      the U+202F joint survives delivery: {joint!r} -> one span")
    return 0


if __name__ == "__main__":
    sys.exit(main())
