#!/usr/bin/env sh
# End-to-end test of the Quarto extension.
#
# `cargo test` covers the layout engine and the renderer. Nothing covers the
# Lua filter, which is where the wire protocol is encoded and where author
# text enters it — so this renders real documents through the real `quarto
# render` and asserts on the HTML that comes out.
set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$root"

cargo build --release -p vertext-cli
PATH="$root/target/release:$PATH"
export PATH

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/_extensions"
cp -R extensions/vertext "$work/_extensions/vertext"

failures=0
check() {
  name=$1
  pattern=$2
  file=$3
  if grep -q "$pattern" "$file"; then
    printf 'ok   %s\n' "$name"
  else
    printf 'FAIL %s (no match for %s)\n' "$name" "$pattern"
    failures=$((failures + 1))
  fi
}
check_absent() {
  name=$1
  pattern=$2
  file=$3
  if grep -q "$pattern" "$file"; then
    printf 'FAIL %s (unexpected match for %s)\n' "$name" "$pattern"
    failures=$((failures + 1))
  else
    printf 'ok   %s\n' "$name"
  fi
}

# Author text carrying the reserved markers must not be able to switch the
# renderer's mode. The literals below are U+E000 and U+E002.
#
# The multi-byte text is load-bearing, not decoration: marker stripping is
# byte-oriented in Lua, and a naive range class silently corrupts any
# neighbouring CJK into invalid UTF-8. An ASCII-only document cannot catch it.
printf '%s\n' '---' 'title: "Injection 山"' 'vertext-page: true' 'filters: [vertext]' \
  'format: {vertext-html: default}' '---' '' '::: {.vertext}' \
  '山川异域，风月同天。' '' \
  'before'"$(printf '\356\200\200')"'after'"$(printf '\356\200\202')"'tail' '' \
  '## 見出し' '' \
  '## Latin Heading Goes Horizontal' '' \
  '| 蒙古文 | 转写 | English |' '|---|---|---|' \
  '| ᠰᠠᠶᠢᠨ | sayin | good |' '| ᠪᠢ | bi | I |' '' \
  '```rust' 'let x = "日本語";' '```' ':::' > "$work/doc.qmd"

quarto render "$work/doc.qmd" --quiet

out="$work/doc.html"
check        "CJK heading stays a vertical column" 'vertext-column-h2'      "$out"
check        "Latin heading goes horizontal"   'vertext-horizontal-h2'      "$out"
check        "fenced code is set horizontally" 'vertext-horizontal-code'    "$out"
check        "CJK prose stays vertical"        'vertext-column-prose'       "$out"
# The defect this whole encoding exists to prevent: a table flattened into one
# run, with every cell boundary lost.
check        "table survives as a table"       '<table class="vertext-table">' "$out"
check        "table cells stay apart"          '<td class="vertext-cell">'   "$out"
check_absent "cells are not welded together"   'ᠰᠠᠶᠢᠨsayin'                  "$out"
check_absent "header cells are not welded"     '蒙古文转写'                   "$out"
# The title goes through the binary like any other heading and takes whichever
# orientation its own script calls for. What matters is that vertext renders it
# at level 1 rather than leaving it to Quarto's horizontal title block.
check        "title is rendered by vertext at h1" 'vertext-\(column\|horizontal\)-h1' "$out"
check        "page mode injects its stylesheet" 'vertext-page-mode'         "$out"
check        "caps published to CSS"           'vertext-latin-cap-prose:12ch' "$out"
# Quarto builds its title block at template time, after this filter runs, so
# the node exists and is hidden by the inlined page stylesheet. Assert the rule
# is present rather than that the markup is gone.
check        "quarto title block is hidden"    '#title-block-header { display: none; }' "$out"
# The injected markers must be gone, and the text around them must survive as
# ordinary prose rather than as a mode switch.
check_absent "no raw markers reach the DOM"    "$(printf '\356\200\200')"   "$out"
check        "injected text stays prose"       'beforeafter'                "$out"
# Stripping markers must not disturb the bytes of neighbouring characters.
check        "CJK survives marker stripping"   '山'                          "$out"
check        "heading keeps its CJK"           '見'                          "$out"
check        "code block keeps its CJK"        '日'                          "$out"
if iconv -f UTF-8 -t UTF-8 "$out" >/dev/null 2>&1; then
  printf 'ok   output is valid UTF-8\n'
else
  printf 'FAIL output is not valid UTF-8\n'
  failures=$((failures + 1))
fi

# U+202F NARROW NO-BREAK SPACE is the bichig suffix separator, not a space:
# `ᠮᠣᠩᠭᠤᠯ` + U+202F + `ᠤᠨ` is one word, the genitive. Unicode gives the mark
# `White_Space=Yes`, so any layer that asks only "is this whitespace" cuts a
# case ending off its stem. Written as an octal escape rather than pasted in,
# because an invisible character in a fixture is a fixture nobody can read.
nnbsp=$(printf '\342\200\257')

