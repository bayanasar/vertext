//! Where every slot came from, and how a caret moves between the source and
//! the layout.
//!
//! A [`Slot`] carries what it shows, not where that text was. Anything that
//! lets a reader put a caret in vertical text needs both directions: a click on
//! a slot has to become a source offset, and a source offset (a search hit, a
//! selection, a cursor restored after an edit) has to become a slot. A map in
//! one direction cannot edit anything.
//!
//! How far this goes is decided by where line breaking lives. The host breaks
//! columns into visual lines, because only the host has font metrics, so the
//! geometry here is the relative one: which column, which slot within it, and
//! which grapheme within that slot. Absolute positions on a page are the
//! host's to compute from those.
//!
//! The map is built by walking the layout's slots over the source it was laid
//! out from. That works because layout never alters a character: every slot's
//! text is its source text, every column boundary is one source line break,
//! and the single exception is the hard hyphen [`layout_text`] adds when it
//! splits a long word with no hyphen of its own. A layout that does not line up
//! with the text is refused rather than guessed at.
//!
//! [`layout_text`]: crate::layout_text

use std::fmt;
use std::ops::Range;

use unicode_segmentation::UnicodeSegmentation;

use crate::{Layout, LayoutConfig, Slot};

/// The hard hyphen [`crate::layout_text`] appends to a piece of a long word.
const INSERTED_HYPHEN: char = '\u{2010}';

/// The source of one slot.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SlotSource {
    /// The slot's column, in source order.
    pub column: usize,
    /// The slot's position within its column.
    pub index: usize,
    /// The bytes of the laid-out text this slot shows.
    pub range: Range<usize>,
    /// The slot ends in a hyphen the layout inserted to split a long word.
    /// That character has no source bytes and no caret position.
    pub inserted_hyphen: bool,
    /// The source offset of every grapheme boundary in the slot, from
    /// `range.start` to `range.end` inclusive.
    boundaries: Vec<usize>,
}

impl SlotSource {
    /// How many source graphemes the slot holds. A Mongolian run is one slot
    /// and many graphemes, and a caret can stand between any two of them.
    pub fn graphemes(&self) -> usize {
        self.boundaries.len() - 1
    }
}

/// A caret: before grapheme `grapheme` of slot `index` in `column`.
///
/// `grapheme` may equal the slot's grapheme count only for the last slot of a
/// column, meaning the end of that column. Everywhere else the position after
/// one slot is written as the start of the next, so each source offset has one
/// caret. A column with no slots has the single caret `index: 0, grapheme: 0`.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub struct Caret {
    pub column: usize,
    pub index: usize,
    pub grapheme: usize,
}

/// The two-way map between a text and its [`Layout`].
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SourceMap {
    slots: Vec<SlotSource>,
    /// Per column: its source bytes, excluding the line break that ends it,
    /// and the position of its first slot in `slots`.
    columns: Vec<(Range<usize>, usize)>,
}

/// A layout that is not the layout of the text it was paired with.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SourceMapError {
    pub column: usize,
    /// The slot that did not match, or `None` where a line break or the end
    /// of the text was expected.
    pub index: Option<usize>,
    pub offset: usize,
}

impl fmt::Display for SourceMapError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self.index {
            Some(index) => write!(f, "slot {index} of column {} does not match the text at byte {}",
                                  self.column, self.offset),
            None => write!(f, "column {} does not end where the text breaks a line (byte {})",
                           self.column, self.offset),
        }
    }
}

impl std::error::Error for SourceMapError {}

fn slot_text(slot: &Slot) -> &str {
    match slot {
        Slot::Upright(s) | Slot::LatinWord(s) | Slot::MongolianRun(s) | Slot::Space(s)
        | Slot::VerticalPunctuation(s) | Slot::CornerPunctuation(s) | Slot::Neutral(s) => s,
    }
}

/// Lays `input` out and maps the result back onto it.
pub fn layout_with_source_map(input: &str, config: &LayoutConfig) -> (Layout, SourceMap) {
    let layout = crate::layout_text(input, config);
    let map = source_map(input, &layout)
        .expect("layout_text altered a character of its own input");
    (layout, map)
}

