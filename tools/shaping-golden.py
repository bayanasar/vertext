#!/usr/bin/env python3
"""The shaping golden: which positional form does the font pick for each letter?

Why this exists
---------------
A letter of the bichig takes a different form at the head, middle and foot of a
word. If the font is not joining, every letter comes out in its ISOLATED form
and the page still looks like writing -- columns of plausible marks, in the
right places, wrong. That is the one failure mode nobody here can catch by
looking, because catching it requires reading the script.

So the golden records glyph NAMES, not a picture. `uni1828.N.init` where an
isolated form belongs is a diff; a human judgement about whether a page "looks
right" is not. Nobody has to read bichig to run this.

What it pins
------------
  font      Noto Sans Mongolian, vendored under goldens/fonts/ and checksummed.
            The golden is a property of the font -- swap the font and every
            expectation here is void, which is why the checksum is a hard gate
            rather than a note. OFL 1.1, so it ships with the tests; a golden
            nobody else can run is not a seal.
  corpus    Every distinct Mongolian run in the kele lessons, frozen into
            goldens/shaping.json at the commit named there. Frozen, not read
            live: CI checks out vertext alone, and a golden that needs a
            sibling checkout is a golden that does not run.
  cases     Hand-built runs for the two in-word separators. The corpus carries
            zero U+202F, so the case the engine just fixed is not in it -- the
            corpus alone would have proved nothing about the thing we changed.

Usage
-----
    python3 tools/shaping-golden.py            # check, exit 1 on any diff
    python3 tools/shaping-golden.py --update    # rewrite the golden
    python3 tools/shaping-golden.py --update --corpus ../kele   # re-extract too

Needs uharfbuzz. CI installs it into a venv; see .forgejo/workflows/ci.yml.
"""

import argparse
import hashlib
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
FONT = ROOT / "goldens" / "fonts" / "NotoSansMongolian-Regular.ttf"
GOLDEN = ROOT / "goldens" / "shaping.json"

# U+202F NARROW NO-BREAK SPACE, the suffix separator: "Mongolia's" is stem +
# separator + suffix, and it must not break across lines. U+180E MONGOLIAN
# VOWEL SEPARATOR detaches a final vowel; it is a format character, so it must
# measure zero. Both appear in what we publish, so both get pinned.
CASES = [
    ("suffix-202f",      "ᠮᠣᠩᠭᠣᠯ ᠤᠨ"),
    ("suffix-space",     "ᠮᠣᠩᠭᠣᠯ ᠤᠨ"),
    ("stem-alone",       "ᠮᠣᠩᠭᠣᠯ"),
    ("suffix-alone",     "ᠤᠨ"),
    ("vowel-180e",       "ᠪᠠᠶᠢᠨ᠎ᠠ"),
    ("vowel-none",       "ᠪᠠᠶᠢᠨᠠ"),
    ("joined-nom",       "ᠨᠣᠮ"),
    ("spaced-nom",       "ᠨ ᠣ ᠮ"),
    ("joined-ger",       "ᠭᠡᠷ"),
    ("spaced-ger",       "ᠭ ᠡ ᠷ"),
    ("joined-mori",      "ᠮᠣᠷᠢ"),
    ("spaced-mori",      "ᠮ ᠣ ᠷ ᠢ"),
]

RUN = re.compile(r"[᠀-᢯ ‍]+")


def shape(font, hb, text, features=None):
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    buf.direction = "ttb"          # bichig runs down the column, not across it
    hb.shape(font, buf, features or {})
    return [
        {"g": font.glyph_to_string(i.codepoint) or f"gid{i.codepoint}",
         "adv": p.y_advance}
        for i, p in zip(buf.glyph_infos, buf.glyph_positions)
    ]


