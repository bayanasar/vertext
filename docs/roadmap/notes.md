# Vertext Notes

A plain-text editor for vertical writing. Placeholder — not started.

## Why it is its own product

Everything else in this repository is a *renderer*: text goes in, geometry
comes out, and the reader never moves the caret. An editor needs the inverse
map — from a click or a keystroke back to an offset in the source — and
nothing in `vertext-core` provides it yet.

That inverse is the blocking dependency for the Neovim plugin and the web IDE
both. A notes app is the smallest honest thing that forces us to build it,
which is why it belongs ahead of them rather than after.

## What the editing model has to answer

- **Where the document starts.** A blank document opens at the right edge for
  CJK and at the left edge for Mongolian, because that is where the first
  column goes. The starting edge is the same `Progression` the renderer
  already carries — but here it also decides where the caret is *born*.
- **Which way the document grows.** Columns accumulate leftward under
  `vertical-rl` and rightward under `vertical-lr`; already-written columns
  stay put while the new one extends the document. The viewport follows the
  caret in the progression direction, so the scroll flips with the script.
- **Hit testing.** A click at (x, y) has to resolve to a character offset.
  The renderer knows where every slot was placed; it currently throws that
  away. Keeping the geometry is most of the work.
- **Caret shape.** A caret in vertical text is a horizontal bar between two
  slots, not a vertical bar between two glyphs. Selection highlights run down
  a column and wrap to the next one in the progression direction.
- **IME.** Composition is the hard case: a preedit string appears, changes
  width as the user types, and commits. In a vertical column the preedit has
  to occupy provisional slots without reflowing the whole document on every
  keystroke.
- **Where a column ends.** Editing forces the question the renderer can
  currently dodge: does a column wrap at the page edge, or run as long as its
  paragraph? A writer needs to know where their next character lands before
  they type it.

## Shape

Deliberately small: a single pane, one document, no explorer and no tabs. Open
a file, type, save. The point is to prove the editing model, not to compete
with an IDE — the IDE can have it once it works here.

Almost certainly WASM over `vertext-core`, sharing the layout with the browser
targets. A native shell is a later question.

## Status

Not started. Blocked on `vertext-wasm` and on the core keeping slot geometry.
