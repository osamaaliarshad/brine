// Colors for Salt's YAML (with its Jinja) in the States file viewer, the way an editor shows it.
// A line-by-line pass that's good enough to read by, not a YAML parser: every character is kept,
// so a line always reads as it is in the file.

export type TokenKind = 'key' | 'fn' | 'string' | 'number' | 'comment' | 'jinja' | 'punct'

export interface Token {
  text: string
  kind?: TokenKind
}

const JINJA = /\{\{.*?\}\}|\{%.*?%\}|\{#.*?#\}/y
const JINJA_START = /\{[{%#]/y
const QUOTED = /"(?:[^"\\]|\\.)*"|'(?:[^']|'')*'/y
const INDENT = /[ \t]*/y
const DASHES = /(?:-(?:[ \t]+|$))+/y
const DOCUMENT = /^(?:---|\.\.\.)(?=\s|$)/
// A Salt state function as a key: pkg.installed, file.managed.
const FUNCTION = /^[A-Za-z_]\w*(?:\.\w+)+$/
const NUMBER = /^[-+]?(?:\d[\d_]*(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?$|^0x[\da-fA-F]+$|^0o[0-7]+$|^[-+]?\.(?:inf|Inf|INF)$|^\.(?:nan|NaN|NAN)$/
const CONSTANT = /^(?:true|True|TRUE|false|False|FALSE|yes|Yes|YES|no|No|NO|on|On|ON|off|Off|OFF|null|Null|NULL|~)$/
const BLOCK = /^[|>][-+1-9]*$/
const FLOW = '[]{},'

/** Salt states and other YAML, by the file's name. */
export function isYamlFile(path: string | null): boolean {
  return !!path && /\.(?:sls|ya?ml)$/i.test(path)
}

function matchAt(pattern: RegExp, line: string, at: number): string | null {
  pattern.lastIndex = at
  return pattern.exec(line)?.[0] ?? null
}

const isSpace = (ch: string | undefined) => ch === ' ' || ch === '\t'

/** Where a mapping key that starts at `from` ends (its colon), or -1 when there's none. */
function keyEnd(line: string, from: number): number {
  if (line[from] === '[' || (line[from] === '{' && !matchAt(JINJA_START, line, from))) return -1
  let i = from
  if (line[i] === '"' || line[i] === "'") {
    const quoted = matchAt(QUOTED, line, i)
    if (!quoted) return -1
    i += quoted.length
  }
  while (i < line.length) {
    if (matchAt(JINJA_START, line, i)) {
      const jinja = matchAt(JINJA, line, i)
      if (!jinja) return -1
      i += jinja.length
      continue
    }
    const ch = line[i]
    if (ch === '#' && (i === from || isSpace(line[i - 1]))) return -1
    if (ch === ':' && (i + 1 === line.length || isSpace(line[i + 1]))) return i
    i++
  }
  return -1
}

/** A key's text, with any Jinja in it picked out. */
function keyTokens(text: string): Token[] {
  const kind: TokenKind = FUNCTION.test(text) ? 'fn' : 'key'
  const out: Token[] = []
  let plain = ''
  for (let i = 0; i < text.length; ) {
    const jinja = matchAt(JINJA, text, i)
    if (jinja) {
      if (plain) out.push({ text: plain, kind })
      plain = ''
      out.push({ text: jinja, kind: 'jinja' })
      i += jinja.length
    } else plain += text[i++]
  }
  if (plain) out.push({ text: plain, kind })
  return out
}

/** A run of plain text in a value: its spaces plain, and what's between them by what it looks like. */
function scalarTokens(run: string, first: boolean): { tokens: Token[]; block: boolean } {
  const core = run.trim()
  const lead = run.slice(0, run.length - run.trimStart().length)
  const trail = run.slice(lead.length + core.length)
  const block = first && BLOCK.test(core)
  const kind: TokenKind = block ? 'punct' : NUMBER.test(core) || CONSTANT.test(core) ? 'number' : 'string'
  const tokens: Token[] = []
  if (lead) tokens.push({ text: lead })
  if (core) tokens.push({ text: core, kind })
  if (trail) tokens.push({ text: trail })
  return { tokens, block }
}

/** A value from `from` to the end of the line. Says whether it opens a block of text (| or >). */
function valueTokens(line: string, from: number, out: Token[]): boolean {
  let first = true
  let block = false
  let i = from
  while (i < line.length) {
    const ch = line[i]!
    if (matchAt(JINJA_START, line, i)) {
      const jinja = matchAt(JINJA, line, i) ?? line.slice(i) // unclosed: the rest of the line
      out.push({ text: jinja, kind: jinja.startsWith('{#') ? 'comment' : 'jinja' })
      i += jinja.length
      first = false
    } else if (ch === '#' && (i === 0 || isSpace(line[i - 1]))) {
      out.push({ text: line.slice(i), kind: 'comment' })
      break
    } else if ((ch === '"' || ch === "'") && (i === from || isSpace(line[i - 1]) || FLOW.includes(line[i - 1]!))) {
      const quoted = matchAt(QUOTED, line, i) ?? line.slice(i)
      out.push({ text: quoted, kind: 'string' })
      i += quoted.length
      first = false
    } else if (FLOW.includes(ch)) {
      out.push({ text: ch, kind: 'punct' })
      i++
      first = false
    } else {
      let end = i
      while (
        end < line.length &&
        !FLOW.includes(line[end]!) &&
        !matchAt(JINJA_START, line, end) &&
        !(line[end] === '#' && isSpace(line[end - 1]))
      )
        end++
      const scalar = scalarTokens(line.slice(i, end), first)
      out.push(...scalar.tokens)
      block ||= scalar.block
      if (line.slice(i, end).trim()) first = false
      i = end
    }
  }
  return block
}

/** The file's lines, each as tokens to color. */
export function highlightYaml(source: string): Token[][] {
  // Inside a block of text (after `key: |`): lines indented past the key's line are text.
  let blockIndent: number | null = null
  return source.split('\n').map((line) => {
    const indent = matchAt(INDENT, line, 0) ?? ''
    if (blockIndent !== null) {
      if (!line.trim()) return line ? [{ text: line }] : []
      if (indent.length > blockIndent) return [{ text: line, kind: 'string' }]
      blockIndent = null
    }
    const out: Token[] = []
    const document = line.match(DOCUMENT)?.[0]
    if (document) {
      out.push({ text: document, kind: 'punct' })
      valueTokens(line, document.length, out)
      return out
    }
    if (indent) out.push({ text: indent })
    let i = indent.length
    const dashes = matchAt(DASHES, line, i)
    if (dashes) {
      out.push({ text: dashes, kind: 'punct' })
      i += dashes.length
    }
    const colon = keyEnd(line, i)
    if (colon > i) {
      out.push(...keyTokens(line.slice(i, colon)), { text: ':', kind: 'punct' })
      i = colon + 1
    }
    if (valueTokens(line, i, out)) blockIndent = indent.length
    return out
  })
}
