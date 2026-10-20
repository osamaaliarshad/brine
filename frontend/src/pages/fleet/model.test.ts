import { describe, expect, it } from 'vitest'
import {
  cellText,
  DEFAULT_VIEW,
  distinctValues,
  filterMinions,
  latestGrainsAt,
  matchesSearch,
  paginate,
  paramsFromView,
  sortMinions,
  viewFromParams,
} from '@/pages/fleet/model'
import { ago, minion } from '@/test/render'

const ids = (list: { id: string }[]) => list.map((m) => m.id)

describe('cellText', () => {
  it.each([
    [null, null],
    [undefined, null],
    ['', null],
    ['site-a', 'site-a'],
    [42, '42'],
    [true, 'true'],
    [['a', 'b'], 'a, b'],
    [{ x: 1 }, '{"x":1}'],
  ])('%j -> %j', (value, expected) => {
    expect(cellText(value)).toBe(expected)
  })
})

describe('search and filters', () => {
  const fleet = [
    minion('rover-01', { ip: '10.0.0.11', columns: { site: 'site-a', app_version: '2.4.1' } }),
    minion('rover-02', { status: 'offline', columns: { site: 'site-b', app_version: '2.3.0' } }),
    minion('dock-01', { os: 'Ubuntu 24.04', columns: { site: 'site-b', app_version: null } }),
  ]

  it('searches ids, IPs, OS and grain values, case-insensitively', () => {
    expect(matchesSearch(fleet[0]!, 'ROVER')).toBe(true)
    expect(matchesSearch(fleet[0]!, '10.0.0.11')).toBe(true)
    expect(matchesSearch(fleet[2]!, 'ubuntu')).toBe(true)
    expect(matchesSearch(fleet[1]!, '2.3.0')).toBe(true)
    expect(matchesSearch(fleet[0]!, 'nope')).toBe(false)
    expect(matchesSearch(fleet[0]!, '   ')).toBe(true)
  })

  it('combines status, group and search', () => {
    expect(ids(filterMinions(fleet, { status: 'all', q: '', group: 'site-b' }, 'site'))).toEqual([
      'rover-02',
      'dock-01',
    ])
    expect(ids(filterMinions(fleet, { status: 'offline', q: '', group: null }, 'site'))).toEqual([
      'rover-02',
    ])
    expect(ids(filterMinions(fleet, { status: 'all', q: 'rover', group: 'site-b' }, 'site'))).toEqual([
      'rover-02',
    ])
  })

  it('lists distinct group values', () => {
    expect(distinctValues(fleet, 'site')).toEqual(['site-a', 'site-b'])
    expect(distinctValues(fleet, 'app_version')).toEqual(['2.3.0', '2.4.1'])
  })
})

describe('sortMinions', () => {
  it('sorts ids naturally (rover-2 before rover-10)', () => {
    const list = [minion('rover-10'), minion('rover-2'), minion('rover-1')]
    expect(ids(sortMinions(list, 'id', 'asc'))).toEqual(['rover-1', 'rover-2', 'rover-10'])
    expect(ids(sortMinions(list, 'id', 'desc'))).toEqual(['rover-10', 'rover-2', 'rover-1'])
  })

  it('sorts connection by status, then most recently seen', () => {
    const list = [
      minion('off-old', { status: 'offline', last_seen_at: ago(3600) }),
      minion('on', { status: 'online' }),
      minion('off-new', { status: 'offline', last_seen_at: ago(60) }),
      minion('stale', { status: 'stale' }),
    ]
    expect(ids(sortMinions(list, 'connection', 'asc'))).toEqual(['on', 'stale', 'off-new', 'off-old'])
  })

  it('sorts grain columns with missing values last', () => {
    const list = [
      minion('a', { columns: { app_version: '2.10.0' } }),
      minion('b', { columns: { app_version: null } }),
      minion('c', { columns: { app_version: '2.9.1' } }),
    ]
    expect(ids(sortMinions(list, 'col:app_version', 'asc'))).toEqual(['c', 'a', 'b'])
  })
})

describe('paginate', () => {
  const items = Array.from({ length: 30 }, (_, i) => i)

  it('slices pages and clamps out-of-range pages', () => {
    expect(paginate(items, 1, 25)).toMatchObject({ page: 1, pages: 2 })
    expect(paginate(items, 2, 25).items).toEqual([25, 26, 27, 28, 29])
    expect(paginate(items, 9, 25).page).toBe(2)
    expect(paginate([], 1, 25)).toEqual({ items: [], page: 1, pages: 1 })
  })
})

describe('URL view state', () => {
  it('round-trips and keeps defaults out of the URL', () => {
    expect(paramsFromView(DEFAULT_VIEW).toString()).toBe('')
    const view = { status: 'offline', q: 'rover', group: 'site-b', sort: 'col:site', dir: 'desc', page: 2 } as const
    expect(viewFromParams(paramsFromView(view))).toEqual(view)
  })

  it('ignores junk values', () => {
    expect(viewFromParams(new URLSearchParams('status=bogus&dir=sideways&page=-3'))).toEqual(DEFAULT_VIEW)
  })
})

it('finds the most recent grains collection', () => {
  expect(latestGrainsAt([minion('a', { grains_at: ago(60) }), minion('b', { grains_at: ago(10) })])).toBe(ago(10))
  expect(latestGrainsAt([minion('a', { grains_at: null })])).toBeNull()
})
