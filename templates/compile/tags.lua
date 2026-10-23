-- The compilation's filter (Implementation Decision 17; ticket 118): wayline's tags out of the paper.
--
-- Code marks every tag of the paper's parts as an empty span before pandoc reads them,
-- `[]{.wayline-tag kind="ref" cite="<slug>"}` for a `ref` tag naming a found work, `unresolved="mark"` for one still
-- unresolved whose claim the order kept marked "to be resolved", and a bare `kind` for every other tag (`res`, `code`,
-- `doc`, `plot`, and a `ref` the order dropped). This filter turns each `ref` span naming a work into a citation,
-- adjacent ones into one citation of several works, writes the marker for a kept claim, and takes every other span out
-- with the space before it, so no tag's text reaches any output. It runs before pandoc-crossref and citeproc.

local MARK = "[to be resolved]"

local function is_tag(el)
  return el ~= nil and el.t == "Span" and el.classes:includes("wayline-tag")
end

local function blank(el)
  return el ~= nil and (el.t == "Space" or el.t == "SoftBreak")
end

local function cite_of(keys)
  local citations = {}
  for _, key in ipairs(keys) do
    table.insert(citations, pandoc.Citation(key, "NormalCitation"))
  end
  return pandoc.Cite({ pandoc.Str("[@" .. table.concat(keys, "; @") .. "]") }, citations)
end

function Inlines(inlines)
  local out = pandoc.Inlines {}
  local at, keys = nil, nil -- where in `out` the citation this filter made last stands, and the works it cites
  local drop_blank = false  -- a tag opened the line: the space after it goes with it
  for _, el in ipairs(inlines) do
    if is_tag(el) then
      local cite = el.attributes["cite"]
      if el.attributes["kind"] == "ref" and cite ~= nil and cite ~= "" then
        if at ~= nil and blank(out[#out]) and #out == at + 1 then
          out:remove(#out)
        end
        if at ~= nil and #out == at then
          table.insert(keys, cite)
          out[at] = cite_of(keys)
        else
          keys = { cite }
          out:insert(cite_of(keys))
          at = #out
        end
        drop_blank = false
      elseif el.attributes["kind"] == "ref" and el.attributes["unresolved"] == "mark" then
        out:insert(pandoc.Str(MARK))
        drop_blank = false
      else
        while blank(out[#out]) do
          out:remove(#out)
        end
        drop_blank = #out == 0
      end
    elseif drop_blank and blank(el) then
      drop_blank = false
    else
      drop_blank = false
      out:insert(el)
    end
  end
  return out
end
