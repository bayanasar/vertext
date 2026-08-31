# Architecture

How a string of markdown becomes columns that read top-to-bottom. This
document is the connective tissue: what each stage owns and why the seams fall
where they do. Per-function detail lives in the doc comments in `crates/`, and
is not repeated here.

## The claim underneath everything

Vertical text is its own layout system, not a rotated horizontal one. Glyph
orientation, column progression, word slotting, and punctuation behaviour are
decisions the model makes explicitly. Nothing in this codebase is a 90°
transform applied to a horizontal engine — that approach produces text that
resembles writing without being it, and ending that is the reason the library
exists.

## The stages

```
markdown  ──► vertext.lua ──► vertext (binary) ──► vertext-html ──► HTML + CSS
   (Quarto)      segments        vertext-core         renderer
                 the AST         lays out
```

| Stage | Crate / file | Owns |
|---|---|---|
| Segmentation | `extensions/vertext/vertext.lua` | Walking Quarto's AST, deciding what is a heading, a list item, a table cell; marking each segment |
| Layout | `crates/vertext-core` | Text and style in, positioned slots out. No I/O, no DOM, nothing that cannot cross `wasm32` |
| Rendering | `crates/vertext-html` | Slots to HTML classes and CSS; the mode protocol |
| Transport | `crates/vertext-cli` | 37 lines of stdin to stdout, so the filter can shell out |
| Page shape | `extensions/vertext-theme/` | SCSS that sizes the page around the columns |

The core is pure so that a future `vertext-wasm` host — browser extension, web
IDE — shares it byte for byte rather than growing a second, subtly different
layout engine. Anything in the core that cannot cross `wasm32` is a design
smell to be quarantined in an adapter.

## The unit of layout is a grapheme cluster

Not the Unicode scalar. A variation selector must stay with the ideograph whose
glyph it selects, a combining mark with its base, a ZWJ emoji sequence with
itself. Split across slots they are silently dropped or rendered as their
unjoined parts — which looks like text and is not.

The one dependency is `unicode-segmentation` for UAX #29 boundaries. It is
table-driven and `no_std`-capable. Hand-rolling cluster boundaries would produce
exactly the near-miss rendering this library exists to end.

## The slot model

A column is a sequence of slots; a slot is one position down the column. The
kinds are in `Slot`:

- `Upright` — an ideograph, kana, or hangul cluster. One character, one slot.
- `LatinWord` — one Latin word, however many letters, in one slot, read
  horizontally within it.
- `MongolianRun` — a whole run kept intact, so a vertical-capable font can
  perform Mongolian joining and vertical substitutions across it. Breaking the
  run is what breaks the joining.
- `Space` — source whitespace, carried through verbatim so a copied paragraph
  matches what was written.
- `VerticalPunctuation` — marks that turn a quarter-circle: brackets, quotes,
  colons, dashes, ellipses, slashes.
- `CornerPunctuation` — stops and commas, which do not turn but move to the
  upper-right of their em square.
- `Neutral` — everything else, upright for now.

**A slot is the unit of every measure in the system.** That single decision is
what makes the orientation heuristic honest, and it is described next.

## Choosing an orientation

Not everything in a document wants to be vertical. `prefers_horizontal` decides
per block, and it counts **slots, not characters**.

One ideograph is one slot. One Latin word is also one slot. A Chinese sentence
quoting `bi yabuqu Ugei` has more Latin letters than Han characters while being,
plainly, a Chinese sentence: a character count flips it horizontal, a slot count
leaves it alone. A language-teaching document is the honest test case for this,
because it is dense with citation forms and every one of them is a short word
standing in for a single idea, exactly like the character it glosses.

Punctuation and whitespace do not vote. They are shared by both writing systems,
and letting them vote hands the decision to a comma-heavy sentence.

There is exactly one heuristic in the system and it only ever chooses an
orientation. Prose is never distinguished from code by guessing — markdown
already says which is which, and where it does not, the author declares it.

