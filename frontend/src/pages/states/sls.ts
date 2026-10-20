import type { StateFile } from '@/api/types'

/** How Salt finds an SLS: `web.nginx` is web/nginx.sls or web/nginx/init.sls. */
export function slsToPath(sls: string, files: StateFile[]): string | null {
  const base = sls.replaceAll('.', '/')
  const paths = new Set(files.map((f) => f.path))
  if (paths.has(`${base}.sls`)) return `${base}.sls`
  if (paths.has(`${base}/init.sls`)) return `${base}/init.sls`
  return null
}
