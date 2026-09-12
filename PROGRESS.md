# PROGRESS — vertext

<!-- progress -->
updated: 2026-09-11
owner: tata
stage: Quarto path works end to end; Mongolian joining proven in the font, proven to reach the page in one piece, and proven by CI to be applied by a real browser — no reader has looked at a page yet
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
  `anton` runner (a container, not the host — see below),
  `.forgejo/workflows/ci.yml`: run **3** green on `673692f9`, run **4** red on
  `8067c09e` with `MODE_CODE`'s assertion deliberately changed to
  `'\u{E0FF}'`, run **5** green again on `67afac27` after the revert. Both
  commits are in `main`'s history.

  Those were recorded here as runs 15/16/17 until 2026-09-03. The SHAs and the
  outcomes were right and the numbers were not — the instance says 3, 4 and 5.
  It matters now because 15, 16 and 17 have since been issued to real runs, and
  two of them are red: 15 on `a38f3bc` and 16 on `7bf49cc` failed because the
  shaping step assumed a host runner, and 17 on `6e416d3` is green after the
  fix. Anyone reading "run 16 red" as the deliberate one would be reading my
  mistake as the seal.

  A gate that has never gone red is a gate whose every green is untested. This
  one has now gone red twice without anyone asking it to, which is the stronger
  version of the same evidence.
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

  That gate proves the FONT joins. It does not prove the engine hands the font
  a whole word, because the binary is nowhere in its chain — see the next item,
  which is issue #7's layer 1b.

