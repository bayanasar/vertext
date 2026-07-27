//! The shared `Layout` → HTML renderer.
//!
//! Every HTML-producing host — the CLI today, `vertext-wasm` tomorrow — goes
//! through this crate, so the slot-to-class mapping and the mode protocol are
//! defined exactly once. The crate is `wasm32`-clean: no I/O, strings in,
//! strings out.

use vertext_core::{
    layout_text, prefers_horizontal, HorizontalKind, Layout, LayoutConfig, Progression, Slot,
};

/// Reserved private-use markers that the Quarto filter inserts around a
/// segment so a single invocation can switch mid-stream between rule sets.
/// Source authors never type these, which is why they live in the Unicode
/// Private Use Area.
///
/// A marker means "everything after me is this kind of segment, until the
/// next marker". Structure that markdown expresses and a flat string cannot —
/// a heading is not a paragraph that happens to be short — has to cross the
/// boundary somehow, and this is the seam it crosses.
///
/// Wire protocol note: `extensions/vertext/vertext.lua` carries the same
/// codepoints as string literals. The `mode_markers_are_the_wire_protocol`
/// test pins the values so a drift on the Rust side cannot pass silently.
pub const MODE_CODE: char = '\u{E000}';
pub const MODE_PROSE: char = '\u{E001}';
/// Heading levels 1–6 occupy U+E002–U+E007.
pub const MODE_HEADING_BASE: u32 = 0xE002;
pub const MAX_HEADING_LEVEL: u8 = 6;
/// A table segment. Within it, cells are separated by [`CELL_SEP`] and rows by
/// [`ROW_SEP`]; a table is 2-D and the wire is a flat string, so the structure
/// needs separators rather than a mode alone.
pub const MODE_TABLE: char = '\u{E008}';
pub const CELL_SEP: char = '\u{E009}';
pub const ROW_SEP: char = '\u{E00A}';
/// One list item. Each item is its own segment: flattening a whole list into
/// a single blob welds the items together *and* mixes their scripts, so a
/// list of mostly-CJK items with Latin terms in them gets classified by the
/// aggregate rather than item by item.
pub const MODE_LIST: char = '\u{E00B}';
/// One item of a *numbered* list. Ordered items already carry their number in
/// the text, so they must not also be given a bullet; a marker of their own
/// is what lets the stylesheet tell them apart.
pub const MODE_LIST_ORDERED: char = '\u{E00C}';
/// One past the last reserved codepoint. The filter strips this whole range
/// from author text; keep the two in step.
pub const RESERVED_END: u32 = 0xE00C;

/// The marker introducing a heading of `level` (clamped to 1–6).
pub fn heading_marker(level: u8) -> char {
    let level = level.clamp(1, MAX_HEADING_LEVEL);
    char::from_u32(MODE_HEADING_BASE + u32::from(level) - 1).expect("heading marker in PUA")
}

/// Single source of truth for the Latin slot caps. The renderer publishes
/// them to CSS as custom properties on the root element, so the stylesheet
/// never hardcodes a width that could drift from the layout.
pub const PROSE_LATIN_CAP: usize = 12;
pub const CODE_LATIN_CAP: usize = 24;

pub fn prose_config(progression: Progression) -> LayoutConfig {
    LayoutConfig {
        max_latin_word_width: PROSE_LATIN_CAP,
        preserve_spaces: false,
        progression,
    }
}

pub fn code_config(progression: Progression) -> LayoutConfig {
    LayoutConfig {
        max_latin_word_width: CODE_LATIN_CAP,
        preserve_spaces: true,
        progression,
    }
}

pub fn escape(text: &str) -> String {
    text.replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
}

fn advance_keyword(progression: Progression) -> &'static str {
    match progression {
        Progression::RightToLeft => "left",
        Progression::LeftToRight => "right",
    }
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
enum Mode {
    Prose,
    Code,
    Heading(u8),
    Table,
    ListItem { ordered: bool },
}

