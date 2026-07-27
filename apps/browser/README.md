# Vertext Browser

A Chromium-based browser whose text stack treats vertical layout as a
first-class flow rather than a late-stage transform.

## Why a whole browser

The extension can repair a page. It cannot repair the engine underneath it: a
content script runs after Blink has already made its layout decisions, so it
works by replacing the engine's output, not by improving it. Anything that
needs to happen *inside* layout — line breaking that knows it is breaking a
vertical line, vertical metrics taken from `vmtx` instead of synthesized,
Mongolian contextual shaping across a line break, ruby that participates in
the column rhythm — is out of an extension's reach by construction.

This is the long game, and it should be named honestly as such: a browser is
a decade-scale undertaking, and most projects that start one die of it. The
justification is not ambition. It is that a script with no correct renderer
anywhere has no other path, and the same argument that produced my script in
1204 applies: adapt the working system rather than invent from nothing.

## Shape

A Chromium fork, kept deliberately thin:

- Blink patches confined to the vertical layout and font-metric paths, so the
  delta against upstream stays reviewable and rebasable. A fork that diverges
  everywhere cannot follow security updates, and a browser that cannot follow
  security updates is not a browser anyone should run.
- `vertext-core` consulted where Blink's assumptions fail — starting with
  Mongolian progression and joining, the case Blink has no correct answer for.
- Everything the fork proves is written up as an upstream bug or patch.
  Rendering the script correctly in one browser is a win; rendering it
  correctly in Chromium is the actual goal, and a fork that never upstreams is
  a fork that ships to nobody.

## Constraints worth stating early

- **Adoption beats elegance.** 'Phags-pa was the more systematic script and it
  is dead. If the browser is not something a Mongolian reader can install and
  use, it does not matter how correct it is.
- **Security is not optional.** Tracking upstream Chromium releases is a hard
  requirement, and it bounds how large the patch set may become.
- **Goldens first.** No claim of correct Mongolian rendering ships without
  reference documents behind it.

## Status

Not started, and correctly last in the queue. The order is `vertext-wasm`,
then the extension, then the Neovim projection, then this. Each one teaches
the layout model something the next needs.
