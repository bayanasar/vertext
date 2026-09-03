# PROGRESS — vertext

<!-- progress -->
updated: 2026-08-30
owner: tata
stage: Quarto path works end to end; Mongolian suffix joining correct in the engine, unproven in the font
<!-- /progress -->

## What this is

A vertical-text layout engine (`vertext-core`), a renderer (`vertext-html`), and
a 37-line stdin→stdout binary (`vertext-cli`) that a Quarto Lua filter shells
out to. The core is pure layout so a future `vertext-wasm` host can share it
byte for byte. CJK ships first; Mongolian `vertical-lr` is the destination, and
nothing in the core may foreclose it.

## Sealed

- `cargo test --workspace` on `0e38451` — 53 green (32 core + 21 html).
- **U+202F crosses the pandoc → filter → binary boundary.** pandoc 3.9 → the
  real `vertext.lua` (4 `quarto.*` calls shimmed) → the real binary emits
  `ᠮᠣᠩᠭᠤᠯ ᠤᠨ` as ONE `vertext-mongolian` span; the old engine emitted two with a
  `vertext-space` between. Run by urtu on review. That is the crossing, not the
  pipeline — `quarto render` has never been run here.
- **The collapse control is clickable.** `kele/tools/check-nav-toggle.py`,
  headless Chrome 152, real `Input.dispatchMouseEvent` — theme-shaped page
  (strip 201→59, columns 549→691) and kele's own lesson (96→34, 486→548), both
  PASS. Same rig on `bedecdb`: `FAIL: strip did not shrink (757 → 757)`. A rig
  that cannot reproduce the failure is not evidence that it is gone.
- **CI runs on every pull request, and the gate has been shown to fail.** The
  `anton` host runner, `.forgejo/workflows/ci.yml`: run 15 green on `673692f9`,
  run 16 **red** on `8067c09e` with `MODE_CODE`'s assertion deliberately
  changed to `'\u{E0FF}'`, run 17 green again on `67afac27` after the revert.
  Both commits are in `main`'s history. A gate that has never gone red is a
  gate whose every green is untested.
- `node examples/test-nav-toggle.js` — 7 green; 3 fail against `bedecdb`.
- `npx sass@1.77.8` — theme compiles clean, `--vertext-nav-target` published.

- **The bichig joins, and a gate says so.** `tools/shaping-golden.py`,
  172 runs — 160 distinct Mongolian runs lifted from the kele lessons at
  `kele@409d212`, plus 12 constructed cases for the two in-word separators.
  `PASS`. The golden records the positional form the shaper picks for each
  letter (`uni1828.N.init uni1823.O.medi uni182E.M.fina` for `ᠨᠣᠮ`), not a
  picture, so nobody has to read bichig to run it. Shown red three ways:
  `--prove` disables `init`/`medi`/`fina` — a non-joining font in all but name —
  and every joined run diffs while no already-isolated run does; a byte appended
  to the font trips the checksum gate ahead of any glyph comparison; and a
  hand-edited expectation diffs. Font and shaper are both pinned
  (`805a55e1…`, harfbuzz 14.4.0), because either can move the glyphs alone.

## Not sealed

- **`page_style()` never declares `--vertext-column-height`.** Missing: any test
  of the column budget in page mode. The documented
  `--vertext-column-theme-height` hook is therefore dead there, in silence.
  `document_style()` does declare it, which is why the browser runs pass.
  Hit independently by two people.
- **Nothing checks that the filter and the binary came from the same source.**
  No `--version`, no comparison, and the two `0.1.0` constants are hand-typed,
  equal by coincidence. A mismatched pair renders wrong with every check green —
  see Open.
- **crates.io is still 0.1.0** (2026-08-08). Nothing in the org installs from it.

## Decisions

- 2026-08-29 **The U+202F fix was merged knowing it left one shape worse than it
  found it**: `ᠢᠢ<U+202F>is written` measured right on `1ac79f0` and wrong on
  `0e38451`. A sealed, correct fix does not wait on an adjacent pre-existing
  defect of the same severity, and `bichig + U+202F + Latin` is rarer in real
  text than the shapes already broken — the separator exists to carry a
  Mongolian suffix. The debt stands until #4 lands.

- 2026-09-02 **Line breaking and kinsoku are the host's, and the boundary is
  now written down** (issue #11, Bayanasar's call). Not a deferral: forbidding a
  column from opening with `。` means owning where the column ends, which means
  measuring, which means fonts at layout time — and a core that holds fonts is
  no longer a core that crosses `wasm32` with no I/O. The alternative on the
  table was pulling break decisions into `vertext-core`; it was not taken, and
  the reason it would ever be taken is print, where there is no browser to
  delegate to. The one state nobody could defend was having neither the feature
  nor the boundary in writing.

- 2026-09-02 **The shaping golden is held to Noto Sans Mongolian, vendored**
  (issue #7). Licensing decided it: Mongolian Baiti has the widest install base
  and Menksoft is what Inner Mongolian print actually looks like, and neither
  can ship with the tests — a golden nobody outside this machine can run is not
  a seal. Noto is OFL 1.1, so `goldens/fonts/` carries the face itself and the
  golden is checksummed against it. Two things the run then settled, neither of
  which the issue had right:
  **U+202F is invisible to the font.** Stem and suffix take the same forms
  across it as across a plain space (`…L.fina nnbsp AO.init A.fina`), and it
  measures a full em, exactly like a space. The font will never carry the
  no-break; keeping the joint in one span is doing all of the work, and the
  golden can only pin `nnbsp` against `space` as glyph names.
  **U+180E detaches, and that is correct.** The issue said the letters either
  side "must still join". They must not: the separator exists to cut a final
  vowel loose, and the font does it at zero advance — `ᠨ` takes `A.fina` and the
  vowel `AA.isol`, against `A.medi` + `A.fina` for the same letters written
  without it. Zero advance means the word measures the same either way.

## Open

- **issue #4 — a transliteration pair changes direction with writing order.**
  `ᠰᠠᠶᠢᠨ(sayin) good` comes out a vertical column and `sayin(ᠰᠠᠶᠢᠨ) good` a
  horizontal line, though both hold 1 vertical and 2 horizontal slots; the first
  is the wrong one. `prefers_horizontal` carries `in_word` across the script
  boundary — `(` takes the word-connector branch — so the run after a bichig
  word goes uncounted, while `layout_text` opens a slot for it. A word list
  mixing both orders flips direction line by line. Carries the U+202F regression
  above. Fix: let `in_bichig` answer *which script owns the open word*, and lock
  the invariant that the measure's slot count equals `layout_text`'s.
- **CI logs cannot be read back.** `actions/runs`, `actions/jobs` and
  `actions/workflows` all return 404 on this instance; only `actions/tasks`
  answers, and it carries status without log text. A reviewer can see that a
  run was green and not what ran inside it — which is how the red run above
  came to be asked for a second time after it had already been performed. The
  gap is in the review path, not in the gate.
- **`alcuka/docs` runs a mismatched pair today.** Its vendored `vertext.lua` is
  blob `9938d18b` (`1ac79f0`, 2026-08-16) while `install-vertext.sh` pins
  `VERTEXT_REF=ebd004c` (2026-08-07) — nine days apart across a commit that
  changed block encoding, the vendoring ahead of the pin. Fix: pin `0e38451` and
  re-vendor as one action. Not tata's lane, and no grant on that repo.
