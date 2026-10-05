# chaji 侘寂 — a Flutter layout theme

An optional vertical-text theme in the
[wabisabi](https://github.com/bayanasar/wabisabi) widget kit, backed by
vertext.

```
wabisabi  — the widget kit (tokens → theme → components)
chaji     — its optional layout theme (Material + Cupertino)
vertext   — what chaji depends on: the slots, through the Dart binding
```

Wabisabi answers *what a widget looks like*. chaji answers *which way the text
runs and where it goes on the screen*. vertext answers *how the text is cut
into slots and which way each one stands*, the same answer the web page gets.

## Where it lives, and why it stays optional

chaji lives in the wabisabi repository, as an optional theme. What makes it
optional is the dependency it brings: the Dart binding in this repository
(`bindings/dart`) and the native library its build hook compiles from
`crates/vertext-ffi`. Wabisabi's runtime depends on the Flutter SDK alone, so
an app that does not use chaji must not carry a native library for it. How
chaji is packaged inside wabisabi to keep that true is wabisabi's decision.

The split between the two repositories:

- **vertext** (`crates/vertext-ffi`, `bindings/dart`): the slots, their kinds,
  their source ranges, the progression, and a gate that holds the binding to
  the slots the page draws.
- **wabisabi** (chaji): everything that needs a font or a widget tree:
  shaping, metrics, painting, line breaking, hit-testing, the theme tokens and
  the pairing with `WabTheme`.

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

chaji is the seam: it takes the columns of slots from the binding's `layout()`
and places them with `dart:ui`. It adds no layout policy of its own: a slot
classified as cornering here must corner exactly as it does in the CLI and the
browser. The binding makes that checkable: its kinds are the page's class
names, and `bindings/dart/tool/parity.dart` holds its slots to the CLI's.

## Shape

On the vertext side, which exists:

```
crates/vertext-ffi/   # cdylib: layout as JSON over a plain C ABI
bindings/dart/        # package:vertext: dart:ffi, a build hook, layout()
```

On the wabisabi side, a sketch for its owner to change:

```
tokens/       # vertical rhythm: column length, gutter, slot advance
theme/        # ChajiTheme — materialTheme() / cupertinoTheme()
components/   # ChajiText, ChajiColumn, ChajiVerticalScroll
```

`ChajiTheme` pairs with `WabTheme` and exposes the same two builders,
`materialTheme()` and `cupertinoTheme()`, because an app already switching on
platform through `WabWidget<C, M>` should not learn a second pattern.

The binding is a plain C ABI, with no code generator in between. No wasm on
mobile: the same crates compile to a native library, so this is the third host
after the CLI and `vertext-wasm`, and it costs the core nothing new.

## Constraints worth stating early

- **Never rotate a run.** Per-slot orientation only. A `RotatedBox` over a
  paragraph is the failure this package exists to replace.
- **Never substitute a character.** No U+FE10–FE4F presentation forms. The text
  a user copies must be the text the author wrote — the same contract the
  renderer holds, and it must hold across FFI too.
- **Progression is data.** Read it from the document; never hardcode CJK.
- **Byte-identical slotting.** The same input must produce the same slots here
  as in the CLI. `bindings/dart/tool/parity.dart` asserts it in CI over the
  shaping golden's corpus.
- **Fonts.** Where no vertical-capable Mongolian font is available, say so
  rather than render a rumor of the script.

## Editing

Display works with what `vertext-core` produces today, and so, on the core
side, does editing. Selection, caret placement and hit-testing need the
inverse map, from a tap back to an offset in the source. That map exists:
`vertext_core::SourceMap` turns a source offset into a caret (column, slot,
grapheme) and back, and `examples/wasm/caret.html` drives it in a browser.
Each slot the binding returns already carries its source range; the caret
calls are not bound yet. What remains for editing is Flutter's half, hit
testing against the slots chaji placed.

## Status

The vertext side of read-only display exists: `crates/vertext-ffi` and the
Dart binding, held by CI to the page's slots. The theme itself, in wabisabi,
has not been started. Editing comes after read-only display.
