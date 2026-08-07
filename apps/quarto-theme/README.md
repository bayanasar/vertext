# VertexT — a Quarto theme

An Asian-native Quarto theme. Not a stylesheet over a Western page: the page
itself is rotated, so every element sits where a vertical reader expects it and
the whole surface reads in one orientation.

## The one hard requirement

**Existing content must not change.** A `.qmd` written for the default theme
renders under VertexT with no edits — no new fences, no wrapper divs, no
per-document classes. Authors opt in once, in `_quarto.yml`, and their corpus
is untouched:

```yaml
format:
  html:
    theme: vertext
```

That constraint is what makes this a *theme* rather than another filter. The
existing `extensions/vertext` filter already lays out content; this decides
where everything *around* the content goes.

## The rotation

A horizontal page puts the banner on top, the table of contents on the left,
the status bar at the bottom, and scrolls down. Rotate the whole model a
quarter-turn and each piece lands where the vertical reader's eye already is:

| Chrome | Horizontal page | VertexT |
|---|---|---|
| Top banner / navbar | top | **right** — the start edge under `vertical-rl` |
| Table of contents | left | **top** |
| Status bar / footer | bottom | **left** — the end edge |
| Scroll | downward | **leftward**, following the columns |

The mapping is not arbitrary decoration. Under `vertical-rl` the block axis
runs right-to-left, so the right edge *is* the start of the document: a banner
there is the banner "at the top" in the only sense the reader experiences.
The footer at the left edge is the same argument at the other end. Each piece
of chrome keeps its meaning and changes its physical side.

Under `vertical-lr` — traditional Mongolian — the two flip: the banner goes
left, the status bar right. The theme must read the document's declared
`vertext-progression` rather than assuming CJK, for exactly the reason the
engine already carries `Progression` as data.

## What already exists to build on

`vertext.lua`'s `page_style()` and `document_style()` already do the hard part
of this. `document_style` collapses Quarto's article grid, turns the content
region into a vertical surface, and hides the pieces that have nothing to
anchor to:

```css
body #quarto-margin-sidebar, body .toc-active #TOC { display: none; }
```

The theme is largely the same work with the opposite intent — instead of
*hiding* the sidebar and TOC because they cannot follow a vertical document,
**place** them on their rotated edges so they can. The existing rules are the
starting point and the thing being replaced.

Two hazards already paid for in the filter, and both apply here:

- **The axis swap.** Under `vertical-rl` the BLOCK axis is horizontal and the
  INLINE axis vertical, so `block-size` means width. This confusion caused six
  separate bugs in the stylesheet; prefer physical properties and say why.
- **The wheel.** Browsers do not map a vertical wheel onto the block axis —
  measured, twice, against a wrong assertion. `SCROLL_SCRIPT` exists for this
  and the theme needs it for the whole page, not just the strip.

## Shape

A Quarto *format extension* rather than a filter, so it composes with the
existing one:

```
_extensions/vertext-theme/
  _extension.yml      # contributes format: html with theme + template partials
  vertext-theme.scss  # the rotated chrome
  partials/           # navbar, TOC, footer placement
```

Quarto builds its title block and navigation from metadata at template time —
*after* filters run. That is why the filter can only hide `#title-block-header`
rather than replace it. A theme reaches the template layer, so VertexT can put
the chrome in the right place instead of suppressing it. This is the reason to
do it as a theme at all.

It depends on the filter for content layout and does not duplicate it. The
filter stays usable standalone under any Pandoc host; the theme is the
Quarto-specific presentation on top.

## Constraints worth stating early

- **No content rewrites, ever.** The moment a document needs a VertexT-specific
  edit, the theme has failed its one requirement.
- **Degrade like the filter does.** No binary means no vertical layout, and a
  rotated chrome around horizontal text is worse than doing nothing — the exact
  failure that reached jishe.org. The theme's chrome rotation must be gated on
  a real render, the same way both page styles now are.
- **Progression is data.** Read it; never hardcode right-to-left. A theme that
  fixes the direction decides permanently which literatures it can carry.
- **Navigation must still work.** Quarto's navbar, sidebar, and TOC carry real
  behaviour, not just markup. Rotating them must not break their links,
  collapse states, or keyboard access.
- **Small viewports.** A horizontally scrolling page with chrome on three edges
  has less room than a vertical one. The theme needs an honest answer for
  phones, even if that answer is a documented fallback.

## Status

Not started. Unblocked — it needs no new crate, only the filter that already
ships. Independent of `vertext-wasm`, so it can proceed in parallel with the
browser targets.
