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

# A Mongolian-primary document declares its progression and every layer must
# follow: the strip's data attribute, and the page's writing-mode. Getting this
# backwards does not look wrong — it reads the document in reverse.
printf '%s\n' '---' 'title: "ᠮᠣᠩᠭᠤᠯ"' 'vertext-page: true' 'vertext-progression: lr' \
  'filters: [vertext]' 'format: {vertext-html: default}' '---' '' '::: {.vertext}' \
  'ᠮᠣᠩᠭᠤᠯ ᠤᠯᠤᠰ ᠮᠠᠨᠳᠤᠨ᠎ᠠ' '' 'ᠪᠢᠴᠢᠭ ᠨᠢ ᠳᠡᠭᠡᠳᠦ ᠡᠴᠡ ᠳᠣᠣᠷ᠎ᠠ' ':::' > "$work/mn.qmd"
quarto render "$work/mn.qmd" --quiet
mn="$work/mn.html"
check        "declared progression reaches the strip" 'data-column-advance="right"' "$mn"
check        "page flows vertical-lr"          'writing-mode: vertical-lr'  "$mn"
check_absent "no CJK progression leaks in"     'data-column-advance="left"' "$mn"
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
printf '%s\n' 'project:' '  type: website' 'website:' '  title: "教程"' \
  '  navbar:' '    left:' '      - href: index.qmd' '        text: 首页' \
  '  page-footer: "footer text"' 'format: vertext-theme-html' > "$theme/_quarto.yml"
printf '%s\n' '---' 'title: "首页"' '---' '' '山川异域，风月同天。' > "$theme/index.qmd"
printf '%s\n' '---' 'title: "ᠮᠣᠩᠭᠤᠯ"' 'vertext-progression: lr' '---' '' \
  'ᠮᠣᠩᠭᠤᠯ ᠤᠯᠤᠰ ᠮᠠᠨᠳᠤᠨ᠎ᠠ' > "$theme/mn.qmd"
quarto render "$theme" --quiet
th="$theme/_site/index.html"
check        "theme renders an unedited document"  'class="vertext'          "$th"
check        "theme stamps the progression"        'data-vertext-progression' "$th"
check        "the navbar survives the rotation"    'quarto-header'            "$th"
check        "the footer survives the rotation"    'nav-footer'               "$th"
# The chrome placement must reach the compiled bundle, not just the source.
if grep -rq 'data-vertext-progression' "$theme/_site/site_libs/"*/*.css 2>/dev/null; then
  printf 'ok   chrome rules reach the compiled stylesheet\n'
else
  printf 'FAIL chrome rules reach the compiled stylesheet\n'
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

printf '\n'
if [ "$failures" -eq 0 ]; then
  printf 'all extension checks passed\n'
else
  printf '%d extension check(s) failed\n' "$failures"
  exit 1
fi
