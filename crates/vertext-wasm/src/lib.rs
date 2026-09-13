//! vertext for the browser.
//!
//! The same [`render_document`] the CLI calls, compiled to `wasm32` and exposed
//! through a plain C ABI: no bindgen, no imports, nothing between the host and
//! the two crates it wraps. A page gets the HTML the CLI would have printed for
//! the same input and options, byte for byte, and `tools/wasm-parity.mjs`
//! holds it to that.
//!
//! It also exposes [`vertext_core::SourceMap`], so a page can turn a click on a
//! slot into a source offset and a source offset back into a slot. That map is
//! for a strip laid out as one vertical block, which is the case a caret needs;
//! input the renderer would split into headings, tables or horizontal blocks
//! has no single layout to map, and the map call says so.
//!
//! Calling convention: the host asks [`vertext_alloc`] for input bytes, writes
//! UTF-8 there, and calls a function with the pointer and length. Results are
//! left in one output buffer, read with [`vertext_output`] and the returned
//! length, and valid until the next call. The input allocation is the host's to
//! release with [`vertext_free`].

use std::cell::RefCell;

use vertext_core::{
    layout_with_source_map, prefers_horizontal, Caret, Progression, SourceMap,
};
use vertext_html::{code_config, prose_config, render_document, RenderOptions};

/// Lay the whole input out as code, as `--code` does.
pub const CODE: u32 = 1;
/// Mark the strip as the page's surface, as `--page` does.
pub const PAGE: u32 = 2;
/// Columns advance left to right, as `--progression lr` does.
pub const LEFT_TO_RIGHT: u32 = 4;

thread_local! {
    static OUTPUT: RefCell<Vec<u8>> = const { RefCell::new(Vec::new()) };
    static MAP: RefCell<Option<SourceMap>> = const { RefCell::new(None) };
}

fn progression(flags: u32) -> Progression {
    if flags & LEFT_TO_RIGHT != 0 { Progression::LeftToRight } else { Progression::RightToLeft }
}

/// The options the CLI would build from the equivalent flags.
pub fn options(flags: u32) -> RenderOptions {
    RenderOptions {
        whole_strip_code: flags & CODE != 0,
        page: flags & PAGE != 0,
        progression: progression(flags),
    }
}

/// What the CLI prints for `input` under `flags`.
pub fn render(input: &str, flags: u32) -> String {
    render_document(input, options(flags))
}

/// The source map of `input` laid out as one vertical strip, or `None` when
/// the renderer would not lay it out that way: it carries mode markers, or its
/// prose is Latin-majority and goes horizontal.
pub fn map(input: &str, flags: u32) -> Option<SourceMap> {
    let text = input.trim_end_matches(['\n', '\r']);
    let code = flags & CODE != 0;
    if text.chars().any(|c| ('\u{E000}'..='\u{E0FF}').contains(&c)) {
        return None;
    }
    if !code && prefers_horizontal(text) {
        return None;
    }
    let config = if code { code_config(progression(flags)) } else { prose_config(progression(flags)) };
    Some(layout_with_source_map(text, &config).1)
}

/// The map as JSON: for each column, each slot's source range, grapheme count
/// and whether it ends in an inserted hyphen.
pub fn map_json(map: &SourceMap) -> String {
    let mut columns = vec![Vec::new(); map.columns()];
    for slot in map.slots() {
        columns[slot.column].push(format!(
            "{{\"start\":{},\"end\":{},\"graphemes\":{},\"hyphen\":{}}}",
            slot.range.start, slot.range.end, slot.graphemes(), slot.inserted_hyphen));
    }
    let columns: Vec<String> = columns.iter().map(|c| format!("[{}]", c.join(","))).collect();
    format!("{{\"columns\":[{}]}}", columns.join(","))
}

fn set_output(bytes: &[u8]) -> usize {
    OUTPUT.with(|o| {
        let mut o = o.borrow_mut();
        o.clear();
        o.extend_from_slice(bytes);
        o.len()
    })
}

/// Reserve `len` bytes for the host to write input into.
#[unsafe(no_mangle)]
pub extern "C" fn vertext_alloc(len: usize) -> *mut u8 {
    let mut buffer = Vec::<u8>::with_capacity(len);
    let pointer = buffer.as_mut_ptr();
    std::mem::forget(buffer);
    pointer
}

/// Release bytes from [`vertext_alloc`].
///
/// # Safety
/// `pointer` and `len` must be exactly what one call to [`vertext_alloc`]
/// returned and was given, released once.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn vertext_free(pointer: *mut u8, len: usize) {
    drop(unsafe { Vec::from_raw_parts(pointer, 0, len) });
}

/// The output buffer the last call wrote.
#[unsafe(no_mangle)]
pub extern "C" fn vertext_output() -> *const u8 {
    OUTPUT.with(|o| o.borrow().as_ptr())
}