/// Maps `layout`, which must be the layout of `input`, back onto `input`.
pub fn source_map(input: &str, layout: &Layout) -> Result<SourceMap, SourceMapError> {
    let mut slots = Vec::new();
    let mut columns = Vec::with_capacity(layout.columns.len());
    let mut cursor = 0;
    for (c, column) in layout.columns.iter().enumerate() {
        if c > 0 {
            // One line break ends the previous column: "\r\n" is one cluster.
            match input[cursor..].graphemes(true).next() {
                Some(br @ ("\n" | "\r" | "\r\n")) => cursor += br.len(),
                _ => return Err(SourceMapError { column: c - 1, index: None, offset: cursor }),
            }
        }
        let start = cursor;
        let first_slot = slots.len();
        for (i, slot) in column.slots.iter().enumerate() {
            let text = slot_text(slot);
            let rest = &input[cursor..];
            let (length, inserted_hyphen) = if rest.starts_with(text) {
                (text.len(), false)
            } else {
                match text.strip_suffix(INSERTED_HYPHEN) {
                    Some(word) if matches!(slot, Slot::LatinWord(_)) && rest.starts_with(word) =>
                        (word.len(), true),
                    _ => return Err(SourceMapError { column: c, index: Some(i), offset: cursor }),
                }
            };
            let range = cursor..cursor + length;
            let boundaries = input[range.clone()]
                .grapheme_indices(true)
                .map(|(offset, _)| cursor + offset)
                .chain(std::iter::once(range.end))
                .collect();
            slots.push(SlotSource { column: c, index: i, range, inserted_hyphen, boundaries });
            cursor += length;
        }
        columns.push((start..cursor, first_slot));
    }
    if cursor != input.len() {
        return Err(SourceMapError {
            column: layout.columns.len().saturating_sub(1),
            index: None,
            offset: cursor,
        });
    }
    Ok(SourceMap { slots, columns })
}

impl SourceMap {
    /// Every slot's source, in source order.
    pub fn slots(&self) -> &[SlotSource] {
        &self.slots
    }

    /// How many columns the layout has, including columns with no slots.
    pub fn columns(&self) -> usize {
        self.columns.len()
    }

    /// The source of slot `index` in `column`.
    pub fn slot(&self, column: usize, index: usize) -> Option<&SlotSource> {
        let (_, first) = self.columns.get(column)?;
        let found = self.slots.get(first + index)?;
        (found.column == column).then_some(found)
    }

    /// The slot that shows the byte at `offset`, if any. Line breaks belong to
    /// no slot.
    pub fn slot_at(&self, offset: usize) -> Option<&SlotSource> {
        let at = self.slots.partition_point(|s| s.range.end <= offset);
        self.slots.get(at).filter(|s| s.range.start <= offset)
    }

    /// The caret at source offset `offset`, or `None` if `offset` is not a
    /// grapheme boundary of the text or falls inside a line break.
    pub fn caret(&self, offset: usize) -> Option<Caret> {
        let column = self.columns.partition_point(|(range, _)| range.end < offset);
        let (range, first) = self.columns.get(column)?;
        if offset < range.start {
            return None;
        }
        let in_column = &self.slots[*first..*first + self.slot_count(column)];
        let Some(last) = in_column.last() else {
            return (offset == range.start).then_some(Caret { column, index: 0, grapheme: 0 });
        };
        if offset == range.end {
            return Some(Caret { column, index: last.index, grapheme: last.graphemes() });
        }
        let slot = &in_column[in_column.partition_point(|s| s.range.end <= offset)];
        let grapheme = slot.boundaries.binary_search(&offset).ok()?;
        Some(Caret { column, index: slot.index, grapheme })
    }

    /// The source offset of `caret`, or `None` if no such caret exists.
    pub fn offset(&self, caret: Caret) -> Option<usize> {
        let (range, _) = self.columns.get(caret.column)?;
        if self.slot_count(caret.column) == 0 {
            return (caret.index == 0 && caret.grapheme == 0).then_some(range.start);
        }
        self.slot(caret.column, caret.index)?.boundaries.get(caret.grapheme).copied()
    }

