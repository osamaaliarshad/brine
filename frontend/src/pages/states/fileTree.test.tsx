import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { FileTree } from '@/pages/states/FileTree'
import { buildTree } from '@/pages/states/tree'

const PATHS = ['top.sls', 'web/nginx/init.sls', 'web/nginx/files/nginx.conf', 'web/app.sls', 'db/postgres.sls', 'motd.sls']

describe('state file tree', () => {
  it('nests paths in folders, folders first', () => {
    const tree = buildTree(PATHS)
    expect(tree.folders.map((f) => f.name)).toEqual(['db', 'web'])
    expect(tree.files).toEqual(['motd.sls', 'top.sls'])
    const web = tree.folders[1]!
    expect(web.files).toEqual(['web/app.sls'])
    expect(web.folders[0]!.path).toBe('web/nginx')
    expect(web.folders[0]!.folders[0]!.files).toEqual(['web/nginx/files/nginx.conf'])
  })

  it('opens on the selected file, and folders fold', async () => {
    const user = userEvent.setup()
    const onOpen = vi.fn()
    render(<FileTree paths={PATHS} selected="web/nginx/init.sls" onOpen={onOpen} />)
    const tree = screen.getByRole('list', { name: 'State files' })
    expect(within(tree).getByRole('button', { name: 'init.sls' })).toHaveAttribute('aria-current', 'true')
    expect(within(tree).queryByRole('button', { name: 'postgres.sls' })).toBeNull() // db/ starts folded
    expect(within(tree).getByRole('button', { name: /^web/ })).toHaveTextContent('3')

    await user.click(within(tree).getByRole('button', { name: /^db/ }))
    await user.click(within(tree).getByRole('button', { name: 'postgres.sls' }))
    expect(onOpen).toHaveBeenCalledWith('db/postgres.sls')
    await user.click(within(tree).getByRole('button', { name: /^web/ }))
    expect(within(tree).queryByRole('button', { name: 'app.sls' })).toBeNull()
  })

  it('filters by path', async () => {
    const user = userEvent.setup()
    render(<FileTree paths={PATHS} selected={null} onOpen={() => {}} />)
    await user.type(screen.getByRole('searchbox', { name: 'Filter files' }), 'nginx')
    const tree = screen.getByRole('list', { name: 'State files' })
    expect(within(tree).getAllByRole('button').map((b) => b.textContent)).toEqual([
      'web/nginx/init.sls',
      'web/nginx/files/nginx.conf',
    ])
    await user.clear(screen.getByRole('searchbox', { name: 'Filter files' }))
    await user.type(screen.getByRole('searchbox', { name: 'Filter files' }), 'zzz')
    expect(screen.getByText('No files match.')).toBeInTheDocument()
  })
})
