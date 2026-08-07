-- VertexT theme: rotate the page chrome a quarter-turn.
--
-- The content filter (../vertext/vertext.lua) lays out the text. This one
-- places everything *around* the text: navbar, table of contents, footer, and
-- the scroll axis. They are separate filters because they answer separate
-- questions, and because the content filter must stay usable under any Pandoc
-- host with no theme at all.
--
-- Why a theme can do what a filter cannot: Quarto assembles its navbar, footer
-- and title block from project metadata at *template* time, after every filter
-- has run. A filter can only hide those nodes (which is what the content
-- filter does with `#title-block-header`). A theme reaches the template layer,
-- so it can put them where a vertical reader expects them instead.
--
-- The rotation, and why each piece lands where it does. Under `vertical-rl`
-- the block axis runs right-to-left, so the RIGHT edge is where the document
-- starts: a banner there is the banner "at the top" in the only sense the
-- reader experiences. The footer at the left edge is the same argument at the
-- other end.
--
--   banner  top    -> right   (start edge)
--   toc     left   -> top
--   status  bottom -> left    (end edge)
--   scroll  down   -> left    (following the columns)
--
-- Under `vertical-lr` (traditional Mongolian) the block axis runs the other
-- way and the two edges swap: banner left, status right. The direction is read
-- from the document, never assumed -- a theme that hardcodes right-to-left has
-- decided permanently which literatures it can carry.

local progression = 'rl'
-- Set only when the content filter actually produced a strip. Everything below
-- is gated on it.
local layout_ran = false

-- The gate, and the reason it exists.
--
-- Rotating the chrome around text that is still horizontal markdown is worse
-- than doing nothing: it is the failure that reached the live site, where a
-- missing binary left `writing-mode: vertical-rl` over horizontal text and
-- laid every Latin word on its side. The content filter now injects its page
-- styles only after a successful render, and this theme must hold the same
-- line -- so the chrome rotation keys off markup the filter cannot emit unless
-- the binary ran.
local function strip_rendered(blocks)
  for _, block in ipairs(blocks) do
    if block.t == 'RawBlock' and block.format == 'html'
       and block.text:find('class="vertext', 1, true) then
      return true
    end
  end
  return false
end

function Meta(meta)
  -- Reset: Quarto reuses one Lua state for every document in a project render,
  -- so state left behind here turns the chrome for a page that never asked.
  progression = 'rl'
  layout_ran = false
  local declared = meta['vertext-progression']
  if declared then
    declared = pandoc.utils.stringify(declared):lower()
    if declared == 'lr' or declared == 'vertical-lr' or declared == 'mongolian' then
      progression = 'lr'
    end
  end
  return meta
end

-- Runs after the content filter's own `Pandoc`, because filters are applied in
-- the order `_extension.yml` lists them and this one is listed second. That
-- ordering is load-bearing: the gate below looks for a strip the content
-- filter produces, so running first would always find nothing and the chrome
-- would never rotate.
function Pandoc(doc)
  if not quarto.doc.is_format('html') then return nil end
  layout_ran = strip_rendered(doc.blocks)
  -- No strip means the binary was missing and the body is ordinary horizontal
  -- markdown. Leave the page alone entirely.
  if not layout_ran then return nil end

  -- The chrome is placed by CSS keyed off this attribute rather than by moving
  -- nodes: Quarto's navbar and sidebar carry real behaviour (collapse state,
  -- keyboard access, search) that reparenting would break. The theme rotates
  -- where they sit, not what they are.
  --
  -- The stylesheet itself is `vertext-theme.scss`, contributed through the
  -- format's `theme:` key and compiled by Quarto. It is NOT registered as an
  -- HTML dependency here: that path expects a plain .css file and would ship
  -- the uncompiled source.
  --
  -- The attribute goes on <html> so the stylesheet can branch on direction
  -- without a second copy of every rule. Getting it there is the awkward part,
  -- and both obvious routes fail:
  --
  --   * `quarto.doc.include_text('in-header', ...)` lands after Quarto has
  --     collected its header includes for this pass, so nothing reaches the
  --     page at all.
  --   * `doc.meta['header-includes']` works for a single-document render and
  --     is SILENTLY DROPPED in a website project -- which is the only mode
  --     this theme is for, and a single-file test cannot catch it. That is the
  --     same shape as the Lua-state leak: a bug only a project render shows.
  --
  -- So the attribute is written from the body instead, where a RawBlock cannot
  -- be discarded. The script is tiny and runs before the strip below it is
  -- parsed, so the chrome is placed on the first paint rather than after a
  -- visible flash on the wrong edges.
  table.insert(doc.blocks, 1, pandoc.RawBlock('html', string.format(
    '<script>document.documentElement.setAttribute(' ..
    '"data-vertext-progression","%s");</script>', progression)))
  return doc
end

return {
  { Meta = Meta },
  { Pandoc = Pandoc },
}