impl Mode {
    fn from_marker(ch: char) -> Option<Mode> {
        if ch == MODE_CODE {
            return Some(Mode::Code);
        }
        if ch == MODE_PROSE {
            return Some(Mode::Prose);
        }
        if ch == MODE_TABLE {
            return Some(Mode::Table);
        }
        if ch == MODE_LIST {
            return Some(Mode::ListItem { ordered: false });
        }
        if ch == MODE_LIST_ORDERED {
            return Some(Mode::ListItem { ordered: true });
        }
        let offset = (ch as u32).checked_sub(MODE_HEADING_BASE)?;
        (offset < u32::from(MAX_HEADING_LEVEL)).then(|| Mode::Heading(offset as u8 + 1))
    }

    fn config(self, progression: Progression) -> LayoutConfig {
        match self {
            // A heading is prose that happens to be short and loud. It gets
            // the prose rule set; only its presentation differs.
            Mode::Prose | Mode::Heading(_) | Mode::Table | Mode::ListItem { .. } => prose_config(progression),
            Mode::Code => code_config(progression),
        }
    }

    fn column_class(self) -> String {
        match self {
            Mode::Prose | Mode::Table => "vertext-column vertext-column-prose".to_string(),
            Mode::ListItem { ordered } => {
                let kind = if ordered { "vertext-column-list-ordered" } else { "vertext-column-list-bullet" };
                format!("vertext-column vertext-column-prose vertext-column-list {kind}")
            }
            Mode::Code => "vertext-column vertext-column-code".to_string(),
            Mode::Heading(level) => format!(
                "vertext-column vertext-column-prose vertext-column-heading vertext-column-h{level}"
            ),
        }
    }

