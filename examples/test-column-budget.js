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

const lua = fs.readFileSync(
  path.join(__dirname, '..', 'extensions', 'vertext', 'vertext.lua'), 'utf8');

let failures = 0;
const check = (name, ok, detail) => {
  if (ok) { console.log(`ok   ${name}`); }
  else { console.error(`FAIL ${name}${detail ? ` -- ${detail}` : ''}`); failures++; }
};

// Each mode's stylesheet, taken by its id so a renamed block fails loudly
// rather than matching some other <style> further down the file.
for (const [mode, id] of [['document', 'vertext-document-mode'],
                          ['page', 'vertext-page-mode']]) {
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
}

if (failures) { console.error(`\nFAIL: ${failures} check(s)`); process.exit(1); }
console.log('\nPASS: both modes declare the column budget and route it through the theme hook');
