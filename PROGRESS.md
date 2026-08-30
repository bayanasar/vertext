# PROGRESS — vertext

<!-- progress -->
updated: 2026-08-29
owner: tata
stage: Quarto path works end to end; Mongolian suffix joining correct in the engine, unproven in the font
<!-- /progress -->

## What this is

A vertical-text layout engine (`vertext-core`), a renderer (`vertext-html`), and
a 37-line stdin→stdout binary (`vertext-cli`, installed as `vertext`) that a
Quarto Lua filter shells out to. The core is pure layout so a future
`vertext-wasm` host can share it byte for byte. CJK ships first; Mongolian
`vertical-lr` is the destination, and nothing in the core may foreclose it.

## Sealed

- `cargo test --workspace` on `0e38451` — 53 green (32 core + 21 html).
- **U+202F crosses the whole pipeline, not just the engine.** pandoc 3.9 → the
  real `vertext.lua` (its 4 `quarto.*` calls shimmed) → the real binary emits
  `vertext-mongolian">ᠮᠣᠩᠭᠤᠯ ᠤᠨ<` as ONE span; the previous engine emitted two
  with a `vertext-space` between. Run by urtu on review, not by the author.
  Equivalent path, not `quarto render`: it seals the crossing, not the pipeline.
- **The collapse control is clickable.** `kele/tools/check-nav-toggle.py`,
  headless Chrome 152, real `Input.dispatchMouseEvent`, twice — theme-shaped
  page (strip 201→59, region 176→34, columns 549→691) and kele's own lesson
  (strip 96→34, columns 486→548). Both PASS, `hitsButton=True` throughout.
- **That rig reproduces the bug it claims to fix** — same rig against
  `bedecdb`'s bytes: `FAIL: strip did not shrink (757 → 757)`. A rig that cannot
  reproduce the failure is not evidence that it is gone.
- `node examples/test-nav-toggle.js` — 7 cases green; 3 fail against `bedecdb`.
- `npx sass@1.77.8` — theme compiles clean, 14 `var(--vertext-nav-depth)` sites,
  `--vertext-nav-target` published.

## Not sealed

- **Mongolian shaping.** The joint reaches the DOM in one span, which is what
  lets a font join across it — nothing checks that it *does*, or that
  initial/medial/final forms are right. Missing: a golden reference rendering of
  real bichig. If wrong, pages look plausible and are wrong to a reader of the
  script.
- **`page_style()` never declares `--vertext-column-height`.** Missing: no test
  covers the column budget in page mode. Consequence: the documented
  `--vertext-column-theme-height` hook is dead there — a theme setting it
  exactly as documented is ignored in silence. `document_style()` does declare
  it, which is why the browser runs above pass. Hit independently by two people.
- **Nothing checks that the filter and the binary come from the same source.**
  `vertext-cli` has no `--version`, the filter compares nothing, and
  `_extension.yml: 0.1.0` / `Cargo.toml: 0.1.0` are hand-typed constants equal
  by coincidence. Consequence: a mismatched pair renders slightly wrong with
  every check green. Not hypothetical — see Open.
- **crates.io is still 0.1.0** (2026-08-08). Not a blocker: nothing in the org
  installs from crates.io.

## Decisions

- 2026-08-28 **U+202F stays inside the Mongolian run** — it is the suffix
  separator (UAX #14 class GL), not a word space, but Unicode gives it
  `White_Space=Yes`, and that one property is the whole bug. Buffered like the
  existing `pending_connectors`: one pass over the text means only the next
  cluster can tell the two readings apart.
- 2026-08-29 **The theme names its strip (`--vertext-nav-target`) instead of the
  engine reordering its id fallback** — on a stock Quarto page `#quarto-sidebar`
  is the left sidebar and `#quarto-header` really is the top strip, so a reorder
  trades one wrong element for another. A filter cannot attribute Quarto's
  template output; the theme that sizes it can name it.
- 2026-08-29 **The resolved strip gets stamped `data-vertext-edge="nav"`** — one
  selector for the stylesheet, and external tools find the element the engine
  chose. This is why `check-nav-toggle.py` needed no change to measure right.
- **Progression is data on the run, never an engine constant**, and declared
  rather than detected: a Chinese document teaching Mongolian and a Mongolian
  document teaching Chinese hold the same scripts and want opposite answers.
- **Punctuation is never swapped for a U+FE10–FE4F presentation form.** The view
  rotates; the character stays what the author typed, or copy-paste,
  find-in-page and screen readers hand back codepoints nobody wrote.

## Open

- **issue #4** — `prefers_horizontal` loses a slot where Mongolian and Latin abut
  with no space. Symmetric: `writtenᠢᠢ` measures `true`, i.e. bichig called
  horizontal. Part is new: after the U+202F change the shape extends past the
  separator (`ᠢᠢ<U+202F>is written` → `false`). Lock the invariant that the
  measure's slot count equals `layout_text`'s, not one string's answer.
- **`alcuka/docs` runs a mismatched pair today.** Its vendored `vertext.lua` is
  blob `9938d18b` (from `1ac79f0`, 2026-08-16); `scripts/install-vertext.sh`
  pins `VERTEXT_REF=ebd004c` (2026-08-07) — nine days apart, across a commit
  that changed block encoding. The vendoring ran ahead of the pin, not behind.
  Fix: pin `0e38451` and re-vendor as one action. Not tata's lane, and tata
  holds no grant on that repo.
