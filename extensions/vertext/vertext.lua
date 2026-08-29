-- Quarto adapter: emit one binary call per `::: {.vertext} … :::` and let the
-- binary segment the input around reserved Unicode Private Use Area markers
-- so that verbatim `CodeBlock` regions get the wider Latin slots and the
-- preserve-spaces policy while prose regions get the default prose policy.
-- A pure code `{.vertext .vertext-code}` div still routes the whole input
-- through the binary's single-mode code path. The binary is deliberately
-- external so an SSG gets deterministic, static HTML and no browser
-- JavaScript is required.
--
-- Wire protocol: these two codepoints are also declared in
-- crates/vertext-html/src/lib.rs as MODE_CODE / MODE_PROSE, pinned there by
-- the `mode_markers_are_the_wire_protocol` test. Do not change one side alone.

-- The reserved block runs from MODE_CODE_POINT to MODE_CODE_POINT + 7:
-- code, prose, then heading levels 1-6.
local MODE_CODE_POINT = 0xE000
local RESERVED_COUNT = 13 -- U+E000 .. U+E00C inclusive
local MODE_CODE = "\u{E000}"
local MODE_PROSE = "\u{E001}"
local MODE_TABLE = "\u{E008}"
local CELL_SEP = "\u{E009}"
local ROW_SEP = "\u{E00A}"
local MODE_LIST = "\u{E00B}"
local MODE_LIST_ORDERED = "\u{E00C}"
-- Heading levels 1-6 occupy U+E002-U+E007, matching MODE_HEADING_BASE in
-- crates/vertext-html/src/lib.rs.
local MODE_HEADING_BASE = 0xE002
local MAX_HEADING_LEVEL = 6

local function heading_marker(level)
  if level < 1 then level = 1 end
  if level > MAX_HEADING_LEVEL then level = MAX_HEADING_LEVEL end
  return utf8.char(MODE_HEADING_BASE + level - 1)
end

-- Document state. Declared before `render` so it is captured as an upvalue;
-- a `local` written after the function would leave `render` reading a nil
-- global instead.
local page_mode = false
-- Whole-document layout without taking over the page (see Meta).
local document_mode = false
-- 'rl' = CJK (vertical-rl), 'lr' = traditional Mongolian (vertical-lr).
local progression = 'rl'
-- Set when an explicit `.vertext-page` div rendered, so its page style can be
-- injected from the Pandoc pass rather than up front.
local page_div_rendered = false

-- The stylesheet must travel with the filter, not with the format.
--
-- `_extension.yml` contributes vertext.css to the `vertext-html` format, which
-- is fine for a standalone document — but a site has its own `format: html`
-- and will never select ours. The filter would then emit correct markup that
-- nothing styles, and the page renders as flat horizontal text: the failure
-- looks like the extension did nothing rather than like a missing stylesheet.
-- Declaring the dependency here means the CSS ships wherever the filter runs.
local stylesheet_added = false
local function ensure_stylesheet()
  if stylesheet_added then return end
  stylesheet_added = true
  quarto.doc.add_html_dependency({ name = 'vertext', stylesheets = { 'vertext.css' } })
end

-- Runs the binary over one marker-tagged string. Kept in one place so the
-- title path and the div path cannot drift in how they invoke it.
--
-- Returns nil when the binary is unavailable. Callers leave their content
-- alone in that case, so the document renders as ordinary horizontal markdown
-- instead of taking down the whole site build. That is honest degradation:
-- horizontal text is visibly not vertical text, so nothing pretends to have
-- worked. Raising here instead would surface as `string expected, got
-- PandocError` from deep inside pandoc's walk, which names neither the real
-- problem nor its fix.
local binary_missing = false
local function render(text, extra_args)
  if binary_missing then return nil end
  local args = { "html", "--progression", progression }
  for _, argument in ipairs(extra_args or {}) do
    table.insert(args, argument)
  end
  local ok, html = pcall(pandoc.pipe, "vertext", args, text)
  if not ok then
    binary_missing = true
    quarto.log.warning(
      "vertext: the `vertext` binary is not on PATH, so this document is " ..
      "rendered horizontally. Build it with `cargo build --release -p " ..
      "vertext-cli` and put target/release on PATH.")
    return nil
  end
  ensure_stylesheet()
  return html
end

