# Vertext

Unicode-aware top-to-bottom text with columns advancing right-to-left. This is
a Cargo workspace intended to grow into three adapters: Quarto/Markdown,
Neovim, and a web IDE.

## Run the demo

```sh
cargo build --release -p vertext-cli
export PATH="$PWD/target/release:$PATH"
mkdir -p examples/_extensions
cp -R extensions/vertext examples/_extensions/vertext
quarto render examples/quarto-demo.qmd
```

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
HTML. A future `vertext-wasm` crate will use the same layout API for live web
IDE and browser preview updates.

Prose Latin slots are capped at 12 characters. Long words are hard-wrapped
with a visible hyphen; code blocks use 24 characters so conventional compound
identifiers remain intact. Dictionary-aware hyphenation is a later opt-in
because it needs a language tag and a hyphenation dictionary.
