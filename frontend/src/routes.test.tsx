import { screen } from '@testing-library/react'
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
