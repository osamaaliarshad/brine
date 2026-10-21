import { describe, expect, it } from 'vitest'
import { isInventoryKey, keyDescription, keyKind, keyLabel, parseInventoryKey } from '@/lib/inventoryKey'

describe('inventory keys', () => {
  it('parses packages and checks like the backend, and leaves grains alone', () => {
    expect(parseInventoryKey('@packages:rover-agent')).toEqual({ source: 'packages', name: 'rover-agent' })
    expect(parseInventoryKey('@containers:web')).toEqual({ source: 'containers', name: 'web' })
    expect(parseInventoryKey('@rover-cli')).toEqual({ source: 'rover-cli', name: '' })
    // Source names have no colon, so the first one ends it; package names may have more.
    expect(parseInventoryKey('@packages:libc6:amd64')).toEqual({ source: 'packages', name: 'libc6:amd64' })
    expect(parseInventoryKey('@rover-cli:')).toEqual({ source: 'rover-cli', name: '' })

    for (const key of ['app_version', 'os:family', '', '@', '@:bash']) expect(parseInventoryKey(key)).toBeNull()
    expect(isInventoryKey('@packages:bash')).toBe(true)
    expect(isInventoryKey('@rover-cli')).toBe(true)
    expect(isInventoryKey('osfinger')).toBe(false)
    expect(isInventoryKey('@')).toBe(false)
  })

  it('labels each key with its name and kind', () => {
    expect(keyLabel('@packages:rover-agent')).toBe('rover-agent')
    expect(keyLabel('@containers:web')).toBe('web')
    expect(keyLabel('@rover-cli')).toBe('rover-cli')
    expect(keyLabel('os:family')).toBe('os:family')

    expect(keyKind('@packages:rover-agent')).toBe('package')
    expect(keyKind('@containers:web')).toBe('check')
    expect(keyKind('@rover-cli')).toBe('check')
    expect(keyKind('os:family')).toBe('grain')

    expect(keyDescription('@packages:rover-agent')).toBe('The rover-agent package')
    expect(keyDescription('@containers:web')).toBe('web, from the containers check')
    expect(keyDescription('@rover-cli')).toBe('The rover-cli check')
    expect(keyDescription('os:family')).toBe('The os:family grain')
  })
})
