import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { describe, expect, it } from 'vitest'
import { routes } from '@/routes'

function renderAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] })
  render(<RouterProvider router={router} />)
}

describe('app shell', () => {
  it('shows the wordmark and main navigation', () => {
    renderAt('/')
    expect(screen.getAllByRole('img', { name: 'brine' }).length).toBeGreaterThan(0)
    const nav = screen.getByRole('navigation', { name: 'Main' })
    for (const label of ['Fleet', 'Jobs', 'Keys', 'Events', 'Issues']) {
      expect(nav).toHaveTextContent(label)
    }
  })

  it('navigates between pages', async () => {
    renderAt('/')
    expect(screen.getByRole('heading', { name: 'Fleet' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('link', { name: 'Jobs' }))
    expect(screen.getByRole('heading', { name: 'Jobs' })).toBeInTheDocument()
  })

  it('renders a not-found page for unknown routes', () => {
    renderAt('/nope')
    expect(screen.getByRole('heading', { name: 'Not found' })).toBeInTheDocument()
  })

  it('toggles the theme', async () => {
    document.documentElement.dataset.theme = 'dark'
    renderAt('/')
    await userEvent.click(screen.getByRole('button', { name: 'Switch to light theme' }))
    expect(document.documentElement.dataset.theme).toBe('light')
  })
})
