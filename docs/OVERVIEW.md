# Overview — the vertext family

One engine and the documents that consume it. Start here if you have never seen
this project. `ARCHITECTURE.md` explains how the engine works; each repository's
`README.md` says how to run it, and each `PROGRESS.md` says which of its claims
have actually been run.

## The chain

```
crates/vertext-core     pure layout: text + style in, positioned slots out
        │               no I/O, no DOM, nothing that cannot cross wasm32
crates/vertext-html     slots ──► HTML columns and CSS
crates/vertext-cli      37 lines: stdin ──► stdout, installed as `vertext`
        │
extensions/vertext/vertext.lua      Quarto filter; shells out to the binary
extensions/vertext-theme/           SCSS; sizes the page around the columns
        │
   ┌────┴───────────────────────────────┐
   │                                    │
alcuka/frontend-kele              alcuka/docs
Mongolian lesson notes            Quarto site (gilfoyle's lane)
```

The filter and the binary talk over a Private Use Area wire protocol. Two halves
from different builds raise no error — only misplaced text. That is this
family's structural weakness and the root of every version incident in it so
far.

| Consumer | How it binds the engine | Exposure |
|---|---|---|
| `frontend-kele` | runs `../vertext/target/release/vertext`, the sibling checkout | none: no pin to drift, picks up a rebuild immediately |
| `alcuka/docs` | vendors `vertext.lua` **and** pins `VERTEXT_REF` for the binary | two independent pins, which can and did drift apart |

## Where it stands

| | Stage | Evidence |
|---|---|---|
| `vertext` | The Quarto path works end to end. CJK correct; Mongolian suffix joining correct in the engine, unproven in the font. | `cargo test --workspace` 53 green on `0e38451`; U+202F verified across pandoc → filter → binary; the collapse control clicked by a real mouse event in headless Chrome 152 |
| `frontend-kele` | 13 pages build and render vertically against the merged engine. | full build on `vertext@0e38451`; nav collapse PASS under real `Input.dispatchMouseEvent` |
| `alcuka/docs` | Consuming a mismatched pair at the time of writing: vendored filter from 2026-08-16, binary pinned to 2026-08-07, across a commit that changed block encoding. | the two SHAs, read off the repository |

Seven adapters are named in `apps/` — browser extension, browser, chaji, notes,
nvim, quarto-theme, web-ide — and every one of them is a README with no code.
The Quarto path is the only shipped host. `vertext-wasm` does not exist yet; the
core is kept pure so that it can.

## What is not proven

In descending order of what it would cost to be wrong:

1. **Mongolian shaping.** The suffix joint reaches the DOM inside one span,
   which is what *lets* a font join across it. Nothing checks that the font
   does, or that initial/medial/final forms are selected right. There is no
   golden of real bichig, so a page can look plausible and read wrong.
2. **Direction of a transliteration pair** (issue #4). `ᠰᠠᠶᠢᠨ(sayin) good` lays
   out as a vertical column and `sayin(ᠰᠠᠶᠢᠨ) good` as a horizontal line, on
   identical slots. Script-with-transliteration is the core content of a lesson
   repository, so this is live rather than theoretical.
3. **Filter/binary provenance.** Nothing compares the two halves.

## The standard this work is held to

- **A rendering claim without a golden is a rumor.** "It parses" and "it looks
  right" are not results.
- **The core stays pure.** Adapter concerns live in adapters, or the core stops
  being worth keeping once the adapters churn.
- **Progression is data on the run, never an engine constant.** CJK advances
  right-to-left, Mongolian left-to-right; an engine that hard-codes one has
  chosen which literatures it betrays.
- **Sealed and unsealed are listed separately, always.** Every claim carries
  either the run that proved it or the run that is missing.
