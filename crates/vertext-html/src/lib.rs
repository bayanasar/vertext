//! The shared `Layout` → HTML renderer.
//!
//! Every HTML-producing host — the CLI today, `vertext-wasm` tomorrow — goes
//! through this crate, so the slot-to-class mapping and the mode protocol are
//! defined exactly once. The crate is `wasm32`-clean: no I/O, strings in,
//! strings out.

use vertext_core::{
    is_mongolian, layout_text, layout_with_source_map, prefers_horizontal, HorizontalKind,
    Layout, LayoutConfig, Progression, Slot, SourceMap,
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
/// One past the last reserved codepoint — exclusive, like every other Rust
/// upper bound. The filter strips `MODE_CODE ..RESERVED_END` from author
/// text; keep the two in step. `vertext.lua` expresses the same bound as
/// `MODE_CODE_POINT + RESERVED_COUNT`, and
/// `the_reserved_range_ends_where_the_filter_stops_stripping` pins them to
/// each other.
pub const RESERVED_END: u32 = 0xE00D;

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
    let last_index = segments.len().saturating_sub(1);
    for (index, (mode, segment_text)) in segments.into_iter().enumerate() {
        let trimmed = segment_text.trim_end_matches(['\n', '\r']);
        // Counted, not merely detected: the LAST segment's first trailing
        // newline is the file's line terminator, and every later one is the
        // author's. Counting '\n' inside the trimmed run keeps CRLF input
        // answering the same as LF.
        let trailing_newlines = segment_text[trimmed.len()..].matches('\n').count();
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
                    render_slots(&mut html, &column.slots, mode != Mode::Code);
                    html.push_str("</div>");
                }
                // Preserve a blank column for a paragraph break that ends the
                // segment (source newline immediately before a mode toggle).
                //
                // Except at the end of the input, where the last newline is the
                // file's terminator and not a break the author typed. Every
                // document ends with one, so counting it put a blank column at
                // the foot of every strip -- six of them on one real page,
                // each holding open a column's width of nothing. A blank line
                // deliberately left at the end still reads as a break: it is
                // the SECOND trailing newline that carries the intent.
                let ends_the_input = index == last_index;
                let author_broke = if ends_the_input {
                    trailing_newlines > 1
                } else {
                    trailing_newlines > 0
                };
                if author_broke && !layout.columns.is_empty() {
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
/// Wrap each Mongolian run in a span the stylesheet can reach, escaping as it
/// goes.
///
/// A horizontal block does not go through slot layout — its text is passed
/// through whole — so the runs inside it carry no class, and the stylesheet's
/// Mongolian `font-family` lives on `.vertext-mongolian`, which only the
/// vertical path emits. The result was measured in a real browser: bichig in a
/// Latin-majority line renders in whatever face the browser falls back to, and
/// with `init`/`medi`/`fina` switched off it does not change at all — nothing
/// was joining it.
///
/// The class is a *different* one on purpose. `.vertext-mongolian` also
/// declares `display: inline-block` and `writing-mode: vertical-lr`; reusing it
/// here would stand the run upright inside a horizontal line, trading a font
/// defect for a layout one. This one carries the face and nothing else.
///
/// U+202F is taken into the run when Mongolian holds it on both sides, for the
/// same reason the layout keeps it inside `Slot::MongolianRun`: it is the joint
/// of a suffix, and a font that receives it split receives two words.
fn mark_mongolian_runs(text: &str) -> String {
    let chars: Vec<char> = text.chars().collect();
    let in_run = |index: usize| -> bool {
        let ch = chars[index];
        if is_mongolian(ch) {
            return true;
        }
        if ch != '\u{202F}' {
            return false;
        }
        let before = index.checked_sub(1).map(|i| is_mongolian(chars[i])).unwrap_or(false);
        let after = chars.get(index + 1).copied().map(is_mongolian).unwrap_or(false);
        before && after
    };

    let mut html = String::with_capacity(text.len());
    let mut index = 0;
    while index < chars.len() {
        if in_run(index) {
            let start = index;
            while index < chars.len() && in_run(index) {
                index += 1;
            }
            let run: String = chars[start..index].iter().collect();
            html.push_str("<span class=\"vertext-mongolian-inline\">");
            html.push_str(&escape(&run));
            html.push_str("</span>");
        } else {
            let start = index;
            while index < chars.len() && !in_run(index) {
                index += 1;
            }
            let plain: String = chars[start..index].iter().collect();
            html.push_str(&escape(&plain));
        }
    }
    html
}

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
    // Prose only. Code keeps its monospace face deliberately, and a span that
    // changed the family mid-line would break the column alignment that is the
    // whole point of setting code in monospace. Bichig inside a code block is
    // therefore still unstyled; it is rare, and trading one visible defect for
    // another silently is how this one got here.
    let body = match kind {
        HorizontalKind::Prose => mark_mongolian_runs(text),
        HorizontalKind::Code => escape(text),
    };
    html.push_str(&format!(
        "<div class=\"vertext-horizontal {kind_class}{heading_class}\" \
         style=\"--vertext-wrap:{wrap}ch\"><{tag}>{body}</{tag}></div>"
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
                // A cell never wraps, so there is no line edge to keep.
                render_slots(html, &column.slots, false);
                html.push_str("</div>");
            }
            html.push_str(&format!("</{cell_tag}>"));
        }
        html.push_str(if header { "</tr></thead><tbody>" } else { "</tr>" });
    }
    html.push_str("</tbody></table>");
}

