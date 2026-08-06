//! The host-independent part of Vertext.
//!
//! The one dependency is `unicode-segmentation` for UAX #29 grapheme cluster
//! boundaries. It is table-driven and `no_std`-capable, so it crosses
//! `wasm32` unchanged; hand-rolling cluster boundaries would produce exactly
//! the near-miss rendering this library exists to end.
//!
//! A host turns a [`Layout`] into HTML, a terminal preview, or a GPU scene. The
//! logical reading direction is always top-to-bottom and a source newline moves
//! to the column on its left.

use unicode_segmentation::UnicodeSegmentation;

/// Which way successive columns advance. This is a property of the *script*,
/// not of "vertical text": CJK columns advance right-to-left, traditional
/// Mongolian advances left-to-right. Hosts must read it from the [`Layout`]
/// rather than assuming a direction.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Progression {
    /// `vertical-rl`: `columns[0]` is the rightmost column (CJK).
    RightToLeft,
    /// `vertical-lr`: `columns[0]` is the leftmost column (Mongolian).
    LeftToRight,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct LayoutConfig {
    /// Maximum number of displayed characters in an upright Latin word slot.
    pub max_latin_word_width: usize,
    /// Code mode retains each source space as an empty vertical row.
    pub preserve_spaces: bool,
    /// Column advance direction, carried onto the produced [`Layout`].
    pub progression: Progression,
}

