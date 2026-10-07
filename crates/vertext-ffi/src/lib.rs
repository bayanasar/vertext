//! vertext for native hosts.
//!
//! A host that draws text itself — Flutter through `dart:ffi` is the first —
//! has no use for HTML. It needs what the renderer would have drawn: each
//! column's slots, what kind each slot is, the text it shows, and where in
//! the source that text came from. This crate hands over exactly that, as
//! JSON over a plain C ABI, and decides nothing on its own: the strip is
//! [`strip_layout`], the kinds are [`slot_kind`], both the ones the page uses,
//! so a slot drawn here is classified exactly as it is on the page.
//!
//! The host still owns everything that needs a font: shaping, metrics, where
//! a column breaks into lines, painting, hit-testing.
//!
//! Calling convention: [`vertext_layout`] takes UTF-8 bytes and returns a
//! buffer the caller owns and releases with [`vertext_free`]. There is no
//! shared output buffer, so calls from different threads do not interfere.
//!
//! The library and its binding are two halves, so they carry a handshake, as
//! the Quarto filter and the binary do: [`vertext_version`] reports the crate
//! version, and the binding refuses a library whose wire version is not its
//! own (`tools/wire-pairs.json`).

use std::ffi::c_char;

use vertext_core::Progression;
use vertext_html::{slot_kind, strip_layout};

/// Lay the whole input out as code, as `--code` does.
pub const CODE: u32 = 1;
/// Columns advance left to right, as `--progression lr` does.
pub const LEFT_TO_RIGHT: u32 = 4;

/// One slot as a host receives it.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HostSlot {
    /// The suffix of the slot's class on the page: `upright`, `latin`,
    /// `mongolian`, `space`, `vform`, `corner`, `neutral` or `combine`.
    pub kind: &'static str,
    /// What the slot shows, including an inserted hyphen.
    pub text: String,
    /// The source bytes the slot shows, excluding an inserted hyphen.
    pub start: usize,
    pub end: usize,
    pub graphemes: usize,
    /// The text ends in a hyphen the layout inserted, which has no source.
    pub hyphen: bool,
}

/// What a host draws for `input` under `flags`: the progression and each
/// column's slots, or `None` where the text is not one vertical strip (see
/// [`strip_layout`]) and the host should set it horizontally.
pub fn slots(input: &str, flags: u32) -> Option<(Progression, Vec<Vec<HostSlot>>)> {
    let progression = if flags & LEFT_TO_RIGHT != 0 {
        Progression::LeftToRight
    } else {
        Progression::RightToLeft
    };
    let (layout, map) = strip_layout(input, flags & CODE != 0, progression)?;
    let columns = layout.columns.iter().enumerate().map(|(c, column)| {
        column.slots.iter().enumerate().map(|(i, slot)| {
            let source = map.slot(c, i).expect("the source map covers every slot of its layout");
            HostSlot {
                kind: slot_kind(slot),
                text: slot.text().to_owned(),
                start: source.range.start,
                end: source.range.end,
                graphemes: source.graphemes(),
                hyphen: source.inserted_hyphen,
            }
        }).collect()
    }).collect();
    Some((layout.progression, columns))
}

fn push_json_string(out: &mut String, text: &str) {
    out.push('"');
    for ch in text.chars() {
        match ch {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            c if (c as u32) < 0x20 => out.push_str(&format!("\\u{:04x}", c as u32)),
            c => out.push(c),
        }
    }
    out.push('"');
}

/// [`slots`] as the JSON [`vertext_layout`] returns:
///
/// ```json
/// {"horizontal":false,"progression":"rl","columns":[[{"kind":"upright",
///  "text":"山","start":0,"end":3,"graphemes":1,"hyphen":false}]]}
/// ```
///
/// or `{"horizontal":true}`. Offsets are UTF-8 byte offsets into the input.
pub fn layout_json(input: &str, flags: u32) -> String {
    let Some((progression, columns)) = slots(input, flags) else {
        return "{\"horizontal\":true}".to_owned();
    };
    let mut out = String::from("{\"horizontal\":false,\"progression\":");
    out.push_str(match progression {
        Progression::RightToLeft => "\"rl\"",
        Progression::LeftToRight => "\"lr\"",
    });
    out.push_str(",\"columns\":[");
    for (c, column) in columns.iter().enumerate() {
        if c > 0 {
            out.push(',');
        }
        out.push('[');
        for (i, slot) in column.iter().enumerate() {
            if i > 0 {
                out.push(',');
            }
            out.push_str("{\"kind\":\"");
            out.push_str(slot.kind);
            out.push_str("\",\"text\":");
            push_json_string(&mut out, &slot.text);
            out.push_str(&format!(",\"start\":{},\"end\":{},\"graphemes\":{},\"hyphen\":{}}}",
                                  slot.start, slot.end, slot.graphemes, slot.hyphen));
        }
        out.push(']');
    }
    out.push_str("]}");
    out
}