# A Mongolian-primary document declares its progression and every layer must
# follow: the strip's data attribute, and the page's writing-mode. Getting this
# backwards does not look wrong — it reads the document in reverse.
printf '%s\n' '---' 'title: "ᠮᠣᠩᠭᠤᠯ"' 'vertext-page: true' 'vertext-progression: lr' \
  'filters: [vertext]' 'format: {vertext-html: default}' '---' '' '::: {.vertext}' \
  'ᠮᠣᠩᠭᠤᠯ ᠤᠯᠤᠰ ᠮᠠᠨᠳᠤᠨ᠎ᠠ' '' 'ᠪᠢᠴᠢᠭ ᠨᠢ ᠳᠡᠭᠡᠳᠦ ᠡᠴᠡ ᠳᠣᠣᠷ᠎ᠠ' '' \
  "ᠮᠣᠩᠭᠤᠯ${nnbsp}ᠤᠨ ᠲᠡᠦᠬᠡ" '' 'ᠬᠢᠴᠢᠶᠡᠯ ᠑–᠕ ᠪᠠ ᠑—᠕' ':::' > "$work/mn.qmd"
quarto render "$work/mn.qmd" --quiet
mn="$work/mn.html"
check        "declared progression reaches the strip" 'data-column-advance="right"' "$mn"
check        "page flows vertical-lr"          'writing-mode: vertical-lr'  "$mn"
check_absent "no CJK progression leaks in"     'data-column-advance="left"' "$mn"
# One dash family, one class. The em dash was in `has_vertical_form` from the
# start and the en dash was not, so a range written `᠑–᠕` fell through to
# `Neutral` and lay flat across the column while an em dash beside it stood
# correctly. Both are asserted so the pair cannot drift apart again.
check        "an en dash turns like its family" 'vertext-vform">–' "$mn"
check        "an em dash still turns"           'vertext-vform">—' "$mn"
# The joint has to survive pandoc, the Lua filter, and the engine. This is the
# only check that watches it make the whole crossing — `cargo test` seals the
# engine alone, and a mark eaten upstream would leave the suffix a separate
# word on the page with every unit test still green.
check        "a case ending stays inside its word" "vertext-mongolian\">ᠮᠣᠩᠭᠤᠯ${nnbsp}ᠤᠨ<" "$mn"
check_absent "no word space splits a suffix"       "vertext-space\">${nnbsp}" "$mn"
# The wheel handler lives on the region and sees a nested scroller's events
# bubble through it. Turning those into column advance would leave a capped
# stack's overflow reachable by scrollbar only -- which makes the cap a hidden
# truncation wearing a scrollbar it never gets to use.
check        "the wheel yields to a nested scroller" 'insideLiveScroller' "$out"
# And the default is untouched for documents that do not declare.
check        "undeclared documents stay CJK"   'data-column-advance="left"' "$out"

# Quarto loads a project's filters once and reuses the Lua state for every
# document. A document that declares `vertext: true` must not turn on
# whole-document layout for the pages rendered after it — including pages that
# never asked for the filter. Rendering both in one project run is the only way
# to catch this; a single-document render cannot.
mkdir -p "$work/proj/_extensions"
cp -R extensions/vertext "$work/proj/_extensions/vertext"
printf '%s\n' 'project:' '  type: default' > "$work/proj/_quarto.yml"
printf '%s\n' '---' 'title: "Vertical"' 'vertext: true' 'filters: [vertext]' '---' '' \
  '山川异域，风月同天。' > "$work/proj/a-vertical.qmd"
printf '%s\n' '---' 'title: "Plain"' 'filters: [vertext]' '---' '' \
  'This page never asked for vertical layout.' > "$work/proj/b-plain.qmd"
quarto render "$work/proj" --quiet

check        "the declaring document is vertical" 'class="vertext'          "$work/proj/a-vertical.html"
check_absent "state does not leak to the next document" 'class="vertext'    "$work/proj/b-plain.html"
check        "the untouched document keeps its text" 'never asked'          "$work/proj/b-plain.html"

# A Div wrapping a code block must keep its code.
#
# `pandoc.utils.stringify` walks INLINES, and a CodeBlock's text is not
# inlines -- so a Div holding code stringifies to the empty string, and the
# encoder's catch-all branch dropped the entire block instead of flattening
# it. Quarto wraps every executed result in `::: {.cell-output}`, so this
# silently deleted every printed output in the book while leaving the prose
# around it intact: the text read as if the programs had produced nothing.
#
# The fixture is written as the AST Quarto produces (a `.cell` Div holding
# source and output) rather than as an executable cell, so the test needs no
# Jupyter kernel to run.
printf '%s\n' '---' 'title: "输出"' 'vertext: true' 'filters: [vertext]' \
  'format: {vertext-html: default}' '---' '' \
  '::: {.cell}' '``` {.python .cell-code}' 'total = sum(range(1, 6))' '```' '' \
  '::: {.cell-output .cell-output-stdout}' '```' 'Sum: 15' '```' ':::' ':::' \
  > "$work/cell.qmd"
