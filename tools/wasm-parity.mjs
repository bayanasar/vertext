#!/usr/bin/env node
// The browser build renders what the CLI renders, byte for byte (#13).
//
// `vertext-core` has kept itself free of I/O and DOM so that a second host
// could share it unchanged, and until vertext-wasm no second host existed, so
// the discipline had cost and no proof. This is the proof: every input below is
// rendered by the release CLI and by the wasm module, under every flag the CLI
// takes, and the two strings must be equal. It also walks the source map the
// wasm module exports, because the caret host in examples/wasm relies on two
// things: that a mapped strip has one span per slot, and that an offset and a
// caret convert back to each other.
//
//   cargo build --release -p vertext-cli
//   cargo build --release -p vertext-wasm --target wasm32-unknown-unknown
//   node tools/wasm-parity.mjs

import { readFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { load, CODE, PAGE, LEFT_TO_RIGHT } from '../examples/wasm/vertext.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const BINARY = path.join(ROOT, 'target/release/vertext');
const WASM = path.join(ROOT, 'target/wasm32-unknown-unknown/release/vertext_wasm.wasm');

const golden = JSON.parse(readFileSync(path.join(ROOT, 'goldens/shaping.json'), 'utf8'));
const inputs = [
  ...golden.corpus.runs,
  ...golden.corpus.lines.map(l => l.text),
  '',
  '\n',
  '山川异域，风月同天。寄诸佛子，共结来缘。\n',
  '第一行\r\n\r\n第三行\n\n',
  'ᠮᠣᠩᠭᠣᠯ\u202fᠤᠨ (mongɣol-un) ᠨᠣᠮ᠃',
  'the genitive ᠮᠣᠩᠭᠣᠯ\u202fᠤᠨ is a single word in this English sentence',
  'internationalization 与 use-after-free',
  'e\u0301cole 葛\ufe00城 👩\u200d💻 <b>&amp;</b>',
  // The wire protocol: a heading, prose, a table, list items and code.
  '\ue002標題\ue001正文，接着寫。\ue008名\ue009意\ue00aᠨᠣᠮ\ue009書\ue001\ue00b一項\ue00c二項\ue000fn main() {}\n\ue001完。',
];
const FLAGS = [0, CODE, PAGE, LEFT_TO_RIGHT, PAGE | LEFT_TO_RIGHT];

function cliArgs(flags) {
  const args = [];
  if (flags & CODE) args.push('--code');
  if (flags & PAGE) args.push('--page');
  args.push('--progression', flags & LEFT_TO_RIGHT ? 'lr' : 'rl');
  return args;
}

const vertext = await load(readFileSync(WASM));
const fails = [];
let compared = 0, mapped = 0, carets = 0;

for (const text of inputs) {
  for (const flags of FLAGS) {
    const cli = spawnSync(BINARY, cliArgs(flags), { input: text, encoding: 'utf8' });
    if (cli.status !== 0) { fails.push(`CLI failed on ${JSON.stringify(text)}: ${cli.stderr}`); continue; }
    const wasm = vertext.render(text, flags);
    compared++;
    if (wasm !== cli.stdout) {
      let at = 0;
      while (at < wasm.length && wasm[at] === cli.stdout[at]) at++;
      fails.push(`flags ${flags}, ${JSON.stringify(text.slice(0, 40))}: differs at ${at}\n` +
                 `  cli  ${JSON.stringify(cli.stdout.slice(at, at + 60))}\n` +
                 `  wasm ${JSON.stringify(wasm.slice(at, at + 60))}`);
      continue;
    }
    if (flags & (PAGE | LEFT_TO_RIGHT)) continue;   // the map does not depend on these

    const map = vertext.map(text, flags);
    if (map === null) continue;
    mapped++;
    const slots = map.columns.flat();
    const spans = (wasm.match(/<span class="vertext-/g) || []).length;
    if (spans !== slots.length) {
      fails.push(`${JSON.stringify(text.slice(0, 40))}: ${spans} spans for ${slots.length} mapped slots`);
    }
    const bytes = new TextEncoder().encode(text).length;
    const seen = new Set();
    for (let o = 0; o <= bytes; o++) {
      const c = vertext.caret(o);
      if (c === null) continue;
      carets++;
      const key = `${c.column}/${c.index}/${c.grapheme}`;
      if (seen.has(key)) fails.push(`${JSON.stringify(text.slice(0, 40))}: byte ${o} repeats caret ${key}`);
      seen.add(key);
      if (vertext.offset(c) !== o) fails.push(`${JSON.stringify(text.slice(0, 40))}: caret ${key} came back as ${vertext.offset(c)}, not ${o}`);
    }
    map.columns.forEach((column, c) => column.forEach((slot, i) => {
      const at = vertext.caret(slot.start);
      if (!at || at.column !== c || at.index !== i || at.grapheme !== 0) {
        fails.push(`${JSON.stringify(text.slice(0, 40))}: slot ${c}/${i} does not start at byte ${slot.start}`);
      }
    }));
  }
}

if (fails.length) {
  console.error(`FAIL: ${fails.length} finding(s)\n`);
  for (const f of fails.slice(0, 15)) console.error('  ' + f);
  process.exit(1);
}
console.log(`PASS: ${compared} renders over ${inputs.length} inputs and ${FLAGS.length} flag sets are byte-identical between the CLI and the wasm module`);
console.log(`      and ${mapped} mapped strips have one span per slot, with ${carets} carets converting to their offsets and back`);