-- Page mode turns the whole document into a vertical surface: the document
-- body gets `writing-mode: vertical-rl`, so every element Quarto emits — the
-- title, the headings, the prose between strips — flows top-to-bottom with
-- columns advancing right-to-left, and the page scrolls horizontally from the
-- right edge. This is the browser's native vertical flow, not a transform.
--
-- The rules live here rather than in vertext.css because they are
-- document-level policy that must only apply when the author asks for it; the
-- stylesheet stays scoped to the strip itself.
-- Document mode: the body stays a normal horizontal page (navbar, sidebar,
-- and table of contents keep working) but the *content region* becomes a
-- vertical surface that scrolls horizontally. Quarto's own title block is
-- hidden and re-rendered through the layout, because a horizontal Chinese
-- title above a vertical Chinese document is the one thing this library
-- exists to stop.
local function document_style()
  return [[
<style id="vertext-document-mode">
  /* The column length budget: how far a paragraph runs before wrapping into
     the next visual column. This is the vertical analogue of a measure, and
     it is what makes a long paragraph reachable instead of running off the
     bottom of the page into nothing.

     The 12rem is a guess about chrome, and it is only ever right for a bare
     document. A THEME knows the real answer -- it is the thing that decides
     how deep the strips are -- so it gets to say, through
     `--vertext-column-theme-height`. Routed through a variable rather than
     left for the theme to override directly because THIS stylesheet wins a
     specificity tie: the filter writes it into the body, after the head, so a
     plain `body { --vertext-column-height: ... }` in a linked theme sheet
     loses and the columns keep the guess. Measured before this existed: a
     466px column in a 347px region, so the last ~120px of every column ran
     under the bottom strip and the text was cut mid-glyph. */
  body {
    --vertext-column-height: var(--vertext-column-theme-height, calc(100vh - 12rem));
  }
  /* The content region becomes the vertical surface.
     `writing-mode: vertical-rl` is doing real work here, not decoration: a
     `flex-direction: row-reverse` strip overflows *leftward*, into negative
     coordinates that no browser will scroll to. Left to itself the document
     is either clipped into a box with its own scrollbar — the "trapped in a
     frame" feeling, where the wheel drives the wrong scroller — or simply
     lost off the left edge. A vertical writing mode makes the browser treat
     rightward-origin horizontal overflow as ordinary scrolling, so the wheel,
     the scrollbar, and the keyboard all work the way they already do.
     Physical `height`/`overflow-x` are used deliberately: under a vertical
     writing mode the logical properties swap axes, and this rule is easier to
     keep correct in physical terms. */
  body #quarto-document-content, body main.content {
    writing-mode: vertical-rl;
    height: calc(100vh - 9rem);
    /* The width must be the *container*, not the content. Left to size itself
       under a vertical writing mode the region grows to fit every column, and
       a box exactly as wide as its contents never scrolls — the document then
       runs off the window with no way to reach it. Pinning the width is what
       turns the overflow into scrolling.
       `100%` rather than `100vw`: `vw` counts the vertical scrollbar's gutter
       as usable width, so the region ends up a scrollbar wider than the space
       it actually has. Under `vertical-rl` that surplus is taken off the
       *right* — the start edge — which slices the first column in half. */
    width: 100%;
    max-width: 100%;
    box-sizing: border-box;
    overflow-x: auto;
    overflow-y: hidden;
    /* Breathing room before the first column and after the last. In
       `vertical-rl` the inline axis is vertical, so these are the physical
       right and left edges — written physically to stay legible. */
    padding: .5rem 1.25rem;
  }
  /* The strip runs its own flex geometry and must not be rotated a second
     time by the region's writing mode. */
  body .vertext {
    writing-mode: horizontal-tb;
    height: 100%;
    width: max-content;
    overflow: visible;
    border: 0;
    padding-inline: 0;
    min-block-size: 0;
  }
  /* Quarto's title block is horizontal; ours is rendered through the layout
     (see the Pandoc filter). Hidden rather than removed because Quarto builds
     it from metadata at template time, after this filter has run. */
  body #title-block-header { display: none; }
  /* The table of contents assumes a vertically scrolling article and has
     nothing to anchor to here. The filter alone offers no edge to put one on;
     the THEME does, and overrides this at matching specificity. */
  body #quarto-margin-sidebar, body .toc-active #TOC { display: none; }
  /* The real `Header` nodes kept beside the strip so Quarto can build a TOC
     at all (see the Pandoc pass). The strip already draws these headings in
     columns, so these copies must not be seen -- but NOT via `display: none`
     or `visibility: hidden`, which drop them from the accessibility tree and
     would hand a screen reader a document with no headings while sighted
     readers get a full outline. This is the standard visually-hidden clip:
     out of the layout, still in the tree, still a valid anchor target.

     Deliberately NOT `position: absolute`, which is what the usual
     visually-hidden recipe uses: taking the anchor out of flow puts it
     wherever the containing block starts, measured at x=-1950 in a document
     that scrolls right-to-left -- outside the scrollable range entirely, so
     following a TOC link updated the hash and scrolled nowhere. In flow and
     zero-width, the anchor sits exactly beside the text it names, which is
     the whole point of it being an anchor. */
  body .vertext-toc-anchor {
    display: inline-block;
    width: 0;
    height: 0;
    margin: 0;
    padding: 0;
    overflow: hidden;
    white-space: nowrap;
    border: 0;
    vertical-align: top;
  }
  /* The heading inside keeps its text for a screen reader while contributing
     no box of its own. */
  body .vertext-toc-anchor > * {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
  }
  /* Give the document the full width of the window.
     Quarto's article grid reserves margin columns for a sidebar and a table
     of contents; in a horizontally scrolling document those reservations are
     dead space, and worse, they are dead space *in the scroll axis* — every
     pixel they take is a column of text the reader has to scroll past
     instead of read. The grid is collapsed to a single full-bleed column. */
  body .page-columns {
    display: block !important;
    grid-template-columns: none !important;
  }
  body #quarto-content > *, body .page-columns > * { grid-column: 1 / -1; }
  body main.content, body #quarto-document-content {
    grid-column: 1 / -1;
    margin-inline: 0;
    padding-inline: 0;
  }
  body #quarto-content { max-width: none; padding-inline: 0; }
</style>
]]
end

