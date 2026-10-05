#!/usr/bin/env node
// The column length budget, and the hook a theme reaches it through.
//
// `--vertext-column-theme-height` is documented as the way a theme says how
// deep the strips are. It only works if the mode stylesheet DECLARES
// `--vertext-column-height` and routes it through that variable: the filter
// writes its <style> into the body, after the head, so it wins a specificity
// tie against any linked theme sheet setting `--vertext-column-height`
// directly. Declare it and the theme is heard; leave it out and the theme's
// answer lands in a variable no rule reads, while vertext.css falls through to
// its own fallback. Nothing says so out loud — the page still renders.
//
// Page mode shipped without the declaration and two people hit it separately
// before anyone found it. That is what an untested hook costs, so both modes
// are checked here rather than the one that was broken.
//
// Not a browser: this reads the emitted CSS text. What it proves is that the
// declaration is there and points at the hook. Whether the resulting number is
// the RIGHT depth is a measurement, and it belongs in front of a real browser.

const fs = require('fs');
const path = require('path');

// Both copies of the filter. vertext-theme vendors its own, and the first cut
// of this fix went into the engine's copy alone -- which is precisely how the
// two drifted apart to begin with, so the gate reads both rather than trusting
// anyone to remember the second one.
const FILTERS = [
  ['engine', path.join(__dirname, '..', 'extensions', 'vertext', 'vertext.lua')],
  ['theme',  path.join(__dirname, '..', 'extensions', 'vertext-theme',
                       '_extensions', 'vertext', 'vertext.lua')],
];

let failures = 0;
const chars = new Set();
const cells = new Set();
const check = (name, ok, detail) => {
  if (ok) { console.log(`ok   ${name}`); }
  else { console.error(`FAIL ${name}${detail ? ` -- ${detail}` : ''}`); failures++; }
};