**The invariant to hold** (issue #4 exists because it was not held): the slot
count the measure arrives at must equal the slot count `layout_text` actually
produces. Pinning the answer for a particular string is a weaker test that turns
into a puzzle at the next change.

## Progression is data

Columns advance right-to-left for CJK (`vertical-rl`) and left-to-right for
traditional Mongolian (`vertical-lr`). Both are facts of their scripts. Getting
it backwards does not look broken — it reads the document in reverse.

It is carried on the `Layout` and declared by the author, never detected,
because it cannot be inferred: a Chinese document teaching Mongolian and a
Mongolian document teaching Chinese contain the same scripts and want opposite
answers. Default is right-to-left. A host must read it from the layout rather
than assuming.

## The document model

`Layout` is the vertical primitive: one run of text as columns of slots. A
`Document` is more, because not everything in it is vertical:

- vertical blocks — columns of slots;
- `HorizontalBlock` — Latin-majority prose (wrapped at 66) or program source
  (80, monospace), stacked so a heading sits above its paragraph rather than
  each claiming a slot beside the columns;
- `Table` — rows become columns.

These decisions live in the core as data so that every adapter reads the same
answer instead of inventing one.

## Mongolian

The destination, and the reason the core's seams must stay open.

**The suffix separator.** U+202F NARROW NO-BREAK SPACE is not a space between
words but a joint inside one. `ᠮᠣᠩᠭᠣᠯ` + NNBSP + `ᠤᠨ` is the genitive: the
separator holds the stem's last letter in its final form, opens the suffix in
its initial form, and forbids a break between them (UAX #14 class GL). Unicode
nevertheless gives it `White_Space=Yes`, so an engine that asks only
`char::is_whitespace` sets the case ending as a separate word — a half-em gap
with the suffix stranded below it and the joining that carries the grammar cut
in two. Overriding that one property, and only where bichig holds the mark on
both sides, is the whole fix.

**Word connectors.** `min-U`, `kedU(n)`, `yabun_a`, `gerel.net`, `uu/UU` are
single words, not a word and a mark and another word. Romanization uses these
marks as letters. A closing bracket joins the word only if the word already
holds the opening one: `kedU(n)` is one word, while the `)` in `词尾(n)形式`
is punctuation because its `(` went out as punctuation too. Balance is what
separates a citation form from an aside.

**Shaping is not proven.** The run reaches the DOM inside one span, which is
what *lets* a font join across it. Nothing yet checks that the font does, or
that initial/medial/final forms are selected right. There is no golden of real
bichig. Until there is, a page can look plausible and read wrong to someone who
reads the script.

## Latin inside a column

A long Latin word gets a predictable hard hyphen at a 12-cluster cap. A hyphen
the author already typed is preferred, and taking it costs nothing: the pieces
still concatenate to the source, so the word is not edited at all. Counting to
the cap is the fallback for a word that offers no such break —
`use-after-free` must not come back as `use-after-f‐ / ree`, which reads as a
different term. Only hyphens qualify; splitting `gerel.net` at the dot would cut
a citation form in half.

Dictionary hyphenation stays a host-configurable future enhancement behind a
language tag. A hyphenation without a language is a guess wearing a suit.

## Punctuation is never substituted

The host rotates the *view*. It must never swap a character for a vertical
presentation form (U+FE10–FE4F). Those look correct and silently destroy the
document: copy-paste, find-in-page, and screen readers then hand back codepoints
the author never typed. A renderer may decide how text appears; the text itself
is content, and content is not ours to edit.

## The wire protocol

The filter and the binary are two processes joined by a flat string, and
markdown structure — a heading is not a paragraph that happens to be short —
has to cross that boundary. It crosses as reserved Private Use Area markers,
each meaning "everything after me is this kind of segment, until the next
marker":

| Codepoint | Meaning |
|---|---|
| U+E000 | code |
| U+E001 | prose |
| U+E002–U+E007 | heading levels 1–6 |
| U+E008 | table (cells separated by U+E009, rows by U+E00A) |
| U+E00B | list item |
| U+E00C | ordered list item |

Two consequences the code enforces:

1. **The filter strips this range from author text.** A decoder cannot tell a
   marker the filter emitted from one a document contained, so a paste
   containing U+E000 would switch the rest of itself into code mode. PUA is rare
   in prose, and rare is not never.
2. **Both sides carry the same constants**, Rust and Lua, and
   `mode_markers_are_the_wire_protocol` asserts every one of the thirteen
   against its literal codepoint, so renumbering any of them on the Rust side
   fails the build rather than passing silently. A round-trip test cannot do
   this job — comparing a constant to itself stays green through a
   renumbering, while the literal in `vertext.lua` quietly comes to mean
   something else.

What is *not* enforced: that the filter and the binary in a given installation
were built from the same source. There is no version handshake, and a mismatched
pair produces no error — only misplaced text, with every check green. See
`PROGRESS.md`.

## Where the seams are

- **The core owns layout and nothing else.** No I/O, no DOM, no terminal. An
  adapter concern that leaks into the core is a defect however convenient.
- **Adapters own their losses, in writing.** A terminal is a horizontal cell
  grid, so a Neovim host is a projection: the core lays out, the adapter maps to
  cells and states exactly what is lost. A documented degradation beats a faked
  fidelity.
- **The renderer is shared.** Every HTML-producing host goes through
  `vertext-html`, so the slot-to-class mapping is defined exactly once.