quarto render "$work/cell.qmd" --quiet
cellout="$work/cell.html"
check "executed output survives the layout"     'Sum: 15'         "$cellout"
check "the cell source survives the layout"     'sum(range(1, 6))' "$cellout"
# Both belong in the horizontal code column, not poured into vertical prose.
check "wrapped code is laid out as code"        'vertext-horizontal-code' "$cellout"

# ...and the same trap once more, for a RawBlock rather than a CodeBlock.
#
# `stringify` returns "" for a RawBlock too, so a Div holding one lost it
# entirely. That is not a corner case: a cell magic that renders its own
# output -- syntax-highlighted source, a plot, a table -- emits it as
# `{=html}` inside `.cell-output-display`. Every code listing in the Crust
# book went this way, leaving each program's printed result on the page with
# the Rust and C++ it came from deleted.
printf '%s\n' '---' 'title: "raw"' 'vertext: true' 'filters: [vertext]' \
  'format: {vertext-html: default}' '---' '' \
  '::: {.cell}' '::: {.cell-output .cell-output-display}' '```{=html}' \
  '<pre class="hl">fn demo() -&gt; i32 { 42 }</pre>' '```' ':::' \
  '::: {.cell-output .cell-output-stdout}' '```' 'Ran: 42' '```' ':::' ':::' \
  > "$work/raw.qmd"
quarto render "$work/raw.qmd" --quiet
rawout="$work/raw.html"
check "a magic's rendered output survives"      'fn demo()'       "$rawout"
check "its printed result survives too"         'Ran: 42'         "$rawout"
# ...and it must be HORIZONTAL. Passing the markup through drops it straight
# into the region's `vertical-rl` flow, where a Rust listing runs down the page
# one character per line. Code is set horizontally in this layout by rule; the
# pass-through silently opted out of it.
check "a magic's output is set horizontally"    'vertext-raw'     "$rawout"

# Without the binary the document must stay an ordinary horizontal page.
# Injecting the page stylesheet anyway turns the content region vertical while
# the text is still horizontal markdown, which lays every Latin word on its
# side and leaves CJK upright -- worse than doing nothing, and exactly what
# reached production. The degraded path had never been rendered in a test.
printf '%s\n' '---' 'title: "Degraded"' 'vertext: true' 'filters: [vertext]' \
  'format: {vertext-html: default}' '---' '' '山川异域 and some English.' > "$work/nobin.qmd"
# quarto is invoked by absolute path so the binary can be taken off PATH
# without taking quarto with it.
quarto_bin=$(command -v quarto)
( PATH="/usr/bin:/bin"; export PATH; "$quarto_bin" render "$work/nobin.qmd" --quiet ) >/dev/null 2>&1 || true
nb="$work/nobin.html"
if [ -f "$nb" ]; then
  check_absent "no page style without the binary"  'vertext-document-mode'  "$nb"
  check_absent "no page style without the binary (page)" 'vertext-page-mode' "$nb"
  check_absent "no strip markup without the binary" 'class="vertext"'       "$nb"
  check        "the text still renders"             'English'               "$nb"
else
  printf 'FAIL degraded-path render produced no output\n'
  failures=$((failures + 1))
fi

# ── The VertexT theme ────────────────────────────────────────────────────
# The theme rotates the page chrome; the filter lays out the text. The whole
# requirement is that an existing document renders under it with NO edits, so
# the fixture below is written for the plain filter and never mentions the
# theme -- the theme is selected in _quarto.yml alone.
#
# The theme embeds its own copy of the content extension, because Quarto
# requires an extension that uses another to embed it. That copy is generated,
# so it can drift from the original -- and a drifted filter is a filter whose
# PUA markers no longer match the binary's. Catch it here.
if diff -r -q extensions/vertext extensions/vertext-theme/_extensions/vertext >/dev/null 2>&1; then
  printf 'ok   the embedded filter matches its source\n'
else
  printf 'FAIL the embedded filter has drifted from extensions/vertext\n'
  printf '     refresh it: cp -R extensions/vertext extensions/vertext-theme/_extensions/\n'
  failures=$((failures + 1))
fi