/// The name of a slot's kind: the suffix of its class on the page
/// (`vertext-upright`), and the kind a host that draws its own slots reads.
/// One table, so such a host classifies every slot exactly as the page does.
pub fn slot_kind(slot: &Slot) -> &'static str {
    match slot {
        Slot::Upright(_) => "upright",
        Slot::LatinWord(_) => "latin",
        Slot::MongolianRun(_) => "mongolian",
        Slot::Space(_) => "space",
        // The character is emitted exactly as the author wrote it. The
        // vertical appearance is the stylesheet's job — see the note on
        // `Slot::VerticalPunctuation`.
        Slot::VerticalPunctuation(_) => "vform",
        Slot::CornerPunctuation(_) => "corner",
        Slot::Neutral(_) => "neutral",
        Slot::Combined(_) => "combine",
    }
}

/// Emits a column's slots, one span each, in order.
///
/// A Latin word, a number and a Mongolian run are each one box on the page,
/// and a line may break on either side of a box wherever it falls: the
/// browser's line-start and line-end rules (CLReq 6.1.1) look at the
/// characters beside a mark, and a box is not one. So in prose (`keep_edges`)
/// a box goes into one `vertext-nobreak` span with the marks right after it
/// that may not begin a line and the opening marks right before it, and that
/// span does not wrap. Connector marks, interpuncts and solidi may not begin
/// a line either, and the browser lets most of them even beside Han, so any
/// slot they follow is held to them the same way. Only the breaks change:
/// the slots, their order and their text are what they were, and a slot
/// span's parent is its column or such a span. In code no line edge is kept,
/// as the marks there are code.
fn render_slots(html: &mut String, slots: &[Slot], keep_edges: bool) {
    let mut i = 0;
    while i < slots.len() {
        let (start, end) = if keep_edges { keep_together(slots, i) } else { (i, i + 1) };
        let grouped = end - start > 1;
        if grouped {
            html.push_str("<span class=\"vertext-nobreak\">");
        }
        for slot in &slots[start..end] {
            // Whitespace is emitted as the character the author typed, never a
            // stand-in glyph. Code indentation is made visible by the
            // stylesheet instead — a background, not a substitution, so the
            // text a reader copies is the text a writer wrote.
            html.push_str(&format!("<span class=\"vertext-{}\">{}</span>",
                                   slot_kind(slot), escape(slot.text())));
        }
        if grouped {
            html.push_str("</span>");
        }
        i = end;
    }
}

/// The slots from `i` on that must share a line: `i..i + 1` unless opening
/// marks from `i` lead up to a box, or the slot at `i` is a box; then the
/// opening marks, the box, and the marks after it that may not begin a line.
/// Or unless the slot after `i` is a connector mark, an interpunct or a
/// solidus: the browser lets those begin a line beside Han too, so the slot
/// at `i` holds them, and the marks after them, the same way.
fn keep_together(slots: &[Slot], i: usize) -> (usize, usize) {
    let is_box = |slot: &Slot| matches!(slot, Slot::LatinWord(_) | Slot::MongolianRun(_));
    let mut b = i;
    while b < slots.len() && may_not_end_a_line(&slots[b]) {
        b += 1;
    }
    let held = if b < slots.len() && is_box(&slots[b]) {
        b
    } else if i + 1 < slots.len() && !matches!(slots[i], Slot::Space(_)) && joins(slots, i + 1) {
        i
    } else {
        return (i, i + 1);
    };
    let mut end = held + 1;
    while end < slots.len() && may_not_start_a_line(slots, end) {
        end += 1;
    }
    (i, end)
}

