-- Quarto adapter: wrap Markdown in ::: {.vertext} ... ::: and render it with
-- the installed `vertext` binary. The binary is deliberately external so an
-- SSG gets deterministic, static HTML and no browser JavaScript is required.
local function blocks_to_text(blocks)
  local parts = {}
  for _, block in ipairs(blocks) do
    -- stringify() deliberately omits CodeBlock text, while Vertext needs the
    -- original Rust/Python/etc. lines as individual vertical columns.
    if block.t == "CodeBlock" then
      table.insert(parts, block.text)
    else
      table.insert(parts, pandoc.utils.stringify(block))
    end
  end
  return table.concat(parts, "\n")
end

function Div(el)
  if not el.classes:includes("vertext") then return nil end
  if not quarto.doc.is_format("html") then return el end
  local text = blocks_to_text(el.content)
  local args = { "html" }
  if el.classes:includes("vertext-code") then table.insert(args, "--code") end
  for _, block in ipairs(el.content) do
    if block.t == "CodeBlock" then
      table.insert(args, "--code-width")
      table.insert(args, "--preserve-spaces")
      break
    end
  end
  local ok, html = pcall(pandoc.pipe, "vertext", args, text)
  if not ok then
    error("Vertext needs the `vertext` binary on PATH. Build it with `cargo build --release -p vertext-cli`.")
  end
  return pandoc.RawBlock("html", html)
end