    /// Which way this segment is set.
    ///
    /// Code is always horizontal — program source has a left-to-right reading
    /// order built into its own syntax, and Japanese and Chinese technical
    /// publishing has set code horizontally inside vertical books for decades.
    /// Prose is decided by which script carries the line. Headings follow the
    /// body so a section title never sits at odds with the section.
    fn block(self, text: &str) -> BlockKind {
        match self {
            Mode::Table => BlockKind::Table,
            Mode::Code => BlockKind::Horizontal(HorizontalKind::Code),
            Mode::Prose | Mode::Heading(_) | Mode::ListItem { .. } => {
                if prefers_horizontal(text) {
                    BlockKind::Horizontal(HorizontalKind::Prose)
                } else {
                    BlockKind::Vertical
                }
            }
        }
    }
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
enum BlockKind {
    Vertical,
    Horizontal(HorizontalKind),
    Table,
}

#[derive(Clone, Copy, Debug)]
pub struct RenderOptions {
    /// Lay the entire input out under the code rule set, ignore the mode
    /// markers, and put `vertext-code` on the root.
    pub whole_strip_code: bool,
    /// Put `vertext-page` on the root. The stylesheet keys full-page vertical
    /// flow (native `writing-mode` on the surrounding page) off this class.
    pub page: bool,
    /// Which way columns advance. A property of the document's script, and
    /// the one thing an engine must never hardcode: every renderer that fixes
    /// this to right-to-left has decided permanently which literatures it can
    /// carry. Declared by the author, because it cannot be inferred — a
    /// Chinese document teaching Mongolian and a Mongolian document teaching
    /// Chinese contain the same scripts and want opposite answers.
    pub progression: Progression,
}

impl Default for RenderOptions {
    fn default() -> Self {
        Self {
            whole_strip_code: false,
            page: false,
            // CJK is the bulk of vertical text on the web; Mongolian
            // documents declare. Neither is privileged in the model.
            progression: Progression::RightToLeft,
        }
    }
}

/// Renders one `.vertext` strip to HTML.
///
/// Without [`RenderOptions::whole_strip_code`] the input is split at the
/// reserved markers into prose/code segments, each laid out under its own
/// rule set.
pub fn render_document(input: &str, options: RenderOptions) -> String {
    let mut segments: Vec<(Mode, String)> = Vec::new();
    if options.whole_strip_code {
        segments.push((Mode::Code, input.to_owned()));
    } else {
        let mut current = (Mode::Prose, String::new());
        for ch in input.chars() {
            match Mode::from_marker(ch) {
                // A marker at the very start has nothing to close, so it
                // retargets the open segment instead of emitting an empty one.
                Some(mode) if current.1.is_empty() && segments.is_empty() => {
                    current = (mode, String::new());
                }
                Some(mode) => {
                    segments.push(std::mem::replace(&mut current, (mode, String::new())));
                }
                None => current.1.push(ch),
            }
        }
        if !current.1.is_empty() || segments.is_empty() {
            segments.push(current);
        }
    }

    let mut root_class = String::from("vertext");
    if options.whole_strip_code {
        root_class.push_str(" vertext-code");
    }
    if options.page {
        root_class.push_str(" vertext-page");
    }
    let advance = advance_keyword(options.progression);
    let mut html = format!(
        "<div class=\"{root_class}\" data-column-advance=\"{advance}\" \
         style=\"--vertext-latin-cap-prose:{PROSE_LATIN_CAP}ch;\
         --vertext-latin-cap-code:{CODE_LATIN_CAP}ch\">"
    );

    let mut emitted_any = false;
    let mut in_stack = false;
    for (mode, segment_text) in segments {
        let trimmed = segment_text.trim_end_matches('\n');
        // A wholly blank segment carries nothing and must stay transparent.
        // The separator newline between a heading and the fenced block under
        // it produces one, and treating it as content made it a vertical block
        // that split the two apart — the heading ended one horizontal stack
        // and its own code block started another.
        if trimmed.is_empty() {
            continue;
        }
        emitted_any = true;
        // `.vertext-code` is the author declaring "set this vertically as
        // code" — the showcase case. A fenced block inside ordinary prose is
        // the opposite instruction and goes horizontal. Same content, and the
        // difference is what the author asked for, never what we guessed.
        let block = if options.whole_strip_code { BlockKind::Vertical } else { mode.block(trimmed) };

        // Consecutive horizontal blocks stack vertically instead of each
        // claiming its own slot beside the columns. Without this a one-word
        // English heading takes a full column's width and leaves the height of
        // the page empty beneath it, with its own paragraph stranded in the
        // next slot over. Stacked, the heading sits on top and its text runs
        // underneath — which is how a heading and its paragraph relate.
        //
        // Tables join the stack for the same reason: a table's caption line
        // belongs above it and its commentary below, not beside it. A table
        // that happens to sit among vertical columns simply ends up alone in
        // its stack, which lays out exactly as it did before.
        let horizontal = matches!(block, BlockKind::Horizontal(_) | BlockKind::Table);
        if horizontal && !in_stack {
            html.push_str("<div class=\"vertext-hstack\">");
            in_stack = true;
        } else if !horizontal && in_stack {
            html.push_str("</div>");
            in_stack = false;
        }

        match block {
            BlockKind::Table => render_table(&mut html, trimmed, options.progression),
            BlockKind::Horizontal(kind) => render_horizontal(&mut html, trimmed, kind, mode),
            BlockKind::Vertical => {
                let layout = layout_text(trimmed, &mode.config(options.progression));
                let column_class = mode.column_class();
                for column in &layout.columns {
                    html.push_str(&format!("<div class=\"{column_class}\">"));
                    render_slots(&mut html, &column.slots);
                    html.push_str("</div>");
                }
                // Preserve a blank column for a paragraph break that ends the
                // segment (source newline immediately before a mode toggle).
                if trimmed.len() < segment_text.len() && !layout.columns.is_empty() {
                    html.push_str(&format!("<div class=\"{column_class}\"></div>"));
                }
            }
        }
    }
    if in_stack {
        html.push_str("</div>");
    }
    if !emitted_any {
        // Empty input must still produce a well-formed empty strip.
        html.push_str("<div class=\"vertext-column vertext-column-prose\"></div>");
    }
    html.push_str("</div>\n");
    html
}

/// A horizontal block: an orthogonal island in the vertical flow.
///
/// The wrap measure is published as a custom property rather than baked into
/// the stylesheet, for the same reason the Latin caps are — one source, no
/// drift. Line breaking is left to the browser, which has the font metrics.
fn render_horizontal(html: &mut String, text: &str, kind: HorizontalKind, mode: Mode) {
    let (kind_class, wrap) = match kind {
        HorizontalKind::Prose => ("vertext-horizontal-prose", kind.default_wrap()),
        HorizontalKind::Code => ("vertext-horizontal-code", kind.default_wrap()),
    };
    let heading_class = match mode {
        Mode::Heading(level) => format!(" vertext-horizontal-heading vertext-horizontal-h{level}"),
        Mode::ListItem { ordered } => {
            let kind = if ordered { " vertext-horizontal-list-ordered" } else { " vertext-horizontal-list-bullet" };
            format!(" vertext-horizontal-list{kind}")
        }
        _ => String::new(),
    };
    let tag = if matches!(kind, HorizontalKind::Code) { "pre" } else { "div" };
    html.push_str(&format!(
        "<div class=\"vertext-horizontal {kind_class}{heading_class}\" \
         style=\"--vertext-wrap:{wrap}ch\"><{tag}>{}</{tag}></div>",
        escape(text)
    ));
}

/// A table. Rows are separated by [`ROW_SEP`] and cells by [`CELL_SEP`].
///
/// Vertical text is the one place a table's structure falls out for free: a
/// row set as a column reads top-to-bottom as one entry, and successive rows
/// advance the way the surrounding text does. A markup `<table>` under
/// `writing-mode: vertical-rl` does exactly that transposition natively, so
/// the row stays a `<tr>` and the browser places it — no transposing here,
/// which keeps the markup honest for screen readers and for `display: block`
/// fallbacks.
///
/// Cell contents go through the ordinary slot layout, so a Mongolian cell
/// keeps its joined run and a Latin cell keeps its word slots. Cells do not
/// hyphenate: the column width is the constraint, and a romanization broken
/// across a hard hyphen is unreadable as a citation form.
fn render_table(html: &mut String, text: &str, progression: Progression) {
    let config = LayoutConfig { max_latin_word_width: usize::MAX, ..prose_config(progression) };
    html.push_str("<table class=\"vertext-table\">");
    for (index, row) in text.split(ROW_SEP).enumerate() {
        if row.is_empty() {
            continue;
        }
        let header = index == 0;
        let cell_tag = if header { "th" } else { "td" };
        html.push_str(if header {
            "<thead><tr class=\"vertext-row vertext-row-header\">"
        } else {
            "<tr class=\"vertext-row\">"
        });
        for cell in row.split(CELL_SEP) {
            html.push_str(&format!("<{cell_tag} class=\"vertext-cell\">"));
            let layout = layout_text(cell, &config);
            for column in &layout.columns {
                html.push_str("<div class=\"vertext-column vertext-column-cell\">");
                render_slots(html, &column.slots);
                html.push_str("</div>");
            }
            html.push_str(&format!("</{cell_tag}>"));
        }
        html.push_str(if header { "</tr></thead><tbody>" } else { "</tr>" });
    }
    html.push_str("</tbody></table>");
}

fn render_slots(html: &mut String, slots: &[Slot]) {
    for slot in slots {
        // Whitespace is emitted as the character the author typed, never a
        // stand-in glyph. Code indentation is made visible by the stylesheet
        // instead — a background, not a substitution, so the text a reader
        // copies is the text a writer wrote.
        let (class, body) = match slot {
            Slot::Upright(s) => ("vertext-upright", escape(s)),
            Slot::LatinWord(s) => ("vertext-latin", escape(s)),
            Slot::MongolianRun(s) => ("vertext-mongolian", escape(s)),
            Slot::Space(s) => ("vertext-space", escape(s)),
            // The character is emitted exactly as the author wrote it. The
            // vertical appearance is the stylesheet's job — see the note on
            // `Slot::VerticalPunctuation`.
            Slot::VerticalPunctuation(s) => ("vertext-vform", escape(s)),
            Slot::CornerPunctuation(s) => ("vertext-corner", escape(s)),
            Slot::Neutral(s) => ("vertext-neutral", escape(s)),
        };
        html.push_str(&format!("<span class=\"{class}\">{body}</span>"));
    }
}

/// Exposes the advance keyword for hosts that render their own shell.
pub fn column_advance(layout: &Layout) -> &'static str {
    advance_keyword(layout.progression)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn mode_markers_are_the_wire_protocol() {
        // These codepoints are duplicated as literals in
        // extensions/vertext/vertext.lua. Do not change one side alone.
        assert_eq!(MODE_CODE, '\u{E000}');
        assert_eq!(MODE_PROSE, '\u{E001}');
        assert_eq!(heading_marker(1), '\u{E002}');
        assert_eq!(heading_marker(6), '\u{E007}');
        // Out-of-range levels clamp rather than producing a stray codepoint.
        assert_eq!(heading_marker(0), heading_marker(1));
        assert_eq!(heading_marker(9), heading_marker(6));
    }

