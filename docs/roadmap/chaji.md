# chaji 侘寂 — a Flutter layout theme

The theme layer that connects `vertext-core` to Flutter, sitting alongside the
[wabisabi](https://github.com/bayanasar/wabisabi) widget kit.

```
wabisabi  — the widget kit (tokens → theme → components)
chaji     — the layout theme (Material + Cupertino), backed by vertext-core
```

Wabisabi answers *what a widget looks like*. chaji answers *which way the text
runs and where it goes on the screen*. They are separate concerns and stay
separate packages.

## Why this cannot live inside wabisabi

Wabisabi is pure Dart with a strict `tokens/ → theme/ → components/` hierarchy
and a single barrel. chaji breaks two of its rules by nature:

- It needs `vertext-core` over FFI, so it ships a native library per platform.
  Folding that into wabisabi would make every consuming app carry native
  binaries for a font-layout concern it may not use.
- It is not a themed widget. It is a layout engine with a theme-shaped surface.

So chaji is its own package that *depends on* wabisabi, or that an app uses
beside it. Wabisabi keeps its pinned-tag discipline and stays pure Dart.

## Why Flutter needs it at all

Flutter does not use the platform text stack — it ships its own (Skia/Impeller,
HarfBuzz shaping, its own line breaker). And Flutter's `Paragraph` has **no
vertical writing mode**: `TextDirection` covers LTR and RTL horizontal text and
nothing else. There is no `writing-mode: vertical-rl` equivalent to configure.

The common workaround is `RotatedBox` around a horizontal paragraph. That is a
transform wearing the costume of vertical text: it turns the whole run,
including the glyphs that should stay upright, and it breaks selection and the
accessibility tree. It is the same class of mistake as substituting Unicode
presentation forms — it looks right and is not.

So the gap on Flutter is wider than on the web, where browsers at least render
CJK serviceably. On Flutter there is no vertical mode to fall back to.

## The division of labour

This is the split `vertext-core` was already built for — it deliberately owns
no font metrics, because "a terminal, a browser, and a PDF measure text
differently, and the core has no font metrics to break with honestly."

**`vertext-core` (ours):**
- slotting — one ideograph is one slot, one Latin word is one slot
- orientation per slot: upright, turned, cornered, Latin, Mongolian run
- the punctuation contract
- progression (`vertical-rl` CJK / `vertical-lr` Mongolian)
- grapheme cluster boundaries

**Flutter / Dart (theirs):**
- shaping each slot with HarfBuzz
- font metrics and glyph selection
- painting and compositing
- hit-testing and gesture handling

chaji is the seam: it takes `Vec<Column>` of `Slot`s across FFI and places them
with `dart:ui`. It adds no layout policy of its own — a slot classified as
cornering here must corner exactly as it does in the CLI and the browser.

## Shape

```
chaji/
  lib/
    tokens/       # vertical rhythm: column length, gutter, slot advance
    theme/        # ChajiTheme — materialTheme() / cupertinoTheme()
    components/   # ChajiColumn, ChajiText, ChajiVerticalScroll
    ffi/          # vertext-core bindings
  rust/           # cdylib wrapper over vertext-core
```

Mirroring wabisabi's three layers deliberately, so the two read as siblings.
`ChajiTheme` pairs with `WabTheme` and exposes the same two builders —
`materialTheme()` and `cupertinoTheme()` — because an app already switching on
platform through `WabWidget<C, M>` should not learn a second pattern.

Binding via `flutter_rust_bridge` or a plain C ABI. No wasm on mobile: the same
crate compiles to a native library, so this is the third host after the CLI and
`vertext-wasm`, and it costs the core nothing new.

## Constraints worth stating early

- **Never rotate a run.** Per-slot orientation only. A `RotatedBox` over a
  paragraph is the failure this package exists to replace.
- **Never substitute a character.** No U+FE10–FE4F presentation forms. The text
  a user copies must be the text the author wrote — the same contract the
  renderer holds, and it must hold across FFI too.
- **Progression is data.** Read it from the document; never hardcode CJK.
- **Byte-identical slotting.** The same input must produce the same slots here
  as in the CLI. Worth a test that asserts it against the shared goldens, the
  same way the browser extension plans to.
- **Fonts.** Where no vertical-capable Mongolian font is available, say so
  rather than render a rumor of the script.

## The blocking dependency for editing

Display works with what `vertext-core` produces today. **Editing does not.**

Selection, caret placement, and hit-testing all need the inverse map — from a
tap at (x, y) back to an offset in the source. `layout_text` currently returns
slots with no positions, and the renderer computes placement and discards it.
That is the same slot-geometry work [Notes](../notes/README.md) is blocked on,
and Flutter needs it for exactly the same reason.

So: read-only vertical text on Flutter is cheap and available now. Editable
vertical text is downstream of a real change to `vertext-core`, shared with
Notes, the Web IDE, and the Neovim cursor mapping.

## Status

Not started. Planned next, after the Quarto work.

Read-only display is unblocked — it needs the FFI wrapper and nothing else new
from the core. Editing is blocked on slot geometry.