/// CLReq 6.1.1's marks that do not begin a line: a closing bracket or
/// quotation mark, or a pause or stop mark, fullwidth or halfwidth, and a
/// pair of question and exclamation marks; and a connector mark, an
/// interpunct or a solidus (`joins`).
fn may_not_start_a_line(slots: &[Slot], i: usize) -> bool {
    joins(slots, i) || match &slots[i] {
        Slot::Combined(_) => true,
        Slot::VerticalPunctuation(s) | Slot::CornerPunctuation(s) | Slot::Neutral(s) =>
            matches!(s.as_str(),
                "）" | "］" | "｝" | "〕" | "〉" | "》" | "」" | "』" | "】" | "〙" | "〗" | "｠"
                | "〞" | "〟" | ")" | "]" | "}" | "’" | "”"
                | "、" | "，" | "。" | "．" | "；" | "：" | "！" | "？"
                | "," | "." | ";" | ":" | "!" | "?"),
        _ => false,
    }
}

/// A connector mark, an interpunct or a solidus, as CLReq's tables of marks
/// list them: none may begin a line, and the browser keeps few of them off
/// one even beside Han. A lone `—` is a connector; two are a dash, which may
/// begin a line, and which the browser keeps whole.
fn joins(slots: &[Slot], i: usize) -> bool {
    let dash = |j: Option<usize>| j.and_then(|j| slots.get(j)).is_some_and(|s| s.text() == "—");
    match &slots[i] {
        Slot::LatinWord(_) | Slot::MongolianRun(_) | Slot::Space(_) => false,
        slot if slot.text() == "—" => !dash(Some(i + 1)) && !dash(i.checked_sub(1)),
        slot => matches!(slot.text(), "～" | "〜" | "-" | "–" | "·" | "・" | "‧" | "/" | "／"),
    }
}

/// An opening bracket or quotation mark: CLReq 6.1.1's marks that do not end
/// a line.
fn may_not_end_a_line(slot: &Slot) -> bool {
    match slot {
        Slot::VerticalPunctuation(s) | Slot::CornerPunctuation(s) | Slot::Neutral(s) =>
            matches!(s.as_str(),
                "（" | "［" | "｛" | "〔" | "〈" | "《" | "「" | "『" | "【" | "〘" | "〖" | "｟"
                | "〝" | "(" | "[" | "{" | "‘" | "“"),
        _ => false,
    }
}

/// One run of text laid out as a single vertical strip, for a host that
/// places slots itself: the layout and its source map, column for column what
/// [`render_document`] draws for the same input. `None` where it would not set
/// the text as one strip: outside code, the text carries a mode marker, or its
/// Latin outweighs its vertical script and it goes horizontal. In code the
/// page reads no markers, and neither does this; any other private-use
/// character is text on the page and is text here.
///
/// The line breaks at the end follow the page too: the last is the file's
/// terminator and draws nothing, and any before it, however many, draw one
/// blank column.
pub fn strip_layout(input: &str, code: bool, progression: Progression)
                    -> Option<(Layout, SourceMap)> {
    let trimmed = input.trim_end_matches(['\n', '\r']);
    if !code && trimmed.chars().any(|c| Mode::from_marker(c).is_some()) {
        return None;
    }
    if !code && prefers_horizontal(trimmed) {
        return None;
    }
    // Keep the first trailing break when there is more than one: laid out, it
    // opens the blank column the page adds, and it is a slice of the input, so
    // the source map still points into it.
    let rest = &input[trimmed.len()..];
    let text = if !trimmed.is_empty() && rest.matches('\n').count() > 1 {
        &input[..trimmed.len() + if rest.starts_with("\r\n") { 2 } else { 1 }]
    } else {
        trimmed
    };
    let config = if code { code_config(progression) } else { prose_config(progression) };
    Some(layout_with_source_map(text, &config))
}