    #[test]
    fn every_marker_round_trips_to_its_mode() {
        assert_eq!(Mode::from_marker(MODE_CODE), Some(Mode::Code));
        assert_eq!(Mode::from_marker(MODE_PROSE), Some(Mode::Prose));
        assert_eq!(Mode::from_marker(MODE_TABLE), Some(Mode::Table));
        assert_eq!(Mode::from_marker(MODE_LIST), Some(Mode::ListItem { ordered: false }));
        assert_eq!(Mode::from_marker(MODE_LIST_ORDERED), Some(Mode::ListItem { ordered: true }));
        for level in 1..=MAX_HEADING_LEVEL {
            assert_eq!(Mode::from_marker(heading_marker(level)), Some(Mode::Heading(level)));
        }
        // Ordinary text must never be mistaken for a marker.
        // '\u{E00D}' is one past the last reserved codepoint and '\u{D7FF}'
        // sits below the whole block. Both must read as ordinary text.
        for ch in ['字', 'a', '\u{E00D}', '\u{D7FF}', '\u{E7FF}'] {
            assert_eq!(Mode::from_marker(ch), None, "{ch:?} should not be a marker");
        }
    }

    #[test]
    fn a_heading_segment_gets_its_level_on_the_column() {
        // A CJK heading stays vertical and carries its level on the column.
        let input = format!("{}中文{MODE_PROSE}山川", heading_marker(2));
        let html = render_document(&input, RenderOptions::default());
        assert!(html.contains("vertext-column-heading vertext-column-h2"));
        assert!(html.contains("vertext-column-prose vertext-column-heading"));
        assert!(!html.contains(heading_marker(2)));
        // A Latin heading goes horizontal and carries its level there instead.
        let latin = format!("{}Chinese{MODE_PROSE}山川", heading_marker(2));
        let html = render_document(&latin, RenderOptions::default());
        assert!(html.contains("vertext-horizontal-heading vertext-horizontal-h2"));
    }

