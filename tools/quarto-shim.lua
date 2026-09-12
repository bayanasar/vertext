-- The four Quarto calls `extensions/vertext/vertext.lua` makes, stubbed so the
-- real filter can run under plain pandoc.
--
-- Why this exists: a Quarto extension filter is not loadable by pandoc on its
-- own -- it expects the `quarto` global that Quarto injects. That is the whole
-- reason the filter has never been executed by anything in this repository:
-- `examples/test-extension.sh` reaches it only through `quarto render`, which no
-- runner here has, so the half of the chain where the wire protocol is ENCODED
-- has never been run by a gate (#30).
--
-- Three functions, four call sites (`grep -n 'quarto\.' extensions/vertext/vertext.lua`):
--
--   quarto.doc.add_html_dependency  -- registers vertext.css. A no-op here: the
--                                      stylesheet is not what this gate reads.
--   quarto.doc.is_format            -- the filter refuses to act on non-HTML
--                                      output. Always true: we render HTML.
--   quarto.log.warning              -- the filter's own diagnostic when the
--                                      binary fails. Kept LOUD, on stderr, so a
--                                      run that silently fell back to plain text
--                                      cannot look like a pass.
--
-- The stubs are deliberately thin. Anything thicker would be this repository
-- writing its own Quarto, and a gate that tests a reimplementation of the host
-- tests nothing about the host.
quarto = {
  doc = {
    add_html_dependency = function(_) end,
    is_format = function(_) return true end,
  },
  log = {
    warning = function(...)
      io.stderr:write("quarto.log.warning: ")
      for _, piece in ipairs({...}) do io.stderr:write(tostring(piece)) end
      io.stderr:write("\n")
    end,
  },
}

-- Load the real filter, unmodified, in this environment. It defines Meta, Div,
-- Pandoc and friends as globals, which is exactly what pandoc collects when a
-- filter file returns nothing.
local here = debug.getinfo(1, "S").source:sub(2):match("(.*)/") or "."
dofile(here .. "/../extensions/vertext/vertext.lua")
