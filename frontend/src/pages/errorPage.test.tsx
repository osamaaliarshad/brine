import { screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { mockApi, renderApp, systemStatus } from '@/test/render'

describe('error page', () => {
  it('keeps the sidebar when a page crashes, and says what happened', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})  // React logs the caught error
    mockApi({ '/api/fleet': { minions: null }, '/api/status': systemStatus() })
    renderApp('/')
    expect(await screen.findByRole('heading', { name: 'Something went wrong on this page' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Reload' })).toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: 'Jobs' })[0]).toBeInTheDocument()
    vi.mocked(console.error).mockRestore()
  })
})
