export const meta = {
  name: 'absorb',
  description: 'Read one promoted paper in full: one reader per chunk with its obligation list, then one synthesizer over every entry',
  whenToUse: 'Only when a wayline absorb session starts it with the args code wrote; it reads no manifest itself',
  phases: [
    { title: 'Read', detail: 'one reader per chunk, one retry for the items it left out' },
    { title: 'Synthesize', detail: 'the dossier prose from every entry, a locator on every sentence' },
  ],
}

// The schemas are the harness's schemas/dossier_entry_list.json and schemas/dossier_sections.json
// without their annotations; tests/test_absorb.py holds the copies equal. A script has no file
// access, so they cannot be read at run time.
const ENTRY_LIST_SCHEMA = /* wayline:schema dossier_entry_list */ {
  "type": "object",
  "required": ["entries"],
  "additionalProperties": false,
  "properties": {
    "entries": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["item_id", "locator", "kind", "content", "importance", "relation_to_intent", "oddities"],
        "additionalProperties": false,
        "properties": {
          "item_id": {"type": "string", "pattern": "^[a-z]+-[0-9]+$", "description": "the inventory item this entry answers, as the obligation list names it"},
          "chunk_id": {"type": "string", "pattern": "^c-[0-9]+$", "description": "the chunk the entry was read from; filled in by the fan-out, not by the reader"},
          "locator": {"type": "string", "pattern": "\\S", "description": "where the item was read: <file>:<line> in the source, or a page of a PDF"},
          "kind": {"type": "string", "enum": ["section", "equation", "figure", "table", "algorithm", "theorem", "appendix"]},
          "content": {"type": "string", "pattern": "\\S", "description": "the item in exact form: an equation's LaTeX as the source writes it, a theorem's statement word for word, a table's cells, a section's argument in the paper's own terms"},
          "importance": {"type": "integer", "minimum": 1, "maximum": 5, "description": "1 is incidental to the paper, 5 is what the paper stands on"},
          "relation_to_intent": {"type": "string", "description": "how this item bears on the project's intent; empty when it does not"},
          "oddities": {"type": "array", "items": {"type": "string", "pattern": "\\S"}, "description": "anything that does not add up: a number that disagrees with another, a step that is skipped, a symbol never defined"},
          "what_it_shows": {"type": "string", "pattern": "\\S", "description": "figures: what the image actually shows, read off the image rather than the caption"},
          "supports_cited_claim": {"type": "string", "pattern": "\\S", "description": "figures: the claim that cites the figure, and whether what it shows supports it"},
          "anything_odd": {"type": "string", "description": "figures: axes, scales, error bars, or panels that mislead or disagree with the text; empty when nothing is"}
        },
        "oneOf": [
          {"properties": {"kind": {"const": "figure"}}, "required": ["what_it_shows", "supports_cited_claim", "anything_odd"]},
          {"properties": {"kind": {"enum": ["section", "equation", "table", "algorithm", "theorem", "appendix"]}}}
        ]
      }
    }
  }
} /* /wayline:schema */

const SECTIONS_SCHEMA = /* wayline:schema dossier_sections */ {
  "type": "object",
  "required": ["method", "claims", "results", "assumptions", "limitations", "flaws_found", "reusable_ideas", "open_questions", "relation_to_intent"],
  "additionalProperties": false,
  "properties": {
    "method": {"type": "array", "items": {"type": "object", "required": ["text", "locators"], "additionalProperties": false, "properties": {"text": {"type": "string", "pattern": "\\S"}, "locators": {"type": "array", "minItems": 1, "items": {"type": "string", "pattern": "\\S"}}}}},
    "claims": {"type": "array", "items": {"type": "object", "required": ["text", "locators"], "additionalProperties": false, "properties": {"text": {"type": "string", "pattern": "\\S"}, "locators": {"type": "array", "minItems": 1, "items": {"type": "string", "pattern": "\\S"}}}}},
    "results": {"type": "array", "items": {"type": "object", "required": ["text", "locators"], "additionalProperties": false, "properties": {"text": {"type": "string", "pattern": "\\S"}, "locators": {"type": "array", "minItems": 1, "items": {"type": "string", "pattern": "\\S"}}}}},
    "assumptions": {"type": "array", "items": {"type": "object", "required": ["text", "locators"], "additionalProperties": false, "properties": {"text": {"type": "string", "pattern": "\\S"}, "locators": {"type": "array", "minItems": 1, "items": {"type": "string", "pattern": "\\S"}}}}},
    "limitations": {"type": "array", "items": {"type": "object", "required": ["text", "locators"], "additionalProperties": false, "properties": {"text": {"type": "string", "pattern": "\\S"}, "locators": {"type": "array", "minItems": 1, "items": {"type": "string", "pattern": "\\S"}}}}},
    "flaws_found": {"type": "array", "items": {"type": "object", "required": ["text", "locators"], "additionalProperties": false, "properties": {"text": {"type": "string", "pattern": "\\S"}, "locators": {"type": "array", "minItems": 1, "items": {"type": "string", "pattern": "\\S"}}}}},
    "reusable_ideas": {"type": "array", "items": {"type": "object", "required": ["text", "locators"], "additionalProperties": false, "properties": {"text": {"type": "string", "pattern": "\\S"}, "locators": {"type": "array", "minItems": 1, "items": {"type": "string", "pattern": "\\S"}}}}},
    "open_questions": {"type": "array", "items": {"type": "object", "required": ["text", "locators"], "additionalProperties": false, "properties": {"text": {"type": "string", "pattern": "\\S"}, "locators": {"type": "array", "minItems": 1, "items": {"type": "string", "pattern": "\\S"}}}}},
    "relation_to_intent": {"type": "array", "items": {"type": "object", "required": ["text", "locators"], "additionalProperties": false, "properties": {"text": {"type": "string", "pattern": "\\S"}, "locators": {"type": "array", "minItems": 1, "items": {"type": "string", "pattern": "\\S"}}}}}
  }
} /* /wayline:schema */