- **And the engine delivers the whole word to it** (#7, layer 1b).
  `tools/delivery-golden.py`, run by CI: 168 single-run strings — the 160 kele
  corpus runs plus the 8 constructed cases that contain no plain space — go
  through the release binary, and the text is taken back OUT of the emitted
  `vertext-mongolian` span before it is shaped. Exactly one span per run,
  byte-identical, and shaping what came back matches the shaping golden's own
  expectation, so the two gates cannot drift apart. The U+202F joint survives:
  `ᠮᠣᠩᠭᠣᠯ<U+202F>ᠤᠨ` arrives as one span.

  Shown red twice, and the second time is the argument for the layer existing.
  Split `Slot::MongolianRun` per character in the core: this gate fails 155 of
  168 while **`shaping-golden.py` still passes all 172** — it is shaping raw
  strings, so it cannot see an engine at all. Then a subtler cut, in
  `vertext-html` alone, dropping U+180E on the way out of the span: **`cargo
  test --workspace` stays 59 green and this gate fails 34 of 168.** A break past
  the core, in a corpus word no unit test names, is invisible to everything else
  in the repository.

  Honest boundary: the crude per-character split IS caught by 4 core unit tests.
  What this gate adds is the seam beyond core — the html layer, the escaping,
  the binary — measured against 160 real words rather than the handful any test
  spells out.

  **And the same question in context** (#29). Those 168 strings arrive with no
  neighbours, so what they pin is that a LONE run is not cut — while #4 and #3
  were both adjacency defects. Ten whole lines from kele at `409d212`, a reason
  recorded per line, plus four built for shapes the lessons lack, now go through
  the same binary: the spans it emits must be EXACTLY that line's runs, in
  order, byte for byte, and each is shaped against the expectation the golden
  already holds. 40 runs in context, no new expectations, because the corpus was
  extracted from those same files.

  Shown red by a cut that fires only next to a FULL-WIDTH bracket, the one kele
  writes: `cargo test` 59 green, shaping 172 green, browser 168 green, the 168
  bare runs green, **the lines red on 3**. The ASCII version of the same cut is
  caught by `the_measure_counts_the_slots_the_layout_produces` on
  `sayin(ᠰᠠᠶᠢᠨ) good`, which is the boundary: this adds the brackets no test
  spells out, on real lines.

  Two absences in kele, both of them edges, are covered by constructed lines
  instead: not one line contains U+202F, and not one line STARTS with bichig.

  **A layout path nothing had looked at.** A measure whose Latin outweighs its
  vertical script lays out horizontally — #4's mechanism — and carries no
  `vertext-mongolian` span at all. Each line now declares the path it must take,
  so a flip is a red; the horizontal one asserts that the run still appears
  whole, since a mid-run tag would hand the font two fragments. Undeclared, a
  change that sent every line horizontal would leave the gate green and empty.

- **And a real browser joins what we deliver** (#7, layer 2).
  `tools/browser-golden.py`: each of the 168 runs is rendered through the real
  binary and the real `vertext.css`, in headless Chrome 152, twice — once
  normally and once with `font-feature-settings: "init" 0, "medi" 0, "fina" 0`,
  which is the browser-side form of the lever `shaping-golden.py --prove`
  already pulls. The two screenshots are compared cell by cell. All 155
  multi-letter runs change; all 13 single-letter runs do not, which is what
  makes the rig discriminating rather than merely noisy, and a cell that
  rendered nothing fails ahead of either check so the gate cannot pass by
  comparing blank to blank.

  Shown red the way that matters: split `Slot::MongolianRun` per character in
  the core and all 155 multi-letter runs render identically with joining on and
  off — the browser has nothing left to join. Font substitution lands in the
  same trap, since a fallback face with no Mongolian features cannot differ
  either.

  It does not say the shapes are the RIGHT ones — that is the shaping golden's
  job, and this gate deliberately reads pixels it cannot interpret.

  **Both layout paths, not one** (#34). Every cell above is a bare run, so every
  one of them is vertical; the horizontal path — where a Latin-majority measure
  keeps the run in the line instead of making it a slot — had never been
  rendered by this gate, and that is where #35's defect was living. Two
  horizontal lines are now in the grid, in their own wider cells (the 72px
  column clipped a sentence of English down to white, and compared white to
  white: the blank check exists for exactly that). Both must change when joining
  is switched off.

  The lever names both classes and carries `!important`, because
  `.vertext-mongolian` declares its own `font-feature-settings` and beats a `*`
  rule on specificity — the first measurement of the horizontal path reported
  "nothing joins anywhere" and was measuring that mistake.

  Shown red twice, and the two reds are distinguishable, which is what #34 asked
  for: drop the face from `.vertext-mongolian-inline` and only the 2 horizontal
  lines report identical, pointing at the stylesheet; drop it from
  `.vertext-mongolian` and the 155 vertical runs report identical instead.

  **And it runs in CI** (#28), which it did not when it was written.
  `azura-ci:latest` has no browser and no `npx`, so the step brings its own:
  chrome-for-testing at a pinned version, cached by that version, plus the 14
  apt packages holding the 16 shared libraries it is otherwise missing. Shown
  red the way #20 requires — run **23** green on `3190420` with the step added,
  run **24** red on `0ff915b` with `JOINING_OFF` replaced by a declaration that
  changes nothing, run **25** green on `1c9b055` after the revert.

  The attribution matters because this instance's logs cannot be read back (see
  Open), so the red has to be placed by what the API does answer: the same suite
  without this step takes 12–15s (runs 20, 21, 22), the two accidental reds this
  repository has had failed at 5s, and run 24 failed at **30s** — the suite,
  plus the cache restoring 391MiB of browser, plus apt, plus the gate running
  and failing. 99s cold to 30s warm is the cache proving itself as well. The
  only difference between 23 and 24 is one constant that nothing but that step
  reads, and the same break reproduces locally with the message the step must
  have printed.

  Two traps are handled in the step rather than left to be discovered: the zip
  alone does not run, so the step fails with `ldd`'s list rather than letting
  the gate time out; and the runner's container gets the default 64MB
  `/dev/shm`, at which size this grid does not fail but HANGS — `browser-golden`
  passes `--disable-dev-shm-usage` for that, and `privileged: false` means the
  shm size is not ours to set.

  The class a run falls in is decided by LETTERS, not codepoints (`e3eb138`).
  A run arrives from the lessons with what rides along inside it, and 46 of the
  160 corpus runs already have more codepoints than letters — sentence
  punctuation, the vowel separator. None of the 46 crosses the "two or more"
  line, so the first version of this gate was green for the right reason by
  luck: a single letter plus a free variation selector is two codepoints and one
  letter, it cannot change when joining is switched off, and the gate would have
  reported `the browser is not applying the joining features` about a correct
  browser. Shown red both ways — the old `len()` fails on `("fvs-single", "ᠠ᠋")`
  while the new count passes the same corpus, and a run with no letter at all
  now fails loudly instead of passing through unexamined. The counter lives next
  to `shape()` in `shaping-golden.py`, one definition for all three gates.

  The measurement route was tried first and abandoned: every letter of this font
  carries the same vertical advance in every positional form, so across all 168
  runs the joined advance sum equals the per-character isolated sum, and the
  only advances in the golden are 0 and 1000. Geometry cannot see joining here.

- **The bichig on the HORIZONTAL path now gets a face that joins** (#35). A
  measure whose Latin outweighs its vertical script lays out horizontally — #4's
  mechanism — and that path emits no `vertext-mongolian` span, which is the class
  the stylesheet hangs the Mongolian `font-family` on. So bichig inside an
  English sentence was rendering in whatever face the browser fell back to.

  Measured before it was written and again after, with the lever
  `browser-golden.py` already uses (`init`/`medi`/`fina` off, compare ink —
  forced with `!important`, because `.vertext-mongolian` declares its own
  `font-feature-settings` and wins on specificity otherwise):

  | | joining off |
  |---|---|
  | vertical run | changes — a joining face is applied |
  | horizontal line, before | **identical** — nothing was joining it |
  | horizontal line, after | changes |

  The fix marks each run on that path with `vertext-mongolian-inline`, a class
  carrying the face and nothing else: reusing `.vertext-mongolian` would also
  bring `writing-mode: vertical-lr` and stand the run upright inside a line of
  English, trading a font defect for a layout one. U+202F stays inside the run
  for the reason it stays inside `Slot::MongolianRun`. Code blocks keep their
  monospace face deliberately.

  `delivery-golden.py` now asserts on that path too — the marked runs must be
  exactly the line's runs, in order — shown red by removing the marking: `want
  ['ᠡᠨᠡ','ᠮᠢᠨᠦ','ᠡᠵᠢ'] got []`. Four unit tests cover the markup, the joint, the
  escaping and the code exemption.

  Found because #33 pinned the horizontal path's existence and #34 asked what it
  looks like; the answer was a defect, not a test gap. **What is still missing is
  the image evidence** — see Not sealed.

- **The theme's vendored filter is byte-identical to its source, and CI says so**
  (#25). `extensions/vertext-theme/_extensions/vertext/` carries its own copy of
  the content extension because Quarto requires an extension that uses another
  to embed it, and the two had drifted twice: once by a whole commit, and again
  by comments edited in the copy rather than refreshed from the source, which
  left it describing the old 8-codepoint block four lines from the constant that
  says 13. Refreshed with `cp -R`, which is the only way it should ever change.

  The assertion already existed, in `examples/test-extension.sh`, and had never
  once executed: that script needs `quarto render` and no runner here has
  Quarto, so the copies sat unequal with every gate green. The comparison needs
  nothing but `diff`, so it is now its own CI step. Shown red by appending one
  line to the copy, green again after the refresh.

- **issue #4 is closed, and so is the U+202F debt it carried.** `3df71a8` let
  the measure say which script owns the open word. Both orders of the
  transliteration pair now lay out horizontal — checked again on `35aab87`
  through the release binary, not only in the unit test.
  The invariant that made it worth fixing is pinned rather than described:
  `the_measure_counts_the_slots_the_layout_produces` walks 21 shapes and
  asserts the measure's slot count equals `layout_text`'s for each. Three of
  them carry U+202F, including `ᠢᠢ<U+202F>is written` — the exact shape the
  2026-08-29 decision below left standing as debt. It is discharged.

- **No strip ends in a blank column any more.** `35aab87`. The blank column
  fires on a paragraph break the author typed, which is what it was always for;
  it no longer fires on the newline that ends the file, which every file has.
  Three tests, shown red against the old condition.

- **The column budget's theme hook is live in both modes, and tested.**
  `examples/test-column-budget.js`, run by CI. `page_style()` never declared
  `--vertext-column-height` at all, so `--vertext-column-theme-height` — the
  documented way a theme states its strip depth — went into a variable no rule
  read, and vertext.css fell through to its own fallback without saying so.
  Two people hit that separately before it was found. Both modes now declare
  it on `body` and route it through the hook, with a fallback each, **in both
  copies of the filter** — the gate reads the engine's and the theme's vendored
  one, because the first cut of the fix went into the engine's alone. Shown red
  three ways: page mode's declaration removed (the shipped state), document
  mode's hook bypassed rather than merely absent, and the theme copy's
  declaration removed while the engine's stands.

  The test was itself wrong first, and the way it was wrong is the reason to
  say so here: both stylesheets explain this variable in a comment that writes
  `body { --vertext-column-height: ... }` as an example, and the first draft
  matched that sentence instead of the code. It reported the hook present on a
  stylesheet stripped of it. Comments are removed before anything is read now.

- **The `anton` runner is a container, and the whole job has been run inside
  it.** Its registration reads `anton:docker://azura-ci:latest`, so a job sees
  that image's toolchain — cargo 1.98, node 18, python3.11 — and not the
  machine's. `ci.yml`'s header asserted the opposite ("there is no container")
  from the day it was written, and the first step written to its word went red:
  runs 15 and 16 (tasks 70, 71) failed on `a38f3bc` and `7bf49cc`, because
  Debian splits `venv` and `pip` out of `python3` into `python3-venv` and the
  image does not carry it. Every one of the five steps has now been executed
  against `azura-ci:latest` on this machine, in order, and the shaping step
  installs what it is missing before using it. The header says what the runner
  is.

  The failure is worth keeping in view: the belief was three weeks old, written
  in a comment nobody had reason to doubt, and it cost two red runs to find —
  which is the same shape as the dead theme hook and the blank column above.
  None of the three was a hard bug. All three were something true that stopped
  being true with nothing watching.

- **The repository no longer commits its own generated artifacts** (#15).
  Sixteen files left the index: `examples/_extensions/vertext/` (three) and the
  `quarto render` output (`examples/quarto-demo.html` plus twelve under
  `examples/quarto-demo_files/libs/`, ~850KB of it minified third-party
  bootstrap, popper, tippy, clipboard and anchor carrying no licence or
  attribution). Three things were checked before they went, not after:
  the committed filter was blob `9938d18b` against a source at `0c24c158`, and
  `9938d18b` is the same revision `alcuka/docs` vendored — the drift was real
  and was the known-bad one; `diff -rq` puts it in `vertext.lua` alone, with
  `_extension.yml` and `vertext.css` identical; and nothing in the repository
  reads either path — the one hit for `_extensions` in a test is
  `examples/test-column-budget.js` reading `extensions/vertext-theme/`'s
  vendored copy, which is a different, legitimately committed file.

  `.gitignore` had named `/examples/_extensions/` since 2026-08-22 and it never
  took effect: git applies the file to untracked paths only, and `git
  check-ignore` answers for a tracked path as though the rule were absent, so
  the one command anyone would run to test the rule reported it working. An
  ignore rule added after the fact needs `git rm --cached` in the same commit.

## Not sealed

- **No one who reads the script has looked at a page yet** (#7, layer 3).
  Layers 1a, 1b and 2 are sealed above: the font joins, the engine delivers a
  whole word to it, and a real browser applies the joining. None of that is a
  reader saying the page is writing rather than marks in the right places, and
  that is Bayanasar himself. `needs-native-reader` on that issue means him
  sitting down with a page, not a third party, so it blocks nothing else.
- **The delivery chain starts at the binary; the filter half has no gate at all**
  (#30). Real documents go pandoc → `vertext.lua` → the PUA wire protocol →
  binary, and all three goldens begin after the filter. That is the half #25 just
  proved drifts. The one thing in the repository that runs the filter is
  `examples/test-extension.sh`, which needs `quarto render` and therefore never
  executes. Feasibility is already on record: the U+202F crossing above was run
  with pandoc 3.9 and the real filter with four `quarto.*` calls shimmed, and
  unlike a browser, pandoc is in Debian's archive — so this is not blocked on the
  image the way #28 is.
- **`examples/render.sh` has been read, not run.** #15 asked for proof that it
  regenerates everything now removed. Half of that is proven by inspection —
  `examples/_extensions/` is a `cp -R` from `extensions/vertext`, which is the
  same operation whose result was just compared byte for byte. The other half
  is `quarto render`, and **quarto is not installed on this machine**, so the
  demo output under `examples/` was untracked on the strength of the script's
  text rather than a run. Whoever has Quarto should run `./examples/render.sh`
  from a clean checkout and confirm both paths come back.
- **The two modes have been measured, and what the length SHOULD be is still
  undecided** (#26). `tools/measure-column-budget.py`, headless Chrome 152, the
  same source through the real binary in both modes at four window sizes, with
  a 400-character upright probe to count what fits:

  | window | mode | column | chars/column |
  |---|---|---|---|
  | 1280×800 | document | 521px | 24 |
  | 1280×800 | page | 612px | 29 |
  | 1920×1080 | document | 801px | 38 |
  | 1920×1080 | page | 612px | 29 |
  | 1280×2000 | document | 1721px | 81 |
  | 1280×2000 | page | 612px | 29 |
  | 768×1024 | document | 745px | 35 |
  | 768×1024 | page | 612px | 29 |

  Document mode runs 24 to 81 characters a column across ordinary windows — a
  3.4× swing in the length of a line, which in vertical setting is the rhythm
  the eye moves in. Page mode is 29, always, whatever the window.

  That half-inverts the issue's own premise, which reads as though the hardcoded
  side were the problem: neither number has a provenance, but the swinging one is
  the one to change first, because a fixed value at least gives the same page
  twice while a window-derived one does not give the same page on two machines.
  Recorded on the issue rather than left in the commit.

  Two things the measurement settled that guessing had wrong. **`34em` is not
  34 characters**: it resolves to 612px and holds 29, because a character cell
  is ~21.2px at this size and not 1em. And the first metric tried was wrong
  too — counting characters per `.vertext-column` measures how the SOURCE was
  chunked, not how the page reads, and grouping them by position fragments on
  every rotated punctuation mark. Hence the boring probe.

  What is NOT decided is step 2 of the issue: what the length should be a
  function of — the window, the window minus `--vertext-nav-depth`, or a
  declared value — and that belongs in the README beside progression, because
  the measure of a page is data and not an engine constant. Changing it moves
  every page already rendered, kele's pixel seal included, so the decision is
  Bayanasar's and the rebuild is `frontend-kele`'s.
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
  Mongolian suffix. The debt stood until #4 landed; `3df71a8` landed it and
  `ᠢᠢ<U+202F>is written` is now one of the shapes the slot-count invariant
  walks. Closed 2026-09-02.

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
