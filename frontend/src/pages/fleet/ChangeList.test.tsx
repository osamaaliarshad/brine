import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import type { InventoryChange } from '@/api/types'
import { ChangeList } from '@/pages/fleet/ChangeList'

const NOW = Date.parse('2026-10-20T12:00:00Z')
const ago = (seconds: number) => new Date(NOW - seconds * 1000).toISOString()

const CHANGES: InventoryChange[] = [
  {
    minion_id: 'rover-01',
    source: 'packages',
    name: 'rover-agent',
    old: '2.3.0',
    new: '2.4.1',
    at: ago(600),
    since: ago(7200),
    jid: null,
    user: null,
  },
  { minion_id: 'rover-01', source: 'rover-cli', name: '', old: null, new: 'rover-cli 1.2.0', at: ago(600), since: ago(7200), jid: null, user: null },
]

describe('ChangeList', () => {
  it("can name what changed, for one minion's history", () => {
    render(
      <MemoryRouter>
        <ChangeList changes={CHANGES} now={NOW} label="Changes" showName />
      </MemoryRouter>,
    )
    const [agent, cli] = within(screen.getByRole('list', { name: 'Changes' })).getAllByRole('listitem')
    expect(agent).toHaveTextContent('10m ago rover-01 rover-agent 2.3.0 → 2.4.1')
    expect(cli).toHaveTextContent('rover-cli rover-cli 1.2.0 (new)') // a single-value check goes by its own name
  })
})
