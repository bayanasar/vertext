# Vertext Browser Extension

A WebExtension (Chrome/Edge/Firefox, MV3) that re-renders vertical text on
pages that ask for it — and on pages that should have asked.

## Why it exists

The web already has `writing-mode: vertical-rl`, and for CJK the browsers do a
serviceable job. Two things they do not do:

- **Traditional Mongolian.** `vertical-lr` with the contextual joining that
  Mongolian requires is broken or absent nearly everywhere. Pages that contain
  bichig are rendered as isolated, unjoined letterforms — legible to no one.
- **Honest fallback.** When a font advertises vertical support and ships no
  `vmtx`, the browser synthesizes metrics silently. The result resembles
  writing without being it.

The extension is the shortest path from `vertext-core` to a reader's eyes on
pages the reader does not control.

## Shape

A content script scans for opted-in regions and replaces them with a rendered
strip:

- `<div lang="mn" data-vertext>` or any element carrying `data-vertext`
- a user-configured per-site selector list
- an explicit "render this selection vertically" context-menu action

Rendering goes through `vertext-wasm`, which wraps `vertext-core` and
`vertext-html` — the same layout code and the same slot-to-class mapping the
Quarto filter uses, so a page rendered by the extension and the same text
rendered by the CLI are byte-identical. That equality is the point, and it is
worth a test that asserts it.

## Constraints worth stating early

- **No remote code.** MV3 forbids it and so do we; the wasm module ships in
  the package.
- **The DOM is someone else's.** Replacement is opt-in and reversible; the
  extension keeps the original nodes and can restore them. A renderer that
  cannot be turned off is a defacement.
- **Fonts.** The extension cannot install fonts. Where no vertical-capable
  Mongolian font is present it must say so in the popup rather than render a
  rumor of the script.

## Status

Not started. `vertext-wasm` is the blocking dependency.
