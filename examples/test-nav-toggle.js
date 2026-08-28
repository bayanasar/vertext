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

// A page, described by which of the three ways to name a strip it offers.
//
//   marked  an element carrying [data-vertext-edge="nav"] -- a host that emits
//           its own chrome
//   named   an element a theme points at with --vertext-nav-target
//   header  #quarto-header, the last resort
//
// A real page can offer more than one, and which one wins is the whole point:
// vertext-theme offers `header` (its right-edge BANNER) and `named`
// (#quarto-sidebar, the actual top strip), and the engine used to take the
// banner.
function makeStrip(name) {
  return { tagName: 'NAV', name, attrs: {}, style: {}, children: [],
           setAttribute(k, v) { this.attrs[k] = v; },
           appendChild(c) { this.children.push(c); } };
}

function makeEnv(depth, opts) {
  opts = opts || { marked: true };
  const classes = new Set();
  const listeners = {};
  const marked = opts.marked ? makeStrip('marked') : null;
  const named = opts.named ? makeStrip('named') : null;
  const header = opts.header ? makeStrip('header') : null;
  // What the theme published. `bad` is a selector that does not parse.
  const target = opts.bad ? '#(' : (opts.named ? '#quarto-sidebar' : '');
  const env = {
    marked, named, header, made: null, store: {}, classes,
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
      querySelector(sel) {
        if (sel.indexOf('data-vertext-edge') >= 0) { return marked; }
        // A browser throws on a malformed selector; so must the stub, or the
        // try/catch around it is never exercised.
        if (sel === '#(') { throw new Error('unparsable selector'); }
        if (target && sel === target) { return named; }
        return null;
      },
      getElementById(id) { return id === 'quarto-header' ? header : null; },
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
               getPropertyValue(p) {
                 if (p === '--vertext-nav-depth') { return depth; }
                 // A CSS string comes back quoted; the script has to strip them.
                 if (p === '--vertext-nav-target') { return target ? '"' + target + '"' : ''; }
                 return '';
               } };
    },
    localStorage: { getItem(k) { return k in env.store ? env.store[k] : null; },
                    setItem(k, v) { env.store[k] = v; } },
    click() { if (listeners.click) { listeners.click(); } },
  };
  // Whichever way it was named, this is the element the button belongs on.
  env.strip = marked || named || header;
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

// 4. THE SHIPPED BUG, pinned. A theme names its strip with
//    `--vertext-nav-target` and `#quarto-header` also exists. In
//    vertext-theme that header is the BANNER on the right edge, so taking it
//    put the button on the banner, blanked the banner's brand and links on
//    collapse, and left the real strip's list at full size inside a strip that
//    had shrunk under it. Everything about the control worked except which
//    element it worked on.
const themed = makeEnv('11rem', { named: true, header: true });
run(themed.document, themed.getComputedStyle, themed.localStorage);
check(themed.made, 'no button when a theme names its strip');
check(themed.named.children[0] === themed.made,
      'button did not go on the element --vertext-nav-target names');
check(themed.header.children.length === 0,
      'button went on #quarto-header while a target was published -- the shipped bug');

// 5. Whatever was chosen says so afterwards. The stylesheet has ONE selector,
//    and `tools/check-nav-toggle.py` reads the same attribute, so a strip found
//    any other way has to end up carrying it.
check(themed.named.attrs['data-vertext-edge'] === 'nav',
      'the chosen strip was not stamped with data-vertext-edge="nav"');

// 6. Nothing named at all: the stock Quarto navbar, unchanged.
const stock = makeEnv('6rem', { header: true });
run(stock.document, stock.getComputedStyle, stock.localStorage);
check(stock.made && stock.header.children[0] === stock.made,
      'the #quarto-header fallback stopped working');

// 7. A selector out of a stylesheet is author input and may not parse. It must
//    fall through to the fallback, not throw and take the whole script down.
const broken = makeEnv('6rem', { bad: true, header: true });
let threw = null;
try { run(broken.document, broken.getComputedStyle, broken.localStorage); }
catch (e) { threw = e; }
check(!threw, 'an unparsable --vertext-nav-target threw: ' + (threw && threw.message));
check(broken.made && broken.header.children[0] === broken.made,
      'an unparsable target did not fall through to #quarto-header');

console.log(fails.length ? 'FAIL:\n  ' + fails.join('\n  ')
                         : 'ok   nav-toggle logic (' + 7 + ' cases)');
process.exit(fails.length ? 1 : 0);