impl Default for LayoutConfig {
    fn default() -> Self {
        Self {
            max_latin_word_width: 12,
            preserve_spaces: false,
            progression: Progression::RightToLeft,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Layout {
    /// Columns are in source order; [`Layout::progression`] says which side
    /// `columns[0]` sits on.
    pub columns: Vec<Column>,
    /// Column advance direction. Data, never a constant.
    pub progression: Progression,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Column {
    pub slots: Vec<Slot>,
}

/// A whole document: a sequence of blocks that advance in one direction.
///
/// [`Layout`] is the vertical primitive — one run of text as columns of
/// slots. A document is more than that, because not everything in it wants to
/// be vertical. Latin-majority prose and program source read horizontally,
/// and a table is a grid. Those decisions belong here, as data, so that every
/// adapter reads the same answer instead of each inventing one.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Document {
    pub blocks: Vec<Block>,
    pub progression: Progression,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Block {
    /// Vertical columns of slots — CJK, Mongolian, mixed prose.
    Vertical(Layout),
    /// A run set horizontally, because setting it vertically would serve no
    /// reader: Latin-majority prose, and program source of any language.
    Horizontal(HorizontalBlock),
    /// A table. Rows become columns under a vertical progression, so a row
    /// reads top-to-bottom as one entry and successive rows advance the same
    /// way the surrounding text does.
    Table(Table),
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HorizontalBlock {
    pub text: String,
    /// Line length in characters. Line breaking itself is the host's job —
    /// a terminal, a browser, and a PDF measure text differently, and the
    /// core has no font metrics to break with honestly.
    pub wrap_columns: usize,
    pub kind: HorizontalKind,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum HorizontalKind {
    /// The measure: 45–75 characters, 66 the long-settled optimum.
    Prose,
    /// Program source. 80 is the narrower of Google's and Mozilla's C++
    /// limits; rustfmt allows 100.
    Code,
}

impl HorizontalKind {
    pub fn default_wrap(self) -> usize {
        match self {
            HorizontalKind::Prose => 66,
            HorizontalKind::Code => 80,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Table {
    pub rows: Vec<Row>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Row {
    /// Each cell is laid out as its own column of slots, so a Mongolian cell
    /// keeps its joined run and a Latin cell keeps its word slots.
    pub cells: Vec<Column>,
    pub header: bool,
}

/// Whether a run of text is better set horizontally than vertically.
///
/// The measure is **slots**, because a slot is what the layout actually
/// produces. One ideograph is one slot; one Latin *word* is also one slot,
/// however many letters it contains. Counting characters instead makes
/// romanization look like English: a Chinese sentence quoting `bi yabuqu
/// Ugei` has more Latin letters than Han characters while being, plainly, a
/// Chinese sentence — and it would be flipped horizontal by a character
/// count and left alone by a slot count.
///
/// This is why a language-teaching document is the honest test case. It is
/// dense with citation forms, and every one of them is a short word standing
/// in for a single idea, exactly like the character it glosses.
///
/// Punctuation and whitespace do not vote: they are shared by both systems,
/// and letting them vote would hand the decision to a comma-heavy sentence.
pub fn prefers_horizontal(text: &str) -> bool {
    let (mut vertical, mut horizontal) = (0usize, 0usize);
    let mut in_word = false;
    for cluster in text.graphemes(true) {
        let Some(base) = cluster.chars().next() else { continue };
        if is_cjk(base) {
            vertical += 1;
            in_word = false;
        } else if is_mongolian(base) {
            // A Mongolian run is one slot, so only its start counts.
            if !in_word {
                vertical += 1;
            }
            in_word = true;
        } else if is_word_char(base) || (in_word && is_word_connector(base)) {
            // A whole Latin word is one slot; count only where it begins.
            if !in_word {
                horizontal += 1;
            }
            in_word = true;
        } else {
            in_word = false;
        }
    }
    horizontal > vertical
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Slot {
    /// An upright ideograph, kana, or hangul grapheme cluster.
    Upright(String),
    /// One normal, horizontally readable Latin word in a vertical slot.
    LatinWord(String),
    /// Keep the run intact so a vertical-capable font can perform Mongolian
    /// joining and vertical substitutions.
    MongolianRun(String),
    /// Whitespace from the source, carried through verbatim so a copied
    /// paragraph matches what was written.
    Space(String),
    /// Punctuation that turns a quarter-circle in vertical text: brackets,
    /// quotes, colons, dashes, ellipses, slashes.
    ///
    /// The host rotates the *view*. It must never swap the character for a
    /// vertical presentation form (U+FE10–FE4F): those look correct and
    /// silently destroy the document, because copy-paste, find-in-page, and
    /// screen readers then yield codepoints the author never typed. A
    /// renderer may decide how text appears; the text itself is content, and
    /// content is not ours to edit.
    VerticalPunctuation(String),
    /// A stop or comma. These do not turn in vertical text — they move to the
    /// upper-right corner of their em square. Again a view-only change.
    CornerPunctuation(String),
    /// Punctuation and other unsupported scripts remain upright for now.
    Neutral(String),
}

/// Creates a top-to-bottom layout. Each source newline starts a new column to
/// the *left*. Whitespace separates Latin words but does not create an empty
/// slot. Long Latin words use predictable hard hyphens; dictionary hyphenation
/// is intentionally a host-configurable future enhancement.
///
/// The unit of layout is the UAX #29 extended grapheme cluster, not the
/// Unicode scalar. A variation selector must stay with the ideograph it
/// selects a glyph for, a combining mark with its base, and a ZWJ emoji
/// sequence with itself — split across slots they are silently dropped or
/// rendered as their unjoined parts, which looks like text and is not.
pub fn layout_text(input: &str, config: &LayoutConfig) -> Layout {
    let mut columns = vec![Column { slots: Vec::new() }];
    let mut latin_word = String::new();
    let mut mongolian_run = String::new();
    // Connectors seen with no word yet holding them. `-n_a` is one word, so a
    // leading mark waits to see whether letters follow; if they do it joins
    // them, and if they do not it becomes punctuation after all.
    let mut pending_connectors = String::new();

    let flush_latin = |columns: &mut Vec<Column>, word: &mut String| {
        if word.is_empty() { return; }
        for piece in split_latin_word(word, config.max_latin_word_width) {
            columns.last_mut().unwrap().slots.push(Slot::LatinWord(piece));
        }
        word.clear();
    };
    let flush_mongolian = |columns: &mut Vec<Column>, run: &mut String| {
        if !run.is_empty() {
            columns.last_mut().unwrap().slots.push(Slot::MongolianRun(std::mem::take(run)));
        }
    };

    // A cluster is classified by its base scalar — the first one. Trailing
    // marks, joiners, and variation selectors ride along with it.
    for cluster in input.graphemes(true) {
        let base = match cluster.chars().next() {
            Some(base) => base,
            None => continue,
        };
        if base == '\n' || base == '\r' {
            // "\r\n" is one cluster and must open one column, not two.
            flush_latin(&mut columns, &mut latin_word);
            flush_mongolian(&mut columns, &mut mongolian_run);
            flush_pending(&mut columns, &mut pending_connectors);
            columns.push(Column { slots: Vec::new() });
        } else if base.is_whitespace() {
            flush_latin(&mut columns, &mut latin_word);
            flush_mongolian(&mut columns, &mut mongolian_run);
            flush_pending(&mut columns, &mut pending_connectors);
            // The space is always kept. It is a character the author typed,
            // and dropping it means a copied paragraph comes back as
            // `可在gerel.net检索` — close enough to look fine and wrong to
            // quote. `preserve_spaces` now decides only whether the space is
            // made *visible* (code indentation), never whether it survives.
            columns.last_mut().unwrap().slots.push(Slot::Space(cluster.to_owned()));
        } else if is_mongolian(base) {
            flush_latin(&mut columns, &mut latin_word);
            // A connector still waiting for a word has just learned that no
            // Latin word is coming. It must be emitted *here*, before the
            // Mongolian run opens — left buffered it would surface when the
            // run flushes, and `= ᠬ` would come back as `ᠬ=`. Reordering
            // the author's characters is as wrong as replacing them.
            flush_pending(&mut columns, &mut pending_connectors);
            mongolian_run.push_str(cluster);
        } else if is_word_char(base) {
            flush_mongolian(&mut columns, &mut mongolian_run);
            latin_word.push_str(&std::mem::take(&mut pending_connectors));
            latin_word.push_str(cluster);
        } else if is_word_connector(base) {
            // Inside a word this mark is a letter: `min-U`, `kedU(n)`, and
            // `-n_a` are one word each. Held on either side by letters it
            // joins them; held by neither it is punctuation.
            if latin_word.is_empty() {
                pending_connectors.push_str(cluster);
            } else {
                latin_word.push_str(cluster);
            }
        } else {
            flush_latin(&mut columns, &mut latin_word);
            flush_mongolian(&mut columns, &mut mongolian_run);
            flush_pending(&mut columns, &mut pending_connectors);
            let slot = if is_corner_punctuation(base) {
                Slot::CornerPunctuation(cluster.to_owned())
            } else if has_vertical_form(base) {
                Slot::VerticalPunctuation(cluster.to_owned())
            } else if is_cjk(base) {
                Slot::Upright(cluster.to_owned())
            } else {
                Slot::Neutral(cluster.to_owned())
            };
            columns.last_mut().unwrap().slots.push(slot);
        }
    }
    flush_latin(&mut columns, &mut latin_word);
    flush_mongolian(&mut columns, &mut mongolian_run);
    flush_pending(&mut columns, &mut pending_connectors);
    Layout { columns, progression: config.progression }
}

/// Emits buffered connectors that never found a word to join.
fn flush_pending(columns: &mut Vec<Column>, pending: &mut String) {
    if pending.is_empty() { return; }
    for cluster in std::mem::take(pending).graphemes(true) {
        let base = cluster.chars().next().unwrap_or(' ');
        let slot = if is_corner_punctuation(base) {
            Slot::CornerPunctuation(cluster.to_owned())
        } else if has_vertical_form(base) {
            Slot::VerticalPunctuation(cluster.to_owned())
        } else {
            Slot::Neutral(cluster.to_owned())
        };
        columns.last_mut().unwrap().slots.push(slot);
    }
}

/// Splits on grapheme-cluster boundaries so a hard hyphen can never land
/// between a base letter and its combining mark.
fn split_latin_word(word: &str, limit: usize) -> Vec<String> {
    let limit = limit.max(2);
    let clusters: Vec<&str> = word.graphemes(true).collect();
    if clusters.len() <= limit { return vec![word.to_owned()]; }
    let payload = limit - 1;
    clusters.chunks(payload).enumerate().map(|(i, chunk)| {
        let mut piece: String = chunk.concat();
        if (i + 1) * payload < clusters.len() { piece.push('‐'); }
        piece
    }).collect()
}

fn is_mongolian(ch: char) -> bool { matches!(ch as u32, 0x1800..=0x18AF | 0x11660..=0x1167F) }
fn is_cjk(ch: char) -> bool { matches!(ch as u32,
    0x3400..=0x4DBF | 0x4E00..=0x9FFF | 0xF900..=0xFAFF |
    0x3040..=0x30FF | 0x31F0..=0x31FF | 0xAC00..=0xD7AF
) }
fn is_latin(ch: char) -> bool { matches!(ch as u32,
    0x0041..=0x005A | 0x0061..=0x007A | 0x00C0..=0x024F | 0x1E00..=0x1EFF
) }
fn is_word_char(ch: char) -> bool { is_latin(ch) || ch.is_ascii_digit() || ch == '_' }

/// Punctuation that behaves as a letter when it sits inside a word.
///
/// `min-U`, `kedU(n)`, `yabun_a`, `gerel.net`, `uu/UU` are single words, not a
/// word and a mark and another word. Mongolian romanization uses these the way
/// bichig uses the MVS and NNBSP: they join what is on either side, and
/// splitting them puts a rotated bracket in the middle of a citation form.
///
/// Standing alone — with a space or an ideograph on the left — the same
/// characters are ordinary punctuation and take a vertical form. So the class
/// is contextual, and only the context decides.
fn is_word_connector(ch: char) -> bool {
    // `/` and `\` are deliberately absent: a slash separates alternatives
    // (`uu/UU`, `ᠤ/ᠦ/ᠥ`) and each alternative wants its own row, so the slash
    // breaks the word rather than joining it.
    matches!(ch, ':' | '"' | '\'' | '(' | ')' | '{' | '}' |
        '=' | '<' | '>' | '[' | ']' | '|' | '-' | '.' | '+' | '_')
}
/// Punctuation that has a distinct vertical presentation form.
///
/// Two families, one treatment. Brackets and quotes have compatibility forms
/// in U+FE30–FE44; CJK commas, stops, colons, dashes, and ellipses have
/// presentation forms in U+FE10–FE19. Both are reached the same way — a
/// vertical writing mode plus the font's `vert`/`vrt2` feature — so both are
/// classified together and the font decides. A stop is repositioned into the
/// corner of its em square; a dash and a colon genuinely rotate. Which of
/// those happens is the font's business, not ours.
///
/// Bare ASCII stays out. A colon in `a:b` must not rotate, and code and
/// romanization are full of them; the fullwidth `：` in Chinese prose is a
/// different character with different typography, and it is the one that
/// wants the vertical form.
/// Stops and commas, which reposition rather than rotate.
fn is_corner_punctuation(ch: char) -> bool {
    // The semicolon sits with the comma and the stop: they are all clause
    // separators and behave as a family, so treating one of them differently
    // makes a sentence look mis-set.
    matches!(ch, '，' | '、' | '。' | '．' | '｡' | '､' | '；' | ';')
}

fn has_vertical_form(ch: char) -> bool {
    matches!(ch,
        // Brackets, quotes, and the ASCII marks that stand between clauses.
        // These reach here only when they are NOT inside a word — see
        // `is_word_connector`, which claims them first when letters surround
        // them.
        '(' | ')' | '[' | ']' | '{' | '}' | '<' | '>' |
        ':' | '"' | '\'' | '=' | '|' |
        // Arrows point along the text. In a vertical column "onward" is
        // downward, so a horizontally-pointing arrow has to turn to keep
        // meaning what it meant. Vertical arrows already point along the
        // flow and are left alone — turning them would aim them sideways.
        '→' | '←' | '↔' | '⇒' | '⇐' | '⇔' | '⟶' | '⟵' | '⟷' |
        '➔' | '➜' | '➝' | '➞' | '⇢' | '⇠' | '↦' | '↤' | '⊸' |
        '（' | '）' | '［' | '］' | '｛' | '｝' |
        '〈' | '〉' | '《' | '》' | '「' | '」' | '『' | '』' |
        '【' | '】' | '〔' | '〕' | '“' | '”' | '‘' | '’' |
        // Separators that genuinely turn. Stops, commas, and semicolons are
        // handled by `is_corner_punctuation`; `！` and `？` stay upright.
        '：' |
        // Dashes, ellipses, and connectors that run along the column.
        '—' | '―' | '－' | '…' | '‥' | '〜' | '～' | '｜' | '‖')
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn a_newline_creates_the_column_to_the_left() {
        let layout = layout_text("中文\n日本", &LayoutConfig::default());
        assert_eq!(layout.columns.len(), 2);
        assert_eq!(layout.columns[0].slots, vec![Slot::Upright("中".into()), Slot::Upright("文".into())]);
    }
    #[test]
    fn long_latin_words_are_bounded() {
        let layout = layout_text("textremificationalization", &LayoutConfig::default());
        assert!(layout.columns[0].slots.iter().all(|slot| match slot { Slot::LatinWord(s) => s.chars().count() <= 12, _ => true }));
    }
    #[test]
    fn punctuation_with_a_vertical_form_gets_its_own_slot() {
        let layout = layout_text("()", &LayoutConfig::default());
        assert_eq!(layout.columns[0].slots, vec![
            Slot::VerticalPunctuation("(".into()),
            Slot::VerticalPunctuation(")".into()),
        ]);
    }
    /// Stops and commas move to the corner of their em square; dashes and
    /// ellipses turn. Two different treatments, and neither is a rotation of
    /// the whole line or a change to the characters.
    /// Semicolons keep company with commas and stops; arrows turn because a
    /// horizontal arrow must keep pointing "onward" when onward is downward;
    /// a vertical arrow already does and is left alone.
    /// The punctuation contract, pinned character by character.
    ///
    /// This table is the agreement, not a sample of it. Every mark below was
    /// decided deliberately and this classification has already churned more
    /// than once — so it is written out in full and any change to it fails
    /// here, loudly, instead of quietly altering how someone's document is
    /// set. If a mark genuinely needs to move, move it *here first*.
    #[test]
    fn the_punctuation_contract() {
        // Turns a quarter-circle. Brackets, quotes, colons, dashes, ellipses,
        // and the ASCII operators that stand between clauses.
        for mark in ['(', ')', '[', ']', '{', '}', '<', '>', ':', '"', '\'',
                     '=', '|',
                     '（', '）', '［', '］', '｛', '｝', '〈', '〉', '《', '》',
                     '「', '」', '『', '』', '【', '】', '〔', '〕',
                     '“', '”', '‘', '’', '：',
                     '—', '―', '－', '…', '‥', '〜', '～', '｜', '‖',
                     '→', '←', '↔', '⇒', '⇐', '⇔', '⟶', '⟵'] {
            let layout = layout_text(&format!("好{mark}好"), &LayoutConfig::default());
            assert_eq!(layout.columns[0].slots[1],
                Slot::VerticalPunctuation(mark.to_string()),
                "{mark:?} must turn");
        }
        // Sits in the corner of its em square. Clause separators travel as a
        // family; splitting one off makes a sentence look mis-set.
        for mark in ['，', '、', '。', '．', '｡', '､', '；', ';'] {
            let layout = layout_text(&format!("好{mark}好"), &LayoutConfig::default());
            assert_eq!(layout.columns[0].slots[1],
                Slot::CornerPunctuation(mark.to_string()),
                "{mark:?} must go to the corner");
        }
        // Stays upright. A turned slash reads as a backslash; `↑`/`↓` already
        // point along the flow; `！`/`？` are upright by convention.
        for mark in ['/', '\\', '↑', '↓', '↕', '！', '？', '!', '?', '+', '*', '%'] {
            let layout = layout_text(&format!("好{mark}好"), &LayoutConfig::default());
            assert_eq!(layout.columns[0].slots[1],
                Slot::Neutral(mark.to_string()),
                "{mark:?} must stay upright");
        }
    }

    #[test]
    fn separators_and_arrows_are_classified_by_behaviour() {
        let layout = layout_text("好；天→月↓日/水", &LayoutConfig::default());
        assert_eq!(layout.columns[0].slots, vec![
            Slot::Upright("好".into()),
            Slot::CornerPunctuation("；".into()),
            Slot::Upright("天".into()),
            Slot::VerticalPunctuation("→".into()),
            Slot::Upright("月".into()),
            Slot::Neutral("↓".into()),
            Slot::Upright("日".into()),
            Slot::Neutral("/".into()),
            Slot::Upright("水".into()),
        ]);
    }
    #[test]
    fn stops_go_to_the_corner_and_dashes_turn() {
        let layout = layout_text("好，天。—…", &LayoutConfig::default());
        assert_eq!(layout.columns[0].slots, vec![
            Slot::Upright("好".into()),
            Slot::CornerPunctuation("，".into()),
            Slot::Upright("天".into()),
            Slot::CornerPunctuation("。".into()),
            Slot::VerticalPunctuation("—".into()),
            Slot::VerticalPunctuation("…".into()),
        ]);
    }
    #[test]
    fn underscores_and_digits_stay_in_a_latin_identifier() {
        let layout = layout_text("hi_nancy v2", &LayoutConfig::default());
        assert_eq!(layout.columns[0].slots, vec![
            Slot::LatinWord("hi_nancy".into()),
            Slot::Space(" ".into()),
            Slot::LatinWord("v2".into()),
        ]);
    }
    /// Golden: the README's own sample. Every scalar accounted for, in order.
    #[test]
    fn golden_shanchuan_yiyu() {
        let layout = layout_text("山川异域，风月同天。", &LayoutConfig::default());
        assert_eq!(layout.progression, Progression::RightToLeft);
        assert_eq!(layout.columns.len(), 1);
        let expected: Vec<Slot> = "山川异域"
            .chars()
            .map(|c| Slot::Upright(c.to_string()))
            .chain([Slot::CornerPunctuation("，".into())])
            .chain("风月同天".chars().map(|c| Slot::Upright(c.to_string())))
            .chain([Slot::CornerPunctuation("。".into())])
            .collect();
        assert_eq!(layout.columns[0].slots, expected);
    }
    /// A variation selector selects which glyph the font draws for an
    /// ideograph. Split into its own slot it selects nothing and the reader
    /// gets the wrong form of a character in someone's name.
    #[test]
    fn a_variation_selector_stays_with_its_ideograph() {
        let layout = layout_text("葛\u{FE00}城", &LayoutConfig::default());
        assert_eq!(layout.columns[0].slots, vec![
            Slot::Upright("葛\u{FE00}".into()),
            Slot::Upright("城".into()),
        ]);
    }
    #[test]
    fn combining_marks_stay_with_their_base() {
        // Devanagari स + virama + त is one cluster; e + combining acute is one
        // Latin grapheme inside a word.
        let layout = layout_text("स\u{094D}त e\u{0301}cole", &LayoutConfig::default());
        assert_eq!(layout.columns[0].slots, vec![
            Slot::Neutral("स\u{094D}त".into()),
            Slot::Space(" ".into()),
            Slot::LatinWord("e\u{0301}cole".into()),
        ]);
    }
    #[test]
    fn zwj_and_flag_sequences_are_one_slot_each() {
        let layout = layout_text("🇯🇵👨\u{200D}👩\u{200D}👧", &LayoutConfig::default());
        assert_eq!(layout.columns[0].slots, vec![
            Slot::Neutral("🇯🇵".into()),
            Slot::Neutral("👨\u{200D}👩\u{200D}👧".into()),
        ]);
    }
    #[test]
    fn a_hard_hyphen_never_splits_a_cluster() {
        // Twelve clusters, each a base plus a combining acute: the cap counts
        // clusters, so no piece may end mid-cluster.
        let word = "e\u{0301}".repeat(14);
        let layout = layout_text(&word, &LayoutConfig::default());
        for slot in &layout.columns[0].slots {
            let Slot::LatinWord(piece) = slot else { panic!("expected Latin slots") };
            assert!(!piece.starts_with('\u{0301}'), "piece begins with an orphaned mark: {piece:?}");
            assert!(piece.graphemes(true).count() <= 12);
        }
    }
    #[test]
    fn a_crlf_newline_opens_one_column() {
        let layout = layout_text("中\r\n日", &LayoutConfig::default());
        assert_eq!(layout.columns.len(), 2);
        assert_eq!(layout.columns[1].slots, vec![Slot::Upright("日".into())]);
    }
    #[test]
    fn orientation_is_decided_by_ink_not_character_count() {
        // Four ideographs outweigh three Latin words, because they carry more
        // of the line. A naive character count would call this horizontal.
        assert!(!prefers_horizontal("山川异域 the of and"));
        assert!(prefers_horizontal("It is a truth universally acknowledged"));
        assert!(!prefers_horizontal("春はあけぼの。やうやう白くなりゆく"));
        // A few Latin words inside CJK stay vertical.
        assert!(!prefers_horizontal("この API は便利です"));
        // Mongolian is a vertical script and must never be called horizontal.
        assert!(!prefers_horizontal("ᠮᠣᠩᠭᠤᠯ ᠤᠯᠤᠰ"));
        // Program source is Latin-majority.
        assert!(prefers_horizontal("fn main() { println!(\"hi\"); }"));
    }
    #[test]
    fn punctuation_alone_does_not_decide_orientation() {
        // No letters at all: nothing votes, so it stays vertical by default.
        assert!(!prefers_horizontal("，。、；：！？"));
        assert!(!prefers_horizontal("...,,,;;;"));
    }
    #[test]
    fn horizontal_kinds_carry_their_conventional_measures() {
        assert_eq!(HorizontalKind::Prose.default_wrap(), 66);
        assert_eq!(HorizontalKind::Code.default_wrap(), 80);
    }
    #[test]
    fn a_mark_between_letters_is_part_of_the_word() {
        // `min-U`, `kedU(n)`, `gerel.net` are single citation forms. Splitting
        // them drops a rotated bracket into the middle of a word.
        let layout = layout_text("min-U kedU(n) gerel.net a=b:c", &LayoutConfig::default());
        let words: Vec<&Slot> = layout.columns[0].slots.iter()
            .filter(|slot| !matches!(slot, Slot::Space(_))).collect();
        assert_eq!(words, vec![
            &Slot::LatinWord("min-U".into()),
            &Slot::LatinWord("kedU(n)".into()),
            &Slot::LatinWord("gerel.net".into()),
            &Slot::LatinWord("a=b:c".into()),
        ]);
    }
    /// A mark with letters on the right joins them too: `-n_a` is one word.
    /// The invariant that matters most: layout never edits the text. Every
    /// slot concatenated back together, in order, must equal the source with
    /// only whitespace removed. A renderer that rewrites content is not
    /// rendering it.
    #[test]
    fn layout_never_alters_a_single_character() {
        // Includes marks pressed directly against Mongolian, Han, and Latin
        // with no space to separate them — the arrangement that exposed a
        // buffered connector surfacing on the wrong side of a run.
        let source = "O = ᠥ。辅音 q（阳）/k（阴）= ᠬ，S=ᠱ，=ᠴ，j=ᠵ。规则：ᠱ(S) 不出现在 i 前，\u{201c}shi\u{201d} 音写作 si。";
        let layout = layout_text(source, &LayoutConfig::default());
        let mut rebuilt = String::new();
        for column in &layout.columns {
            for slot in &column.slots {
                match slot {
                    Slot::Upright(s) | Slot::LatinWord(s) | Slot::MongolianRun(s)
                    | Slot::VerticalPunctuation(s) | Slot::CornerPunctuation(s)
                    | Slot::Neutral(s) | Slot::Space(s) => rebuilt.push_str(s),
                }
            }
        }
        // Whitespace included: a dropped space makes `可在 gerel.net 检索`
        // come back as `可在gerel.net检索`, which is close enough to look
        // right and wrong to quote.
        assert_eq!(rebuilt, source, "layout must not add, drop, or swap characters");
    }

    #[test]
    fn a_leading_mark_joins_the_word_that_follows() {
        let layout = layout_text("-n_a / -n_e", &LayoutConfig::default());
        let marks: Vec<&Slot> = layout.columns[0].slots.iter()
            .filter(|slot| !matches!(slot, Slot::Space(_))).collect();
        assert_eq!(marks, vec![
            &Slot::LatinWord("-n_a".into()),
            // A slash separates alternatives, so each gets its own row. It
            // stays upright: a turned slash reads as a backslash.
            &Slot::Neutral("/".into()),
            &Slot::LatinWord("-n_e".into()),
        ]);
    }
    /// A slash breaks a word even between letters: `uu/UU` is two forms, and
    /// each wants its own row.
    #[test]
    fn a_slash_always_breaks() {
        let layout = layout_text("uu/UU", &LayoutConfig::default());
        assert_eq!(layout.columns[0].slots, vec![
            Slot::LatinWord("uu".into()),
            Slot::Neutral("/".into()),
            Slot::LatinWord("UU".into()),
        ]);
    }
    /// Fullwidth punctuation must never be swallowed by an adjacent Latin
    /// letter: `q（阳）` is a letter, a bracket, an ideograph, a bracket.
    #[test]
    fn fullwidth_marks_never_join_a_latin_word() {
        let layout = layout_text("q（阳）", &LayoutConfig::default());
        assert_eq!(layout.columns[0].slots, vec![
            Slot::LatinWord("q".into()),
            Slot::VerticalPunctuation("（".into()),
            Slot::Upright("阳".into()),
            Slot::VerticalPunctuation("）".into()),
        ]);
    }
    #[test]
    fn the_same_mark_standing_alone_takes_a_vertical_form() {
        // Nothing holds it on the left, so it is punctuation again.
        let layout = layout_text("好（天）= 川", &LayoutConfig::default());
        let marks: Vec<&Slot> = layout.columns[0].slots.iter()
            .filter(|slot| !matches!(slot, Slot::Space(_))).collect();
        assert_eq!(marks, vec![
            &Slot::Upright("好".into()),
            &Slot::VerticalPunctuation("（".into()),
            &Slot::Upright("天".into()),
            &Slot::VerticalPunctuation("）".into()),
            &Slot::VerticalPunctuation("=".into()),
            &Slot::Upright("川".into()),
        ]);
    }
    /// The orientation measure counts slots, not characters. A Chinese
    /// sentence quoting romanization has more Latin letters than Han
    /// characters and is still, plainly, a Chinese sentence.
    #[test]
    fn romanization_does_not_flip_a_chinese_sentence_horizontal() {
        assert!(!prefers_horizontal(
            "3. 将来否定 = 词典形 + Ugei：bi yabuqu Ugei（我不去），不是 *yabun_a Ugei。"));
        assert!(!prefers_horizontal("4. 疑问词 uu/UU 也和谐：iren_e UU。"));
        assert!(!prefers_horizontal(
            "Ugei 否定\u{201d}有\u{201d}，bisi 否定\u{201d}是\u{201d}：mori Ugei（没有马）vs tere mori bisi（那不是马）。"));
        // Genuine English still goes horizontal.
        assert!(prefers_horizontal("It is a truth universally acknowledged, that a single man"));
    }

    #[test]
    fn progression_is_carried_as_data() {
        let config = LayoutConfig { progression: Progression::LeftToRight, ..Default::default() };
        assert_eq!(layout_text("ᠮᠣᠩᠭᠤᠯ", &config).progression, Progression::LeftToRight);
    }
    #[test]
    fn code_mode_keeps_indentation_as_blank_rows() {
        let config = LayoutConfig { max_latin_word_width: 24, preserve_spaces: true, ..Default::default() };
        let layout = layout_text("  let", &config);
        assert_eq!(layout.columns[0].slots, vec![
            Slot::Space(" ".into()),
            Slot::Space(" ".into()),
            Slot::LatinWord("let".into()),
        ]);
    }
}