static VERSION: &str = concat!(env!("CARGO_PKG_VERSION"), "\0");

/// The crate version, NUL-terminated and static, for the binding's handshake.
#[unsafe(no_mangle)]
pub extern "C" fn vertext_version() -> *const c_char {
    VERSION.as_ptr().cast()
}

/// Lay out `len` bytes of UTF-8 at `input` and return [`layout_json`] in a
/// new buffer, its length written to `out_len`. Input that is not UTF-8
/// returns null and writes 0, and so does a layout that panics: a panic may
/// not unwind out of an `extern "C"` function, where it would abort the host
/// process with it. Release the buffer with [`vertext_free`].
///
/// # Safety
/// `input` must address `len` initialized bytes, or be null with `len` 0, and
/// `out_len` must be valid for a write.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn vertext_layout(input: *const u8, len: usize, flags: u32,
                                        out_len: *mut usize) -> *mut u8 {
    let bytes = if len == 0 { &[][..] } else { unsafe { std::slice::from_raw_parts(input, len) } };
    let Ok(text) = std::str::from_utf8(bytes) else {
        unsafe { *out_len = 0 };
        return std::ptr::null_mut();
    };
    unsafe { export(|| layout_json(text, flags), out_len) }
}

/// Run `json` and hand its bytes over as [`vertext_layout`] does, or null and
/// 0 if it panics.
///
/// # Safety
/// `out_len` must be valid for a write.
unsafe fn export(json: impl FnOnce() -> String + std::panic::UnwindSafe,
                 out_len: *mut usize) -> *mut u8 {
    let Ok(json) = std::panic::catch_unwind(json) else {
        unsafe { *out_len = 0 };
        return std::ptr::null_mut();
    };
    let json = json.into_bytes().into_boxed_slice();
    unsafe { *out_len = json.len() };
    Box::into_raw(json).cast()
}