/// Exposes the advance keyword for hosts that render their own shell.
pub fn column_advance(layout: &Layout) -> &'static str {
    advance_keyword(layout.progression)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The Rust upper bound and the Lua strip loop must name the same edge.
    ///
    /// `RESERVED_END` exists for one reason — "keep the two in step" — and
    /// until now nothing checked that it did. It said "one past the last"
    /// while holding the last, so anyone implementing a stripper from its own
    /// documentation would have left `MODE_LIST_ORDERED` in the author's text:
    /// an ordered-list marker surviving into a document, no error, no warning.
    ///
    /// `vertext.lua` writes the same edge as `MODE_CODE_POINT +
    /// RESERVED_COUNT`, with `RESERVED_COUNT = 13`. Changing either side alone
    /// now fails here.
    #[test]
    fn the_reserved_range_ends_where_the_filter_stops_stripping() {
        assert_eq!(RESERVED_END, MODE_LIST_ORDERED as u32 + 1);
        assert_eq!(RESERVED_END, MODE_CODE as u32 + 13);
        assert!(Mode::from_marker(MODE_LIST_ORDERED).is_some());
        assert!(char::from_u32(RESERVED_END).and_then(Mode::from_marker).is_none());
    }

    /// The columns a host is handed are the columns the page draws, counted
    /// per column: blank ones included, and with the page's reading of
    /// private-use characters.
    #[test]
    fn a_strip_has_the_columns_the_page_draws() {
        let page_columns = |input: &str, code: bool| -> Vec<usize> {
            let html = render_document(input, RenderOptions {
                whole_strip_code: code, page: false, progression: Progression::RightToLeft,
            });
            html.split("<div class=\"vertext-column").skip(1)
                .map(|column| column.split("</div>").next().unwrap().matches("<span").count())
                .collect()
        };
        let strip_columns = |input: &str, code: bool| -> Option<Vec<usize>> {
            strip_layout(input, code, Progression::RightToLeft)
                .map(|(layout, _)| layout.columns.iter().map(|c| c.slots.len()).collect())
        };
        for (input, code) in [
            ("第一行\r\n\r\n第三行\n\n", false),
            ("第一行\n", false),
            ("第一行\n\n\n\n", false),
            ("第一行\r\n\r\n", false),
            ("ᠮᠣᠩᠭᠣᠯ\n\n", false),
            ("let x = 1;\n\n", true),
            ("山川\u{E0A0}字", false),
            ("山川\u{E009}字", false),
            ("山川\u{E000}x", true),
        ] {
            assert_eq!(strip_columns(input, code), Some(page_columns(input, code)),
                       "{input:?} code {code}");
        }
        // A marker the page reads splits the text into blocks: no one strip.
        assert_eq!(strip_columns("山川\u{E000}x", false), None);
        assert_eq!(strip_columns("\u{E002}標題\u{E001}正文", false), None);
    }

    #[test]
    fn mode_markers_are_the_wire_protocol() {
        // These codepoints are duplicated as literals in
        // extensions/vertext/vertext.lua. Do not change one side alone.
        assert_eq!(MODE_CODE, '\u{E000}');
        assert_eq!(MODE_PROSE, '\u{E001}');
        assert_eq!(heading_marker(1), '\u{E002}');
        assert_eq!(heading_marker(2), '\u{E003}');
        assert_eq!(heading_marker(3), '\u{E004}');
        assert_eq!(heading_marker(4), '\u{E005}');
        assert_eq!(heading_marker(5), '\u{E006}');
        assert_eq!(heading_marker(6), '\u{E007}');
        assert_eq!(MODE_TABLE, '\u{E008}');
        assert_eq!(CELL_SEP, '\u{E009}');
        assert_eq!(ROW_SEP, '\u{E00A}');
        assert_eq!(MODE_LIST, '\u{E00B}');
        assert_eq!(MODE_LIST_ORDERED, '\u{E00C}');
        // Every reserved codepoint is pinned above. A round-trip test cannot
        // stand in for this one: it compares a constant against itself, so
        // renumbering MODE_TABLE would leave it green while the literal in
        // extensions/vertext/vertext.lua silently means something else.
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

    /// CLReq 6.1.1's connector marks, interpuncts and solidi. The browser lets
    /// some of them begin a line even beside Han, so each shares a span that
    /// does not wrap with the slot before it.
    #[test]
    fn a_connector_an_interpunct_or_a_solidus_holds_to_the_slot_before_it() {
        let slot = |kind: &str, text: &str| format!("<span class=\"vertext-{kind}\">{text}</span>");
        let kept = |slots: &[String]| format!("<span class=\"vertext-nobreak\">{}</span>", slots.concat());
        let html = render_document("永～永·永／永・见2000～2010与〝sayin〞", RenderOptions::default());
        // Beside Han, where the browser lets them begin a line.
        assert!(html.contains(&kept(&[slot("upright", "永"), slot("vform", "～")])), "{html}");
        assert!(html.contains(&kept(&[slot("upright", "永"), slot("neutral", "·")])), "{html}");
        assert!(html.contains(&kept(&[slot("upright", "永"), slot("neutral", "／")])), "{html}");
        assert!(html.contains(&kept(&[slot("upright", "永"), slot("upright", "・")])), "{html}");
        // Beside a box, and the vertical quotation marks around one.
        assert!(html.contains(&kept(&[slot("latin", "2000"), slot("vform", "～")])), "{html}");
        assert!(html.contains(&kept(&[slot("neutral", "〝"), slot("latin", "sayin"),
                                      slot("neutral", "〞")])), "{html}");
        // A lone `—` is a connector; two are a dash, which may begin a line.
        let html = render_document("北京—上海，永——永", RenderOptions::default());
        assert!(html.contains(&kept(&[slot("upright", "京"), slot("vform", "—")])), "{html}");
        assert_eq!(html.matches("vertext-nobreak").count(), 1, "{html}");
    }

    /// CLReq 6.1.1 beside a box. A line may break on either side of a Latin
    /// word, a number or a Mongolian run, so each shares a span that does not
    /// wrap with the marks that may not leave it at a line edge.
    #[test]
    fn a_box_and_the_marks_that_hold_to_it_share_a_span() {
        let slot = |kind: &str, text: &str| format!("<span class=\"vertext-{kind}\">{text}</span>");
        let kept = |slots: &[String]| format!("<span class=\"vertext-nobreak\">{}</span>", slots.concat());
        let input = "永sayin，见（2026）。读《ᠮᠣᠩᠭᠣᠯ》a，b永，「永」";
        let html = render_document(input, RenderOptions::default());
        assert!(html.contains(&kept(&[slot("latin", "sayin"), slot("corner", "，")])), "{html}");
        assert!(html.contains(&kept(&[slot("vform", "（"), slot("latin", "2026"),
                                      slot("vform", "）"), slot("corner", "。")])), "{html}");
        assert!(html.contains(&kept(&[slot("vform", "《"), slot("mongolian", "ᠮᠣᠩᠭᠣᠯ"),
                                      slot("vform", "》")])), "{html}");
        assert!(html.contains(&kept(&[slot("latin", "a"), slot("corner", "，")])), "{html}");
        // A box with no mark beside it, and marks beside a Han character, are
        // left to the browser, which keeps those itself.
        assert_eq!(html.matches("vertext-nobreak").count(), 4, "{html}");
        // The text is the text: a span adds no character.
        let mut text = String::new();
        let mut in_tag = false;
        for ch in html.chars() {
            match ch {
                '<' => in_tag = true,
                '>' => in_tag = false,
                _ if !in_tag => text.push(ch),
                _ => {}
            }
        }
        assert_eq!(text.trim_end_matches('\n'), input);
        // In code the marks are code, and no edge is kept.
        let code = render_document("x，(y)，", RenderOptions { whole_strip_code: true, ..Default::default() });
        assert!(!code.contains("vertext-nobreak"), "{code}");
        // A run of opening marks holds to the box as a whole, as a run of
        // closing marks does.
        let html = render_document("永「（sayin）」永", RenderOptions::default());
        assert!(html.contains(&kept(&[slot("vform", "「"), slot("vform", "（"), slot("latin", "sayin"),
                                      slot("vform", "）"), slot("vform", "」")])), "{html}");
        // A table cell is not prose, and keeps nothing together.
        let table = render_document("\u{E008}名\u{E009}sayin，\u{E001}", RenderOptions::default());
        assert!(table.contains(&slot("latin", "sayin")), "{table}");
        assert!(!table.contains("vertext-nobreak"), "{table}");
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
    fn bichig_in_a_horizontal_line_carries_a_face_it_can_join_with() {
        // The defect this pins was measured in a browser before it was fixed:
        // on the horizontal path the runs carried no class, the stylesheet's
        // Mongolian family lives on one, and with init/medi/fina switched off
        // the render did not change by a single pixel -- nothing was joining
        // it. Real glyphs, wrong font, grammar severed.
        let html = render_document(
            "ene minU eji (ᠡᠨᠡ ᠮᠢᠨᠦ ᠡᠵᠢ) is my mother.",
            RenderOptions::default(),
        );
        assert!(html.contains("vertext-horizontal-prose"), "this line is horizontal");
        assert!(
            html.contains("<span class=\"vertext-mongolian-inline\">ᠡᠨᠡ</span>"),
            "each run is marked so the stylesheet can reach it: {html}"
        );
        // Not the vertical class: that one also declares writing-mode, which
        // would stand the run upright inside a line of English.
        assert!(!html.contains("\"vertext-mongolian\""));
        // The Latin around it is untouched, and still escaped.
        assert!(html.contains("ene minU eji ("));
    }

    #[test]
    fn a_suffix_joint_stays_inside_one_inline_run() {
        // Same reason the layout keeps U+202F inside Slot::MongolianRun: split
        // across two spans, the font sees two words and the genitive breaks.
        let html = render_document(
            "the genitive ᠮᠣᠩᠭᠣᠯ\u{202F}ᠤᠨ is one word in this sentence",
            RenderOptions::default(),
        );
        assert!(html.contains("vertext-horizontal-prose"));
        assert!(
            html.contains("<span class=\"vertext-mongolian-inline\">ᠮᠣᠩᠭᠣᠯ\u{202F}ᠤᠨ</span>"),
            "the joint is inside the run: {html}"
        );
    }

    #[test]
    fn marking_runs_does_not_stop_escaping_the_rest() {
        let html = render_document(
            "a & b <tag> and ᠨᠣᠮ in a mostly Latin line of prose here",
            RenderOptions::default(),
        );
        assert!(html.contains("vertext-horizontal-prose"));
        assert!(html.contains("a &amp; b &lt;tag&gt;"), "{html}");
        assert!(html.contains("<span class=\"vertext-mongolian-inline\">ᠨᠣᠮ</span>"));
    }

    #[test]
    fn code_keeps_its_monospace_face() {
        // Deliberate: a family change mid-line breaks the column alignment that
        // is the whole point of setting code in monospace.
        let input = format!("{MODE_CODE}let x = \"ᠨᠣᠮ\";{MODE_PROSE}");
        let html = render_document(&input, RenderOptions::default());
        assert!(html.contains("vertext-horizontal-code"));
        assert!(!html.contains("vertext-mongolian-inline"), "{html}");
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

    /// A case ending reaches the DOM inside its stem's span.
    ///
    /// This is the artifact the browser actually shapes. Split across two
    /// spans with a `vertext-space` between them, the stylesheet gives that
    /// space a fixed half-em box (`.vertext-space { height: .5em }`) and the
    /// suffix drops a row: a genitive set as a separate word. One span is also
    /// what lets the font join across the joint and keeps the browser from
    /// breaking a line there, which U+202F forbids.
    #[test]
    fn a_suffix_separator_reaches_the_dom_inside_the_run() {
        let options = RenderOptions {
            progression: Progression::LeftToRight,
            ..Default::default()
        };
        let html = render_document("ᠮᠣᠩᠭᠣᠯ\u{202F}ᠤᠨ", options);
        assert!(html.contains("<span class=\"vertext-mongolian\">ᠮᠣᠩᠭᠣᠯ\u{202F}ᠤᠨ</span>"),
            "the stem and its case ending must share one span: {html}");
        assert!(!html.contains("vertext-space"),
            "no word space belongs inside a suffixed word: {html}");
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

    const BLANK_COLUMN: &str = "<div class=\"vertext-column vertext-column-prose\"></div>";

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

    // The three below divide one condition that used to be a single "were any
    // trailing newlines trimmed?". Every file ends with a newline, so that
    // question was answered yes for every document ever rendered, and each one
    // carried a blank column at its foot holding open a column's width of
    // nothing -- six on one real page. What the blank column is FOR is a
    // break the author typed, which is why the toggle case above still keeps
    // one and why a deliberate blank line at the end still counts.

    #[test]
    fn the_terminating_newline_is_not_a_paragraph_break() {
        let html = render_document("散文\n", RenderOptions::default());
        assert!(!html.contains(BLANK_COLUMN), "{html}");
    }

    #[test]
    fn a_blank_line_left_at_the_end_still_is_one() {
        let html = render_document("散文\n\n", RenderOptions::default());
        assert!(html.contains(BLANK_COLUMN), "{html}");
    }

    #[test]
    fn crlf_answers_the_same_as_lf_at_the_end() {
        let terminator = render_document("散文\r\n", RenderOptions::default());
        let break_too = render_document("散文\r\n\r\n", RenderOptions::default());
        assert!(!terminator.contains(BLANK_COLUMN), "{terminator}");
        assert!(break_too.contains(BLANK_COLUMN), "{break_too}");
    }
}
