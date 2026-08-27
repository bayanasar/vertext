#!/usr/bin/env node
// The nav-collapse control's LOGIC, exercised against a stub DOM.
//
// This is deliberately not a browser. `examples/test-extension.sh` asserts on
// markup and `cargo test` covers layout; neither can run a script, so the
// attach rule and the click handler had no cover at all. A stub DOM is enough
// to prove the branches -- opt-in, persistence, the way back -- and it runs
// anywhere node does, with no Quarto and no Chrome.
//
// What it does NOT prove, and what nothing here can: that a real mouse event
// at the button's centre LANDS on the button, and that collapsing moves real
// pixels. A control that renders correctly and is unclickable has shipped from
// this extension before, green the whole way. For that, drive a real browser --
// `tools/check-nav-toggle.py` in the kele repo does exactly that, and its
// selectors are this engine's, so it can be pointed at any page we render.

const fs = require('fs');
const path = require('path');

const lua = fs.readFileSync(
  path.join(__dirname, '..', 'extensions', 'vertext', 'vertext.lua'), 'utf8');
const block = /local NAV_TOGGLE = \[\[\n([\s\S]*?)\n\]\]/.exec(lua);
if (!block) { console.error('FAIL: NAV_TOGGLE not found in vertext.lua'); process.exit(1); }
const script = /<script>([\s\S]*?)<\/script>/.exec(block[1]);
if (!script) { console.error('FAIL: no <script> inside NAV_TOGGLE'); process.exit(1); }

function makeEnv(depth) {
  const classes = new Set();
  const listeners = {};
  const strip = { tagName: 'NAV', style: {}, children: [],
                  appendChild(c) { this.children.push(c); } };
  const env = {
    strip, made: null, store: {}, classes,
    document: {
      readyState: 'complete',
      documentElement: {
        attrs: { 'data-vertext-nav-label': 'Hide',
                 'data-vertext-nav-label-collapsed': 'Show' },
        getAttribute(k) { return this.attrs[k] || null; },
      },
      body: { classList: {
        toggle(n, on) { on ? classes.add(n) : classes.delete(n); },
        contains(n) { return classes.has(n); } } },
      querySelector(sel) { return sel.indexOf('data-vertext-edge') >= 0 ? strip : null; },
      getElementById() { return null; },
      createElement() {
        const el = { attrs: {}, textContent: '', className: '', type: '',
                     setAttribute(k, v) { this.attrs[k] = v; },
                     addEventListener(k, fn) { listeners[k] = fn; } };
        env.made = el; return el;
      },
      addEventListener() {},
    },
    getComputedStyle() {
      return { position: 'fixed',
               getPropertyValue(p) { return p === '--vertext-nav-depth' ? depth : ''; } };
    },
    localStorage: { getItem(k) { return k in env.store ? env.store[k] : null; },
                    setItem(k, v) { env.store[k] = v; } },
    click() { if (listeners.click) { listeners.click(); } },
  };
  return env;
}

const run = new Function('document', 'getComputedStyle', 'localStorage', script[1]);
const fails = [];
function check(cond, msg) { if (!cond) { fails.push(msg); } }

// 1. The theme published a depth: the engine builds the control.
const on = makeEnv(' 6rem ');
run(on.document, on.getComputedStyle, on.localStorage);
check(on.made, 'no button created when --vertext-nav-depth is declared');
if (on.made) {
  check(on.strip.children[0] === on.made, 'button not appended to the strip');
  check(on.made.className === 'vertext-nav-toggle', 'wrong class: ' + on.made.className);
  check(!on.classes.has('vertext-nav-collapsed'), 'starts collapsed with nothing stored');
  check(on.made.attrs['aria-label'] === 'Hide', 'label not taken from the host');
  on.click();
  check(on.classes.has('vertext-nav-collapsed'), 'click did not collapse');
  check(on.store['vertext-nav-collapsed'] === '1', 'collapse not persisted');
  check(on.made.attrs['aria-expanded'] === 'false', 'aria-expanded not updated');
  on.click();
  check(!on.classes.has('vertext-nav-collapsed'), 'second click did not expand -- no way back');
  check(on.store['vertext-nav-collapsed'] === '0', 'expand not persisted');
}

// 2. No depth published: no control. A theme that still bakes its depth into a
//    build-time constant must get NOTHING, not a button that moves no pixels.
const off = makeEnv('');
run(off.document, off.getComputedStyle, off.localStorage);
check(!off.made, 'button created on a page that never declared --vertext-nav-depth');

// 3. A stored choice survives the reload.
const kept = makeEnv('6rem');
kept.store['vertext-nav-collapsed'] = '1';
run(kept.document, kept.getComputedStyle, kept.localStorage);
check(kept.classes.has('vertext-nav-collapsed'), 'stored collapsed state ignored on load');

console.log(fails.length ? 'FAIL:\n  ' + fails.join('\n  ')
                         : 'ok   nav-toggle logic (' + 3 + ' cases)');
process.exit(fails.length ? 1 : 0);
