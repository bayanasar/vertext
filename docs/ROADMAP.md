# Roadmap — the hosts that do not exist yet

Seven adapters have been designed and none of them has been written. This file
is the index of that design work; the documents themselves are in
[`roadmap/`](roadmap/), unchanged from where they used to live under `apps/`.

They were moved because the directory layout was making a claim the code did
not support. A stranger cloning the repository saw seven project directories
under `apps/` and concluded there were seven frontends. That is the same
failure this project keeps naming in its own work — a control that renders and
cannot be clicked, a vendored filter running ahead of its pin — except that
this one misleads a reader rather than a test.

The designs are real work and are kept in full. Only their shelf changed.

| Host | State | Blocked on |
|---|---|---|
| [Quarto theme](roadmap/quarto-theme.md) | Partly real: `extensions/vertext-theme/` ships the SCSS and the nav collapse. The document describes more than exists. | — |
| [chaji 侘寂 (Flutter)](roadmap/chaji.md) | Design only | — |
| [Browser extension](roadmap/browser-extension.md) | Design only | `vertext-wasm` |
| [Notes](roadmap/notes.md) | Design only | `vertext-wasm`, slot geometry |
| [Neovim plugin](roadmap/nvim.md) | Design only | — |
| [Web IDE](roadmap/web-ide.md) | Design only | `vertext-wasm`, slot geometry |
| [Browser](roadmap/browser.md) | Design only, last in the queue | `vertext-wasm`, slot geometry |

The one shipped host is the Markdown/Quarto extension in
[`extensions/vertext`](../extensions/vertext), which is in production.

Two pieces of engine work stand between the design documents and any of the
browser-side hosts. `vertext-wasm` wraps `vertext-core` and `vertext-html` so
those hosts render byte-identically to the CLI. **Slot geometry** — retaining
slot positions and the map back to a source offset — is what every product
that lets a reader place a caret is waiting on.