    #[test]
    fn headings_do_not_leak_into_the_following_prose() {
        let input = format!("{}中文{MODE_PROSE}山川", heading_marker(2));
        let html = render_document(&input, RenderOptions::default());
        let heading_at = html.find("vertext-column-heading").unwrap();
        let prose_at = html.rfind("vertext-column-prose\"").unwrap();
        assert!(prose_at > heading_at, "the prose column must follow the heading column");
    }

    #[test]
    fn empty_input_produces_a_well_formed_empty_strip() {
        let html = render_document("", RenderOptions::default());
        assert!(html.contains("<div class=\"vertext-column vertext-column-prose\"></div>"));
        assert!(html.starts_with("<div class=\"vertext\""));
    }

    #[test]
    fn prose_and_code_segments_get_their_own_column_classes() {
        let input = format!("散文\n{MODE_CODE}let x = 1{MODE_PROSE}又散文");
        let html = render_document(&input, RenderOptions::default());
        // CJK prose stays vertical; the fenced code becomes a horizontal block.
        assert!(html.contains("vertext-column-prose"));
        assert!(html.contains("vertext-horizontal-code"));
        // The markers themselves must never reach the output.
        assert!(!html.contains(MODE_CODE));
        assert!(!html.contains(MODE_PROSE));
    }