theme=$work/theme
mkdir -p "$theme/_extensions"
cp -R extensions/vertext-theme "$theme/_extensions/vertext-theme"
# The content filter as a project extension in its own right, ALONGSIDE the
# theme's embedded copy. That is his zh site's layout, and it is what lets a
# page name `filters: [vertext]` itself -- Quarto resolves a filter name only
# against the project's own `_extensions`, never across into another
# extension's, so without this the twice-filtered page below cannot render at
# all and the render aborts for everything after it.
cp -R extensions/vertext "$theme/_extensions/vertext"
# The theme deliberately declares no `theme:` of its own -- a flat list there
# and a site's light/dark MAP merge into a shape Quarto cannot resolve, and it
# dies inside layerTheme naming neither the file nor the theme. So the scss
# ships as an asset the site copies in and names, which is what a real site has
# to do; the fixture does it the same way or it is not testing the real path.
cp extensions/vertext-theme/vertext-theme.scss "$theme/vertext-theme.scss"
printf '%s\n' 'project:' '  type: website' 'website:' '  title: "教程"' \
  '  navbar:' '    left:' '      - href: index.qmd' '        text: 首页' \
  '  page-footer: "footer text"' 'format:' '  vertext-theme-html:' \
  '    theme: [cosmo, vertext-theme.scss]' > "$theme/_quarto.yml"
# Two headings, because the TOC checks below need something to list -- a page
# with only a title has no entries and would fail for the wrong reason.
printf '%s\n' '---' 'title: "首页"' '---' '' '## 第一節' '' '山川异域，风月同天。' \
  '' '## 第二節' '' '寄諸佛子，共結來緣。' > "$theme/index.qmd"
printf '%s\n' '---' 'title: "ᠮᠣᠩᠭᠤᠯ"' 'vertext-progression: lr' '---' '' \
  'ᠮᠣᠩᠭᠤᠯ ᠤᠯᠤᠰ ᠮᠠᠨᠳᠤᠨ᠎ᠠ' > "$theme/mn.qmd"
# A page naming the content filter in its OWN frontmatter while the theme's
# format defaults already carry it, so the filter is applied TWICE to it. Not
# hypothetical: the Mongolian lesson page on the live site does exactly this,
# and every heading and the title came back drawn twice, side by side --
# because everything else the first pass produced is an inert RawBlock, while
# the title and the TOC anchors are still live nodes for the second one to
# find. A single-pass fixture cannot see this at all.
printf '%s\n' '---' 'title: "雙寫"' 'filters:' '  - vertext' '---' '' \
  '## 唯一標題' '' '山川异域，风月同天。' > "$theme/twice.qmd"
quarto render "$theme" --quiet
th="$theme/_site/index.html"
check        "theme renders an unedited document"  'class="vertext'          "$th"
check        "theme stamps the progression"        'data-vertext-progression' "$th"
check        "the navbar survives the rotation"    'quarto-header'            "$th"
check        "the footer survives the rotation"    'nav-footer'               "$th"
# The table of contents. Pandoc fills `$toc$` by walking `Header` blocks, and
# the filter encodes every heading into the strip -- so for a long time a
# vertext page simply had no TOC, on every document there had ever been, and
# Quarto parked the empty sidebar off-screen where it read like a placement
# bug in the theme. The Pandoc pass now keeps the real `Header` nodes beside
# the strip. Filter ORDERING cannot substitute for this: `$toc$` is computed by
# the writer, after every filter has run.
check        "a vertical page still builds a TOC" 'doc-toc'                   "$th"
check        "the TOC anchors survive"            'vertext-toc-anchor'        "$th"
# Applying the filter twice must lay the page out ONCE. Counted, not grepped
# for presence: the bug was a heading that appeared, correctly, and then again.
twice="$theme/_site/twice.html"
if [ -f "$twice" ]; then
  h2s=$(grep -o 'vertext-column-h2' "$twice" | wc -l | tr -d ' ')
  h1s=$(grep -o 'vertext-column-h1' "$twice" | wc -l | tr -d ' ')
  if [ "$h2s" = "1" ] && [ "$h1s" = "1" ]; then
    printf 'ok   a twice-applied filter lays the page out once\n'
  else
    printf 'FAIL twice-applied filter drew the title %s and the heading %s times\n' "$h1s" "$h2s"
    failures=$((failures + 1))
  fi
else
  printf 'FAIL the twice-filtered page did not render\n'
  failures=$((failures + 1))
fi
# An unbalanced comment in the injected stylesheet does not error and does not
# show up in any markup check: the CSS parser discards the rule that FOLLOWS it
# and the page reads as a layout bug somewhere else entirely. A stray `*/` cost
# the anchor-hiding rule exactly this way, leaving every TOC anchor a full
# height block in the flow.
style=$(sed -n '/<style id="vertext-document-mode">/,/<\/style>/p' "$th")
opens=$(printf '%s' "$style" | grep -o '/\*' | wc -l | tr -d ' ')
closes=$(printf '%s' "$style" | grep -o '\*/' | wc -l | tr -d ' ')
if [ -n "$style" ] && [ "$opens" = "$closes" ]; then
  printf 'ok   the injected stylesheet has balanced comments\n'
