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
    let (vertical, horizontal) = measure_slots(text);
    horizontal > vertical
}

/// The slot census behind [`prefers_horizontal`]: vertical slots, then
/// horizontal ones.
///
/// It must agree with [`layout_text`] about what a slot is — the count here
/// equals the number of [`Slot::Upright`] plus [`Slot::MongolianRun`] slots
/// that function emits, and the number of [`Slot::LatinWord`] slots. Pinning
/// the answer for one string is weaker and turns into a puzzle at the next
/// change; the invariant is that these two ways of counting cannot disagree.
///
/// Which script holds the open word is the whole of it. A word ends at a
/// change of script even where no space separates the two, because that is
/// where `layout_text` closes its slot and opens the next: `writtenᠢᠢ` is a
/// Latin word and a bichig run, not one thing. Tracking only *whether* a word
/// is open loses that boundary, and loses it in both directions — the run
/// after a Latin word goes uncounted, and so does the word after a run.
fn measure_slots(text: &str) -> (usize, usize) {
    let (mut vertical, mut horizontal) = (0usize, 0usize);
    // Exactly one of these is true while a word is open, and the pair is the
    // answer to "whose word is it": the suffix separator joins bichig and
    // nothing else, and a bracket continues a Latin word and nothing else.
    let mut in_latin = false;
    let mut in_bichig = false;
    for cluster in text.graphemes(true) {
        let Some(base) = cluster.chars().next() else { continue };
        if is_cjk(base) {
            vertical += 1;
            in_latin = false;
            in_bichig = false;
        } else if is_mongolian(base) {
            // A Mongolian run is one slot, so only its start counts — and a
            // Latin word to the left does not make this its continuation.
            if !in_bichig {
                vertical += 1;
            }
            in_latin = false;
            in_bichig = true;
        } else if is_word_char(base) {
            // A whole Latin word is one slot; count only where it begins, and
            // a bichig run to the left does not make this its continuation.
            if !in_latin {
                horizontal += 1;
            }
            in_latin = true;
            in_bichig = false;
        } else if in_latin && is_word_connector(base) {
            // Inside the word, as `layout_text` reads it: `kedU(n)`,
            // `gerel.net`. A connector with no Latin word open is punctuation
            // there and must be punctuation here too, so it falls through.
        } else if in_bichig && is_suffix_separator(base) {
            // The word continues across the joint. A stem and its case ending
            // are one word and one slot — see `is_suffix_separator` — and
            // counting them twice weighs the same word twice, which is the
            // measure disagreeing with the layout about what a slot is.
        } else {
            in_latin = false;
            in_bichig = false;
        }
    }
    (vertical, horizontal)
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
    // Whether those buffered connectors may still join a word that follows.
    //
    // A connector joins letters only when letters hold it on BOTH sides. At the
    // start of a line, or after a space, `-n_a` is still one word — nothing has
    // claimed the mark, so a following word may. But after an ideograph the
    // mark has already been decided: `词尾(n)` is a Chinese sentence with a
    // bracketed gloss, and the bracket must turn like every other bracket in
    // that sentence. Without this the same paren lies flat next to Han and
    // turns next to a space, which is what left a line of prose with some
    // brackets rotated and some not.
    let mut connectors_may_join = true;
    // A suffix separator waiting to learn what follows it. Bichig on the right
    // claims it into the run; anything else — an ideograph, a newline, the end
    // of the input — leaves it the narrow space it is also named for. The same
    // deferral as `pending_connectors`, for the same reason: one pass over the
    // text, and only the next cluster can tell the two readings apart.
    let mut pending_separator = String::new();

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
        // A buffered separator learns here what followed it. This settles
        // before the branches so every one of them sees a decided state, and
        // it closes the run first: the mark goes after the stem it failed to
        // join, never ahead of it.
        if !pending_separator.is_empty() && !is_mongolian(base) {
            flush_mongolian(&mut columns, &mut mongolian_run);
            columns.last_mut().unwrap().slots
                .push(Slot::Space(std::mem::take(&mut pending_separator)));
        }
        if base == '\n' || base == '\r' {
            // "\r\n" is one cluster and must open one column, not two.
            flush_latin(&mut columns, &mut latin_word);
            flush_mongolian(&mut columns, &mut mongolian_run);
            flush_pending(&mut columns, &mut pending_connectors);
            connectors_may_join = true;
            columns.push(Column { slots: Vec::new() });
        } else if base.is_whitespace() {
            if is_suffix_separator(base) && !mongolian_run.is_empty() {
                // Not a space here: the joint that holds a case ending onto
                // its stem. Hold it until the next cluster says whether a
                // suffix actually follows.
                pending_separator.push_str(cluster);
                continue;
            }
            flush_latin(&mut columns, &mut latin_word);
            flush_mongolian(&mut columns, &mut mongolian_run);
            flush_pending(&mut columns, &mut pending_connectors);
            // The space is always kept. It is a character the author typed,
            // and dropping it means a copied paragraph comes back as
            // `可在gerel.net检索` — close enough to look fine and wrong to
            // quote. `preserve_spaces` now decides only whether the space is
            // made *visible* (code indentation), never whether it survives.
            columns.last_mut().unwrap().slots.push(Slot::Space(cluster.to_owned()));
            // A space frees the next mark to join whatever follows it.
            connectors_may_join = true;
        } else if is_mongolian(base) {
            flush_latin(&mut columns, &mut latin_word);
            // A connector still waiting for a word has just learned that no
            // Latin word is coming. It must be emitted *here*, before the
            // Mongolian run opens — left buffered it would surface when the
            // run flushes, and `= ᠬ` would come back as `ᠬ=`. Reordering
            // the author's characters is as wrong as replacing them.
            flush_pending(&mut columns, &mut pending_connectors);
            // Bichig is not Latin: `ᠱ(S)` is a script paired with its
            // transliteration, so the bracket belongs to the sentence.
            connectors_may_join = false;
            // A separator the previous letter held back has its answer: the
            // suffix arrived, so the joint goes into the run it joins.
            mongolian_run.push_str(&std::mem::take(&mut pending_separator));
            mongolian_run.push_str(cluster);
        } else if is_word_char(base) {
            flush_mongolian(&mut columns, &mut mongolian_run);
            latin_word.push_str(&std::mem::take(&mut pending_connectors));
            latin_word.push_str(cluster);
            connectors_may_join = true;
        } else if is_word_connector(base) && (connectors_may_join || !latin_word.is_empty()) {
            // Inside a word this mark is a letter: `min-U`, `kedU(n)`, and
            // `-n_a` are one word each. Held on either side by letters it
            // joins them; held by neither it is punctuation.
            //
            // A mark at the tail of an open word is buffered rather than
            // appended, because whether it belongs to that word is not yet
            // known: the letters in `kedU(n)` claim it, but the ideograph in
            // `(n)形式` does not, and only the next character tells them apart.
            // Buffering defers the choice to the branch that sees it.
            //
            // Unless it closes a bracket the word already opened. `kedU(n)` is
            // one citation form and its `)` has letters on the left and its own
            // `(` inside the word -- the pair is balanced, so the mark is the
            // word's own and needs no lookahead. Deferring it would strand the
            // closing bracket outside the word at end of input.
            if closes_open_bracket(base, &latin_word) {
                latin_word.push_str(cluster);
            } else {
                pending_connectors.push_str(cluster);
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
            // An ideograph (or any other non-word character) on the left ends a
            // word. A connector that follows it opens an aside in a sentence
            // rather than continuing a citation form, so it must not be held
            // back waiting for letters to join.
            connectors_may_join = false;
            columns.last_mut().unwrap().slots.push(slot);
        }
    }
    flush_latin(&mut columns, &mut latin_word);
    flush_mongolian(&mut columns, &mut mongolian_run);
    // Nothing followed it, so it was the narrow space after all.
    if !pending_separator.is_empty() {
        columns.last_mut().unwrap().slots.push(Slot::Space(pending_separator));
    }
    flush_pending(&mut columns, &mut pending_connectors);
    Layout { columns, progression: config.progression }
}

