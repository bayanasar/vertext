# PROGRESS — vertext

<!-- progress -->
updated: 2026-10-04
owner: maintainer
stage: Quarto path works end to end; Mongolian joining proven in the font, proven to reach the page in one piece, and proven by CI to be applied by a real browser — no reader has looked at a page yet
<!-- /progress -->

## What this is

A vertical-text layout engine (`vertext-core`), a renderer (`vertext-html`), and
a 37-line stdin→stdout binary (`vertext-cli`) that a Quarto Lua filter shells
out to, and `vertext-wasm`, the same renderer for a browser. The core is pure
layout so that the two hosts share it byte for byte. CJK ships first; Mongolian `vertical-lr` is the destination, and
nothing in the core may foreclose it.

## Sealed

- `cargo test --workspace` on `0e38451` — 53 green (32 core + 21 html).
- **U+202F crosses the pandoc → filter → binary boundary.** pandoc 3.9 → the
  real `vertext.lua` (4 `quarto.*` calls shimmed) → the real binary emits
  `ᠮᠣᠩᠭᠤᠯ ᠤᠨ` as ONE `vertext-mongolian` span; the old engine emitted two with a
  `vertext-space` between. Run by a reviewer. That is the crossing, not the
  pipeline — the first real `quarto render` is the release-archive check below.
- **The collapse control is clickable.** the lesson site's `tools/check-nav-toggle.py`,
  headless Chrome 152, real `Input.dispatchMouseEvent` — theme-shaped page
  (strip 201→59, columns 549→691) and one of its own lessons (96→34, 486→548), both
  PASS. Same rig on `bedecdb`: `FAIL: strip did not shrink (757 → 757)`. A rig
  that cannot reproduce the failure is not evidence that it is gone.