else
  printf 'FAIL injected stylesheet has %s comment opens and %s closes\n' "$opens" "$closes"
  failures=$((failures + 1))
fi
check "the anchor-hiding rule survives parsing" 'body .vertext-toc-anchor {' "$th"
# The column budget belongs to whatever knows the chrome. The filter's own
# `calc(100vh - 12rem)` is a guess, and under this theme it was wrong by the
# depth of the bottom strip -- so every column ran under the page TOC and the
# text was cut mid-glyph while the region's own insets measured correctly.
check "the filter defers its column budget" 'var(--vertext-column-theme-height' "$th"
# The chrome placement must reach the compiled bundle, not just the source.
if grep -rq 'data-vertext-progression' "$theme/_site/site_libs/"*/*.css 2>/dev/null; then
  printf 'ok   chrome rules reach the compiled stylesheet\n'
else
  printf 'FAIL chrome rules reach the compiled stylesheet\n'
  failures=$((failures + 1))
fi
# The other half of the column budget: the theme has to actually publish the
# value the filter defers to, in the COMPILED bundle. Source-only would pass
# while the site kept the guess.
if grep -rq 'vertext-column-theme-height' "$theme/_site/site_libs/"*/*.css 2>/dev/null; then
  printf 'ok   the theme publishes a column budget\n'
else
  printf 'FAIL the theme never publishes --vertext-column-theme-height\n'
  failures=$((failures + 1))
fi
# And it must be measured from the CONTAINER, not from the viewport. The first
# version restated the chrome arithmetic per layout and got the clearance wrong
# by the wrapper's padding and the line-height overshoot -- 8px instead of 2rem,
# which still reads as text cut off against the edge. `100%` of the filter's own
# wrapper is the usable run in every layout and cannot drift from the insets.
if grep -rq 'vertext-column-theme-height: calc(100% -' "$theme/_site/site_libs/"*/*.css 2>/dev/null; then
  printf 'ok   the column budget is measured from the container\n'
else
  printf 'FAIL the column budget went back to viewport arithmetic\n'
  failures=$((failures + 1))
fi
# A table cell needs the ABSOLUTE cap instead: its containing block is the
# table, whose height is content-derived, so a percentage max-height has
# nothing to resolve against and is dropped entirely.
if grep -rq 'vertext-cell-cap' "$theme/_site/site_libs/"*/*.css 2>/dev/null; then
  printf 'ok   the theme publishes a cell cap\n'
else
  printf 'FAIL no --vertext-cell-cap: a long table cell can run off the page\n'
  failures=$((failures + 1))