/// # Safety
/// `pointer` must address `len` initialized bytes.
unsafe fn input<'a>(pointer: *const u8, len: usize) -> Option<&'a str> {
    std::str::from_utf8(unsafe { std::slice::from_raw_parts(pointer, len) }).ok()
}

/// Render the input; returns the length of the HTML in the output buffer.
/// Input that is not UTF-8 returns `usize::MAX` and leaves no output.
///
/// # Safety
/// `pointer` must address `len` initialized bytes.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn vertext_render(pointer: *const u8, len: usize, flags: u32) -> usize {
    match unsafe { input(pointer, len) } {
        Some(text) => set_output(render(text, flags).as_bytes()),
        None => usize::MAX,
    }
}

/// Build the source map for the input and keep it for [`vertext_caret`] and
/// [`vertext_offset`]; returns the length of its JSON in the output buffer, or
/// `usize::MAX` when the input has no single vertical layout (see [`map`]).
///
/// # Safety
/// `pointer` must address `len` initialized bytes.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn vertext_map(pointer: *const u8, len: usize, flags: u32) -> usize {
    let built = unsafe { input(pointer, len) }.and_then(|text| map(text, flags));
    let length = match &built {
        Some(m) => set_output(map_json(m).as_bytes()),
        None => usize::MAX,
    };
    MAP.with(|slot| *slot.borrow_mut() = built);
    length
}

/// The caret at a source offset of the last mapped input, as
/// `column`, `index` and `grapheme` written to the output buffer as three
/// little-endian u32. Returns 12, or 0 when there is no caret there.
#[unsafe(no_mangle)]
pub extern "C" fn vertext_caret(offset: usize) -> usize {
    let caret = MAP.with(|m| m.borrow().as_ref().and_then(|m| m.caret(offset)));
    match caret {
        Some(c) => {
            let mut bytes = Vec::with_capacity(12);
            for n in [c.column, c.index, c.grapheme] {
                bytes.extend_from_slice(&(n as u32).to_le_bytes());
            }
            set_output(&bytes)
        }
        None => 0,
    }
}

/// The source offset of a caret in the last mapped input, or -1.
#[unsafe(no_mangle)]
pub extern "C" fn vertext_offset(column: usize, index: usize, grapheme: usize) -> isize {
    MAP.with(|m| {
        m.borrow().as_ref()
            .and_then(|m| m.offset(Caret { column, index, grapheme }))
            .map_or(-1, |o| o as isize)
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_exports_render_what_render_document_does() {
        let text = "山川异域，风月同天。\nᠮᠣᠩᠭᠣᠯ\u{202F}ᠤᠨ";
        let pointer = vertext_alloc(text.len());
        unsafe {
            std::ptr::copy_nonoverlapping(text.as_ptr(), pointer, text.len());
            let len = vertext_render(pointer, text.len(), PAGE | LEFT_TO_RIGHT);
            let html = std::slice::from_raw_parts(vertext_output(), len);
            assert_eq!(html, render_document(text, RenderOptions {
                whole_strip_code: false, page: true, progression: Progression::LeftToRight,
            }).as_bytes());
            vertext_free(pointer, text.len());
        }
    }

    #[test]
    fn the_map_is_the_layout_the_renderer_draws() {
        let text = "山川异域\nᠮᠣᠩᠭᠣᠯ\u{202F}ᠤᠨ ᠨᠣᠮ\n";
        let html = render(text, 0);
        let m = map(text, 0).unwrap();
        // One column div per mapped column, one span per mapped slot.
        let columns = html.matches("<div class=\"vertext-column").count();
        let spans = html.matches("<span class=\"vertext-").count();
        let mapped = map_json(&m);
        assert_eq!(columns, mapped.matches('[').count() - 1, "{mapped}");
        assert_eq!(spans, m.slots().len());
        assert_eq!(mapped.matches("\"start\"").count(), spans);
    }

    #[test]
    fn input_with_no_single_vertical_layout_has_no_map() {
        assert!(map("\u{E002}標題\u{E001}正文", 0).is_none());
        assert!(map("this paragraph is plainly English and goes horizontal", 0).is_none());
    }

    #[test]
    fn a_caret_round_trips_through_the_exports() {
        let text = "ᠮᠣᠩᠭᠣᠯ\u{202F}ᠤᠨ";
        let pointer = vertext_alloc(text.len());
        unsafe {
            std::ptr::copy_nonoverlapping(text.as_ptr(), pointer, text.len());
            assert_ne!(vertext_map(pointer, text.len(), 0), usize::MAX);
            vertext_free(pointer, text.len());
        }
        let joint = text.find('\u{202F}').unwrap();
        assert_eq!(vertext_caret(joint), 12);
        let bytes = unsafe { std::slice::from_raw_parts(vertext_output(), 12) };
        let grapheme = u32::from_le_bytes(bytes[8..12].try_into().unwrap());
        assert_eq!(grapheme, 6);
        assert_eq!(vertext_offset(0, 0, 6), joint as isize);
        assert_eq!(vertext_offset(0, 0, 99), -1);
    }
}