// Each mode's stylesheet, taken by its id so a renamed block fails loudly
// rather than matching some other <style> further down the file.
for (const [copy, file] of FILTERS) {
 const lua = fs.readFileSync(file, 'utf8');
 for (const [modeName, id] of [['document', 'vertext-document-mode'],
                               ['page', 'vertext-page-mode']]) {
  const mode = `${copy}/${modeName}`;
  const block = new RegExp(`<style id="${id}">([\\s\\S]*?)</style>`).exec(lua);
  if (!block) { check(`${mode} mode: stylesheet found`, false, `no <style id="${id}">`); continue; }
  // Comments first, and before anything reads the text. Both mode stylesheets
  // explain this variable at length, and one of those explanations WRITES the
  // property name inside a `body { ... }` example. An earlier draft of this
  // file matched that sentence, captured through to the real declaration's
  // semicolon, and reported the theme hook present on a stylesheet that had
  // been stripped of it -- passing for the wrong reason is the failure mode a
  // text-matching test has, so the text has to be the code.
  const css = block[1].replace(/\/\*[\s\S]*?\*\//g, '');

  const declaration = /--vertext-column-height:\s*([^;]+);/.exec(css);
  check(`${mode} mode declares --vertext-column-height`, !!declaration);
  if (!declaration) continue;

  const value = declaration[1].trim();
  check(`${mode} mode routes it through the theme hook`,
        /var\(\s*--vertext-column-theme-height\s*,/.test(value), value);

  // A hook with no fallback leaves the budget empty on every page that does
  // not set it, which is worse than the guess it replaced.
  check(`${mode} mode keeps a fallback for pages with no theme`,
        /var\(\s*--vertext-column-theme-height\s*,\s*\S[^)]*\)/.test(value), value);

  // The declaration has to sit on `body`: the filter's specificity advantage
  // is the whole reason the indirection exists, and a rule on `:root` or on
  // `.vertext` would not have it.
  const onBody = new RegExp(`body\\s*\\{[^{}]*--vertext-column-height`).test(css);
  check(`${mode} mode declares it on body`, onBody);

  // Issue #26 settled what the budget IS: a declared number of characters,
  // capped by the space the theme reports. Both halves have to be in the one
  // declaration -- the count without the cap runs under the chrome on a short
  // window, and the cap without the count is the window-following measure the
  // issue replaced.
  const counted = /min\(\s*calc\(\s*var\(\s*--vertext-column-chars\s*,\s*(\d+)\s*\)\s*\*\s*var\(\s*--vertext-cell\s*,\s*(\d+)px\s*\)\s*\)\s*,\s*var\(\s*--vertext-column-theme-height/.exec(value);
  check(`${mode} mode budgets a declared character count, capped by the theme hook`, !!counted, value);
  if (counted) {
    chars.add(counted[1]);
    cells.add(counted[2]);
  }
 }
}

// One default across both modes and both copies. The cell is declared once,
// as `--vertext-cell` in vertext.css (#48): the budget multiplies characters
// by it and the upright glyph is set at it, so the two cannot part. The
// filter keeps a px fallback for a page without the stylesheet, which has to
// be the declared value -- that fallback is the one second copy left.
check('one default character count everywhere', chars.size === 1, [...chars].join(', '));
const stylesheet = fs.readFileSync(
  path.join(__dirname, '..', 'extensions', 'vertext', 'vertext.css'), 'utf8')
  .replace(/\/\*[\s\S]*?\*\//g, '');
const declared = /:root\s*\{\s*--vertext-cell:\s*(\d+)px;\s*\}/.exec(stylesheet);
check('the stylesheet declares the cell once, on :root', !!declared);
const cell = declared && declared[1];
check('the filter fallback is the declared cell', cells.size === 1 && cells.has(cell),
      `declared ${cell}px, fallbacks ${[...cells].join(', ')}px`);
// No size in the stylesheet may restate the cell as a number: every px equal
// to it outside the declaration is a second source waiting to drift.
const restated = cell ? (stylesheet.match(new RegExp(`(?<![\\d.])${cell}px`, 'g')) || []).length - 1 : -1;
check('the stylesheet never restates the cell', restated === 0, `${restated} restatement(s)`);
const upright = /\.vertext-upright,\s*\.vertext-neutral\s*\{\s*font-size:\s*var\(--vertext-cell\);/.test(stylesheet);
check('the upright glyph is set at the cell', upright);
// Latin and Mongolian are sized against the cell too (MLReq 7.3.3, 7.3.4), so
// a page that changes the cell keeps the three scripts in proportion. A px
// literal here is a size that stays behind when the cell moves.
for (const [slot, ratio] of [['latin', '14 / 18'], ['mongolian', '15 / 18']]) {
  const block = new RegExp(`(?:^|\\n)\\.vertext-${slot}\\s*\\{([^}]*)\\}`).exec(stylesheet);
  check(`a ${slot} slot is sized against the cell`,
        !!block && block[1].includes(`font-size: calc(var(--vertext-cell) * ${ratio});`),
        block ? (/font-size:[^;]*;/.exec(block[1]) || ['no font-size'])[0] : 'no rule');
}
for (const [copy, file] of FILTERS) {
  const lua = fs.readFileSync(file, 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
  const bare = cell ? (lua.match(new RegExp(`(?<![\\d.])${cell}px`, 'g')) || []).length : -1;
  const fallback = cell ? (lua.match(new RegExp(`var\\(--vertext-cell, ${cell}px\\)`, 'g')) || []).length : -2;
  check(`${copy} filter restates the cell only as the fallback`, bare === fallback,
        `${bare} px literal(s), ${fallback} of them fallbacks`);
}
// Every fallback in the stylesheet spends the same measure, so a strip on a
// page with no mode stylesheet still gets the declared count.
const fallbacks = stylesheet.match(/var\(--vertext-column-height,\s*[^;]*;/g) || [];
check('every stylesheet fallback reads the declared count',
      fallbacks.length > 0 && fallbacks.every(f => /var\(--vertext-column-chars,\s*\d+\)\s*\*\s*var\(--vertext-cell\)/.test(f)),
      fallbacks.filter(f => !/--vertext-cell/.test(f)).join(' | '));
// And the YAML key has to reach the property.
for (const [copy, file] of FILTERS) {
  const lua = fs.readFileSync(file, 'utf8');
  check(`${copy} filter reads vertext-column-chars`, /meta\['vertext-column-chars'\]/.test(lua));
  check(`${copy} filter emits --vertext-column-chars on body`,
        /body \{ --vertext-column-chars: /.test(lua));
}

if (failures) { console.error(`\nFAIL: ${failures} check(s)`); process.exit(1); }
console.log('\nPASS: both modes budget a declared character count, capped through the theme hook');