fi
# Digits stand upright in a rotated strip: a numeral is text here, not a Latin
# word, and the content filter's own slot model already treats it that way.
# Needs both halves -- the spans (script) and the rule (stylesheet) -- because
# `text-combine-upright: digits` is unsupported in Chrome and only `all` works,
# which needs an element around the digit run.
check "the strip script uprights digit runs" 'vertext-tcu' "$th"
if grep -rq 'text-combine-upright:all' "$theme/_site/site_libs/"*/*.css 2>/dev/null; then
  printf 'ok   upright digits reach the compiled stylesheet\n'
else
  printf 'FAIL no text-combine-upright rule in the compiled stylesheet\n'
  failures=$((failures + 1))
fi
# A bracket must be turned ONCE. In a vertical writing mode the browser has
# already given these marks their vertical form -- `vert`/`vrt2` for the
# fullwidth ones, the Unicode vertical-orientation rules for the ASCII ones and
# the arrows -- so a `rotate(90deg)` here is a SECOND quarter-turn. It stood
# every bracket back upright and pointed `→` backwards, on every vertical
# document there has ever been. The character is still never substituted; the
# turn just belongs to the layer that knows the glyph's metrics.
vcss=$(find "$theme/_site" -name 'vertext.css' 2>/dev/null | head -1)
if [ -n "$vcss" ]; then
  if awk '/^\.vertext-vform[[:space:]]*\{/,/\}/' "$vcss" | grep -q 'rotate'; then
    printf 'FAIL .vertext-vform rotates a mark the browser has already turned\n'
    failures=$((failures + 1))
  else
    printf 'ok   a vertical form is turned once, not twice\n'
  fi
  # ...and the other half of the same contract, which the check above cannot
  # see. Dropping the `transform` is only correct because the column's
  # `text-orientation: upright` is overridden here: `upright` stands every
  # character up and suppresses the Unicode rule that turns a mark with no
  # vertical glyph of its own. Without `mixed`, the fullwidth brackets still
  # come out right (the font substitutes for those) while every ASCII mark,
  # arrow and dash lies flat -- half the marks correct, which is exactly how
  # this shipped once already.
  if awk '/^\.vertext-vform[[:space:]]*\{/,/\}/' "$vcss" | grep -q 'text-orientation:[[:space:]]*mixed'; then
    printf 'ok   the turning slot keeps per-character orientation\n'
  else
    printf 'FAIL .vertext-vform inherits upright and leaves ASCII marks flat\n'
    failures=$((failures + 1))
  fi
  # A stack of horizontal blocks and tables is one flex item and cannot wrap
  # into the next column the way a text column does. Uncapped it grows past the
  # region, and the region is `overflow-y: hidden`, so the tail is cut with no
  # scrollbar and nothing on screen saying text is missing -- measured at 188px
  # of a code listing and 139px of a table on the live site. Capping to the
  # column budget is only half of it: without `overflow-y` the cap is a tidier
  # clip, which hides content rather than truncating it.
  hstack_rule=$(awk '/^\.vertext-hstack,/,/\}/' "$vcss")
  if printf '%s' "$hstack_rule" | grep -q 'max-height:[[:space:]]*var(--vertext-column-height'; then
    printf 'ok   a stack is capped to the column budget\n'
  else
    printf 'FAIL a stack can grow past the region and be cut\n'
    failures=$((failures + 1))
  fi
  if printf '%s' "$hstack_rule" | grep -q 'overflow-y:[[:space:]]*auto'; then
    printf 'ok   a capped stack keeps its overflow reachable\n'
  else
    printf 'FAIL a capped stack hides its overflow instead of scrolling it\n'
    failures=$((failures + 1))
  fi
else
  printf 'FAIL vertext.css was not shipped with the themed site\n'
  failures=$((failures + 1))
fi
# The content region must NOT clip. Quarto makes the section sidebar, the TOC
# strip and the glass CHILDREN of `#quarto-content`; the theme pins all three
# to viewport edges with `position: fixed`, but the region is itself `fixed`,
# so it is their containing block and an `overflow: hidden` on it clips them.
# That is what cut the first characters off every section-sidebar entry while
# the DOM reported the text starting at x=13 -- placed correctly, painted
# clipped. The clip belongs on `main`, which is the scrolling text surface and
# the only child that ever needed one. Asserted on the compiled CSS because
# this is a rule the suite can see; what it cannot see is the paint, which is
# why this one was found in a screenshot and not here.
#
# BOTH halves are asserted, and that is the point. A first version of this
# check only looked for the clip on `main`; reintroducing the bug left that
# rule in place and merely put `overflow: hidden` BACK on the region, so the
# check passed with the bug present. Adding a clip somewhere harmless does not
# mean the harmful one is gone -- the region not clipping is the actual claim.
# The section sidebar must start AFTER the status edge, never at `left: 0`.
# Pinned there it sits under the status bar, which holds the same edge at
# z-index 1020 with an opaque background, and the first ~30px of every entry is
# PAINTED OVER -- the list read "ve — Fuchsia OS" instead of "dive — …". It is
# indistinguishable from the clipping bug above by measurement alone (the DOM
# reports the right x and no ancestor clips), and was told apart only by
# painting a marker at x=0 and seeing it covered too.
#
# Matched against the MINIFIED text, which keeps the descendant space before
# `#quarto-sidebar`. A first version of this check omitted that space, matched
# nothing, and so passed happily with the bug reintroduced -- an assertion that
# cannot fail is worse than no assertion, because it reads as coverage.
sidebar_rule=$(grep -rho 'body:not(:has(.chapter-title)) #quarto-sidebar{[^}]*}' \
                 "$theme/_site/site_libs/"*/*.css 2>/dev/null | head -1)
if [ -z "$sidebar_rule" ]; then
  printf 'FAIL the section sidebar placement rule never reached the stylesheet\n'
  failures=$((failures + 1))
elif printf '%s' "$sidebar_rule" | grep -q 'left:0[;}]'; then
  printf 'FAIL the section sidebar sits under the status bar\n'
  failures=$((failures + 1))
else
  printf 'ok   the section sidebar clears the status edge\n'
fi
# The two lists sit on OPPOSITE edges: the section/chapter list across the top
# ("where am I in this work"), the page's own headings across the bottom
# ("where am I in this page"). Asserted because it is a layout decision that
# reads as arbitrary from the CSS alone, so a later edit could quietly put them
# back on the same edge -- which is where they started, and why the wider list
# ended up hidden down the side.
if printf '%s' "$sidebar_rule" | grep -q 'top:0'; then
  printf 'ok   the nav list takes the top edge\n'
else
  printf 'FAIL the nav list is no longer on the top edge\n'
  failures=$((failures + 1))