/// Release a buffer [`vertext_layout`] returned.
///
/// # Safety
/// `pointer` and `len` must be exactly a buffer and length [`vertext_layout`]
/// returned, released once. Null is ignored.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn vertext_free(pointer: *mut u8, len: usize) {
    if !pointer.is_null() {
        drop(unsafe { Box::from_raw(std::ptr::slice_from_raw_parts_mut(pointer, len)) });
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use vertext_html::{render_document, RenderOptions};

    /// The hard hyphen the layout appends to a piece of a long word.
    const INSERTED_HYPHEN: char = '\u{2010}';

    const MIXED: &str = "山川异域，风月同天。\n「寄诸佛子」 共结来缘\nᠮᠣᠩᠭᠣᠯ\u{202F}ᠤᠨ ᠪᠠᠶᠢᠨ\u{180E}ᠠ᠃";

    fn call(input: &[u8], flags: u32) -> Option<Vec<u8>> {
        let mut len = usize::MAX;
        let pointer = unsafe { vertext_layout(input.as_ptr(), input.len(), flags, &mut len) };
        if pointer.is_null() {
            assert_eq!(len, 0);
            return None;
        }
        let out = unsafe { std::slice::from_raw_parts(pointer, len) }.to_vec();
        unsafe { vertext_free(pointer, len) };
        Some(out)
    }

    #[test]
    fn the_export_returns_layout_json() {
        for flags in [0, CODE, LEFT_TO_RIGHT, CODE | LEFT_TO_RIGHT] {
            assert_eq!(call(MIXED.as_bytes(), flags).unwrap(), layout_json(MIXED, flags).as_bytes());
        }
        assert_eq!(call(b"", 0).unwrap(), layout_json("", 0).as_bytes());
    }

    #[test]
    fn input_that_is_not_utf8_returns_null() {
        assert!(call(&[0xe5, 0xb1], 0).is_none());
    }

    #[test]
    fn a_layout_that_panics_returns_null_instead_of_unwinding() {
        let mut len = usize::MAX;
        let pointer = unsafe { export(|| panic!("a layout that fails"), &mut len) };
        assert!(pointer.is_null());
        assert_eq!(len, 0);
    }

    #[test]
    fn the_version_export_is_the_crate_version() {
        let version = unsafe { std::ffi::CStr::from_ptr(vertext_version()) };
        assert_eq!(version.to_str().unwrap(), env!("CARGO_PKG_VERSION"));
    }

    /// The kinds and texts are the spans the page draws for the same input,
    /// column by column: a host painting these slots paints what the CLI
    /// renders. Read back from the bytes the export returns, so the JSON
    /// writing is on the path too: a character it drops is a slot that no
    /// longer matches its span.
    #[test]
    fn the_slots_are_the_spans_the_page_draws() {
        for flags in [0, CODE, LEFT_TO_RIGHT] {
            let html = render_document(MIXED, RenderOptions {
                whole_strip_code: flags & CODE != 0,
                page: false,
                progression: if flags & LEFT_TO_RIGHT != 0 {
                    Progression::LeftToRight
                } else {
                    Progression::RightToLeft
                },
            });
            let page: Vec<Vec<(String, String)>> = html.split("<div class=\"vertext-column")
                .skip(1)
                .map(|column| {
                    let mut spans = Vec::new();
                    let mut rest = column.split("</div>").next().unwrap();
                    while let Some(at) = rest.find("<span class=\"vertext-") {
                        rest = &rest[at + "<span class=\"vertext-".len()..];
                        let (kind, after) = rest.split_once("\">").unwrap();
                        let (body, after) = after.split_once("</span>").unwrap();
                        spans.push((kind.to_owned(), body.to_owned()));
                        rest = after;
                    }
                    spans
                })
                .collect();
            let json: serde_json::Value =
                serde_json::from_slice(&call(MIXED.as_bytes(), flags).unwrap()).unwrap();
            let drawn: Vec<Vec<(String, String)>> = json["columns"].as_array().unwrap().iter()
                .map(|column| column.as_array().unwrap().iter()
                    .map(|slot| (slot["kind"].as_str().unwrap().to_owned(),
                                 slot["text"].as_str().unwrap().to_owned()))
                    .collect())
                .collect();
            assert_eq!(drawn, page, "flags {flags}");
        }
    }

    #[test]
    fn every_slot_shows_its_own_source() {
        let long = "山 internationalization 川";
        for (input, flags) in [(MIXED, 0), (MIXED, CODE), (long, 0)] {
            let (_, columns) = slots(input, flags).unwrap();
            let mut last = 0;
            for slot in columns.iter().flatten() {
                assert!(slot.start >= last, "{slot:?}");
                let shown = if slot.hyphen {
                    slot.text.strip_suffix(INSERTED_HYPHEN).unwrap()
                } else {
                    &slot.text
                };
                assert_eq!(&input[slot.start..slot.end], shown, "{slot:?}");
                last = slot.end;
            }
        }
        let (_, columns) = slots(long, 0).unwrap();
        assert!(columns.iter().flatten().any(|s| s.hyphen), "the long word is split");
    }

    #[test]
    fn the_progression_is_reported_not_assumed() {
        assert!(layout_json(MIXED, 0).contains("\"progression\":\"rl\""));
        assert!(layout_json(MIXED, LEFT_TO_RIGHT).contains("\"progression\":\"lr\""));
    }

    #[test]
    fn text_that_is_not_one_vertical_strip_says_so() {
        assert_eq!(layout_json("this paragraph is plainly English and goes horizontal", 0),
                   "{\"horizontal\":true}");
        assert_eq!(layout_json("\u{E002}標題\u{E001}正文", 0), "{\"horizontal\":true}");
    }

    #[test]
    fn strings_are_escaped_as_json() {
        let mut out = String::new();
        push_json_string(&mut out, "a\"b\\c\u{1}d");
        assert_eq!(out, "\"a\\\"b\\\\c\\u0001d\"");
    }
}