-- Wheel-to-column-advance.
--
-- This is the one place the extension needs script, and it is worth stating
-- why. The claim that browsers map a vertical wheel onto the block axis in a
-- vertical writing mode is **false** — measured with real wheel events
-- through the debugging protocol, wheel-down scrolls a vertical-rl page
-- *downward*, or does nothing, and never advances the columns. A vertical
-- document is therefore unreadable by mouse without this.
--
-- It is progressive enhancement, not a rendering dependency: the page is
-- laid out identically with script disabled, and remains scrollable by
-- scrollbar, keyboard, and trackpad-horizontal. Only the wheel is repaired.
--
-- Direction comes from the document's declared progression rather than a
-- guess: `scrollLeft` runs from 0 at the start edge toward negative under
-- `vertical-rl`, and toward positive under `vertical-lr`.
local SCROLL_SCRIPT = [[
<script>
(function () {
  function ready(fn) {
    if (document.readyState !== 'loading') { fn(); }
    else { document.addEventListener('DOMContentLoaded', fn); }
  }
  ready(function () {
    var strip = document.querySelector('.vertext[data-column-advance]');
    if (!strip) { return; }
    var forward = strip.getAttribute('data-column-advance') === 'right' ? 1 : -1;
    var candidates = [
      document.querySelector('#quarto-document-content'),
      document.querySelector('main.content'),
      document.scrollingElement
    ];
    var target = null;
    for (var i = 0; i < candidates.length; i++) {
      var el = candidates[i];
      if (el && el.scrollWidth > el.clientWidth + 1) { target = el; break; }
    }
    if (!target) { return; }
    var listener = (target === document.scrollingElement) ? window : target;
    // A block too tall for the region -- a long code listing, a big table --
    // is capped and scrolls inside itself, because the region cannot scroll on
    // the y axis without fighting the column wrap. That only counts as a fix
    // if the wheel can actually reach it: this handler sits on the region and
    // sees those events bubble, and turning them into column advance would
    // leave the overflow unreachable by the one gesture people use. So a
    // gesture that starts inside a y-scroller with room left in that direction
    // belongs to the scroller, and this handler keeps its hands off.
    function insideLiveScroller(node, delta) {
      for (var el = node; el && el !== target; el = el.parentElement) {
        if (el.scrollHeight <= el.clientHeight + 1) { continue; }
        var style = getComputedStyle(el).overflowY;
        if (style !== 'auto' && style !== 'scroll') { continue; }
        var room = delta > 0
          ? el.scrollHeight - el.clientHeight - el.scrollTop > 1
          : el.scrollTop > 1;
        if (room) { return true; }
      }
      return false;
    }
    listener.addEventListener('wheel', function (event) {
      // Leave zoom and genuine horizontal gestures alone.
      if (event.ctrlKey || !event.deltaY) { return; }
      if (Math.abs(event.deltaX) > Math.abs(event.deltaY)) { return; }
      if (target.scrollWidth <= target.clientWidth + 1) { return; }
      if (insideLiveScroller(event.target, event.deltaY)) { return; }
      var before = target.scrollLeft;
      target.scrollLeft = before + forward * event.deltaY;
      // Only claim the gesture if it actually moved; at either end the page
      // should still be able to do whatever it would normally do.
      if (target.scrollLeft !== before) { event.preventDefault(); }
    }, { passive: false });
  });
})();
</script>
]]

