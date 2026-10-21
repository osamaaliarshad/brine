export type TreeFolder = { name: string; path: string; folders: TreeFolder[]; files: string[] }

/** Paths like "web/nginx/init.sls" as nested folders, folders first, both alphabetical. */
export function buildTree(paths: string[]): TreeFolder {
  const root: TreeFolder = { name: '', path: '', folders: [], files: [] }
  for (const path of paths) {
    const parts = path.split('/')
    let folder = root
    for (const part of parts.slice(0, -1)) {
      const at = folder.path ? `${folder.path}/${part}` : part
      let next = folder.folders.find((f) => f.name === part)
      if (!next) {
        next = { name: part, path: at, folders: [], files: [] }
        folder.folders.push(next)
      }
      folder = next
    }
    folder.files.push(path)
  }
  const sort = (folder: TreeFolder) => {
    folder.folders.sort((a, b) => a.name.localeCompare(b.name))
    folder.files.sort((a, b) => a.localeCompare(b))
    folder.folders.forEach(sort)
  }
  sort(root)
  return root
}

export function countFiles(folder: TreeFolder): number {
  return folder.files.length + folder.folders.reduce((n, f) => n + countFiles(f), 0)
}
