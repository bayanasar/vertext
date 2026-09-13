// The JavaScript side of crates/vertext-wasm. No bundler and no bindgen: the
// module exports plain functions over its own memory, and this file is the
// whole of the glue. Works in browsers and in Node.
//
// Offsets in the source map are UTF-8 byte offsets, because that is what the
// engine measures. JavaScript strings index UTF-16 code units, so a host that
// talks to a textarea converts with `byteToUtf16` and `utf16ToByte`.

export const CODE = 1;
export const PAGE = 2;
export const LEFT_TO_RIGHT = 4;

const NONE = 0xFFFFFFFF;           // usize::MAX on wasm32
const encoder = new TextEncoder();
const decoder = new TextDecoder('utf-8', { fatal: true });

export async function load(bytes) {
  const { instance } = await WebAssembly.instantiate(bytes, {});
  return new Vertext(instance.exports);
}

export class Vertext {
  constructor(exports) { this.x = exports; }

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