-- A vertical page spends its DEPTH on chrome, and depth is the scarce axis:
-- a top strip that costs 11rem out of a 100vh column is a tenth of every line
-- of text on the page, on every page. Horizontally that same strip costs
-- nothing anyone notices. So a vertical theme needs a way to give the depth
-- back, and this is it.
--
-- The control is the engine's; the geometry stays the theme's. The theme
-- publishes its strip depth as `--vertext-nav-depth` and uses that property
-- everywhere it currently writes the number -- the strip's own size AND the
-- content region's inset. This script then swaps the property and the whole
-- geometry follows from one value.
--
-- The opt-in is the PROPERTY BEING DECLARED, not a class or an attribute in
-- the markup, and that is deliberate. A theme that still bakes its depth into
-- a Sass constant would get a button that renders, clicks, flips a class, and
-- moves nothing -- which is the worst outcome available here, worse than no
-- button, because it looks like it worked. Reading the computed property is
-- the one check that proves the theme actually routed its geometry through a
-- runtime value. No property, no button.
--
-- Naming the strip is its own problem, and getting it wrong is invisible in
-- exactly the way this control exists to avoid. Three ways, in falling order
-- of who actually knows which element the depth sizes:
--
--   1. `[data-vertext-edge="nav"]` -- a host that emits its own chrome and can
--      mark it. kele does.
--   2. `--vertext-nav-target`, a selector published beside the depth by a theme
--      that sizes Quarto's TEMPLATE output, which a filter cannot reach to give
--      an attribute to. Same block, same contract, so a theme that moves its
--      strip moves both or neither.
--   3. `#quarto-header` -- the last resort, and right for a stock Quarto navbar.
--
-- Guessing by id alone was wrong and it shipped. In `vertext-theme`
-- `#quarto-header` is the BANNER pinned to the right edge; the top strip is
-- `#quarto-sidebar`. Measured in a real browser: the button attached to the
-- banner, the collapse blanked the banner's brand and links, and the actual
-- strip kept its full section list inside 59px, over the text the collapse had
-- just handed back. The click landed, the class flipped, the property moved the
-- region -- every part worked except which element it worked on, and no markup
-- assertion can see that.
--
-- Whichever way it is found, the script stamps `data-vertext-edge="nav"` on it.
-- The stylesheet then needs one selector, and any tool pointed at the page
-- finds the same element the engine chose.
local NAV_TOGGLE = [[
<style id="vertext-nav-toggle">
  body.vertext-nav-collapsed {
    --vertext-nav-depth: var(--vertext-nav-depth-collapsed, 2.1rem);
  }
  /* The list goes; the strip and its button stay. Hiding the strip outright
     would take the control with it, and a control you cannot get back to is
     not a collapse, it is a one-way door. `visibility` rather than `display`
     so the strip does not reflow its own button on the way down. */
  body.vertext-nav-collapsed [data-vertext-edge="nav"] > *:not(.vertext-nav-toggle) {
    visibility: hidden;
  }
  /* Physical properties deliberately: this button is pinned to a viewport
     edge, and under a vertical writing mode the logical ones swap under it. */
  .vertext-nav-toggle {
    position: absolute;
    top: .35rem;
    right: .45rem;
    z-index: 2;
    /* Hit-testing goes by BOXES, not by paint. A control that renders in the
       right place and is not clickable has happened in this extension before
       and passed every markup assertion in the suite, so the button gets a
       real box with real padding rather than relying on a glyph's own ink. */
    min-width: 1.9rem;
    min-height: 1.9rem;
    padding: 0;
    line-height: 1;
    writing-mode: horizontal-tb;
    cursor: pointer;
    background: transparent;
    border: 1px solid rgba(128, 128, 128, .4);
    border-radius: .25rem;
    color: inherit;
    opacity: .75;
  }
  .vertext-nav-toggle:hover { opacity: 1; }
  .vertext-nav-toggle:focus-visible { outline: 2px solid currentColor; outline-offset: 2px; }
</style>
<script>
(function () {
  var KEY = 'vertext-nav-collapsed';
  function ready(fn) {
    if (document.readyState !== 'loading') { fn(); }
    else { document.addEventListener('DOMContentLoaded', fn); }
  }
  ready(function () {
    var strip = document.querySelector('[data-vertext-edge="nav"]');
    if (!strip) {
      // A theme sizing Quarto's own chrome names the element beside the depth.
      // Quoted, because it is a CSS string; the quotes come back with it.
      var target = getComputedStyle(document.documentElement)
        .getPropertyValue('--vertext-nav-target').trim().replace(/^['"]|['"]$/g, '');
      // A selector from a stylesheet is author input and may not parse.
      if (target) { try { strip = document.querySelector(target); } catch (e) {} }
    }
    if (!strip) { strip = document.getElementById('quarto-header'); }
    if (!strip) { return; }
    // The theme must have routed its depth through the property, or the
    // button would flip a class that changes nothing. See the note above.
    var depth = getComputedStyle(document.body).getPropertyValue('--vertext-nav-depth');
    if (!depth || !depth.trim()) { return; }

    var root = document.documentElement;
    var open = root.getAttribute('data-vertext-nav-label') || 'Collapse navigation';
    var shut = root.getAttribute('data-vertext-nav-label-collapsed') || 'Expand navigation';

    var button = document.createElement('button');
    button.className = 'vertext-nav-toggle';
    button.type = 'button';
    if (getComputedStyle(strip).position === 'static') { strip.style.position = 'relative'; }
    // However it was found, the strip now says so itself: one selector for the
    // stylesheet above, and the same element for anything else reading the page.
    strip.setAttribute('data-vertext-edge', 'nav');
    strip.appendChild(button);

    function apply(collapsed) {
      document.body.classList.toggle('vertext-nav-collapsed', collapsed);
      button.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
      button.setAttribute('aria-label', collapsed ? shut : open);
      button.setAttribute('title', collapsed ? shut : open);
      button.textContent = collapsed ? '▸' : '▾';
    }
    var stored = null;
    // Storage throws outright in some contexts -- private windows, thumbnail
    // capture, browsers set to block site data -- so it is never read bare.
    try { stored = localStorage.getItem(KEY); } catch (e) {}
    apply(stored === '1');
    button.addEventListener('click', function () {
      var collapsed = !document.body.classList.contains('vertext-nav-collapsed');
      apply(collapsed);
      try { localStorage.setItem(KEY, collapsed ? '1' : '0'); } catch (e) {}
    });
  });
})();
</script>
]]

local function page_style(mode)
  local writing_mode = (mode == 'lr') and 'vertical-lr' or 'vertical-rl'
  return ([[
<style id="vertext-page-mode">
  html { block-size: 100%; }
  /* `vertical-rl` puts the block axis horizontal, advancing right-to-left, and
     the inline axis vertical. The viewport height therefore bounds the line
     length, and the document grows — and scrolls — leftward from the right
     edge, which is where the browser starts the scroll position on its own. */
  /* Axis note, because it is the easiest thing in CSS to get backwards: under
     `vertical-rl` the BLOCK axis is horizontal (right-to-left) and the INLINE
     axis is vertical. So `block-size` here means width and `inline-size` means
     height. Constraining `block-size` on a descendant clamps the document's
     width and pushes the columns out of view. */
  body {
    writing-mode: WRITING_MODE;
    box-sizing: border-box;
    block-size: 100%;
    max-block-size: 100%;
    margin: 0;
    padding: 1.5rem 2rem;
    overflow-x: auto;
    overflow-y: hidden;
  }
  /* Quarto's grid chrome assumes a horizontal axis. Collapse it to plain block
     flow so the page's writing mode, not a grid template, decides placement.
     Sizes stay auto on both axes: the vertical flow does the measuring. */
  body #quarto-content,
  body .page-columns,
  body .content,
  body main {
    display: block;
    block-size: auto;
    max-block-size: none;
    inline-size: 100%;
    max-inline-size: none;
    margin: 0;
    padding: 0;
    grid-template-columns: none;
  }
  /* Quarto's title block is replaced by a rendered vertext strip (see the
     Pandoc filter below), so the title obeys the same layout rules as the
     body it heads.
     It is hidden rather than removed because Quarto builds the title block
     from metadata at template time, after this filter's Meta pass has run —
     setting `title-block-style: none` from here is too late to take effect.
     The rule is safe to rely on: this stylesheet is inlined into the document
     by `header-includes`, so it cannot fail to load independently of the
     markup it hides. An author who wants the node gone entirely can set
     `title-block-style: none` in the document's own YAML. */
  body #title-block-header { display: none; }
  /* A vertext strip runs its own flex geometry and must not be rotated a
     second time by the page's writing mode. Nested in an orthogonal flow it
     takes the viewport height as its block size and sizes its inline axis to
     the columns, so the page — not the strip — owns the scrolling. */
  body .vertext {
    writing-mode: horizontal-tb;
    border: 0;
    padding: 0;
    overflow: visible;
    min-block-size: 0;
    block-size: 100%;
    /* Orthogonal-flow boxes are stretched to the container's block extent by
       default, which would give every strip the full viewport width. Shrink
       each one to its own columns so several strips (title, then body) sit
       side by side instead of each claiming a screenful. */
    inline-size: max-content;
    align-items: flex-start;
  }
</style>
]]):gsub('WRITING_MODE', writing_mode)
end

local function strip_trailing_newlines(text)
  return (text:gsub("\n+$", ""))
end

-- Removes the reserved markers from author text.
--
-- The markers are the wire protocol, and this filter is the only thing
-- entitled to emit them. A decoder cannot distinguish a marker the filter
-- inserted from one that was sitting in the source: a document containing
-- U+E000 would silently switch the rest of itself into code mode. Private Use
-- Area codepoints are rare in prose but "rare" is not "never" — PUA is exactly
-- where fonts park custom glyphs, and a corpus of historical script sitting in
-- a legacy PUA encoding is a real document, not a hypothetical one.
--
-- So author text is sanitized at the point it enters the protocol. U+E000
-- through U+E007 are stripped; everything else passes through untouched.
-- Note the loop: Lua patterns match BYTES, so a range class written as
-- `[\u{E000}-\u{E007}]` is not a codepoint range at all. It is the byte set
-- implied by those characters' UTF-8 encodings, and it happily deletes the
-- lead or continuation byte out of the middle of an unrelated character —
-- turning 山 into invalid UTF-8. A literal multi-byte string is safe as a
-- pattern because UTF-8 is self-synchronizing: no character's encoding can
-- appear inside another's.
local function strip_markers(text)
  for offset = 0, RESERVED_COUNT - 1 do
    text = text:gsub(utf8.char(MODE_CODE_POINT + offset), "")
  end
  return text
end

local function content_of(block)
  return strip_markers(pandoc.utils.stringify(block))
end

-- Encodes a Pandoc Table onto the wire as rows of cells.
--
-- A table is the one construct whose structure vertical text renders *better*
-- than horizontal: a row set as a column reads top-to-bottom as one entry, and
-- rows advance the way the surrounding text does. Losing the cell boundaries
-- (which stringify does) turns a four-field vocabulary entry into an
-- unreadable run — the exact failure this encoding exists to prevent.
local function encode_table(tbl)
  local rows = {}

  local function add_row(row)
    local cells = {}
    for _, cell in ipairs(row.cells) do
      table.insert(cells, content_of(cell.contents))
    end
    if #cells > 0 then
      table.insert(rows, table.concat(cells, CELL_SEP))
    end
  end

  -- Header first: the binary treats row 0 as the header row.
  if tbl.head and tbl.head.rows then
    for _, row in ipairs(tbl.head.rows) do add_row(row) end
  end
  for _, body in ipairs(tbl.bodies or {}) do
    for _, row in ipairs(body.body or {}) do add_row(row) end
  end
  if tbl.foot and tbl.foot.rows then
    for _, row in ipairs(tbl.foot.rows) do add_row(row) end
  end

  if #rows == 0 then return nil end
  return MODE_TABLE .. table.concat(rows, ROW_SEP) .. MODE_PROSE
end

-- Document-level switch: `vertext-page: true` in the YAML header.
--
-- Every piece of state is reset here, because Quarto loads a project's filters
-- once and reuses the same Lua state for every document in the render. Without
-- this reset, one document declaring `vertext: true` silently turns on
-- whole-document layout for every page rendered after it — including pages
-- that never asked for the filter at all.
function Meta(meta)
  page_mode = false
  document_mode = false
  page_div_rendered = false
  progression = 'rl'
  stylesheet_added = false
  -- Progression is read whether or not the document is in page mode, because
  -- a strip embedded in an ordinary horizontal page still advances one way.
  local declared = meta['vertext-progression']
  if declared then
    declared = pandoc.utils.stringify(declared):lower()
    if declared == 'lr' or declared == 'vertical-lr' or declared == 'mongolian' then
      progression = 'lr'
    end
  end
  -- `vertext: true` lays the whole document out vertically while leaving the
  -- surrounding page alone -- navbar, sidebar, and table of contents keep
  -- working. `vertext-page: true` additionally turns the page itself into a
  -- vertical surface, which takes over the body and is only appropriate for a
  -- standalone document with no site chrome around it.
  if meta['vertext'] == true or meta['vertext'] == 'true' then
    document_mode = true
  end
  if meta['vertext-page'] == true or meta['vertext-page'] == 'true' then
    document_mode = true
    page_mode = true
  end
  -- The page styles are NOT injected here. They turn the content region into a
  -- vertical surface, which is only correct if the layout actually ran: without
  -- the binary the text stays ordinary horizontal markdown, and a horizontal
  -- paragraph inside `writing-mode: vertical-rl` lays every Latin word on its
  -- side while CJK stands upright. That is worse than doing nothing, and it is
  -- what a missing binary shipped to production. Injection now happens in the
  -- Pandoc pass, only once a strip has genuinely been rendered.
  return meta
end

-- Encodes a list of Pandoc blocks onto the wire.
--
-- Shared by the `::: {.vertext}` div and by whole-page mode, so a document
-- that opts in with `vertext-page: true` gets exactly the same treatment as
-- one that wraps its content by hand — an author writing a vertical document
-- should not have to fence the entire thing.
--
-- Declared before the definition because a Div recurses back into it.
local encode_blocks

function encode_blocks(blocks)
  local parts = {}
  for _, block in ipairs(blocks) do
    if block.t == "CodeBlock" then
      -- Bracket verbatim source with mode-switch markers so the binary can
      -- toggle into code rule set around this block and back out.
      table.insert(parts,
        MODE_CODE .. strip_markers(strip_trailing_newlines(block.text)) .. MODE_PROSE)
    elseif block.t == "Table" then
      local encoded = encode_table(block)
      if encoded then table.insert(parts, encoded) end
    elseif block.t == "BulletList" or block.t == "OrderedList" then
      -- Each item is its own segment. Flattening the whole list into one
      -- string welds the items together and, worse, classifies them as a
      -- lump: six mostly-Chinese items that each carry a Latin term add up
      -- to a Latin-majority blob and the entire list turns horizontal.
      local ordered = block.t == "OrderedList"
      local number = ordered and (block.start or 1) or nil
      for _, item in ipairs(block.content) do
        local body = content_of(item)
        if body ~= "" then
          if ordered then
            body = tostring(number) .. ". " .. body
            number = number + 1
          end
          table.insert(parts, (ordered and MODE_LIST_ORDERED or MODE_LIST) .. body .. MODE_PROSE)
        end
      end
    elseif block.t == "Header" then
      -- A heading is structure, not a short paragraph. Carry its level across
      -- the boundary so the binary can give it its own column class; without
      -- this the stringify below would flatten `## Chinese` into the bare word
      -- `Chinese`, indistinguishable from prose.
      table.insert(parts,
        heading_marker(block.level) .. content_of(block) .. MODE_PROSE)
    elseif block.t == "Div" then
      -- Recurse rather than stringify. A Div is a wrapper, and the blocks
      -- inside it deserve exactly the treatment they would get at top level:
      -- a CodeBlock in here is still code and must reach the branch above.
      --
      -- Stringifying instead is not merely lossy, it is silently *empty*:
      -- `pandoc.utils.stringify` walks inlines, and a CodeBlock's text is not
      -- inlines, so a Div wrapping code stringifies to "" and the whole block
      -- disappears from the document. That is how Quarto's executed output
      -- vanished -- `.cell-output` is a Div around a CodeBlock, so every
      -- `Sum: 15` a notebook printed was dropped while the prose around it
      -- survived, making it look like an output-specific bug. It is not
      -- specific to `.cell-output`; any Div holding code was erased.
      local inner = encode_blocks(block.content)
      if inner ~= "" then table.insert(parts, inner) end
    else
      -- Everything else is still flattened to its characters: inline emphasis,
      -- links, and list structure do not survive. Documented in the README
      -- rather than silently implied.
      table.insert(parts, content_of(block))
    end
  end
  return strip_trailing_newlines(table.concat(parts, "\n"))
end

function Div(el)
  if not el.classes:includes("vertext") then return nil end
  if not quarto.doc.is_format("html") then return el end

  local pure_code = el.classes:includes("vertext-code")
  local text = encode_blocks(el.content)
  if text == "" then return pandoc.RawBlock("html", "") end

  local args = {}
  if pure_code then
    -- Force the binary's single-mode code path (it ignores the markers when
    -- any whole-strip flag is set, so this branch keeps the rendered root
    -- class as `vertext vertext-code`).
    table.insert(args, "--code")
    table.insert(args, "--code-width")
    table.insert(args, "--preserve-spaces")
  end
  if el.classes:includes("vertext-page") then
    table.insert(args, "--page")
  end
  local html = render(text, args)
  -- No binary: hand the original content back untouched rather than emitting
  -- a broken block.
  if not html then return nil end
  -- A `.vertext-page` div asks for the whole page to go vertical, and it never
  -- reaches the Pandoc pass, so it registers its own page style here — again
  -- only after a successful render.
  if el.classes:includes("vertext-page") then
    page_div_rendered = true
  end
  return pandoc.RawBlock("html", html)
end

-- Page mode: the whole document is one vertical surface.
--
-- Everything that is not already a rendered strip goes through the layout,
-- title included. Quarto's own title block is hidden and the title is
-- re-rendered as a level-1 heading, so it obeys the same rules as the body it
-- heads -- a CSS `text-orientation: sideways` on the original would be a
-- transform wearing the costume of vertical text.
--
-- Because the whole body is handled here, a document that declares
-- `vertext-page: true` needs no `::: {.vertext}` fence at all. Explicit divs
-- still work and are passed through untouched: `Div` has already replaced them
-- with RawBlocks by the time this runs.
function Pandoc(doc)
  if not quarto.doc.is_format("html") then return nil end
  -- Laying out an already-laid-out document is not a smaller version of the
  -- job; it is a different and wrong one. The filter can be applied twice --
  -- the theme's format defaults name it AND a page may name it again in its own
  -- `filters:` -- and the second pass sees a document whose prose is inert
  -- RawBlocks but whose title and heading anchors are still live nodes. Only
  -- those get laid out again, so the page came back with its title and every
  -- heading drawn TWICE, side by side, and nothing else changed.
  --
  -- The guard is on `doc.meta` rather than a module-level flag on purpose:
  -- Quarto reuses one Lua state for every document in a project render, so a
  -- flag set for one page would silence the filter for every page after it.
  -- It also cannot key off "are there vertext RawBlocks already", because the
  -- `Div` handler above produces exactly those, earlier in THIS same pass.
  if doc.meta['vertext-rendered'] then return nil end
  -- A document that only carries an explicit `.vertext-page` div still needs
  -- its page style attached; it just has no body to lay out.
  if not document_mode then
    if page_div_rendered and stylesheet_added then
      local includes = doc.meta['header-includes'] or pandoc.MetaList({})
      if includes.t ~= 'MetaList' then
        includes = pandoc.MetaList({ includes })
      end
      includes[#includes + 1] = pandoc.MetaBlocks({
        pandoc.RawBlock('html', page_style(progression) .. SCROLL_SCRIPT .. NAV_TOGGLE) })
      doc.meta['header-includes'] = includes
      doc.meta['vertext-rendered'] = true
      return doc
    end
    return nil
  end

  local strip_args = page_mode and { "--page" } or {}
  local rendered = {}
  local pending = {}

  -- The title becomes the first segment of the first strip rather than a strip
  -- of its own. Two strips are two block-level boxes, and block boxes stack
  -- *down* the page — which would leave the document scrolling vertically to
  -- get from the title to the text, in a layout whose whole point is that it
  -- scrolls sideways. One strip, one scroll direction.
  local prefix = ""
  local title = doc.meta.title
  if title then
    local text = strip_markers(pandoc.utils.stringify(title))
    if text ~= "" then
      prefix = heading_marker(1) .. text .. MODE_PROSE
    end
  end

  local function flush()
    if #pending == 0 and prefix == "" then return end
    local text = prefix .. encode_blocks(pending)
    prefix = ""
    local html = text ~= "" and render(text, strip_args) or nil
    if html then
      table.insert(rendered, pandoc.RawBlock("html", html))
    else
      -- Degrade to the untouched blocks so the document still renders.
      for _, block in ipairs(pending) do table.insert(rendered, block) end
    end
    pending = {}
  end

  -- Structural HTML with text inside it: keep the structure, lay out the text.
  --
  -- Passing such a Div through whole is right for a code listing, which is one
  -- opaque lump of rendered markup. It is wrong for a hand-written panel -- the
  -- crew roster is the case that named this -- where the raw tags are the
  -- CARDS and the Chinese between them is ordinary prose that should be set in
  -- columns like every other paragraph on the site. Passing it through left the
  -- one page of hand-written HTML reading horizontally.
  --
  -- So walk it: raw tags survive untouched and keep the layout they describe,
  -- nested Divs recurse, and each run of real content between them becomes its
  -- own small strip. That is what "every micro div gets the normal treatment"
  -- means -- the container decides where the card sits, the engine decides how
  -- the text inside it reads.
  local function relayout_raw(block)
    if block.t ~= "Div" or not block.content then return block end
    local out, group = {}, {}
    local function flush_group()
      if #group == 0 then return end
      local text = encode_blocks(group)
      local html = text ~= "" and render(text, strip_args) or nil
      if html then
        table.insert(out, pandoc.RawBlock("html", html))
      else
        for _, b in ipairs(group) do table.insert(out, b) end
      end
      group = {}
    end
    for _, inner in ipairs(block.content) do
      if inner.t == "RawBlock" then
        flush_group()
        table.insert(out, inner)
      elseif inner.t == "Div" then
        flush_group()
        table.insert(out, relayout_raw(inner))
      else
        table.insert(group, inner)
      end
    end
    flush_group()
    return pandoc.Div(out, block.attr)
  end

  -- Quarto carries its own machinery in the document AST as hidden divs --
  -- `quarto-navigation-envelope` holds the navbar and footer,
  -- `quarto-meta-markdown` the title and description -- and extracts them into
  -- the page template afterwards. They are not document content, and laying
  -- them out puts the whole navbar through the vertical engine: the reader
  -- gets `Pegboard /external/pegboard/index.html` set in columns at the end of
  -- the text, and the title pasted three times. They must pass through
  -- untouched, because Quarto still needs them to build the page.
  --
  -- `quarto-embedded-source-code` is the same kind of thing and had to be
  -- added after it shipped: `code-tools: true` puts the document's ENTIRE
  -- source, frontmatter and all, into a hidden div for the "View Source"
  -- modal. Quarto keeps it out of sight with CSS; this filter saw an ordinary
  -- CodeBlock, laid it out, and printed the whole `.qmd` -- `---`, `title:`
  -- and all -- as a code strip at the end of every page. It looks like the
  -- document dumping its own source, which is exactly what it is, and it only
  -- appears on projects that enable the feature.
  local CHROME_CLASSES = {
    hidden = true,
    ["quarto-embedded-source-code"] = true,
    -- An anchor this pass emitted on a PREVIOUS run. The filter can legitimately
    -- run twice on one document -- the theme's format defaults carry it, and a
    -- page may also name it in its own `filters:` -- and everything else it
    -- produced comes back as a RawBlock, which passes through untouched. These
    -- do not: an anchor holds a REAL `Header` node, because that is the entire
    -- reason it exists (see below), so a second pass laid it out into a strip
    -- of its own and every heading rendered TWICE, side by side. Measured on
    -- the Mongolian lesson page, the only one carrying a page-level `filters:`:
    -- 66 heading columns against 36 anchors. Skipping them here makes the pass
    -- idempotent, which is the property that was missing -- rather than relying
    -- on no document ever declaring the filter twice.
    ["vertext-toc-anchor"] = true,
  }
  local function is_quarto_chrome(block)
    if not (block.attr and block.attr.classes) then return false end
    for _, class in ipairs(block.attr.classes) do
      if CHROME_CLASSES[class] then return true end
    end
    return false
  end

  -- A Div holding a RawBlock must not reach the encoder.
  --
  -- The wire format is text, and `pandoc.utils.stringify` on a RawBlock returns
  -- "" -- so such a block does not merely lose its markup, it DISAPPEARS. This
  -- is the third time this exact trap has bitten (Div-wrapping-CodeBlock, then
  -- executed output, now this) and it hides the same way every time: silently
  -- empty, never an error.
  --
  -- What it cost: every code listing in the Crust book. The `%%rust` and
  -- `%%cpp` magics emit their syntax-highlighted source as a RawBlock html
  -- inside `.cell-output-display`, with `#| echo: false` hiding the Python
  -- wrapper -- so the page kept each program's printed result (a CodeBlock,
  -- which the encoder does handle) and dropped every line of the Rust and C++
  -- the lesson was actually about. A page of answers with no questions.
  --
  -- Passing the Div through untouched is right rather than merely expedient:
  -- the content is already rendered HTML that Quarto styles, and laying out
  -- pre-highlighted markup as vertical slots would destroy the highlighting
  -- that is the point of it.
  local function holds_raw_block(block)
    if block.t == "RawBlock" then return true end
    if block.t ~= "Div" or not block.content then return false end
    for _, inner in ipairs(block.content) do
      if holds_raw_block(inner) then return true end
    end
    return false
  end

  -- Headings are carried across in BOTH forms, and the reason is Quarto's
  -- table of contents.
  --
  -- Pandoc fills `$toc$` by walking `Header` blocks, and by the time it looks
  -- there are none left: every heading has been encoded into the strip and
  -- comes back as a `vertext-column-heading` div inside one RawBlock. Nothing
  -- errors -- the page just renders with no TOC, on every vertext document
  -- there has ever been, and Quarto then stamps `.zindex-bottom` on the empty
  -- sidebar and parks it off-screen, which reads like a placement bug in the
  -- theme rather than a missing heading two files away.
  --
  -- Filter ORDERING cannot fix it (both `pre-quarto` and `post-quarto` were
  -- tried): `$toc$` is computed by the WRITER, after every filter has run. The
  -- headings have to be real `Header` nodes sitting in the AST this pass
  -- returns. So each one is emitted next to the strip that draws it, keeping
  -- document order so the TOC reads in the right sequence. The stylesheet
  -- takes them out of the visual flow -- they are already drawn, in columns,
  -- inside the strip.
  local function emit_toc_headings(blocks)
    for _, block in ipairs(blocks) do
      if block.t == "Header" then
        table.insert(rendered,
          pandoc.Div({ pandoc.Header(block.level, block.content, block.attr) },
                     pandoc.Attr("", { "vertext-toc-anchor" }, {})))
      elseif block.t == "Div" and block.content then
        emit_toc_headings(block.content)
      end
    end
  end

  for _, block in ipairs(doc.blocks) do
    -- A RawBlock at this point is a strip `Div` already rendered; emitting it
    -- as-is keeps an author's explicit fences intact.
    if block.t ~= "RawBlock" and not is_quarto_chrome(block) and holds_raw_block(block) then
      -- Passed through, but NOT unstyled. The region it lands in is
      -- `writing-mode: vertical-rl`, so already-rendered HTML inherits it and a
      -- code listing comes out running down the page one character at a time.
      -- Code is horizontal in this layout by rule -- it is set as a wrapped
      -- horizontal block, not poured into vertical slots -- and passing the
      -- markup through untouched silently opted it out of that rule.
      flush()
      table.insert(rendered,
        pandoc.Div({ block }, pandoc.Attr("", { "vertext-raw" }, {})))
    elseif block.t == "RawBlock" or is_quarto_chrome(block) then
      flush()
      table.insert(rendered, block)
    else
      if block.t == "Header" or block.t == "Div" then
        -- Flush first so the anchor lands AFTER the strip carrying the text
        -- before it, keeping the reading order Pandoc will walk.
        flush()
        emit_toc_headings({ block })
      end
      table.insert(pending, block)
    end
  end
  flush()

  -- Only now, with a strip actually rendered, is it safe to make the page
  -- vertical. If the binary was missing every block passed through untouched,
  -- and the document must stay the plain horizontal page it already is.
  if stylesheet_added then
    local includes = doc.meta['header-includes'] or pandoc.MetaList({})
    if includes.t ~= 'MetaList' then
      includes = pandoc.MetaList({ includes })
    end
    local style = (page_mode or page_div_rendered)
      and page_style(progression) or document_style()
    includes[#includes + 1] = pandoc.MetaBlocks({
      pandoc.RawBlock('html', style .. SCROLL_SCRIPT .. NAV_TOGGLE) })
    doc.meta['header-includes'] = includes
  end

  doc.blocks = rendered
  doc.meta['vertext-rendered'] = true
  return doc
end

-- Meta must run before Div so page mode is known when strips render, and
-- Pandoc last so it prepends the title strip to the finished blocks.
return {
  { Meta = Meta },
  { Div = Div },
  { Pandoc = Pandoc },
}
