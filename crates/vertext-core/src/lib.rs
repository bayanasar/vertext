//! The host-independent part of Vertext.
//!
//! A host turns a [`Layout`] into HTML, a terminal preview, or a GPU scene. The
//! logical reading direction is always top-to-bottom and a source newline moves
//! to the column on its left.

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct LayoutConfig {
    /// Maximum number of displayed characters in an upright Latin word slot.
    pub max_latin_word_width: usize,
    /// Code mode retains each source space as an empty vertical row.
    pub preserve_spaces: bool,
}

impl Default for LayoutConfig {
    fn default() -> Self {
        Self {
            max_latin_word_width: 12,
            preserve_spaces: false,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Layout {
    /// Columns are in source order: `columns[0]` is the rightmost column.
    pub columns: Vec<Column>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Column {
    pub slots: Vec<Slot>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Slot {
    /// An upright ideograph, kana, or hangul grapheme (the initial MVP treats a
    /// Unicode scalar as a grapheme; a later UAX #29 upgrade belongs here).
    Upright(String),
    /// One normal, horizontally readable Latin word in a vertical slot.
    LatinWord(String),
    /// Keep the run intact so a vertical-capable font can perform Mongolian
    /// joining and vertical substitutions.
    MongolianRun(String),
    /// An intentionally blank vertical row, used to retain code indentation.
    Space,
    /// Paired punctuation rotates clockwise: an opening mark faces down toward
    /// its closer, and the closer faces up toward its opener.
    PairedPunctuation(String),
    /// Punctuation and other unsupported scripts remain upright for now.
    Neutral(String),
}

/// Creates a top-to-bottom layout. Each source newline starts a new column to
/// the *left*. Whitespace separates Latin words but does not create an empty
/// slot. Long Latin words use predictable hard hyphens; dictionary hyphenation
/// is intentionally a host-configurable future enhancement.
pub fn layout_text(input: &str, config: &LayoutConfig) -> Layout {
    let mut columns = vec![Column { slots: Vec::new() }];
    let mut latin_word = String::new();
    let mut mongolian_run = String::new();

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

    for ch in input.chars() {
        if ch == '\n' {
            flush_latin(&mut columns, &mut latin_word);
            flush_mongolian(&mut columns, &mut mongolian_run);
            columns.push(Column { slots: Vec::new() });
        } else if ch.is_whitespace() {
            flush_latin(&mut columns, &mut latin_word);
            flush_mongolian(&mut columns, &mut mongolian_run);
            if config.preserve_spaces {
                columns.last_mut().unwrap().slots.push(Slot::Space);
            }
        } else if is_mongolian(ch) {
            flush_latin(&mut columns, &mut latin_word);
            mongolian_run.push(ch);
        } else if is_word_char(ch) {
            flush_mongolian(&mut columns, &mut mongolian_run);
            latin_word.push(ch);
        } else {
            flush_latin(&mut columns, &mut latin_word);
            flush_mongolian(&mut columns, &mut mongolian_run);
            let slot = if is_paired_punctuation(ch) {
                Slot::PairedPunctuation(ch.to_string())
            } else if is_cjk(ch) {
                Slot::Upright(ch.to_string())
            } else {
                Slot::Neutral(ch.to_string())
            };
            columns.last_mut().unwrap().slots.push(slot);
        }
    }
    flush_latin(&mut columns, &mut latin_word);
    flush_mongolian(&mut columns, &mut mongolian_run);
    Layout { columns }
}

fn split_latin_word(word: &str, limit: usize) -> Vec<String> {
    let limit = limit.max(2);
    let chars: Vec<char> = word.chars().collect();
    if chars.len() <= limit { return vec![word.to_owned()]; }
    let payload = limit - 1;
    chars.chunks(payload).enumerate().map(|(i, chunk)| {
        let mut piece: String = chunk.iter().collect();
        if (i + 1) * payload < chars.len() { piece.push('‐'); }
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
fn is_paired_punctuation(ch: char) -> bool {
    matches!(ch, '(' | ')' | '[' | ']' | '{' | '}' | '<' | '>' |
        '=' | '-' | ':' | '\'' | '"' |
        '（' | '）' | '［' | '］' | '｛' | '｝' |
        '〈' | '〉' | '《' | '》' | '「' | '」' | '『' | '』' |
        '【' | '】' | '〔' | '〕' | '“' | '”' | '‘' | '’')
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
    fn paired_punctuation_has_its_own_orientation_slot() {
        let layout = layout_text("()", &LayoutConfig::default());
        assert_eq!(layout.columns[0].slots, vec![
            Slot::PairedPunctuation("(".into()),
            Slot::PairedPunctuation(")".into()),
        ]);
    }
    #[test]
    fn underscores_and_digits_stay_in_a_latin_identifier() {
        let layout = layout_text("hi_nancy v2", &LayoutConfig::default());
        assert_eq!(layout.columns[0].slots, vec![
            Slot::LatinWord("hi_nancy".into()),
            Slot::LatinWord("v2".into()),
        ]);
    }
    #[test]
    fn code_mode_keeps_indentation_as_blank_rows() {
        let config = LayoutConfig { max_latin_word_width: 24, preserve_spaces: true };
        let layout = layout_text("  let", &config);
        assert_eq!(layout.columns[0].slots, vec![
            Slot::Space,
            Slot::Space,
            Slot::LatinWord("let".into()),
        ]);
    }
}
