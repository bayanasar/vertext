# Vertext

Unicode-aware top-to-bottom text with columns advancing right-to-left.

Vertical text is its own layout system, not a rotated horizontal one. Glyph
orientation, column progression, and Latin handling are decisions the layout
model makes explicitly; nothing here is a 90° transform on a horizontal
engine.

Design documentation lives in [`docs/`](docs/): [`docs/OVERVIEW.md`](docs/OVERVIEW.md)
for the engine and the documents that consume it, and
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for how the layout works end to
end. [`PROGRESS.md`](PROGRESS.md) records which claims have actually been run.

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

### Collapsing the top strip

On a vertical page, depth is the scarce axis: a navigation strip that costs
11rem out of a 100vh column takes a tenth of every line of text, on every
page. Horizontally the same strip costs nothing anyone notices.

So the extension ships a control that hands that depth back, and a theme opts
in by publishing its top-edge depth as a custom property:

```css
:root {
  --vertext-nav-depth: 11rem;        /* the strip AND the content inset read this */
  --vertext-nav-depth-collapsed: 2.1rem;   /* optional; this is the default */
}
```

Every rule that would otherwise write the number — the strip's own size, the
content region's top inset, any `calc()` deriving a height from it — must read
`var(--vertext-nav-depth)` instead. That is the whole contract: one value
moves, and the geometry follows.

The extension then builds the button itself and appends it to the strip, which
it finds by `[data-vertext-edge="nav"]`, falling back to Quarto's
`#quarto-header`. Collapsing sets `vertext-nav-collapsed` on the body; the
choice is remembered in `localStorage`. The strip shrinks to a bar that still
carries the button — never to nothing, because a control you cannot get back
to is a one-way door, not a collapse.

**A page that does not declare `--vertext-nav-depth` gets no button at all.**
That is deliberate. A theme still baking its depth into a build-time constant
would otherwise get a control that renders, clicks, flips a class and moves
nothing — which is worse than no control, because it looks like it worked.
Reading the computed property back is the one check that proves the geometry
really is a runtime value.

Two optional attributes on `<html>` localize the tooltip, which defaults to
English: `data-vertext-nav-label` and `data-vertext-nav-label-collapsed`.

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

A Mongolian run is kept whole, and U+202F NARROW NO-BREAK SPACE is kept inside
it. In bichig that mark is not a space between words but the joint inside one:
`ᠮᠣᠩᠭᠣᠯ` + U+202F + `ᠤᠨ` is the genitive "Mongolia's". The separator holds the
stem's last letter in its final form, opens the suffix in its initial form, and
forbids a break between the two — UAX #14 gives it class GL. Unicode
nevertheless gives it `White_Space=Yes`, so an engine that asks only
`is_whitespace` sets every case ending as a separate word: a half-em gap in the
column with the suffix stranded a row below it. It joins only where Mongolian
holds it on both sides; anywhere else — French before a colon, digit grouping —
it is the narrow space its name describes and keeps its own slot.

## Workspace

| Crate | Role |
|---|---|
| `vertext-core` | Pure layout engine. Text in, positioned slots out. No I/O, no DOM — it must cross `wasm32` unchanged. |
| `vertext-html` | Shared `Layout` → HTML renderer and the mode protocol. Every HTML host goes through it, so the slot-to-class mapping exists once. |
| `vertext-cli` | Thin stdin-to-stdout shell over `vertext-html`. |

Products in `apps/` are adapters over the same core:

| Product | Status |
|---|---|
| Markdown / Quarto extension (`extensions/vertext`) | **Done** — shipping in production |
| [VertexT Quarto theme](apps/quarto-theme/README.md) | Planned next — Asian-native page chrome; unblocked |
| [chaji 侘寂 (Flutter)](apps/chaji/README.md) | Planned — layout theme over `vertext-core`, sibling to the wabisabi widget kit |
| [Browser extension](apps/browser-extension/README.md) | Planned — blocked on `vertext-wasm` |
| [Notes](apps/notes/README.md) | Planned — blocked on `vertext-wasm` and slot geometry |
| [Neovim plugin](apps/nvim/README.md) | Planned — an honest lossy projection onto the terminal grid |
| [Web IDE](apps/web-ide/README.md) | Planned |
| [Browser](apps/browser/README.md) | Planned, last in the queue |

The markdown path is complete: the filter renders real documents end to end
and is in production. It is a Pandoc filter with four Quarto-specific calls,
so other Pandoc-based generators are a small port; non-Pandoc generators
(Hugo's goldmark, remark, python-markdown) each need their own adapter over
the same wire protocol.

Two crates are still ahead. `vertext-wasm` wraps `vertext-core` and
`vertext-html` so the browser targets render byte-identically to the CLI, and
unblocks three products. **Slot geometry** — retaining slot positions and the
map back to a source offset — is the other, and every product that lets a
reader place a caret is blocked on it: Notes, the Web IDE, the Neovim cursor
mapping, and editable text in chaji.

## Tests

```sh
cargo test --workspace         # layout engine and renderer
./examples/test-extension.sh   # the Quarto filter, through real `quarto render`
node examples/test-nav-toggle.js   # the collapse control's branches, in a stub DOM
```

The last one exists because the other two cannot run a script: `cargo test`
stops at the renderer and `test-extension.sh` greps markup. It covers the
opt-in rule, persistence, and the way back — and it explicitly does **not**
cover hit-testing or layout. A control that renders in the right place and is
unclickable has shipped from here before, with every check green the whole
way; only a real browser driving a real mouse event catches that, and the
`kele` repo's `tools/check-nav-toggle.py` is that test.

### Getting a browser and a pandoc without installing Quarto

Neither of the last two needs Quarto itself, and neither needs root. This is
worth writing down because "no browser here" was believed on this project for
longer than it was true, and a control shipped unclicked on the strength of it.

```sh
uv pip install --target . pypandoc_binary      # pandoc + lua, ./pypandoc/files/pandoc
npx @puppeteer/browsers install chrome@stable  # a real Chrome, into ./chrome
npx sass extensions/vertext-theme/vertext-theme.scss theme.css
```

With those three, the whole crossing can be driven by hand: pandoc parses the
markdown, the real `vertext.lua` runs over the AST with Quarto's four `quarto.*`
calls shimmed, and the real `vertext` binary lays it out. For the collapse
control, build a page carrying the compiled theme and the `NAV_TOGGLE` block
read straight out of `vertext.lua` — extracted, never retyped, or the thing
under test is a copy of it — serve it, and point `check-nav-toggle.py` at it
with Chrome started as:

```sh
chrome --headless=new --remote-debugging-port=9222 --window-size=1400,900
```

Run the check against the previous commit as well. A rig that cannot reproduce
the failure is not evidence that the failure is gone.

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