- **CI runs on every pull request, and the gate has been shown to fail.** The
  runner (a container, not the host — see below),
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
  172 runs — 160 distinct Mongolian runs lifted from the lesson corpus at
  `409d212`, plus 12 constructed cases for the two in-word separators.
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
  `tools/delivery-golden.py`, run by CI: 168 single-run strings — the 160 corpus
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
  were both adjacency defects. Ten whole lines from the lessons at `409d212`, a reason
  recorded per line, plus four built for shapes the lessons lack, now go through
  the same binary: the spans it emits must be EXACTLY that line's runs, in
  order, byte for byte, and each is shaped against the expectation the golden
  already holds. 38 runs in context, no new expectations, because the corpus was
  extracted from those same files.

  Shown red by a cut that fires only next to a FULL-WIDTH bracket, the one the lessons
  writes: `cargo test` 59 green, shaping 172 green, browser 168 green, the 168
  bare runs green, **the lines red on 3**. The ASCII version of the same cut is
  caught by `the_measure_counts_the_slots_the_layout_produces` on
  `sayin(ᠰᠠᠶᠢᠨ) good`, which is the boundary: this adds the brackets no test
  spells out, on real lines.

  Two absences in the lessons, both of them edges, are covered by constructed lines
  instead: not one line contains U+202F, and not one line STARTS with bichig.

  The U+202F half of that was false until #39. Two of the three constructed
  lines named for the joint held U+0020 from the day they were written, so what
  they checked was an ordinary word break, and the count was 40 because each
  counted the stem and the suffix as two runs. The joints are `\u202f` escapes
  now, since the two characters cannot be told apart by eye, and a case named
  for the joint that does not contain one stops the tools at import. Shown red
  by making the renderer's scan stop joining U+202F: with the old cases the gate
  is red on 1 line, with the fixed ones on 3.

  **A layout path nothing had looked at.** A measure whose Latin outweighs its
  vertical script lays out horizontally — #4's mechanism — and carries no
  `vertext-mongolian` span at all. Each line now declares the path it must take,
  so a flip is a red; the horizontal one asserts that the run still appears
  whole, since a mid-run tag would hand the font two fragments. Undeclared, a
  change that sent every line horizontal would leave the gate green and empty.

  **And every vertical line is asked the horizontal question too** (#38). Where
  a run starts and ends is defined twice — `Slot::MongolianRun` in the core,
  `mark_mongolian_runs` in the renderer — and the edges that could split them
  (U+1802/U+1803 after a word, U+180E) were only in the vertical lines. Each of
  the 13 now also goes through with enough Latin words appended to flip it, and
  the gate checks that it did flip; the inline-marked runs must equal the same
  `runs_in()` list: 2
  horizontal lines checked became 15. Shown red by a cut in the renderer's scan
  alone, ending a run at U+180E: `cargo test` 63 green, the gate as it was on
  `main` green, **the pushed lines red on 4** (`ᠪᠠᠶᠢᠨ<U+180E>ᠠ` came back as two
  runs), every vertical assertion still green. The red lands only on the side
  that split. Merging the two definitions into one was left for the day they
  actually disagree, as the issue asks.

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
  The CI image has no browser and no `npx`, so the step brings its own:
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
- **The filter half of the chain runs, and CI says so** (#30). Every gate above
  starts at the binary — they hand it text on stdin. A real document goes
  pandoc → `vertext.lua` → the PUA wire protocol → the binary, and that first
  half had never been executed by anything that can fail. It is also the half
  that moves: #25 found the theme's copy a whole commit behind, and the
  assertion that would have caught it needed `quarto render`.

  `tools/filter-golden.py` runs the real filter under plain pandoc.
  `tools/quarto-shim.lua` supplies the three `quarto.*` functions the filter
  calls — `doc.add_html_dependency`, `doc.is_format`, `log.warning` — and
  nothing else, then `dofile`s the filter unmodified. That is the route a reviewer
  took by hand for the U+202F crossing recorded above; this makes it a gate
  rather than a memory. 160 corpus runs cross the whole chain as one span each
  and shape as the golden recorded, every block kind the wire encodes comes back
  as itself (heading at its level, table with cells, both list kinds, code), and
  **stderr must be empty**: the filter's own fallback warns and then ships plain
  horizontal text, which looks like a clean render to everything else.

  Shown red twice. `--prove` takes the binary off PATH — the accident this gate
  exists for — and the chain falls back to plain text with 0 spans, which the
  gate reports. And an off-by-one in the filter's `MODE_HEADING_BASE`, the same
  class as #17's `RESERVED_END`: `cargo test` 59 green, shaping 172 green,
  delivery 168 green, browser 168 green, **this gate red**, because headings
  stopped arriving as headings.

  pandoc is Debian's 2.17 rather than Quarto's 3.x. Both were run against these
  fixtures and the HTML came back byte-identical, so the ~5s apt package is
  bought instead of a 33MiB tarball; pin a 3.x the way the browser is pinned if
  they ever diverge. The theme's vendored copy is not run separately — the step
  above proves the two are byte-identical, so running one runs both.

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

- **The runner is a container, and the whole job has been run inside
  it.** Its label maps to a docker image, so a job sees
  that image's toolchain — cargo 1.98, node 18, python3.11 — and not the
  machine's. `ci.yml`'s header asserted the opposite ("there is no container")
  from the day it was written, and the first step written to its word went red:
  runs 15 and 16 (tasks 70, 71) failed on `a38f3bc` and `7bf49cc`, because
  Debian splits `venv` and `pip` out of `python3` into `python3-venv` and the
  image does not carry it. Every one of the five steps has now been executed
  against the CI image on this machine, in order, and the shaping step
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
  `9938d18b` is the same revision a downstream documentation site vendored — the drift was real
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

- **Romanization with `ɣ`/`γ`, and Cyrillic, stay whole words** (#42). Found by
  a reader, not a gate: `(mongɣol-un)` in a vertical line came out as `(mong`,
  an upright `ɣ` and `ol-un`, because the Latin-word class stopped at U+024F and
  IPA `ɣ` is U+0263. The same rule laid `Монгол` out one upright letter per
  slot. The class now also takes letters (not punctuation) from IPA, Greek,
  Cyrillic, the phonetic and the later Latin extensions. `cargo test --workspace`
  65 green; the two new tests fail on the old rule; delivery, browser and
  column-budget gates green. The lessons romanize with `G`, which is why no
  gate ever saw it.

- **A reader of the script has read the pages** (#7, layer 3), 2026-09-12, the
  reader the issue names, in a browser over the network rather than a
  screenshot. Read: lesson 6 of the lessons (built with vertext 0.2.0 and the
  golden's pinned font, U+180E in 26 places) — "looks good"; and the U+202F
  constructed lines — the bare run, the joint in brackets and the joint on the
  horizontal path read as written. The fourth, the joint in a sentence, was
  reported wrong, and the fault was beside the bichig rather than in it: the
  romanization `(mongɣol-un)` split around its `ɣ`, which is #42. The comparison
  columns with init/medi/fina switched off read as isolated letters, which is
  what they are for.

  Layers 1a, 1b and 2 said the font joins, the engine hands it whole words and
  a browser applies the joining. This is the one that says the result is
  writing, and it found a defect none of the three could see.

- **0.2.0 is on crates.io** (#9, step 1). `cargo publish --workspace` from
  `a10ff22`, tagged `v0.2.0`; crates.io lists all three crates at 0.2.0,
  uploaded 2026-09-13 02:26 UTC, each package 6 files. `cargo install
  vertext-cli --version 0.2.0 --locked` from crates.io into an empty root prints
  `vertext 0.2.0`, which the filter's `^vertext%s+(%d+%.%d+)` reads as `0.2`, its
  `WIRE_VERSION`.

  The first real publish failed verification with `E0603: function
  is_mongolian is private`, although the tree was right. A dry-run from before
  the horizontal-path MR (#36) made that function public had left a
  `vertext-core 0.2.0` build in `target/debug`, and cargo keys a
  registry crate's build by name and version, not by content, so it checked the
  new `vertext-html` against the old core. Deleting that unit fixed it. Before
  publishing a version that was dry-run on an older tree, remove
  `target/package` and the `vertext-core-*` units it built, or `cargo clean`.

- **`quarto add` installs the filter from a release zip, and real Quarto
  renders with it** (#9). `tools/quarto-archive.py` builds
  `vertext-quarto-0.2.0.zip` (`_extensions/vertext/`, three files, sha256
  `877e7e26…`, byte-identical across builds) from `extensions/vertext`, and CI
  builds it on every run. Quarto 1.10.18's Linux release, unpacked outside the
  tree: `quarto add http://127.0.0.1:…/vertext-quarto-0.2.0.zip --no-prompt`
  installs three files byte-identical to the source; `quarto render` of a page
  with Han and `ᠮᠣᠩᠭᠣᠯ<U+202F>ᠤᠨ ᠨᠣᠮ᠃`, with the binary from `cargo install
  vertext-cli --version 0.2.0` first on PATH, gives 8 upright slots and 2
  Mongolian spans, the joint inside the first, and no warning. The same render
  with a stub answering `vertext 0.1.0` prints the refusal and emits no spans.

  The public `v0.2.0` release now carries the zip (sha256 as above, release
  tag at `a10ff22`), and the README's command was run as written:
  `quarto add https://github.com/bayanasar/vertext/releases/download/v0.2.0/vertext-quarto-0.2.0.zip`
  installs three files identical to `v0.2.0:extensions/vertext`, and the render
  above repeats with the joint in one span.

  The format follows Quarto's installer source, not a guess: a URL that is not
  a GitHub repository or archive is saved as `extension.zip` whatever it is, and
  the name chooses the unpacker, so a tarball there fails; and `_extensions/`
  at the archive root is used as is.

- **A column is a declared number of characters, capped by the space there
  is** (#26). Both mode stylesheets budget
  `min(calc(var(--vertext-column-chars, 34) * 18px), <space>)`, the space being
  the theme hook or the mode's own fallback, and `vertext-column-chars:` in the
  YAML sets the count. Rendered with Quarto 1.10.18 and measured in headless
  Chrome, against the same documents on `main`:

  | document | window | `main` | now |
  |---|---|---|---|
  | page mode, nothing declared | 1280×2000 | 612px | 612px |
  | page mode, nothing declared | 1280×500 | 612px, bottom at 638 | 449px |
  | document mode, nothing declared | 1280×2000 | 1796px | 612px |
  | document mode, nothing declared | 1280×500 | 296px | 296px |
  | page mode, `vertext-column-chars: 20` | both | — | 360px |
  | a fenced strip on an ordinary page, 20 | both | — | 360px |
  | page mode, `vertext-column-chars: abc` | both | — | default, with a warning |

  `tools/measure-column-budget.py --cjk-font …` reports 612px and 34
  characters, 18.0px each, in both modes wherever the window has room.
  `examples/test-column-budget.js` now also requires the count, the cap, one
  default and one cell size across both modes and both filter copies, and that
  the cell is the upright glyph size; shown red by restoring the old
  document-mode declaration, and by setting the upright size to 20px.

  **A correction to what was recorded before.** The first measurement for this
  issue said `34em` holds 29 characters because a cell is ~21.2px. That was the
  measuring machine, not the page: it has no CJK font, and Chrome's tofu box
  advances 21px where the 18px cell does. With a CJK font loaded the same column
  holds 34. Every character count recorded for #26 before this was low by about
  a sixth, and the measuring tool now refuses to report when its probe does not
  advance by the cell.

- **Every slot maps back to its source, and a caret moves both ways** (#12).
  `vertext_core::source_map` walks a layout over the text it came from and
  records each slot's column, position, byte range and grapheme boundaries;
  `SourceMap::caret` and `SourceMap::offset` convert between a source offset
  and `(column, slot, grapheme)`. `cargo test -p vertext-core`: on 20 texts
  covering CRLF and blank lines, U+202F joints and trailing separators, U+180E,
  a variation selector, ZWJ emoji, combining marks, buffered connectors, split
  long words and IPA/Cyrillic words, every slot's range holds exactly its text,
  the uncovered bytes are exactly the line breaks, and every grapheme boundary
  goes to a distinct caret and back. A Mongolian run of 9 graphemes is one slot
  with 9 caret positions inside it. The only character layout adds, the hyphen
  that splits a long word, is flagged and has no bytes. A layout that changes a
  tab into a space fails both property tests, and a layout of a different text
  is refused. `cargo build -p vertext-core --target wasm32-unknown-unknown`
  builds.

- **The browser build renders the CLI's bytes, and a caret uses the source
  map** (#13, #12). `vertext-wasm` exports `render_document` and the source map
  through a C ABI with no imports (129KB release). `node tools/wasm-parity.mjs`:
  895 renders — the 160 corpus runs, the 13 lines, and wire-protocol, CRLF, code
  and escaping inputs, under 5 flag sets — equal to `target/release/vertext`
  byte for byte, and on the 353 mapped strips one span per slot with 3239 carets
  converting to offsets and back. Red when the glue sends the page flag as the
  wrong bit, and when the wasm ignores it. `python3 tools/wasm-caret.py`: in
  headless Chrome, `examples/wasm/caret.html` clicks each of 35 graphemes
  through `caretRangeFromPoint` and the textarea caret lands on that character,
  including each letter inside a 9-grapheme Mongolian run; 23 caret moves outline
  their slot. Red when the grapheme index is fixed at 0: every click inside the
  run lands at its start. Both run in CI. The caret check waits for the page to
  POST its result rather than dumping the DOM after a virtual-time budget,
  which did not wait for the font and reported nothing in 3 of 12 runs (#47);
  15 of 15 green since.

- **The module and its glue refuse each other across releases, and ship as one
  archive** (#46). `vertext_version` exports the crate version; the glue's
  `load()` throws `VersionMismatch` unless its wire version is the glue's
  (MAJOR.MINOR for a release, the whole version for a pre-release), so a patch
  release may not change an export or the source
  map's meaning. `tools/wasm-caret.py` loads the page three more times — glue
  changed by one digit, the version inside the `.wasm` changed by one digit,
  the export renamed away — and each is refused, naming both sides. Red
  with the check disabled (all three render), and with only the missing-export
  branch removed (the refusal is a `TypeError`, not the versions).
  `tools/wasm-archive.py` builds `vertext-wasm-<version>.zip` (`vertext.mjs`,
  `vertext.wasm`) in CI on every run, refusing when the version declarations
  disagree (shown with the glue at `0.3`), when the module does not
  load through the glue, or when it carries a build-machine path. The last is
  real: a release `.wasm` keeps panic locations, and dependency paths sit under
  `$CARGO_HOME` — a home directory in a published file. Built with the prefixes
  remapped, the archive has the same sha256 from two checkout paths; without
  the remap it is refused.

- **The upright cell is declared once** (#48). `--vertext-cell: 18px` on
  `:root` in `vertext.css` is the glyph size and the unit the column budget
  counts in; the stylesheet's 10 restatements now read it, and the filter's 2
  budgets read it with an 18px fallback for a page without the stylesheet.
  `examples/test-column-budget.js` requires the fallback to equal the
  declaration and no other px equal to the cell in the stylesheet or filter;
  red for a restated `18px` in `.vertext-corner`, for a declaration changed to
  20px, and for one fallback changed to 20px. Real render, Chrome with Noto
  Sans SC: `tools/measure-column-budget.py` gives the same table as `main` on
  4 windows × 2 modes, and the 4 measurement pages screenshot byte-identical
  to `main`'s. Declared at 20px, both modes give 680px columns holding 34
  characters at 20px each. The tool now reads the cell from the page.

- **A document mode page opens at its first column in either progression**
  (#52). The content region took `vertical-rl` whatever the document declared,
  so a Mongolian (`vertical-lr`) document opened at its end: measured through
  the real filter, the first column at x=-100 in a 900px window and the last in
  view. The region now follows the progression, as page mode already did.
  `tools/progression-scroll.py`, in CI: one overflowing document per
  progression through pandoc, the filter and the binary, in headless Chrome;
  the first column must be in the viewport on load. Red with the region written
  back to `vertical-rl`: the `lr` document's first column at x=-2359.

- **Conformance to CLReq and MLReq is written down** (#10).
  `docs/CONFORMANCE.md` classifies every section; the measurements behind its
  line-length and line-gap rows, taken in headless Chrome with Noto Sans SC:
  34 declared characters give a 612px column, 18.0px per character, so the
  setting is solid; in a 1280×713 viewport (`--window-size=1280,800`) the
  document-mode column is capped at 521px (713 − 12rem), which is not a whole
  number of 18px cells; and the lines of one wrapped paragraph sit 24.2px
  apart, a 6.2px gap, 34% of the 18px frame, against CLReq's usual 50–100%.
  The last is not in CI. Both have since been met, and a gate measures them:
  see "The page keeps CLReq's geometry".

- **Main no longer claims a released version** (#55). From `v0.2.0` until
  this change main still said 0.2.0, so a half built from a checkout and a half
  from the release passed each other's handshake. Main now says `0.3.0-dev`,
  and a pre-release speaks its whole version (`tools/versions.py` states the
  rule; the filter and the glue apply it). Run through pandoc 3.9 and the shim:
  the `v0.2.0` release's filter against this binary, `vertext 0.3.0-dev`, warns
  "the filter speaks wire version 0.2 and the binary on PATH speaks 0.3" and
  emits no spans; this filter against a binary built at `v0.2.0` warns "the
  filter is 0.3.0-dev (wire version 0.3.0-dev) and the binary on PATH is 0.2.0
  (wire version 0.2)" and emits no spans. `tools/filter-golden.py` adds a stub
  reporting the release this pre-release is heading for (`vertext 0.3.0`):
  refused, and accepted once the pre-release branch is removed from the rule.
  `tools/wasm-parity.mjs` checks the glue's rule on four pairs; red with the
  same branch removed. The `version` gate: the four declarations are one
  string, and a version an existing tag names is built only at that tag. Red
  with all four set back to `0.2.0` (tagged `v0.2.0`, HEAD elsewhere), and with
  only the glue left at `0.3.0-dev`; both archives refuse the first case too.

  Review then found two holes, both closed. The rule had three
  implementations and no shared cases: Python's `wire()` had no caller or
  test, and nothing reached the filter's release branch. The pairs are now
  data, `tools/wire-pairs.json` (8 pairs), and each implementation is held to
  all of them: `version-gate.py` for Python, `wasm-parity.mjs` for the glue,
  and `filter-golden.py` for the filter, running a copy whose only change is
  its `VERSION` against a stub that reports the other side. Red with a
  release's wire changed to MAJOR.MINOR.PATCH, in the filter and in the glue
  separately: each gate names `0.3.0`/`0.3.1` both ways, and the old
  `filter-golden.py` stays green through the filter's cut. And the gate only
  stopped a version EQUAL to a tag, so an untagged `0.2.1` would have passed
  and paired with `v0.2.0`. Off a tag it now refuses any version whose wire a
  tag already speaks: red with all four at `0.2.1` and at `0.2.0`, green at
  `0.3.0` (no tag speaks 0.3 yet) and `0.3.0-dev`.

  That green at `0.3.0` was the last hole: between setting a new minor and
  cutting its tag, every commit that lands builds halves claiming the release.
  Off a tag the gate now refuses every release version, and a release commit
  is pushed together with its tag. The rule's 7 cases run in the gate itself
  (`RELEASE_CASES` in `tools/version-gate.py`), so the cases are red whatever
  version main carries: with the release branch removed, the gate fails on
  exactly the untagged `0.3.0`. In a scratch clone with all four declarations
  set: `0.3.0` untagged red, `0.3.0` with `v0.3.0` on HEAD green, `0.3.1`
  untagged red.

- **The lesson site builds from the 0.2.0 release** (#9, step 2). Merged in
  that site's repository: `build.py` pins `VERTEXT_VERSION = "0.2.0"`, and its
  fetch tool installs the binary from crates.io and the filter from the
  release zip, checked against a pinned sha256. On its merge request its 13
  pages were byte-identical to the build from the 0.2.0 source, and a tampered
  zip and a 0.1 binary were both refused. It no longer reads a sibling checkout.

- **A native host gets the slots the page draws** (#62, #63, #64). The
  backend of chaji, the Flutter theme: `crates/vertext-ffi` hands each slot's
  kind, text and source range over a C ABI, and `bindings/dart` binds it, with
  a build hook that compiles the library, so a consumer places no file by
  hand. The strip and the kinds come from `vertext-html` itself
  (`strip_layout`, `slot_kind`), shared with the wasm host and the renderer.
  `cargo test -p vertext-ffi` 8 green, including the slots against the spans
  `render_document` emits; `dart test` 7 green; an empty project outside the
  repository depending on the binding by path builds and lays text out. The
  CI gate `dart-parity` (`bindings/dart/tool/parity.dart`) lays out 178
  inputs, the shaping golden's corpus plus edge cases, under 3 flag sets
  through the binding and through the release CLI: 530 vertical layouts give
  the page's 1693 slots in order, each slot's UTF-16 range is its own text,
  and the 4 horizontal ones have no column on the page either. Green in CI on
  `eaf11c5`, where the image keeps rustup outside $HOME, so the hook found the
  toolchain from PATH alone. Shown red three ways: U+180E dropped in the Dart
  decoding, 222 findings with `cargo test` all green; a code point above
  U+FFFF counted as one UTF-16 unit, caught on `𠀋` by the range check; U+180E
  dropped in the FFI serialization, red here and in the crate's own tests.
  The binding refuses a library from another release, naming both versions
  (shown with the binding set to `0.2.0`), and its wire rule is held to
  `tools/wire-pairs.json`.

- **The page keeps CLReq's geometry** (#71, #72, #73, #74, #75, #77). `tools/page-geometry.py`,
  CI gate `page-geometry`: documents through pandoc, the real filter and the
  binary, in headless Chrome 152 with Noto Sans SC pinned by tag and sha256.
  A short window ends a column on a whole cell: 504px (28 cells) in document
  mode at 900x700 and 450px (25) in page mode at 900x500, where the space is
  508px and 452px; red with the rounding's `@supports` made unsatisfiable.
  The lines of a paragraph sit 27.0px apart, a 50% gap of the 18px frame,
  where they sat 24.0px apart (33%) before. Setting the line height alone gave
  32.5px: every slot is centred with `vertical-align: middle`, half an
  x-height off the column's own baseline, and the column's strut added that
  to every line. The slots now carry the pitch and the strut is zero. The
  browser gates (`browser-golden`, `progression-scroll`, `wasm-caret`) stay
  green, and a mixed page screenshotted before and after differs only in the
  spacing of its lines.

  **Every line is a pitch, whatever fills it** (#83). With the strut at zero,
  only the slots that carry the pitch as a line height held it; the Latin and
  Mongolian slots are boxes, and a line of nothing but bichig measured 18.0px
  from the next, its runs almost touching. The Mongolian run now takes the
  pitch as its line height and a Latin word is at least a pitch wide, so
  `page-geometry` measures 8 lines of bichig alone (`vertical-lr`, Noto Sans
  Mongolian) and 6 lines around two of short Latin words alone at 27.0px; red
  before at 18.0px. A paragraph mixing Han, bichig and Latin words up to
  `internationally` keeps its line pitches to the tenth of a pixel in both
  progressions (87.0 and 72.9px, set by the long words), so a mixed page does
  not move.

  The line-edge paragraphs (#75, #77) put a mark exactly at the end of a line,
  which holds only for the column length they were built for. They were built
  for 28 cells and never checked it: on a host whose 900x700 window gives
  360px (20 cells), every one passed without asking anything, and kept passing
  with `line-break: anywhere`. The gate now measures the column first, builds
  the paragraphs for it, and fails if the column is another length; with that,
  `line-break: anywhere` is red on all 16 marks. `punctuation-ink` now also
  asks the page which of its faces loaded, since ink alone cannot tell a
  pinned face from an installed one: red with Noto Sans TC emptied.

  **The pause and stop marks never turn, and sit where the face puts them**
  (#73). `tools/punctuation-ink.py`, CI gate `punctuation-ink`: `口<mark>口`
  for each of `、，。．；：！？`, as the binary renders it, at a 96px cell,
  screenshotted twice, once with the mark hidden, so the difference is the
  mark's ink alone. Measured before changing anything: Noto Sans SC's vertical
  forms already place the short marks at (0.80, 0.19) of the frame, the
  Mainland corner, and `；：！？` to the right; Noto Sans TC's centre all of
  them. The stylesheet's `translate(.32em, -.34em)` then moved them again,
  to (0.93, -0.15) in SC, past the top of the frame, and to (0.82, 0.17) in TC,
  the Mainland corner on Taiwan text. The translate is gone and the colon is a
  pause mark in the core. Green in 5 language settings (no `lang` and `zh-CN`
  on SC faces, `zh-TW`, `zh-HK`, `zh-Hant` on TC); red on 18 with the translate
  put back, on 5 with the marks rotated, and `the_punctuation_contract` red
  with the colon reclassified as turning. Two things measured and not gated:
  Noto Sans CJK SC under `zh-TW` centres `！？` but not `、，。．；：`, a gap in
  that face's `locl`; and turning `vert` off to force the centre makes Chrome
  draw the vertical presentation forms, which sit in the corner regardless.

  **Question and exclamation marks used together share a cell** (#74). The
  core pairs `？！`, `！？`, `？？` and `！！` into one slot, `combine`, and the
  page sets it with `text-combine-upright: all`; three marks are a pair and a
  single, so they take two cells as GB/T 15834 asks. Prose only. In the
  `page-geometry` gate each of 3 pairs is one 18px cell along the line; red at
  36px with the property removed, and the core test red with the pairing pass
  skipped. The new kind reaches the Dart binding, and `dart-parity` holds it
  to the page's class (179 inputs, 1726 slots).

  **A number keeps its sign and unit** (#75). Measured before changing
  anything: each paragraph left the end of its first line room for `50` and
  not `%` (and so on for `30℃`, `¥100`, `-5`), and Chrome split all four
  across lines, because the number and the sign were two boxes. The core now
  joins a sign or unit to the number's own slot (CLReq 6.1.2.2's list, and the
  currency symbols either side). The same four cases in `page-geometry` now
  keep each pair on one line. A sign with a word on its other side joins
  neither (`30°C`, `US$100`, `5−3`): joined, it set two Latin slots side by
  side, which the slot census behind the horizontal decision counts as two
  words and the layout as one. Six such inputs broke that invariant while its
  test stayed green, because the test had none of them; with them added it was
  red on all six and on `1990－2000年`, whose fullwidth hyphen-minus was read
  as the sign of `2000`. It is a range mark and keeps its vertical form.

  **No closing mark starts a line, no opening mark ends one** (#77). Found in
  a screenshot taken for #73: `。` at the top of a column. Each paragraph in
  `page-geometry` fills a line and puts one mark where the next begins (or an
  opening mark in the last cell): with the pause marks and brackets as
  `inline-block`, 10 of `、，。．；：！？）」』》` began a line and all 4 of `（「『《`
  ended one; only `！？`, already plain inline, held. An atomic inline box may
  break on either side, so the browser's rules never saw those characters. As
  plain inline text, all 16 hold. Screenshots before and after: the brackets
  keep their vertical forms and the arrows still turn, and a two-em dash that
  was split across two lines now moves whole.

## Not sealed



- **`examples/render.sh` has been read, not run.** #15 asked for proof that it
  regenerates everything now removed. Half of that is proven by inspection —
  `examples/_extensions/` is a `cp -R` from `extensions/vertext`, which is the
  same operation whose result was just compared byte for byte. The other half
  is `quarto render`, and **quarto is not installed on this machine**, so the
  demo output under `examples/` was untracked on the strength of the script's
  text rather than a run. Whoever has Quarto should run `./examples/render.sh`
  from a clean checkout and confirm both paths come back.
- **The lesson site built on this engine has not moved to the declared
  measure** (#26). It sets `--vertext-column-height: calc(100% - 2rem)`
  directly, which overrides the engine's budget, so its pages still follow the
  window: 30 to 96 characters a column on one lesson across the windows
  measured. Moving it means declaring only the space
  (`--vertext-column-theme-height`) and rebuilding and re-sealing its pages,
  which is a change in that repository.
- **A mismatched pair is now refused, not rendered** (#9, step 3). The rule
  below was tightened for pre-releases and a fourth declaration; see "Main no
  longer claims a released version". `vertext --version` printed `vertext
  0.2.0` at the time, and the filter asks for it once per document before it
  sends anything: if the binary does not speak the filter's `WIRE_VERSION` —
  MAJOR.MINOR, because the protocol is what has to match and a patch does not
  move it — the document is left horizontal with a warning naming both
  versions. Degrade, never raise: the same path a missing binary already took,
  for the same reason.

  `tools/filter-golden.py` presents two binaries it must refuse — one reporting
  another release, one too old to know `--version` at all, which reads the empty
  stdin and prints an empty render, and is why the filter's pattern is anchored
  to the word `vertext` rather than hunting for digits. Both are refused, with
  no spans emitted.

  The three version declarations — `Cargo.toml`, `_extension.yml`, the filter's
  `WIRE_VERSION` — were equal by coincidence, all three hand-typed. The same
  gate now asserts they are one version: shown red by setting `WIRE_VERSION` to
  `0.2`, where the handshake refuses the very binary it ships with.

  **It guards ONE direction, and the wording matters.** A 0.2 filter refuses a
  binary that is not 0.2. A 0.1 filter has no handshake in it at all and will
  drive a 0.2 binary straight into misplaced text, exactly as before — the old
  half cannot be taught. So "the two refuse each other" is false, and saying it
  would leave the next person believing both directions are held. The direction
  that is not held closes only by release discipline: both halves installed from
  one artifact, which is #9's steps 1 and 2.

  The binary this really guards against is 0.1, which has no `--version` branch
  and reads stdin instead — so asking it for a version could have meant asking
  it to WAIT, and a hung site build is harder to attribute than wrong text,
  because wrong text at least appears. It does not hang, and that is measured,
  not assumed: a real 0.1 binary built from `4f6ea5b`, first on PATH, through
  the real filter under pandoc — **exit 0 in under a second, no spans, and the
  refusal on stderr**. `pandoc.pipe` closes the child's stdin, so the read
  returns at once. The gate keeps that shape under a stub with a 60s timeout, so
  a host whose pipe stops closing stdin shows up as a red test rather than a
  build that hangs for as long as someone will wait.

  What this does NOT do is make the mismatch impossible, which is what #9 is
  actually for: two consumers still install the two halves separately, so there
  is still a pair to mismatch. This is the second line of defence the issue
  asks for, built before the first.
- **A sign between two words breaks from its number.** `30°C` is three slots,
  and a line may fall after `30`. Joining `°` to either word would set two
  Latin slots side by side, which the slot census forbids; CLReq 6.1.2.2 is
  Partial for it.

- **The docs site still pins its two halves separately** (#9, step 2). It
  vendors the filter and pins the binary on its own; its switch to the release
  is #43, which belongs to that site's owner.

- **No release carries the wasm archive yet** (#46). The `v0.2.0` tag
  predates it; the next tag should attach `vertext-wasm-<version>.zip` beside
  the filter's zip, and until then a browser host has only a build from source.

- **The Dart binding builds for Linux only.** Its build hook refuses other
  targets with a message. Android, iOS, macOS and Windows each need a Rust
  target and a test on that platform. The theme itself, in the wabisabi kit,
  has not been started (#67).

## Decisions

- 2026-09-12 **The filter ships to `quarto add` as a zip attached to the tagged
  release, not as an `_extensions/` copy at the repository root** — because the
  tree already holds the source and the copy the theme must vendor, and those
  two have drifted once (#25); a third copy is a third thing to keep equal,
  while an archive built from the source at release time cannot drift. The
  version is in the file name so the filter and the binary are visibly one
  release.

- 2026-09-12 **Column length is a declared number of characters, capped by the
  space on the page, default 34** (#26) — because a length that follows the
  window is not a measure: on one lesson page it ran 30 to 96 characters across
  ordinary windows, so one document was a different page on each screen. A
  fixed length without the cap runs under the chrome on a short window. Chosen
  over following the window and over filling the space after all three were
  built as real pages and read. 34 because 34 cells of 18px is the 612px the
  old `34em` gave, so a page that declares nothing keeps its measure.

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

- **CI logs still cannot be read back, but a red now names its gate** (#32).
  `actions/runs`, `actions/jobs` and `actions/workflows` all return 404 on this
  instance — Forgejo 11.0.16 — and only `actions/tasks` answers, with status and
  no log text. That is unchanged and is not ours to fix.

  What changed is the question a reviewer can get answered. Every gate step in
  `ci.yml` now carries an `id`, and a last step running under `if: always()`
  writes one commit status per gate through the API that does answer:

      GET /api/v1/repos/{owner}/{repo}/commits/<sha>/statuses
        failure  gate/filter-copies    failure in this run
        warning  gate/delivery-golden  skipped in this run
        success  gate/engine           success in this run

  That is a real run — run **31** on `19ec07a`, red on purpose by appending one
  line to the theme's vendored filter, the exact drift #25 was filed for. Run
  **30** on `33e2519` is the green it followed, and the revert is green again.
  Forgejo hands the job a usable `secrets.GITHUB_TOKEN`; no repository secret
  had to be created, which was the one thing this might have needed a decision
  for. The gate list has no second copy: it is the ids, so a gate added later
  reports itself.

  Two things this does not do. It does not recover the log text, so *why* a gate
  failed is still reproduced locally. And a reporter that cannot report exits
  non-zero rather than passing quietly — it cannot mask a gate failure, since
  the gate's own step has already failed by then.

  CI also runs on **every branch** now, not only `main` and pull requests. Under
  C14 a work branch carries a milestone's commits for days before any MR exists,
  and until this it ran no gate until the MR opened.
- **The downstream documentation site runs a mismatched pair today.** Its vendored `vertext.lua` is
  blob `9938d18b` (`1ac79f0`, 2026-08-16) while `install-vertext.sh` pins
  `VERTEXT_REF=ebd004c` (2026-08-07) — nine days apart across a commit that
  changed block encoding, the vendoring ahead of the pin. Fix: pin `0e38451` and
  re-vendor as one action. That change belongs to that site's owner.
