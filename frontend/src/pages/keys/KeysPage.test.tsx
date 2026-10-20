import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Key } from '@/api/types'
import { ago, mockApi, NOW, renderApp, systemStatus } from '@/test/render'

const KEYS: Key[] = [
  { id: 'rover-01', key_state: 'accepted', fingerprint: 'aa:bb:cc:dd:ee:ff:00:11:22:33:44:55', first_seen_at: ago(86400), last_seen_at: ago(5), status: 'online' },
  { id: 'rover-03', key_state: 'accepted', fingerprint: '11:22', first_seen_at: ago(86400), last_seen_at: ago(3600), status: 'offline' },
  { id: 'rover-04', key_state: 'pending', fingerprint: 'ff:ee', first_seen_at: ago(1200), last_seen_at: null, status: null },
]

describe('KeysPage', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(NOW)
    mockApi({ '/api/keys': KEYS, '/api/status': systemStatus() })
  })
  afterEach(() => vi.useRealTimers())

  it('lists pending keys first with a call to action', async () => {
    renderApp('/keys')
    expect(await screen.findByText('1 key waiting for approval.')).toBeInTheDocument()
    const names = screen.getAllByRole('row').slice(1).map((r) => within(r).getAllByRole('cell')[0]!.textContent)
    expect(names).toEqual(['rover-04', 'rover-01', 'rover-03'])
    const pending = screen.getByText('rover-04').closest('tr')!
    expect(within(pending).getByText('Waiting since 20m ago')).toBeInTheDocument()
    expect(within(pending).queryByRole('link')).toBeNull() // not a minion page yet
  })

  it('shows fingerprints shortened, with the full value on hover', async () => {
    renderApp('/keys')
    const fp = await screen.findByTitle('aa:bb:cc:dd:ee:ff:00:11:22:33:44:55')
    expect(fp).toHaveTextContent('aa:bb:cc:dd…22:33:44:55')
  })

  it('filters by state', async () => {
    const user = userEvent.setup()
    renderApp('/keys')
    await user.click(await screen.findByRole('tab', { name: /Accepted/ }))
    expect(screen.queryByText('rover-04')).toBeNull()
    expect(screen.getByText('Last seen 1h ago')).toBeInTheDocument()
    // States with no keys aren't offered.
    expect(screen.queryByRole('tab', { name: /Rejected/ })).toBeNull()
  })
})
