# Vertext

Unicode-aware top-to-bottom text with columns advancing right-to-left.

Vertical text is its own layout system, not a rotated horizontal one. Glyph
orientation, column progression, and Latin handling are decisions the layout
model makes explicitly; nothing here is a 90° transform on a horizontal
engine.

## Run the demo

```sh
./examples/render.sh
```

That builds the binary, copies the extension into `examples/_extensions/`, and
renders `examples/quarto-demo.qmd`. The extension directory is generated —
`extensions/vertext` is the only copy in the repository.

Use it in a Quarto document after copying the extension to
`_extensions/vertext` (or installing it with `quarto add` once this repository
is published):

```markdown
---
filters: [vertext]
format:
  vertext-html: default
---

::: {.vertext}
山川异域，风月同天。
:::
```

The extension invokes the `vertext` binary at render time, producing static
HTML. No browser JavaScript is required.

### Orientation

Not everything in a document wants to be vertical. Each block decides:

| Content | Rendering | Decided by |
|---|---|---|
| CJK / Mongolian paragraph | Vertical columns | East Asian Width majority |
| Latin-majority paragraph | Horizontal block, 66ch | The same measure, inverted |
| Fenced or indented code | Horizontal block, 80ch, monospace | Markdown declared it code |
| Table | Rows become columns | Markdown declared it a table |
| `::: {.vertext .vertext-code}` | Vertical code | The author declared it |

The majority is measured in ink, not characters: ideographs and Mongolian
count double, because 山川异域 is four characters and a whole clause while "It
is a truth universally acknowledged" is thirty-eight for a comparable amount
of meaning. Punctuation does not vote.

There is exactly one heuristic in the system and it only ever chooses an
orientation. Prose is never distinguished from code by guessing — markdown
already says which is which, and where it does not, the author can.

Consecutive horizontal blocks stack: a heading sits on top of its paragraph
rather than each claiming a slot beside the columns.

### Progression

Columns advance right-to-left for CJK (`vertical-rl`) and left-to-right for
traditional Mongolian (`vertical-lr`). Both are facts of their scripts, and
getting it backwards does not look wrong — it reads the document in reverse.

```yaml
vertext-progression: lr    # traditional Mongolian
```

It is declared rather than detected because it cannot be inferred: a Chinese
document teaching Mongolian and a Mongolian document teaching Chinese contain
the same scripts and want opposite answers. Default is right-to-left.

### Whole-document mode

```yaml
vertext: true          # lay the document out vertically, keep the page chrome
vertext-page: true     # additionally make the page itself a vertical surface
```

`vertext: true` suits a document inside a site — navbar, sidebar, and table of
contents keep working. `vertext-page: true` takes over the body and suits a
standalone document. Either way no `::: {.vertext}` fence is needed; explicit
fences still work for laying out one region of an otherwise horizontal page.

### What markdown survives

The filter flattens each block to characters before handing it to the binary,
so structure only crosses the boundary where the wire protocol carries it.
Today that is two things:

| Markdown | Result |
|---|---|
| Headings (`#`–`######`) | Own block, level-scaled, with a section rule |
| Fenced / indented code | Own block, horizontal, indentation preserved |
| Tables | Real `<table>`; rows become columns, cells never hyphenate |
| Paragraphs | Own block, oriented by the rule above |
| Emphasis, links, lists | **Flattened to their text.** The markup is lost |

The last row is a real limitation, not a rounding error: `*emphasis*` arrives
as the bare word. Each construct needs its own marker in the protocol before
it can be rendered as itself, and until it has one it should be listed here
rather than silently implied. Lists are the next worth carrying across.

### Whole-page vertical flow

Add `vertext-page: true` to the document's YAML and the page itself becomes a
vertical surface: `writing-mode: vertical-rl` on the body, so the title, the
headings, and the prose between strips all flow top-to-bottom with columns
advancing right-to-left, and the document scrolls horizontally from the right
edge. This is the browser's native vertical flow — the strip is not a box
embedded in a horizontal page.

The document title is re-rendered through the binary as a level-1 heading and
Quarto's own title block is hidden, so the title obeys the same layout rules
as the body it heads. Rotating it with `text-orientation: sideways` would have
been a transform wearing the costume of vertical text.

## Layout

Columns run top-to-bottom; a source newline starts the column to the *left*.
`Layout::progression` carries the advance direction as data — `RightToLeft`
(`vertical-rl`, CJK) or `LeftToRight` (`vertical-lr`, traditional Mongolian) —
because progression is a property of the script, not a property of the engine.
The renderer stamps it on the root as `data-column-advance` and the stylesheet
follows.

Prose Latin slots are capped at 12 characters; long words are hard-wrapped
with a visible hyphen. Code blocks use 24 so conventional compound identifiers
stay intact. The caps are declared once, in `vertext-html`, and published to
CSS as custom properties — a cap written in two places drifts, and a drifted
cap truncates silently instead of wrapping visibly. Dictionary-aware
hyphenation is a later opt-in because it needs a language tag and a
hyphenation dictionary, and a hyphenation without a language is a guess.

## Workspace

| Crate | Role |
|---|---|
| `vertext-core` | Pure layout engine. Text in, positioned slots out. No I/O, no DOM — it must cross `wasm32` unchanged. |
| `vertext-html` | Shared `Layout` → HTML renderer and the mode protocol. Every HTML host goes through it, so the slot-to-class mapping exists once. |
| `vertext-cli` | Thin stdin-to-stdout shell over `vertext-html`. |

Products in `apps/` are adapters over the same core:

| Product | Status |
|---|---|
| Quarto / Markdown extension (`extensions/vertext`) | Working end to end |
| [Neovim plugin](apps/nvim/README.md) | Planned — an honest lossy projection onto the terminal grid |
| [Web IDE](apps/web-ide/README.md) | Planned |
| [Browser extension](apps/browser-extension/README.md) | Planned — blocked on `vertext-wasm` |
| [Browser](apps/browser/README.md) | Planned, last in the queue |

`vertext-wasm` is the next crate: it will wrap `vertext-core` and
`vertext-html` so the browser targets render byte-identically to the CLI.

## Tests

```sh
cargo test --workspace        # layout engine and renderer
./examples/test-extension.sh  # the Quarto filter, through real `quarto render`
```

Layout invariants and the mode protocol are unit-tested; the README's
山川异域，风月同天 sample is pinned as a golden. Correctness claims for a
script require a reference rendering behind them — "it parses" is not "it
renders".

The unit of layout is the UAX #29 extended grapheme cluster, so a variation
selector stays with the ideograph whose glyph it selects, a combining mark
with its base, and a ZWJ emoji sequence with itself. This is the reason
`vertext-core` has its one dependency, `unicode-segmentation`: cluster
boundaries are table-driven, and a hand-rolled approximation renders text
that is wrong in exactly the ways a reader notices and a test does not.

The extension test document is deliberately multi-byte. Marker stripping in
the filter is byte-oriented, and an ASCII-only fixture cannot catch a pattern
that corrupts neighbouring CJK.

## License

MIT.
