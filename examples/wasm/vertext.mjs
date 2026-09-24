// The JavaScript side of crates/vertext-wasm. No bundler and no bindgen: the
// module exports plain functions over its own memory, and this file is the
// whole of the glue. Works in browsers and in Node.
//
// Offsets in the source map are UTF-8 byte offsets, because that is what the
// engine measures. JavaScript strings index UTF-16 code units, so a host that
// talks to a textarea converts with `byteToUtf16` and `utf16ToByte`.
//
// This file and the .wasm are two halves of one release that travel
// separately, so `load` refuses a module that does not speak this glue's
// WIRE_VERSION -- MAJOR.MINOR, the rule the Quarto filter applies to the
// binary -- instead of rendering with it.

export const CODE = 1;
export const PAGE = 2;
export const LEFT_TO_RIGHT = 4;

export const WIRE_VERSION = '0.2';

const NONE = 0xFFFFFFFF;           // usize::MAX on wasm32
const encoder = new TextEncoder();
const decoder = new TextDecoder('utf-8', { fatal: true });

export class VersionMismatch extends Error {
  constructor(wasm) {
    super(`vertext.wasm is ${wasm ?? 'from before the version handshake'} but vertext.mjs ` +
          `speaks ${WIRE_VERSION}: load both from one release`);
    this.name = 'VersionMismatch';
    this.wasm = wasm;
    this.glue = WIRE_VERSION;
  }
}

/** Instantiate the module; throws VersionMismatch rather than return one that does not match. */
export async function load(bytes) {
  const { instance } = await WebAssembly.instantiate(bytes, {});
  const x = instance.exports;
  let version = null;
  if (typeof x.vertext_version === 'function') {
    const length = x.vertext_version();
    version = decoder.decode(new Uint8Array(x.memory.buffer, x.vertext_output(), length));
  }
  if (version === null || version.split('.').slice(0, 2).join('.') !== WIRE_VERSION) {
    throw new VersionMismatch(version);
  }
  return new Vertext(x, version);
}

export class Vertext {
  constructor(exports, version) { this.x = exports; this.version = version; }

  #call(fn, text, flags) {
    const input = encoder.encode(text);
    const pointer = this.x.vertext_alloc(input.length);
    new Uint8Array(this.x.memory.buffer, pointer, input.length).set(input);
    const length = fn(pointer, input.length, flags) >>> 0;
    const out = length === NONE ? null
      : new Uint8Array(this.x.memory.buffer, this.x.vertext_output(), length).slice();
    this.x.vertext_free(pointer, input.length);
    return out;
  }

  /** The HTML the CLI prints for `text` under `flags`. */
  render(text, flags = 0) {
    return decoder.decode(this.#call(this.x.vertext_render, text, flags));
  }

  /** The source map of `text` as one vertical strip, or null. Kept for caret/offset. */
  map(text, flags = 0) {
    const out = this.#call(this.x.vertext_map, text, flags);
    return out === null ? null : JSON.parse(decoder.decode(out));
  }

  /** The caret at a UTF-8 byte offset of the last mapped text, or null. */
  caret(offset) {
    if (this.x.vertext_caret(offset) === 0) return null;
    const v = new DataView(this.x.memory.buffer, this.x.vertext_output(), 12);
    return { column: v.getUint32(0, true), index: v.getUint32(4, true), grapheme: v.getUint32(8, true) };
  }

  /** The UTF-8 byte offset of a caret in the last mapped text, or null. */
  offset({ column, index, grapheme }) {
    const o = this.x.vertext_offset(column, index, grapheme);
    return o < 0 ? null : o;
  }
}

export function utf16ToByte(text, index) {
  return encoder.encode(text.slice(0, index)).length;
}

export function byteToUtf16(text, byte) {
  const bytes = encoder.encode(text);
  return decoder.decode(bytes.slice(0, byte)).length;
}