    #[test]
    fn leading_code_marker_does_not_create_an_empty_prose_segment() {
        let input = format!("{MODE_CODE}code{MODE_PROSE}");
        let html = render_document(&input, RenderOptions::default());
        assert!(!html.contains("vertext-column-prose\"><"));
        assert!(html.contains("vertext-horizontal-code"));
    }

    #[test]
    fn whole_strip_code_sets_root_class_and_ignores_markers() {
        // `.vertext-code` is an explicit request for vertical code, so it
        // must NOT be turned horizontal by the orientation rule.
        let html = render_document("  let", RenderOptions { whole_strip_code: true, ..Default::default() });
        assert!(html.starts_with("<div class=\"vertext vertext-code\""));
        assert!(html.contains("vertext-space"), "indentation must survive");
        assert!(html.contains("vertext-column-code"), "must stay vertical");
        assert!(!html.contains("vertext-horizontal"));
    }

    #[test]
    fn latin_caps_are_published_as_css_custom_properties() {
        let html = render_document("字", RenderOptions::default());
        assert!(html.contains("--vertext-latin-cap-prose:12ch"));
        assert!(html.contains("--vertext-latin-cap-code:24ch"));
    }

    #[test]
    fn progression_reaches_the_dom_as_data() {
        let html = render_document("字", RenderOptions::default());
        assert!(html.contains("data-column-advance=\"left\""));
    }

    #[test]
    fn a_table_keeps_its_cells_apart() {
        let input = format!(
            "{MODE_TABLE}蒙古文{CELL_SEP}转写{ROW_SEP}ᠰᠠᠶᠢᠨ{CELL_SEP}sayin"
        );
        let html = render_document(&input, RenderOptions::default());
        assert!(html.contains("<table class=\"vertext-table\">"));
        assert!(html.contains("<th class=\"vertext-cell\">"));
        assert!(html.contains("<td class=\"vertext-cell\">"));
        // The failure this exists to prevent: cells welding into one run.
        assert!(!html.contains("蒙古文转写"));
        assert!(!html.contains("ᠰᠠᠶᠢᠨsayin"));
        // The Mongolian cell keeps its joined run rather than per-glyph slots.
        assert!(html.contains("<span class=\"vertext-mongolian\">ᠰᠠᠶᠢᠨ</span>"));
        assert!(!html.contains(CELL_SEP));
        assert!(!html.contains(ROW_SEP));
    }

    #[test]
    fn a_table_stacks_with_the_text_around_it() {
        // Caption above, table, commentary below — one stack, not three slots
        // side by side.
        let input = format!(
            "A vocabulary table follows.{MODE_TABLE}x{CELL_SEP}y{MODE_PROSE}\
             Read each column top to bottom."
        );
        let html = render_document(&input, RenderOptions::default());
        assert_eq!(html.matches("vertext-hstack").count(), 1);
        let stack = html.find("vertext-hstack").unwrap();
        let table = html.find("vertext-table").unwrap();
        let close = html.rfind("</div></div>").unwrap();
        assert!(stack < table && table < close, "the table must sit inside the stack");
    }

