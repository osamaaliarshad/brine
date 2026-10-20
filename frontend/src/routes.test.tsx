import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import { fleet, mockApi, renderApp, systemStatus } from '@/test/render'

describe('app shell', () => {
  beforeEach(() => {
    mockApi({ '/api/fleet': fleet([]), '/api/status': systemStatus() })
  })

  it('shows the wordmark and main navigation', () => {
    renderApp('/')
    expect(screen.getAllByRole('img', { name: 'brine' }).length).toBeGreaterThan(0)
    const nav = screen.getByRole('navigation', { name: 'Main' })
    for (const label of ['Fleet', 'Jobs', 'Keys', 'Events', 'Issues']) {
      expect(nav).toHaveTextContent(label)
    }
  })

  it('navigates between pages', async () => {
    renderApp('/')
    expect(screen.getByRole('heading', { name: 'Fleet' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('link', { name: 'Jobs' }))
    expect(screen.getByRole('heading', { name: 'Jobs' })).toBeInTheDocument()
  })

  it('has a page per minion', () => {
    renderApp('/minions/rover-01')
    expect(screen.getByRole('heading', { name: 'rover-01' })).toBeInTheDocument()
  })

  it('renders a not-found page for unknown routes', () => {
    renderApp('/nope')
    expect(screen.getByRole('heading', { name: 'Not found' })).toBeInTheDocument()
  })

  it('toggles the theme', async () => {
    document.documentElement.dataset.theme = 'dark'
    renderApp('/')
    await userEvent.click(screen.getByRole('button', { name: 'Switch to light theme' }))
    expect(document.documentElement.dataset.theme).toBe('light')
  })

  it('opens one live-update stream', async () => {
    const { FakeEventSource } = await import('@/test/setup')
    renderApp('/')
    expect(FakeEventSource.instances.map((s) => s.url)).toEqual(['/api/stream'])
  })
})

describe('collapsible sidebar', () => {
  beforeEach(() => {
    mockApi({ '/api/fleet': fleet([]), '/api/status': systemStatus() })
  })

  it('collapses to icons with the b mark, and remembers it', async () => {
    const user = userEvent.setup()
    renderApp('/')
    const nav = screen.getAllByRole('navigation', { name: 'Main' })[0]!
    await user.click(screen.getAllByRole('button', { name: 'Collapse sidebar' })[0]!)
    expect(localStorage.getItem('brine-sidebar-collapsed')).toBe('1')
    // Labels stay available to screen readers and as tooltips.
    expect(within(nav).getByRole('link', { name: 'Jobs' })).toHaveAttribute('title', 'Jobs')
    expect(screen.getAllByRole('button', { name: 'Expand sidebar' })).toHaveLength(1)
  })

  it('toggles with the [ key, but not while typing', async () => {
    const user = userEvent.setup()
    renderApp('/')
    await user.keyboard('[[') // '[[' is a literal '[' in user-event syntax
    expect(localStorage.getItem('brine-sidebar-collapsed')).toBe('1')
    await user.click(screen.getByRole('searchbox', { name: 'Search minions' }))
    await user.keyboard('[[') // '[[' is a literal '[' in user-event syntax
    expect(localStorage.getItem('brine-sidebar-collapsed')).toBe('1')
  })
})