/// Whether a closing mark completes a bracket the word already holds open.
///
/// `kedU(n)` is one word: its `)` matches a `(` that letters already claimed,
/// so it joins them with no lookahead. `词尾(n)形式` never gets here for its
/// `)` — that `(` went out as punctuation, so the word holds nothing open and
/// the closing mark is punctuation too. Balance is what separates a citation
/// form from an aside in a sentence.
fn closes_open_bracket(ch: char, word: &str) -> bool {
    let opener = match ch {
        ')' => '(',
        ']' => '[',
        '}' => '{',
        '>' => '<',
        _ => return false,
    };
    let opens = word.chars().filter(|&c| c == opener).count();
    let closes = word.chars().filter(|&c| c == ch).count();
    opens > closes
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
///
/// A hyphen the author already typed is a break opportunity, and taking it
/// costs nothing: the pieces still concatenate to the source, so a word broken
/// there is not edited at all. Counting to the cap is the fallback for a word
/// that offers no such break — `use-after-free` must not come back as
/// `use-after-f‐` / `ree`, which reads as a different term.
///
/// Only hyphens qualify. The other word connectors in `is_word_connector`
/// *join* — splitting `gerel.net` at the dot or `kedU(n)` at the paren cuts a
/// citation form in half.
fn split_latin_word(word: &str, limit: usize) -> Vec<String> {
    let limit = limit.max(2);
    let clusters: Vec<&str> = word.graphemes(true).collect();
    if clusters.len() <= limit { return vec![word.to_owned()]; }

    // The rightmost hyphen that still fits, so the piece before it is as full
    // as it can be. The break falls *after* the hyphen — that is where a
    // hyphenated word is allowed to break, and it leaves the mark on the line
    // that earned it.
    let hyphen = clusters[..limit].iter()
        .rposition(|cluster| matches!(*cluster, "-" | "\u{2010}"))
        .map(|index| index + 1)
        // A hyphen in the last position would leave an empty remainder; there
        // is nothing after it to move to the next piece.
        .filter(|split| *split < clusters.len());

    match hyphen {
        Some(split) => {
            let mut pieces = vec![clusters[..split].concat()];
            pieces.extend(split_latin_word(&clusters[split..].concat(), limit));
            pieces
        }
        None => {
            // No break of its own: count, and reserve one slot for the mark
            // that says the break was ours.
            let payload = limit - 1;
            let mut pieces = vec![{
                let mut piece: String = clusters[..payload].concat();
                piece.push('‐');
                piece
            }];
            pieces.extend(split_latin_word(&clusters[payload..].concat(), limit));
            pieces
        }
    }
}

fn is_mongolian(ch: char) -> bool { matches!(ch as u32, 0x1800..=0x18AF | 0x11660..=0x1167F) }

/// U+202F NARROW NO-BREAK SPACE — in bichig, the suffix separator.
///
/// This mark is not a space between words but a joint inside one. `ᠮᠣᠩᠭᠣᠯ` +
/// NNBSP + `ᠤᠨ` is the genitive "Mongolia's": the separator holds the stem's
/// last letter in its final form, opens the suffix in its initial form, and
/// forbids a break between them — UAX #14 gives it class GL, non-breaking on
/// both sides. The case suffixes are all attached this way.
///
/// Unicode nonetheless gives it `White_Space=Yes`, so `char::is_whitespace`
/// answers true and an engine that asks only that question sets a case ending
/// as a separate word: a half-em gap in the column with the suffix stranded
/// below it, and the joining that carries the grammar cut in two. That one
/// property is what this function exists to override — and only where bichig
/// holds the mark on both sides, because U+202F is also the ordinary narrow
/// space that its name describes.
///
/// U+180E MONGOLIAN VOWEL SEPARATOR needs no such rescue. It was `Zs` until
/// Unicode 6.3 and is `Cf` now, so it is not whitespace to begin with, and it
/// already rides inside the run as an ordinary character of the Mongolian
/// block — as do the free variation selectors U+180B–180D, which are `Extend`
/// and never leave the cluster they modify.
fn is_suffix_separator(ch: char) -> bool { ch == '\u{202F}' }

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
        // The whole dash family, not just the em dash: a range written `᠑–᠕`
        // reached here on an en dash, missed this list, and fell through to
        // `Neutral`, where nothing turns it — so it lay flat across the column
        // while the em dashes on the same page stood correctly. Every mark
        // Unicode calls a dash belongs to one class; picking three of them out
        // by hand is what let the other five drift.
        //
        // ASCII `-` is deliberately NOT here. `is_word_connector` claims it
        // first so that a word breaks at the hyphen it already has, and it only
        // reaches this function when no word holds it.
        '—' | '―' | '－' | '–' | '‐' | '‑' | '‒' | '−' | '⸺' | '⸻' |
        '…' | '‥' | '〜' | '～' | '｜' | '‖')
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
                     // The rest of the dash family. The em dash was here from
                     // the start and its siblings were not, so `᠑–᠕` came out
                     // with the dash lying flat across the column while an em
                     // dash two lines above it turned correctly.
                     '–', '‐', '‑', '‒', '−', '⸺', '⸻',
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
    /// The other half of the contract above, and the boundary between them.
    ///
    /// A connector joins letters only when letters hold it on BOTH sides.
    /// Pressed against an ideograph it is an ordinary bracket in a Chinese
    /// sentence and takes its vertical form, exactly as `is_word_connector`
    /// has always said it should ("with a space or an ideograph on the left
    /// ... ordinary punctuation").
    ///
    /// This is the case a Chinese document teaching Mongolian is made of:
    /// `不稳定词尾(n)` is a gloss inside prose, while `kedU(n)` in the glossary
    /// beside it is one citation form. Same characters, different job, and the
    /// character on the left is what tells them apart. Getting this wrong
    /// leaves a sentence where some brackets turn and some lie flat.
    #[test]
    fn a_mark_against_an_ideograph_is_punctuation() {
        let layout = layout_text("词尾(n)形式", &LayoutConfig::default());
        assert_eq!(layout.columns[0].slots, vec![
            Slot::Upright("词".into()),
            Slot::Upright("尾".into()),
            Slot::VerticalPunctuation("(".into()),
            Slot::LatinWord("n".into()),
            Slot::VerticalPunctuation(")".into()),
            Slot::Upright("形".into()),
            Slot::Upright("式".into()),
        ]);
        // A closing bracket followed by an ideograph closes the aside; it must
        // not swallow the ideograph's side of the boundary either.
        let mongolian = layout_text("ᠱ(S) 不", &LayoutConfig::default());
        assert_eq!(mongolian.columns[0].slots, vec![
            Slot::MongolianRun("ᠱ".into()),
            Slot::VerticalPunctuation("(".into()),
            Slot::LatinWord("S".into()),
            Slot::VerticalPunctuation(")".into()),
            Slot::Space(" ".into()),
            Slot::Upright("不".into()),
        ]);
        // And the citation form is untouched: letters on both sides still join.
        let citation = layout_text("kedU(n)", &LayoutConfig::default());
        assert_eq!(citation.columns[0].slots, vec![Slot::LatinWord("kedU(n)".into())]);
    }
    /// A long word breaks at a hyphen it already has, rather than counting to
    /// the cap and inserting one.
    ///
    /// `use-after-free` came back as `use-after-f‐` / `ree`, which reads as a
    /// different term. A hyphen is already a sanctioned break point, so
    /// breaking there needs no inserted mark at all — and a break that adds
    /// nothing leaves the text identical to the source.
    #[test]
    fn a_long_word_breaks_at_the_hyphen_it_already_has() {
        // 15 clusters against the default cap of 12.
        assert_eq!(split_latin_word("use-after-free", 12),
            vec!["use-after-".to_owned(), "free".to_owned()]);
        // Nothing was inserted: the pieces rebuild the source exactly.
        assert_eq!(split_latin_word("use-after-free", 12).concat(), "use-after-free");

        // The rightmost hyphen that still fits wins, so each piece is as full
        // as it can be. `-in-` would fit too, but leaves a longer remainder.
        assert_eq!(split_latin_word("copy-on-write-semantics", 14),
            vec!["copy-on-write-".to_owned(), "semantics".to_owned()]);

        // A remainder that still overflows keeps breaking, and the tail falls
        // back to counting when it holds no hyphen of its own.
        assert_eq!(split_latin_word("well-known-supercalifragilistic", 12),
            vec!["well-known-".to_owned(), "supercalifr‐".to_owned(), "agilistic".to_owned()]);

        // A hyphen too far right to help is no break opportunity: the prefix
        // before it still exceeds the cap, so counting takes over.
        assert_eq!(split_latin_word("supercalifragilistic-x", 12),
            vec!["supercalifr‐".to_owned(), "agilistic-x".to_owned()]);

        // A trailing hyphen must not produce an empty piece.
        assert_eq!(split_latin_word("autoconfiguration-", 12),
            vec!["autoconfigu‐".to_owned(), "ration-".to_owned()]);

        // Only hyphens are break opportunities. The other word connectors join
        // — splitting `gerel.net` at the dot, or `kedU(n)` at the paren, breaks
        // a citation form in half.
        assert_eq!(split_latin_word("gerel.net.example.org", 12),
            vec!["gerel.net.e‐".to_owned(), "xample.org".to_owned()]);

        // Short enough to leave alone, hyphen or not.
        assert_eq!(split_latin_word("use-after", 12), vec!["use-after".to_owned()]);
    }

    /// A hyphen break survives the full layout path, not just the splitter,
    /// and leaves the source character-for-character intact.
    #[test]
    fn breaking_at_a_hyphen_alters_no_character() {
        let source = "在 use-after-free 中";
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
        assert_eq!(rebuilt, source, "a hyphen break must insert nothing");
        assert!(!rebuilt.contains('\u{2010}'), "no break mark was needed here");
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
    /// The suffix separator holds a case ending onto its stem, and the layout
    /// must keep them in one run.
    ///
    /// `ᠮᠣᠩᠭᠣᠯ` + U+202F + `ᠤᠨ` is one word, the genitive "Mongolia's". Because
    /// Unicode gives U+202F `White_Space=Yes`, the whitespace branch used to
    /// close the run, emit a `Space` slot, and open a second run — which on
    /// the page is a half-em gap with the case ending stranded below it, read
    /// by anyone who reads the script as two words instead of one.
    #[test]
    fn a_suffix_separator_is_part_of_the_word_not_a_space() {
        let genitive = "ᠮᠣᠩᠭᠣᠯ\u{202F}ᠤᠨ";
        assert_eq!(layout_text(genitive, &LayoutConfig::default()).columns[0].slots,
            vec![Slot::MongolianRun(genitive.into())],
            "the joint must stay inside the run it joins");
        // Every case ending attaches the same way, and a word may carry more
        // than one joint.
        let dative = "ᠮᠣᠩᠭᠣᠯ\u{202F}ᠳᠤ\u{202F}ᠪᠠᠨ";
        assert_eq!(layout_text(dative, &LayoutConfig::default()).columns[0].slots,
            vec![Slot::MongolianRun(dative.into())]);
        // A word space between two suffixed words is still a word space: the
        // fix must not swallow the boundary it does not own.
        let phrase = "ᠮᠣᠩᠭᠣᠯ\u{202F}ᠤᠨ ᠲᠡᠦᠬᠡ\u{202F}ᠶᠢ";
        assert_eq!(layout_text(phrase, &LayoutConfig::default()).columns[0].slots, vec![
            Slot::MongolianRun("ᠮᠣᠩᠭᠣᠯ\u{202F}ᠤᠨ".into()),
            Slot::Space(" ".into()),
            Slot::MongolianRun("ᠲᠡᠦᠬᠡ\u{202F}ᠶᠢ".into()),
        ]);
    }

    /// The other half of the contract: U+202F joins only where bichig holds it
    /// on both sides. Elsewhere it is the narrow space its name describes —
    /// French uses it before a colon, and typography uses it to group digits —
    /// so it keeps its own slot there, exactly as any other space would.
    #[test]
    fn a_narrow_space_outside_bichig_is_still_a_space() {
        // Nothing Mongolian on the left.
        assert_eq!(layout_text("好\u{202F}ᠤᠨ", &LayoutConfig::default()).columns[0].slots, vec![
            Slot::Upright("好".into()),
            Slot::Space("\u{202F}".into()),
            Slot::MongolianRun("ᠤᠨ".into()),
        ]);
        // Nothing Mongolian on the right: the run closes and the mark falls
        // back to being the space it also is.
        assert_eq!(layout_text("ᠮᠣᠩᠭᠣᠯ\u{202F}好", &LayoutConfig::default()).columns[0].slots, vec![
            Slot::MongolianRun("ᠮᠣᠩᠭᠣᠯ".into()),
            Slot::Space("\u{202F}".into()),
            Slot::Upright("好".into()),
        ]);
        // A newline is not a suffix either, and the mark must not follow the
        // column break: it belongs to the column the stem is in.
        let broken = layout_text("ᠮᠣᠩᠭᠣᠯ\u{202F}\nᠤᠨ", &LayoutConfig::default());
        assert_eq!(broken.columns[0].slots, vec![
            Slot::MongolianRun("ᠮᠣᠩᠭᠣᠯ".into()),
            Slot::Space("\u{202F}".into()),
        ]);
        assert_eq!(broken.columns[1].slots, vec![Slot::MongolianRun("ᠤᠨ".into())]);
        // Nothing follows it at all.
        assert_eq!(layout_text("ᠮᠣᠩᠭᠣᠯ\u{202F}", &LayoutConfig::default()).columns[0].slots, vec![
            Slot::MongolianRun("ᠮᠣᠩᠭᠣᠯ".into()),
            Slot::Space("\u{202F}".into()),
        ]);
        // Latin on both sides is not bichig: the mark never joins the word.
        assert_eq!(layout_text("Chapitre\u{202F}: 1", &LayoutConfig::default()).columns[0].slots, vec![
            Slot::LatinWord("Chapitre".into()),
            Slot::Space("\u{202F}".into()),
            Slot::VerticalPunctuation(":".into()),
            Slot::Space(" ".into()),
            Slot::LatinWord("1".into()),
        ]);
    }

    /// `layout_never_alters_a_single_character`, over text full of joints.
    /// Whether a separator joined a word or stood as a space, it must come
    /// back in place and in order — a buffered mark that resurfaces on the
    /// wrong side of a run is the same defect as a dropped one.
    #[test]
    fn suffix_separators_survive_the_round_trip() {
        let source = "ᠮᠣᠩᠭᠣᠯ\u{202F}ᠤᠨ ᠲᠡᠦᠬᠡ\u{202F}ᠶᠢ 读\u{202F}好 ᠪᠢ\u{202F}\nᠮᠣᠩᠭᠣᠯ\u{202F}";
        let layout = layout_text(source, &LayoutConfig::default());
        let mut rebuilt = String::new();
        for (index, column) in layout.columns.iter().enumerate() {
            if index > 0 { rebuilt.push('\n'); }
            for slot in &column.slots {
                match slot {
                    Slot::Upright(s) | Slot::LatinWord(s) | Slot::MongolianRun(s)
                    | Slot::VerticalPunctuation(s) | Slot::CornerPunctuation(s)
                    | Slot::Neutral(s) | Slot::Space(s) => rebuilt.push_str(s),
                }
            }
        }
        assert_eq!(rebuilt, source, "a joint must not be added, dropped, or moved");
    }

    /// The orientation measure counts slots, so it has to count a suffixed
    /// word the way the layout does: once.
    #[test]
    fn the_orientation_measure_counts_a_suffixed_word_once() {
        let genitive = "ᠮᠣᠩᠭᠣᠯ\u{202F}ᠤᠨ";
        assert_eq!(layout_text(genitive, &LayoutConfig::default()).columns[0].slots.len(), 1);
        // Two Latin slots against one Mongolian slot. Counted as two the word
        // would have tied the line and held it vertical — the same word
        // weighed twice. The unsuffixed stem in the same sentence has always
        // gone this way, so the fix only made the two agree; it is not a
        // judgment that bichig belongs on a horizontal line.
        assert!(prefers_horizontal("ᠮᠣᠩᠭᠣᠯ is written"));
        assert!(prefers_horizontal(&format!("{genitive} is written")));
        // And bichig on its own is never called horizontal, joints or not.
        assert!(!prefers_horizontal("ᠮᠣᠩᠭᠣᠯ\u{202F}ᠤᠨ ᠲᠡᠦᠬᠡ\u{202F}ᠶᠢ"));
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

    /// The measure and the layout may not disagree about what a slot is.
    ///
    /// This is the invariant, not the answer for any one string. Pinning
    /// `prefers_horizontal("ᠢᠢis written") == false` records a symptom and
    /// becomes a puzzle at the next change; a disagreement between these two
    /// counts is always a defect. Issue #4 was exactly such a disagreement,
    /// and it ran in both directions: a Latin word swallowed after a bichig
    /// run, and a bichig run swallowed after a Latin word.
    ///
    /// Consecutive `LatinWord` slots count as one, because that is
    /// hyphenation: `internationalization` lays out as two slots and is one
    /// word with one opinion about direction. Consecutive `Upright` slots are
    /// not merged — each ideograph really is its own slot and its own vote.
    #[test]
    fn the_measure_counts_the_slots_the_layout_produces() {
        let cases = [
            // The pair from issue #4: identical content, opposite order.
            "ᠰᠠᠶᠢᠨ(sayin) good",
            "sayin(ᠰᠠᠶᠢᠨ) good",
            // Script boundaries with no space between, both directions.
            "writtenᠢᠢ",
            "ᠢᠢis written",
            "ᠢᠢ is written",
            "the ᠮᠣᠩᠭᠣᠬscript",
            "ᠢᠢ好",
            "好is written",
            // The suffix separator, joining and not joining.
            "ᠮᠣᠩᠭᠣᠬ\u{202F}ᠤᠨ",
            "ᠢᠢ\u{202F}is written",
            "ᠢᠢ\u{202F}ᠶᠨ is written",
            // Connectors inside a word, and one with no word to join.
            "kedU(n)",
            "gerel.net",
            "min-U yabun_a uu/UU",
            "ᠰᠠᠶᠢᠨ(",
            // Hyphenation: one word, two slots, one vote.
            "use-after-free",
            "internationalization",
            // Plain cases in both systems.
            "hello world",
            "山川异域，风月同天",
            "ᠢᠢ",
            "",
        ];

        for text in cases {
            let layout = layout_text(text, &LayoutConfig::default());
            let (mut vertical, mut horizontal) = (0usize, 0usize);
            let mut previous_was_latin = false;
            for slot in layout.columns.iter().flat_map(|column| column.slots.iter()) {
                match slot {
                    Slot::Upright(_) | Slot::MongolianRun(_) => {
                        vertical += 1;
                        previous_was_latin = false;
                    }
                    Slot::LatinWord(_) => {
                        if !previous_was_latin {
                            horizontal += 1;
                        }
                        previous_was_latin = true;
                    }
                    _ => previous_was_latin = false,
                }
            }
            assert_eq!(
                measure_slots(text),
                (vertical, horizontal),
                "measure and layout disagree on {text:?}"
            );
        }
    }

    /// A word and its transliteration read the same way whichever comes first.
    ///
    /// This is the consequence a reader sees, and the reason issue #4 was not
    /// the low-severity miscount it first looked like: a glossary written
    /// bichig-first and one written Latin-first are the same content, and a
    /// list that mixes the two orders had its direction flip line by line.
    /// The value itself is not pinned — the pair agreeing is the property.
    #[test]
    fn a_transliteration_pair_reads_the_same_way_in_either_order() {
        assert_eq!(
            prefers_horizontal("ᠰᠠᠶᠢᠨ(sayin) good"),
            prefers_horizontal("sayin(ᠰᠠᠶᠢᠨ) good"),
        );
    }
}