def extract(corpus_root):
    """Every distinct Mongolian run in the kele lessons, in first-seen order."""
    root = pathlib.Path(corpus_root)
    files = sorted((root / "lessons").glob("*.md")) + [root / "index.md"]
    runs = {}
    for f in files:
        for m in RUN.finditer(f.read_text(encoding="utf-8")):
            r = m.group(0).strip()
            if any(0x1820 <= ord(c) <= 0x18AF for c in r):
                runs.setdefault(r, f.name)
    return runs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--update", action="store_true")
    ap.add_argument("--corpus", help="path to a kele checkout, to re-extract")
    ap.add_argument("--prove", action="store_true",
                    help="show the golden can go red: shape with joining OFF")
    args = ap.parse_args()

    try:
        import uharfbuzz as hb
    except ImportError:
        sys.exit("needs uharfbuzz:  python3 -m venv .venv && .venv/bin/pip install uharfbuzz")

    digest = hashlib.sha256(FONT.read_bytes()).hexdigest()
    blob = hb.Blob.from_file_path(str(FONT))
    face = hb.Face(blob)
    font = hb.Font(face)

    old = json.loads(GOLDEN.read_text(encoding="utf-8")) if GOLDEN.exists() else {}

    if args.corpus:
        runs = extract(args.corpus)
        # Name the commit, not the path: "../kele" says nothing a year from now
        # about which lessons these 160 runs were taken from.
        head = subprocess.run(["git", "-C", args.corpus, "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True).stdout.strip() or "unknown"
        corpus = {"source": "kele", "commit": head, "runs": list(runs)}
    else:
        corpus = old.get("corpus", {"source": None, "runs": []})

    entries = {name: shape(font, hb, text) for name, text in CASES}
    entries.update({f"corpus:{r}": shape(font, hb, r) for r in corpus["runs"]})

    fresh = {
        "font": {"file": str(FONT.relative_to(ROOT)), "sha256": digest,
                 "upem": face.upem},
        "shaper": {"harfbuzz": hb.version_string(),
                   "uharfbuzz": getattr(hb, "__version__", "?")},
        "corpus": corpus,
        "shaped": entries,
    }

    if args.update:
        GOLDEN.write_text(json.dumps(fresh, ensure_ascii=False, indent=1) + "\n",
                          encoding="utf-8")
        print(f"wrote {GOLDEN.relative_to(ROOT)}: {len(entries)} runs "
              f"({len(CASES)} constructed + {len(corpus['runs'])} corpus)")
        return 0

    if not old:
        sys.exit("no golden yet -- run with --update --corpus ../kele")

    if args.prove:
        # A gate that has never gone red is a gate whose every green is
        # untested. Joining is exactly the `init`/`medi`/`fina` features, so
        # turning them off IS a non-joining font -- the failure this golden
        # exists for, without shipping a second font to fake it. Every joined
        # run must diff, and the isolated ones must not: a rig that reports a
        # diff everywhere is not discriminating, it is just noisy.
        off = {"init": False, "medi": False, "fina": False}
        blind, wrong = [], []
        for name, text in CASES:
            got = shape(font, hb, text, off)
            differs = got != old["shaped"][name]
            if name.startswith(("joined-", "suffix-", "vowel-", "stem-")) and not differs:
                blind.append(name)
            if name.startswith("spaced-") and differs:
                wrong.append(name)
        if blind:
            print(f"FAIL: joining off, yet these still match the golden: {blind}")
            print("      the golden cannot see the failure it exists for")
            return 1
        if wrong:
            print(f"FAIL: already-isolated runs changed too: {wrong}")
            return 1
        print(f"PROVEN: with init/medi/fina disabled, every joined run diffs "
              f"from the golden and no isolated run does.")
        print(f"        e.g. joined-nom -> "
              f"{' '.join(g['g'] for g in shape(font, hb, 'ᠨᠣᠮ', off))}")
        print(f"        golden has     -> "
              f"{' '.join(g['g'] for g in old['shaped']['joined-nom'])}")
        return 0

    was = old.get("shaper", {}).get("harfbuzz")
    now = hb.version_string()
    if was and was != now:
        print(f"note: harfbuzz {was} when the golden was written, {now} now. "
              f"Any diff below may be the shaper, not the font.\n")

    fails = []
    if old["font"]["sha256"] != digest:
        fails.append(f"FONT CHANGED: golden {old['font']['sha256'][:12]} "
                     f"vs file {digest[:12]} -- every expectation below is void")
    for name, want in old["shaped"].items():
        got = entries.get(name)
        if got is None:
            fails.append(f"{name}: in the golden, not shaped now")
        elif got != want:
            fails.append(f"{name}:\n     want {' '.join(g['g'] for g in want)}"
                         f"\n     got  {' '.join(g['g'] for g in got)}")
    for name in entries.keys() - old["shaped"].keys():
        fails.append(f"{name}: shaped now, not in the golden (--update to accept)")

    if fails:
        print(f"FAIL: {len(fails)} of {len(old['shaped'])} runs\n")
        for f in fails[:20]:
            print("  " + f)
        return 1

    joined = old["shaped"]["joined-nom"]
    isolated = old["shaped"]["spaced-nom"]
    print(f"PASS: {len(old['shaped'])} runs shape as recorded "
          f"({len(CASES)} constructed + {len(old['corpus']['runs'])} corpus)")
    print(f"      font {digest[:12]}, upem {face.upem}")
    print(f"      joining live: {' '.join(g['g'] for g in joined)}")
    print(f"      vs isolated:  {' '.join(g['g'] for g in isolated)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