// The session passes `args` as an object or, as the live M3 session did, as the JSON text of one.
const input = typeof args === 'string' ? JSON.parse(args) : args
if (!input || typeof input !== 'object' || !Array.isArray(input.chunks) || input.chunks.length === 0) {
  throw new Error('absorb: args must be the object the wayline absorb session was given, with a non-empty chunks list')
}
for (const chunk of input.chunks) {
  if (!chunk || typeof chunk.id !== 'string' || typeof chunk.path !== 'string' || !Array.isArray(chunk.obligations)) {
    throw new Error('absorb: every chunk needs an id, a path, and an obligations list')
  }
}
const reader = input.reader || {}
const synthesizer = input.synthesizer || {}

function imageLine(chunk) {
  const images = chunk.images || []
  if (images.length === 0) return ''
  const listed = images.map(path => `\`${path}\``).join(', ')
  return images.length === 1
    ? ` Then open the image file ${listed} with the Read tool and look at it.`
    : ` Then open each of the image files ${listed} with the Read tool and look at them: they are the figure's panels.`
}

function readerPrompt(chunk) {
  return [
    `Read the chunk file \`${chunk.path}\` with the Read tool, in full.${imageLine(chunk)}`,
    'The chunk file says how to read it, gives the project\'s intent, lists your obligation items, and prints the text with its line numbers. Open nothing else.',
    `Return one entry for each of these ${chunk.obligations.length} item(s), and for nothing else: ${chunk.obligations.join(', ')}.`,
  ].join('\n\n')
}

function retryPrompt(chunk, missing) {
  return [
    `Read the chunk file \`${chunk.path}\` with the Read tool, in full.${imageLine(chunk)}`,
    `An earlier read of this chunk left out ${missing.length} item(s) of its obligation list. Return one entry for each of these, and for nothing else: ${missing.join(', ')}.`,
  ].join('\n\n')
}

function readerOptions(chunk, label) {
  return { agentType: 'reader', schema: ENTRY_LIST_SCHEMA, model: reader.model, effort: reader.effort, label, phase: 'Read' }
}

function missingFrom(chunk, result) {
  const answered = new Set(((result && result.entries) || []).map(entry => entry.item_id))
  return chunk.obligations.filter(id => !answered.has(id))
}

phase('Read')
const read = await pipeline(
  input.chunks,
  chunk => agent(readerPrompt(chunk), readerOptions(chunk, `read:${chunk.id}`)),
  async (first, chunk) => {
    const missing = missingFrom(chunk, first)
    if (missing.length === 0) return { chunk, entries: first.entries, retried: false }
    const again = await agent(retryPrompt(chunk, missing), readerOptions(chunk, `retry:${chunk.id}`))
    const kept = (first && first.entries) || []
    const added = ((again && again.entries) || []).filter(entry => missing.includes(entry.item_id))
    return { chunk, entries: kept.concat(added), retried: true }
  },
)

const entries = []
const failures = []
read.forEach((outcome, index) => {
  const chunk = input.chunks[index]
  if (!outcome) {
    failures.push({ chunk: chunk.id, reason: 'the reader returned nothing, and neither did its retry', missing: chunk.obligations })
    return
  }
  for (const entry of outcome.entries) entries.push(Object.assign({}, entry, { chunk_id: chunk.id }))
  const missing = missingFrom(chunk, outcome)
  if (missing.length) failures.push({ chunk: chunk.id, reason: 'the reader left obligation items out, and so did its retry', missing })
})
log(`${entries.length} entries from ${input.chunks.length} chunk(s); ${failures.length} chunk(s) came back short`)

phase('Synthesize')
let sections = null
if (entries.length === 0) {
  failures.push({ chunk: null, reason: 'no reader returned an entry, so the synthesizer was not started', missing: [] })
} else {
  const intent = input.intent ? `The project's intent is in \`${input.intent}\`; read it first, and open nothing else.` : 'The project states no intent yet.'
  const prompt = [
    `Write the prose sections of the level-2 dossier of \`${input.slug}\` from the readers' entries below and from nothing else: method, claims, results, assumptions, limitations, flaws found, reusable ideas, open questions, and the relation to the project's intent. Every sentence carries at least one locator copied from the entries it rests on, an entry's \`locator\` or its \`item_id\`. A section with nothing to say is an empty list.`,
    intent,
    'The entries, one JSON object per line:',
    entries.map(entry => JSON.stringify(entry)).join('\n'),
  ].join('\n\n')
  sections = await agent(prompt, { agentType: 'synthesizer', schema: SECTIONS_SCHEMA, model: synthesizer.model, effort: synthesizer.effort, label: 'synthesize', phase: 'Synthesize' })
  if (!sections) failures.push({ chunk: null, reason: 'the synthesizer returned nothing', missing: [] })
}

return { entries, sections, failures }