    #[test]
    fn table_cells_never_hyphenate() {
        // A romanization broken across a hard hyphen is unusable as a
        // citation form; the column width is the constraint instead.
        let input = format!("{MODE_TABLE}x{CELL_SEP}bayarlal_a_bayartai_teyimu");
        let html = render_document(&input, RenderOptions::default());
        assert!(html.contains("bayarlal_a_bayartai_teyimu"));
        assert!(!html.contains('‐'));
    }

    #[test]
    fn latin_prose_is_set_horizontally_and_cjk_is_not() {
        let english = render_document(
            "It is a truth universally acknowledged, that a single man",
            RenderOptions::default(),
        );
        assert!(english.contains("vertext-horizontal-prose"));
        assert!(english.contains("--vertext-wrap:66ch"));
        assert!(!english.contains("vertext-column-prose\">"));

        let chinese = render_document("山川异域，风月同天。", RenderOptions::default());
        assert!(chinese.contains("vertext-column-prose"));
        assert!(!chinese.contains("vertext-horizontal"));
    }

    #[test]
    fn fenced_code_is_horizontal_at_the_code_measure() {
        let input = format!("{MODE_CODE}fn main() {{}}{MODE_PROSE}");
        let html = render_document(&input, RenderOptions::default());
        assert!(html.contains("vertext-horizontal-code"));
        assert!(html.contains("--vertext-wrap:80ch"));
        assert!(html.contains("<pre>"));
        // Source must still be escaped inside the pre.
        let injected = format!("{MODE_CODE}<script>{MODE_PROSE}");
        assert!(!render_document(&injected, RenderOptions::default()).contains("<script>"));
    }

    #[test]
    fn mongolian_progression_reaches_the_dom_and_the_layout() {
        let options = RenderOptions {
            progression: Progression::LeftToRight,
            ..Default::default()
        };
        let html = render_document("ᠮᠣᠩᠭᠤᠯ\nᠤᠯᠤᠰ", options);
        // `right` means columns advance rightward: vertical-lr, the Mongolian
        // direction. Getting this backwards does not look wrong, it reads the
        // document in reverse order.
        assert!(html.contains("data-column-advance=\"right\""));
        assert!(!html.contains("data-column-advance=\"left\""));
        // And the default stays CJK for every document that does not declare.
        let cjk = render_document("山川", RenderOptions::default());
        assert!(cjk.contains("data-column-advance=\"left\""));
    }

    /// The renderer must never substitute a character. Presentation forms
    /// like U+FE35 look right and destroy the document: copy-paste, find,
    /// and screen readers all yield codepoints the author never typed. The
    /// view rotates; the text is untouched.
    #[test]
    fn punctuation_is_never_substituted() {
        let source = "好（天）：川、月。—…「引」";
        let html = render_document(source, RenderOptions::default());
        for original in ['（', '）', '：', '、', '。', '—', '…', '「', '」'] {
            assert!(html.contains(original), "{original} must survive verbatim");
        }
        // Nothing from the vertical presentation blocks may appear.
        for ch in html.chars() {
            let c = ch as u32;
            assert!(!(0xFE10..=0xFE19).contains(&c), "presentation form {ch:?} leaked in");
            assert!(!(0xFE30..=0xFE4F).contains(&c), "presentation form {ch:?} leaked in");
        }
    }

    #[test]
    fn page_mode_marks_the_root() {
        let html = render_document("字", RenderOptions { page: true, ..Default::default() });
        assert!(html.starts_with("<div class=\"vertext vertext-page\""));
    }

    #[test]
    fn user_text_is_escaped() {
        let html = render_document("<script>", RenderOptions::default());
        assert!(!html.contains("<script>"));
        assert!(html.contains("&lt;"));
    }

    #[test]
    fn trailing_newline_before_mode_toggle_keeps_a_blank_column() {
        let input = format!("散文\n{MODE_CODE}code{MODE_PROSE}");
        let html = render_document(&input, RenderOptions::default());
        assert!(html.contains("<div class=\"vertext-column vertext-column-prose\"></div>"));
    }
}