    fn slot_count(&self, column: usize) -> usize {
        let (_, first) = self.columns[column];
        let next = self.columns.get(column + 1).map_or(self.slots.len(), |(_, f)| *f);
        next - first
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::layout_text;

    /// Shapes the layout treats specially, each of which could put a slot's
    /// bytes somewhere other than where the walk expects them.
    const CASES: &[&str] = &[
        "",
        "\n",
        "山川异域，风月同天。寄诸佛子，共结来缘。",
        "第一行\r\n\r\n第三行\n",
        "ᠮᠣᠩᠭᠣᠯ\u{202F}ᠤᠨ ᠨᠣᠮ᠃",
        "ᠢᠢ\u{202F}is written",
        "ᠢᠢ\u{202F}",
        "ᠨᠡᠷ\u{180E}ᠡ ᠪᠠᠶᠢᠨ\u{180E}ᠠ ᠤᠤ?",
        "ᠠ\u{180B}ᠳ",
        "ᠰᠠᠶᠢᠨ(sayin) good",
        "sayin(ᠰᠠᠶᠢᠨ) good",
        "kedU(n) gerel.net min-U yabun_a uu/UU",
        "= ᠬ",
        "词尾(n)形式",
        "internationalization is a long word",
        "use-after-free",
        "e\u{0301}cole स\u{094D}त 葛\u{FE00}城",
        "👩\u{200D}💻 codes",
        "(mongɣol-un) čaγan Монгол хэл",
        "  indented\ttab",
    ];

    fn maps(text: &str) -> (Layout, SourceMap) {
        let config = LayoutConfig::default();
        let layout = layout_text(text, &config);
        let map = source_map(text, &layout).unwrap_or_else(|e| panic!("{text:?}: {e}"));
        (layout, map)
    }

    #[test]
    fn every_slot_maps_to_the_bytes_it_shows() {
        for text in CASES {
            let (layout, map) = maps(text);
            let laid: Vec<&Slot> = layout.columns.iter().flat_map(|c| c.slots.iter()).collect();
            assert_eq!(map.slots().len(), laid.len(), "{text:?}");
            let mut covered = 0;
            for (source, slot) in map.slots().iter().zip(laid) {
                let shown = slot_text(slot);
                let expected = if source.inserted_hyphen {
                    shown.strip_suffix(INSERTED_HYPHEN).unwrap()
                } else {
                    shown
                };
                assert_eq!(&text[source.range.clone()], expected, "{text:?} {source:?}");
                assert_eq!(map.slot(source.column, source.index), Some(source));
                assert!(source.range.start >= covered, "{text:?}: slots out of order");
                covered += source.range.len();
            }
            // Everything not in a slot is a line break, one per column boundary.
            let breaks: usize = text.graphemes(true)
                .filter(|g| matches!(*g, "\n" | "\r" | "\r\n")).map(str::len).sum();
            assert_eq!(covered + breaks, text.len(), "{text:?}");
            assert_eq!(layout.columns.len(), text.graphemes(true)
                .filter(|g| matches!(*g, "\n" | "\r" | "\r\n")).count() + 1, "{text:?}");
        }
    }

    #[test]
    fn every_grapheme_boundary_round_trips_through_a_caret() {
        for text in CASES {
            let (_, map) = maps(text);
            let mut offsets: Vec<usize> = text.grapheme_indices(true).map(|(o, _)| o).collect();
            offsets.push(text.len());
            let breaks: Vec<Range<usize>> = text.grapheme_indices(true)
                .filter(|(_, g)| matches!(*g, "\n" | "\r" | "\r\n"))
                .map(|(o, g)| o..o + g.len())
                .collect();
            let mut seen = std::collections::HashSet::new();
            for offset in offsets {
                let caret = map.caret(offset)
                    .unwrap_or_else(|| panic!("{text:?}: no caret at byte {offset}"));
                assert_eq!(map.offset(caret), Some(offset), "{text:?} {caret:?}");
                assert!(seen.insert(caret), "{text:?}: two offsets share {caret:?}");
            }
            // And a byte inside a line break, or inside a grapheme, has none.
            for br in breaks.iter().filter(|b| b.len() > 1) {
                assert_eq!(map.caret(br.start + 1), None, "{text:?}");
            }
        }
    }

    #[test]
    fn a_caret_can_stand_inside_a_mongolian_run() {
        // One slot, because the font must receive the word whole -- and nine
        // places a cursor can go, because a writer edits letters, not slots.
        let text = "ᠮᠣᠩᠭᠣᠯ\u{202F}ᠤᠨ";
        let (layout, map) = maps(text);
        assert_eq!(layout.columns[0].slots.len(), 1);
        let run = map.slot(0, 0).unwrap();
        assert_eq!(run.graphemes(), 9);
        let joint = text.find('\u{202F}').unwrap();
        assert_eq!(map.caret(joint), Some(Caret { column: 0, index: 0, grapheme: 6 }));
        assert_eq!(map.offset(Caret { column: 0, index: 0, grapheme: 7 }), Some(joint + 3));
        assert_eq!(map.slot_at(joint), Some(run));
    }

    #[test]
    fn an_inserted_hyphen_has_no_source_bytes() {
        let text = "internationalization";
        let (layout, map) = maps(text);
        assert!(layout.columns[0].slots.len() > 1);
        let first = map.slot(0, 0).unwrap();
        assert!(first.inserted_hyphen);
        assert_eq!(first.graphemes(), text[first.range.clone()].chars().count());
        // The position after the visible hyphen is the start of the next piece.
        assert_eq!(map.caret(first.range.end), Some(Caret { column: 0, index: 1, grapheme: 0 }));
        // A hyphen the author typed is source, and is not flagged.
        let (_, typed) = maps("use-after-free-and-then-some");
        assert!(typed.slots().iter().all(|s| !s.inserted_hyphen));
    }

    #[test]
    fn a_blank_line_is_a_column_with_one_caret() {
        let text = "上\n\n下";
        let (layout, map) = maps(text);
        assert_eq!(layout.columns[1].slots.len(), 0);
        assert_eq!(map.caret(text.find("\n\n").unwrap() + 1),
                   Some(Caret { column: 1, index: 0, grapheme: 0 }));
        assert_eq!(map.offset(Caret { column: 1, index: 0, grapheme: 1 }), None);
    }

    #[test]
    fn a_layout_of_another_text_is_refused() {
        let layout = layout_text("山川异域", &LayoutConfig::default());
        let error = source_map("山川異域", &layout).unwrap_err();
        assert_eq!(error, SourceMapError { column: 0, index: Some(2), offset: 6 });
        assert!(source_map("山川异域\n", &layout).is_err());
    }
}