fi
# Matched by the DECLARATIONS, not by one exact selector string: the placement
# rule is shared by the site and the book now, so its selector is a
# comma-joined list and a pattern ending `#quarto-margin-sidebar{` stopped
# matching the moment the book was added to it -- a red that meant nothing had
# moved at all.
toc_rule=$(grep -rho '[^}]*#quarto-margin-sidebar{[^}]*}' \
             "$theme/_site/site_libs/"*/*.css 2>/dev/null \
           | grep 'position:fixed' | head -1)
if printf '%s' "$toc_rule" | grep -q 'bottom:0'; then
  printf 'ok   the page TOC takes the bottom edge\n'
else
  printf 'FAIL the page TOC is no longer on the bottom edge\n'
  failures=$((failures + 1))
fi
region_clips=$(grep -rho '#quarto-content{[^}]*}' "$theme/_site/site_libs/"*/*.css 2>/dev/null \
                | grep -c 'overflow:hidden' || true)
if grep -rq '#quarto-content>main{overflow:hidden}' "$theme/_site/site_libs/"*/*.css 2>/dev/null \
   && [ "${region_clips:-0}" -eq 0 ]; then
  printf 'ok   the clip is on the text surface, not the region\n'
else
  printf 'FAIL the content region may be clipping its own fixed chrome\n'
  failures=$((failures + 1))
fi

# A site with a light/dark theme MAP, which is the shape that broke. While the
# theme declared its own flat `theme:`, this render died with a bare
# `TypeError: Path must be a string, received "{"light":[...]}"` -- no mention
# of the theme, on a real site, from a config that looks perfectly ordinary.
# Both arms must compile, so a dark bundle has to appear alongside the light.
map=$work/thememap
mkdir -p "$map/_extensions"
cp -R extensions/vertext-theme "$map/_extensions/vertext-theme"
cp extensions/vertext-theme/vertext-theme.scss "$map/vertext-theme.scss"
printf '%s\n' 'project:' '  type: website' 'website:' '  title: "教程"' \
  'format:' '  vertext-theme-html:' '    theme:' \
  '      light: [cosmo, vertext-theme.scss]' \
  '      dark: [darkly, vertext-theme.scss]' > "$map/_quarto.yml"
printf '%s\n' '---' 'title: "首页"' '---' '' '山川异域，风月同天。' > "$map/index.qmd"
if quarto render "$map" --quiet >/dev/null 2>&1 && [ -f "$map/_site/index.html" ]; then
  printf 'ok   a light/dark theme map renders\n'
  if ls "$map/_site/site_libs/bootstrap/"*dark*.css >/dev/null 2>&1; then
    printf 'ok   both arms of the theme map compile\n'
  else
    printf 'FAIL the dark arm of the theme map did not compile\n'
    failures=$((failures + 1))
  fi
else
  printf 'FAIL a light/dark theme map fails to render\n'
  failures=$((failures + 1))
fi

# A BOOK project. Different chrome from a website: no navbar, and the chapter
# list lives in `#quarto-sidebar`, which the theme has to place or the book is
# unnavigable -- measured before it did, the sidebar was 14px at the bottom of
# the page while an empty banner held 55x813 of nothing.
#
# The rules are scoped on `.chapter-title`, which Quarto emits for book chapter
# entries and nowhere else. Two earlier scopes failed silently and are the
# reason this check exists: `body.quarto-book` (no such class) and
# `body.nav-sidebar:not(.nav-fixed)` (right for a bare book, wrong for one
# embedded in a site, because injecting a navbar adds `nav-fixed`).
book=$work/book
mkdir -p "$book/_extensions"
cp -R extensions/vertext-theme "$book/_extensions/vertext-theme"
cp extensions/vertext-theme/vertext-theme.scss "$book/vertext-theme.scss"
printf '%s\n' 'project:' '  type: book' 'book:' '  title: "測試書"' \
  '  chapters:' '    - index.qmd' '    - ch1.qmd' \
  'format:' '  vertext-theme-html:' '    theme: [cosmo, vertext-theme.scss]' \
  > "$book/_quarto.yml"
printf '%s\n' '---' 'title: "序"' '---' '' '山川异域，风月同天。' > "$book/index.qmd"
printf '%s\n' '---' 'title: "第一章"' '---' '' '寄諸佛子，共結來緣。' > "$book/ch1.qmd"
if quarto render "$book" --quiet >/dev/null 2>&1 && [ -f "$book/_book/index.html" ]; then
  printf 'ok   a book project renders under the theme\n'
  check "the book lays its text out vertically" 'vertext-column' "$book/_book/index.html"
  check "the book keeps its chapter sidebar"    'quarto-sidebar'  "$book/_book/index.html"
  # The placement rules must reach the compiled bundle, not merely the source.
  if grep -rq 'chapter-title' "$book/_book/site_libs/bootstrap/"*.css 2>/dev/null; then
    printf 'ok   the book chrome rules reach the compiled stylesheet\n'
  else
    printf 'FAIL the book chrome rules never reached the stylesheet\n'
    failures=$((failures + 1))
  fi
  # The chapter strip turns with the page, like every other piece of chrome.
  # It was set horizontal for a while on the argument that chapter titles are
  # too long to rotate; measured, the longest is 29 characters against 30 on a
  # site page, so the argument did not hold and the one book on the site read
  # left-to-right while everything around it had turned.
  # A book keeps its own page TOC. It was hidden while the chapter list was
  # horizontal and pinned at a different depth, because the two fought for the
  # top-right corner. Rotated and at the standard depth they sit on opposite
  # edges like everywhere else, and a chapter should still say where you are
  # inside it.
  if grep -rhoq 'body:has(\.chapter-title) #quarto-margin-sidebar{display:none}' \
       "$book/_book/site_libs/bootstrap/"*.css 2>/dev/null; then
    printf 'FAIL a book still hides its own page TOC\n'
    failures=$((failures + 1))
  else
    printf 'ok   a book keeps its page TOC\n'
  fi
  bookstrip=$(grep -rho 'body:has(\.chapter-title) #quarto-sidebar{[^}]*}' \
              "$book/_book/site_libs/bootstrap/"*.css 2>/dev/null | head -1)
  if printf '%s' "$bookstrip" | grep -q 'writing-mode:vertical-rl'; then
    printf 'ok   the book chapter strip turns with the page\n'
  else
    printf 'FAIL the book chapter strip reads left-to-right while the page has turned\n'
    failures=$((failures + 1))
  fi
  # A book must not also get the per-page TOC strip: its chapter sidebar
  # already holds that edge, and the two painted over each other in the
  # top-right corner. Rendered, not asserted -- the rule that broke this was
  # not the placement rule but the grid-flattening one two blocks away, whose
  # `display: block !important` forced the strip back on. So the check is that
  # the strip is EXCLUDED from that selector, which is what actually failed.
  if grep -rq 'not(#quarto-margin-sidebar)' "$book/_book/site_libs/bootstrap/"*.css 2>/dev/null; then
    printf 'ok   the book TOC strip can be hidden at all\n'
  else
    printf 'FAIL the grid rule still forces the TOC strip visible on a book\n'
    failures=$((failures + 1))
  fi
  # A closed Bootstrap modal must stay `display: none`. `code-tools: true` puts
  # `#quarto-embedded-source-code-modal` inside the content region, and the
  # grid rule above forced it to `block` -- an invisible full-viewport click
  # target (opacity 0, pointer-events auto, z-index 1055) that killed every
  # control on the book's chapter sidebar while looking completely correct.
  # Found by clicking a live page; no screenshot and no markup check can see it.
  if grep -rq 'not(.modal)' "$book/_book/site_libs/bootstrap/"*.css 2>/dev/null; then
    printf 'ok   a closed modal cannot swallow the page\n'
  else
    printf 'FAIL the grid rule forces closed modals visible over the chrome\n'
    failures=$((failures + 1))
  fi
else
  printf 'FAIL a book project fails to render under the theme\n'
  failures=$((failures + 1))
fi
# The attribute is set from a script, so the rendered form is a setAttribute
# call rather than a literal `attr="lr"` -- match what is actually emitted.
check        "Mongolian declares the opposite edge" 'data-vertext-progression","lr"' "$theme/_site/mn.html"
check_absent "CJK progression does not leak in"     'data-vertext-progression","rl"' "$theme/_site/mn.html"
check        "a CJK page in the same project stays rl" 'data-vertext-progression","rl"' "$theme/_site/index.html"

# The theme must hold the same line the filter does: rotating the chrome around
# text that is still horizontal markdown is the live-site failure wearing a
# different hat. No binary, no rotation.
rm -rf "$theme/_site"
( PATH="/usr/bin:/bin"; export PATH; "$quarto_bin" render "$theme" --quiet ) >/dev/null 2>&1 || true
if [ -f "$th" ]; then
  check_absent "theme does not rotate without the binary" 'data-vertext-progression' "$th"
  check_absent "no strip markup without the binary (theme)" 'class="vertext"'        "$th"
  check        "the themed text still renders"             '山川异域'                "$th"
else
  printf 'FAIL themed degraded-path render produced no output\n'
  failures=$((failures + 1))
fi

# Everything above greps markup, and markup cannot answer whether a script
# runs. The nav-collapse control is script, so its branches are checked in a
# stub DOM instead. Skipped rather than failed where node is absent: this file
# already needs cargo and quarto, and a third hard dependency for one test
# would cost more than it buys.
printf '\n'
if command -v node >/dev/null 2>&1; then
  if node "$root/examples/test-nav-toggle.js"; then
    :
  else
    failures=$((failures + 1))
  fi
else
  printf 'skip nav-toggle logic (no node)\n'
fi

printf '\n'
if [ "$failures" -eq 0 ]; then
  printf 'all extension checks passed\n'
else
  printf '%d extension check(s) failed\n' "$failures"
  exit 1
fi
