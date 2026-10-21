import { describe, expect, it } from 'vitest'
import { commandLine, formatArgs } from '@/pages/jobs/format'

describe('job arguments', () => {
  it('read like the salt CLI', () => {
    expect(formatArgs(['curl', { refresh: true, __kwarg__: true }])).toBe('curl refresh=true')
  })

  it.each([
    [['motd', { test: true, __kwarg__: true }], 'state.apply motd test=true'],
    [['ls -l /tmp'], 'state.apply "ls -l /tmp"'],
    [['say "hi"'], 'state.apply "say \\"hi\\""'],
    [['C:\\temp'], 'state.apply "C:\\\\temp"'],
    [[{ pkgs: ['vim', 'git'], __kwarg__: true }], 'state.apply "pkgs=[\\"vim\\",\\"git\\"]"'],
    [[''], 'state.apply ""'],
    [[42], 'state.apply 42'],
  ])('come back as a command line: %j', (args, expected) => {
    expect(commandLine('state.apply', args)).toBe(expected)
  })
})
