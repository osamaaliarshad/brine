import { describe, expect, it } from 'vitest'
import { highlightYaml, isYamlFile } from '@/lib/yamlHighlight'

/** Each line as [text, kind] pairs, plain text as kind ''. */
function tokens(source: string) {
  return highlightYaml(source).map((line) => line.map((t) => [t.text, t.kind ?? '']))
}

describe('highlightYaml', () => {
  it('colors a state: its id, function, keys and values', () => {
    expect(tokens('nginx:\n  pkg.installed:\n    - version: 1.24\n    - refresh: True')).toEqual([
      [['nginx', 'key'], [':', 'punct']],
      [['  ', ''], ['pkg.installed', 'fn'], [':', 'punct']],
      [['    ', ''], ['- ', 'punct'], ['version', 'key'], [':', 'punct'], [' ', ''], ['1.24', 'number']],
      [['    ', ''], ['- ', 'punct'], ['refresh', 'key'], [':', 'punct'], [' ', ''], ['True', 'number']],
    ])
  })

  it('colors strings, quoted or not, and comments', () => {
    expect(tokens(`name: "/etc/motd" # the banner\nsource: salt://motd\n# all of it`)).toEqual([
      [['name', 'key'], [':', 'punct'], [' ', ''], ['"/etc/motd"', 'string'], [' ', ''], ['# the banner', 'comment']],
      [['source', 'key'], [':', 'punct'], [' ', ''], ['salt://motd', 'string']],
      [['# all of it', 'comment']],
    ])
  })

  it('colors Jinja wherever it is, keys included', () => {
    expect(tokens("{% for user in users %}\n{{ user }}_home:\n  file.directory:\n    - user: {{ user }}\n{# done #}")).toEqual([
      [['{% for user in users %}', 'jinja']],
      [['{{ user }}', 'jinja'], ['_home', 'key'], [':', 'punct']],
      [['  ', ''], ['file.directory', 'fn'], [':', 'punct']],
      [['    ', ''], ['- ', 'punct'], ['user', 'key'], [':', 'punct'], [' ', ''], ['{{ user }}', 'jinja']],
      [['{# done #}', 'comment']],
    ])
  })

  it("doesn't take a colon inside a value, a URL or quotes for a key", () => {
    expect(tokens(`- 'a: b'\n- http://example.com`)).toEqual([
      [['- ', 'punct'], ["'a: b'", 'string']],
      [['- ', 'punct'], ['http://example.com', 'string']],
    ])
  })

  it('keeps a block of text as a string until it ends', () => {
    expect(tokens('contents: |\n  line one: still text\n  # not a comment\nnext: 1')).toEqual([
      [['contents', 'key'], [':', 'punct'], [' ', ''], ['|', 'punct']],
      [['  line one: still text', 'string']],
      [['  # not a comment', 'string']],
      [['next', 'key'], [':', 'punct'], [' ', ''], ['1', 'number']],
    ])
  })

  it('reads files with Windows line endings the same', () => {
    expect(tokens('nginx:\r\n  pkg.installed:\r\n    -\r\n')).toEqual([
      [['nginx', 'key'], [':', 'punct'], ['\r', '']],
      [['  ', ''], ['pkg.installed', 'fn'], [':', 'punct'], ['\r', '']],
      [['    ', ''], ['-', 'punct'], ['\r', '']],
      [],
    ])
  })

  it('keeps every character, so the lines read as they are', () => {
    const source = "a:\n  - [1, two]\n  - {k: v}\n---\n\tweird: 'it''s'  # ok"
    expect(highlightYaml(source).map((line) => line.map((t) => t.text).join(''))).toEqual(source.split('\n'))
  })
})

describe('isYamlFile', () => {
  it('knows Salt states and YAML by their extension', () => {
    expect(['top.sls', 'web/init.SLS', 'pillar.yaml', 'a.yml'].map(isYamlFile)).toEqual([true, true, true, true])
    expect(['motd', 'nginx.conf', 'run.sh', null].map(isYamlFile)).toEqual([false, false, false, false])
  })
})
