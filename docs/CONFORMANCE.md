# Conformance

Where vertext stands against the W3C layout requirements for the scripts it
sets, section by section. The rest of `docs/` explains how vertext is built
and why; this document measures it against a standard somebody else wrote.

| Document | Version read |
|---|---|
| [CLReq](https://www.w3.org/TR/clreq/), Requirements for Chinese Text Layout | Group Note Draft, 1 September 2026 |
| [MLReq](https://www.w3.org/TR/mlreq/), Mongolian Layout Requirements | Group Draft Note, 10 July 2025 |
| [Chinese Layout Gap Analysis](https://www.w3.org/TR/clreq-gap/) | Group Draft Note, 31 October 2025 |

This page ages with those documents, not with commits. Re-read it when one of
them publishes a new version, or when vertext changes a behaviour listed here.

## How to read it

vertext has two parts. The engine turns text into columns of classified slots.
The stylesheet and the browser then set those slots. Line breaking, kinsoku,
justification and font choice happen in the browser, and that split is a design
decision (see "What the engine does not decide" in the README). So a
requirement can be met by vertext, handed to the browser, or not met at all.
The table says which.

| Status | Meaning |
|---|---|
| **Conforms** | Met, and a test or measurement that has actually run shows it. The evidence column names it. |
| **Partial** | Some of it is met, or it looks right but nothing has measured it. The note says which. |
| **Not implemented** | Not met. The note says whether that is by design (the browser's job, print-only) or simply not built. |
| **Informative** | The section describes the script and states no requirement. |

Sections are the unit. A section that mixes several requirements takes the
status of the weakest one, and the note names the parts. Evidence is either a
`cargo test` name (Rust tests in `crates/`), a CI gate (a step in
`.forgejo/workflows/ci.yml`), or a measurement recorded in `PROGRESS.md`.

## Summary

Rows in the tables below (a row is a section, or a group of sections that share
a verdict):

| | Conforms | Partial | Not implemented | Informative |
|---|---|---|---|---|
| CLReq | 9 | 12 | 22 | 3 |
| MLReq | 3 | 12 | 7 | 3 |

The pattern is the same in both. Direction, orientation, keeping words whole
and preserving the text are met and tested. Anything that needs the engine to
measure (justification, punctuation compression, widows, hanging punctuation),
anything that needs markup vertext does not carry (ruby, emphasis marks,
interlinear lines, decoration), and anything print-only (pages, running heads,
page numbers) is not met.

Three findings are worth reading before the tables:

- **Punctuation placement is the face's.** The pause and stop marks, the
  fullwidth colon among them, never turn. Where they sit is regional, and a
  CJK face's vertical forms already place them by region, so vertext moves
  nothing: a Mainland face puts them in the corner, a Taiwan face centres
  them. Until October 2026 vertext translated them again over the face, which
  pushed a comma past the top of its frame and gave Taiwan text the Mainland
  position, and it classed the colon with the marks that turn. One limit is a
  face's, not vertext's: a face that serves every region may not switch its
  vertical forms with the language (Noto Sans CJK SC under `zh-TW` switches
  `！？` and not `、，。．；：`), so a Taiwan page wants a Taiwan face.
- **Every Latin run is set horizontally in the column.** That includes acronyms,
  words and digits. CLReq describes three treatments by kind: acronyms upright
  letter by letter, words rotated 90° clockwise, and 2–3 digit numbers
  horizontal-in-vertical. vertext uses only the third, for all of them.
- **In the Mongolian golden font, U+202F is as wide as a space.** The engine
  keeps the suffix joint inside its word, as MLReq requires. But MLReq 6.2.2 also
  asks for the gap before a suffix to differ from the gap between words, and the
  shaping golden records `nnbsp` and `space` at the same advance.

## CLReq

### 2 Text direction

| Section | Status | Note | Evidence |
|---|---|---|---|
| 2.1.1 Writing modes in Chinese | Informative | Both modes exist: vertical columns, with horizontal blocks for Latin-majority prose, code and tables. | |
| 2.1.2 Arrangement of characters and lines | Conforms | Characters run top to bottom and columns advance right to left. Progression is data, not a constant. | `a_newline_creates_the_column_to_the_left`, `progression_reaches_the_dom_as_data`, gate `progression-scroll` |
| 2.1.2 Punctuation position | Conforms | `、，。．；：` and `！？` never turn. They are placed by the face's vertical forms: in Noto Sans SC to the right and, for the short marks, in the upper half (Mainland); in Noto Sans TC at the centre, under `zh-TW`, `zh-HK` and `zh-Hant`. A face that does not switch its forms with the language keeps its own region's placement. | `the_punctuation_contract`, gate `punctuation-ink` |
| 2.1.2 Western text in vertical | Partial | Only horizontal-in-vertical is used, for every Latin or digit run. No upright acronyms, no rotation. Runs longer than 12 characters break with a visible hyphen. | `long_latin_words_are_bounded`, `a_long_word_breaks_at_the_hyphen_it_already_has` |
| 2.1.2 Table captions | Not implemented | The wire protocol carries no caption. | |
| 2.1.2 Table header row on the right | Partial | Header cells are real `<th>` and the table is `vertical-rl`, so the header row falls on the right. Nothing measures where it lands. | `a_table_keeps_its_cells_apart` |
| 2.1.2 Incomplete lines on multi-column pages | Not implemented | No pagination. | |
| 2.1.3 Mixed text composition in vertical | Partial | As 2.1.2. No Han–Western spacing is applied (CLReq: up to ¼ em). Quotation marks around Western text do not follow its orientation: `“”` always take the vertical form. | |

### 3 Glyph shaping and positioning

| Section | Status | Note | Evidence |
|---|---|---|---|
| 3.1.1 Song, Kai, Hei, Fangsong | Not implemented | Typeface is the page's choice. The stylesheet names no CJK family. | |

### 4 Typographic units

| Section | Status | Note | Evidence |
|---|---|---|---|
| 4.1 Characters and encoding | Conforms | Layout never changes a character: no fullwidth substitution, no presentation forms, variation selectors kept with their base. | `layout_never_alters_a_single_character`, `punctuation_is_never_substituted`, `a_variation_selector_stays_with_its_ideograph` |
| 4.1.1 Erhua (U+16FF2) | Partial | Set upright in its own slot. Its reduced size is the font's business, and nothing checks it. | |

### 5 Punctuation and inline features

| Section | Status | Note | Evidence |
|---|---|---|---|
| 5.1 Phrase and section boundaries | Partial | Dashes (`—`, `⸺` and the rest of the family), ellipses and connectors take the vertical form. `·` and `/` stay upright. Keeping a two-em dash on one line is left to the browser's line breaker. Interpunct width by region is not handled. | `the_punctuation_contract`, `separators_and_arrows_are_classified_by_behaviour` |
| 5.1.1.1 Fullwidth full stop | Conforms | `．` joins the corner family with `。`. | `the_punctuation_contract` |
| 5.1.1.2 Taiwan/Hong Kong special cases | Partial | The placement is the face's (see 2.1.2), so a Taiwan or Hong Kong publication that wants the Mainland placement gets it from a Mainland face or `lang`, for the whole page. Nothing chooses it for one passage. | gate `punctuation-ink` |
| 5.1.1.3 `?!` and repeated marks | Conforms | Two of `？！` used together, in either order or of one kind, become one slot set side by side in one cell (`text-combine-upright: all`); three take two cells, a pair and a single. Prose only: in code they are operators and stay as written. | `question_and_exclamation_marks_used_together_share_a_space`, gate `page-geometry` |
| 5.1.1.4 Death-indication mark | Not implemented | No markup for it. | |
| 5.2 Quotations and citations | Partial | Corner brackets and book title brackets `《》〈〉` take the vertical form from the font. Vertical presentation forms are never written into the text, as CLReq's note asks. Wavy book-title marks and proper-noun marks are interlinear and not implemented (see 5.6.1). | `the_punctuation_contract`, `punctuation_is_never_substituted` |
| 5.3.1 Emphasis marks | Not implemented | Markdown emphasis is flattened to plain text before layout. | |
| 5.4.1 Ellipsis | Partial | `……` is two vertical-form slots. That it stays on one line is the browser's line breaker; no test checks it. | `the_punctuation_contract` |
| 5.5 Ruby: pronunciation, Bopomofo, romanization, bilingual annotations, interlinear comments (5.5.1–5.5.7) | Not implemented | No ruby in the wire protocol. The gap analysis records browser gaps here too (bopomofo positioning, in-page search, selection). | |
| 5.6.1 Interlinear punctuation | Not implemented | No proper-noun, book-title-line or emphasis marks. | |
| 5.7 Data formats and numbers | Informative | Marked TBD in CLReq. | |

### 6 Line and paragraph layout

| Section | Status | Note | Evidence |
|---|---|---|---|
| 6.1.1 Line start and line end prohibition | Not implemented | By design: line breaking is the browser's (UAX #14 and CSS `line-break`). The engine does not measure, so it cannot own a break. | README, "What the engine does not decide" |
| 6.1.2.1 Two-em dash and ellipsis unbroken | Partial | Each is one or two vertical-form slots; whether they stay together is the browser's. | |
| 6.1.2.2 Digits and their prefixes and suffixes | Conforms | A digit run is one slot and never splits. `%`, `‰`, `‱`, the degree signs and a trailing currency symbol join the number before them, and `+`, `-`, `±`, `−` and a leading currency symbol the number after them, so no line falls between them. Measured first: as separate slots, Chrome broke between them in all four cases tried. Prose only. | `a_number_keeps_its_sign_and_unit`, gate `page-geometry` |
| 6.1.2.3 Annotation marks | Not implemented | No superscript or note markup. | |
| 6.1.3 Hanging punctuation | Not implemented | Nothing hangs. | |
| 6.1.4 Western words unbroken | Partial | A Latin word is one slot, set with `white-space: nowrap`, prefers a hyphen it already has, and no character is changed by a break. But a word longer than 12 characters is cut at the cap by count, with a visible hyphen, not at a syllable: CLReq allows a break only where the word is hyphenated, and a count is not a hyphenation. | `long_latin_words_are_bounded`, `breaking_at_a_hyphen_alters_no_character`, `a_hard_hyphen_never_splits_a_cluster` |
| 6.2.1.1 First-line indents | Partial | No indent. Paragraphs are separated by a blank column, which CLReq lists as one of the accepted methods. | `a_blank_line_is_a_column_with_one_caret` |
| 6.2.1.2 Paragraph indent | Not implemented | | |
| 6.2.1.3 Single line alignment | Not implemented | Headings and short lines start at the line start. No centring or even spacing. | |
| 6.2.2 Line adjustment (6.2.2.1–6.2.2.4) | Not implemented | No justification. It needs measurement, which the engine does not have. | |
| 6.2.3 Proportional Western text and justification | Not implemented | As 6.2.2. | |
| 6.2.4 Grid alignment | Not implemented | A horizontal Latin run takes its natural width. Han characters after it are not realigned to the grid. | |
| 6.3.1 Solid setting | Conforms | Characters are set solid: a column of N declared characters is exactly N cells long, with no added spacing. | `tools/measure-column-budget.py`, recorded in PROGRESS |
| 6.3.1.1–6.3.1.3 Loose, even and reduced spacing | Not implemented | Styling left to the page. | |
| 6.3.2 Punctuation width adjustment (6.3.2.1–6.3.2.3) | Not implemented | Every mark keeps a full em. That matches the many Taiwan publications that do not adjust, but no choice is offered. | |
| 6.3.3 Mixed text in horizontal | Not implemented | Horizontal blocks are left to the browser, with no Han–Western spacing (the gap analysis tracks the CSS side). | |
| 6.4 Baselines, line height | Informative | The character frame is the 18px cell (`--vertext-cell`), declared once and used for both glyph size and column length. | gate `column-budget` |

### 7 Page and book layout

| Section | Status | Note | Evidence |
|---|---|---|---|
| 7.1.1.1–7.1.1.4 Page format and type area | Not implemented | No pages. Page mode makes the browser window the surface. | |
| 7.1.1.5 Line length a multiple of the font size | Conforms | A column is the declared number of 18px cells long, 34 by default, until the space runs out; then the space is rounded down to a whole cell, so a short window shortens the column by whole characters. Any count from 1 to 400 is accepted: CLReq's 10–55 for vertical body text is a usual range, and the count is the author's. | gates `column-budget` and `page-geometry` |
| 7.1.1.5 Line gap 50–100% of the frame | Conforms | The lines of a paragraph are one pitch apart, the cell plus `--vertext-line-gap` of it: half by default, the low end of the usual range, and a page may declare another value. The slots carry the pitch and the column's own strut is zero, so the font's metrics no longer add to it. | gate `page-geometry` (Noto Sans SC: 27px apart, a 50% gap) |
| 7.1.2 Widows and orphans | Not implemented | By design, as 6.2.2. | |
| 7.1.3.1–7.1.3.2 Heading types, sizes and alignment | Partial | Six heading levels scale 1.75, 1.4, 1.2, 1.1, 1, 1 with weight 600, and start at the line start. CLReq suggests 10–20% larger than body text, and an indent that grows with the level. | `a_heading_segment_gets_its_level_on_the_column` |
| 7.1.3.3–7.1.3.5 New recto, page breaks, run-in headings | Not implemented | No pagination. | |
| 7.2 Page headers, footers and page numbers | Not implemented | No pagination. | |

### 8 Forms and user interaction

CLReq gives no content here.

## MLReq

MLReq says it covers basic web display and leaves "paper layout" out. The
second half of that sentence matters here, because print is where vertext
would eventually need its own measurement. See "Beyond both documents" below.

| Section | Status | Note | Evidence |
|---|---|---|---|
| 1, 2 Introduction and script overview | Informative | | |
| 3.1 Writing mode | Conforms | Top to bottom, columns left to right (`vertext-progression: lr`). Checked in the DOM, in the layout, and in a real browser. | `mongolian_progression_reaches_the_dom_and_the_layout`, gates `browser-golden` and `progression-scroll` |
| 4.1 Slopes, weights, italics | Informative | vertext never synthesises italics. | |
| 5.1.1 U+202F and the suffix | Conforms | A suffix and its U+202F stay inside the word's run. The run is one inline box of `max-content` length, so it never wraps and the suffix cannot start a line. | `a_suffix_separator_is_part_of_the_word_not_a_space`, `a_suffix_joint_stays_inside_one_inline_run`, gate `delivery-golden` |
| 5.1.2 Selection | Partial | Slots are inline spans in a real vertical writing mode, so selection follows the columns and copies as continuous text. The highlight's alignment to the baseline is the browser's. Nothing measures either. | |
| 5.1.3 Cursor movement keys | Partial | The engine maps any caret, including one inside a Mongolian run, to a source offset and back, and a demo host uses it. Arrow-key movement is the host's; vertext ships no editor. | `a_caret_can_stand_inside_a_mongolian_run`, gates `wasm-parity` and `wasm-caret` |
| 5.1.4 Mouse pointer and wheel | Partial | A click inside a Mongolian run lands between the letters clicked. The filter ships a wheel handler that scrolls the vertical page sideways, in the direction the progression gives. The wheel is not tested in CI, and the caret shape is the browser's. | gate `wasm-caret` |
| 6.1.1 Punctuation rules | Partial | `᠂` and `᠃` stay inside the word's run, so they never start a line; golden runs contain both. Brackets and colon pairing across lines are the browser's. Centring comes from the font and is not measured. | gate `delivery-golden` |
| 6.2.1 Right line, left line, strikethrough | Not implemented | No decoration markup: links and emphasis are flattened. | |
| 6.2.2 Width, height and spacing | Partial | The run is shaped whole, so letter heights balance as the font designed. The gap before a suffix is not distinct from a word space: in Noto Sans Mongolian, `nnbsp` and `space` have the same advance, and vertext adjusts neither. | `tools/shaping-golden.py` records both advances |
| 6.3 Emphasis | Not implemented | Emphasis is flattened. | |
| 7.1 Words not split | Conforms | A Mongolian run is never split by the engine and never wraps in the browser. Every golden run arrives on the page as one span, and the browser joins it. | gates `delivery-golden` and `browser-golden` |
| 7.2 Alignment and justification | Partial | Each slot is centred across its column (the default MLReq names). Top-and-bottom justification, MLReq's default for multi-line text, is not done. | |
| 7.3.1 Baseline position | Partial | Runs are `vertical-align: middle` and the font puts the baseline on the centre line. Not measured. | |
| 7.3.2–7.3.3 Mixed with other scripts, numbers and Latin | Partial | Latin and digits are horizontal boxes centred in the column. Latin and Mongolian are sized in proportion to the CJK cell (14 and 15 against 18), so changing the cell keeps the three in step. How their centre lines align is not measured. | `examples/test-column-budget.js` |
| 7.3.4 Mixed with Chinese and Japanese | Partial | Han characters stay upright inside a `vertical-lr` column, as required. Their centre line against the Mongolian baseline is not measured. | |
| 7.4 Lists and counters | Partial | An ordered item carries its number as text, and that number reads left to right as a horizontal slot. Not measured. | |
| 8.1.1–8.1.2 Binding, page turning, paper | Not implemented | No pagination. | |
| 8.1.3–8.1.4 Scrolling direction and scroll bar | Partial | In document mode a Mongolian document opens at its first column and scrolls left to right, and the region scrolls horizontally, so its scroll bar runs along the bottom. Page mode sets its writing mode by the same rule, but no gate opens a page-mode document. The wheel direction is not tested (see 5.1.4). | gate `progression-scroll` |
| 8.1.5 Columns | Not implemented | No multi-column page layout. | |
| 8.1.6 Illustrations | Not implemented | Images are outside the wire protocol. | |
| 8.2 Tables | Partial | A table in a `vertical-lr` document is itself `vertical-lr`, with header cells as `<th>`. Cell alignment against the baseline is not measured. | `a_table_keeps_its_cells_apart` |
| 8.3.1 Page numbering | Not implemented | No pagination. | |
| 8.4 Forms (8.4.1–8.4.4) | Not implemented | vertext renders documents. The demo host's textarea is horizontal. | |
| A Suggested CSS extensions | Informative | | |

## The gap analysis

The CLReq gap analysis lists what browsers cannot yet do. For vertext it answers
a narrower question: which requirements must vertext handle itself, and which
can it hand to the browser?

| Gap | Effect on vertext |
|---|---|
| Horizontal-in-vertical lacks the `digits` value (`text-combine-upright`) | Not used. A Latin or digit run is its own horizontal box, which works in every engine and wraps at the Latin cap. It also means acronyms and words get the horizontal treatment too (CLReq 2.1.2). |
| Upright text orientation — fixed | The column is `text-orientation: upright`. vertext relies on it for Han characters. |
| Table cells ignore a vertical writing mode set on the cell | Not hit: the writing mode is set on the whole table. |
| List counters cannot stand upright | Not hit: ordered items carry their number as text. |
| Punctuation glyphs in system fonts miss CLReq positions | Relevant: vertext hands brackets, dashes and the colon to the font's `vert`, so a font with poor vertical forms sets them poorly. Only the corner marks are placed by vertext itself. |
| Emphasis marks, ruby, bopomofo, warichu | Not used; vertext carries none of these (see CLReq 5.3, 5.5). |
| No Han–Western spacing (`text-autospace`) | Not worked around. CLReq 2.1.3 and 6.3.3 stay unmet. |
| Line breaking before `“`, ideographic space | Inherited as is, because line breaking is the browser's. |
| Vertical form controls | Not relevant to documents. |

## Beyond both documents

What vertext does that neither document asks for:

- **Orientation is decided per block by ink.** A paragraph whose ideographs and
  Mongolian outweigh its Latin goes vertical; otherwise it stays horizontal in
  the vertical flow. Code and tables follow the markup, not a guess.
- **Joining is proven, not assumed.** The Mongolian shaping golden records the
  positional form the shaper picks for every letter of every corpus run, so the check
  does not depend on anyone reading the script. A browser golden then shows that
  the page really joins them.
- **The text is never edited.** No presentation forms, no fullwidth
  substitution, and the only character layout adds (the hyphen at the Latin cap)
  is marked as having no source bytes. What a reader copies is what the author
  wrote.
- **Carets map to the source.** Every slot knows the source bytes it shows, and
  a caret converts both ways, including inside a Mongolian run.
- **Column length is declared in characters.** It is not taken from the window.

MLReq leaves paper layout out on purpose, and CLReq's page chapter is where
vertext is weakest. Both point the same way: the work that would move many of
the rows above from "Not implemented" is print, and print needs the engine to
measure glyphs. The README gives the reason it does not today.
