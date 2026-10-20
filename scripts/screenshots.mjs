#!/usr/bin/env node
// Regenerate the README screenshots from a running brine (demo data only). Node 22+, no deps.
//
//   docker compose -f docker-compose.demo.yml up -d --build --wait
//   (cd frontend && npm run build)
//   (cd backend && BRINE_CONFIG=../demo/brine.yaml uv run uvicorn app.main:create_app --factory)
//   node scripts/screenshots.mjs --stop-minion rover-03
//
// Drives headless Chrome/Chromium/Edge over the DevTools protocol (set BRINE_CHROME to choose a
// binary) and waits until each page has finished loading, so shots never catch a spinner.
// Writes docs/assets/screenshots/<page>-<light|dark>.png.
//
// Never point this at a real fleet: the images are committed to a public repo.

import { spawn, spawnSync } from 'node:child_process'
import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { parseArgs } from 'node:util'

const REPO = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const OUT = join(REPO, 'docs', 'assets', 'screenshots')

const getJson = async (url) => (await fetch(url)).json()

// [name, path or async (base) => path]. Add each page as it's built; the README shows them in
// this order.
export const PAGES = [
  ['fleet', '/'],
  ['grains', '/?tab=grains&grain=app_version'],
  ['nodegroups', '/?tab=nodegroups'],
  ['minion', '/minions/rover-01'],
  ['jobs', '/jobs'],
  ['state-runs', '/jobs?tab=states'],
  // The most recent state.apply: in the demo, dock-01's calibration state fails on purpose.
  ['job', async (base) => `/jobs/${(await getJson(`${base}/api/jobs?fun=state.apply&limit=1`)).jobs[0].jid}`],
  ['keys', '/keys'],
  ['states', '/states'],
  ['automation', '/automation'],
  ['events', '/events'],
  ['issues', '/issues'],
  // With sign-in off there are no sign-ins to show; looking at pillar is audited either way.
  [
    'audit',
    async (base) => {
      for (const id of ['rover-01', 'dock-01']) await fetch(`${base}/api/minions/${id}/live/pillar`)
      return '/audit'
    },
  ],
  ['settings', '/settings'],
]

const THEMES = ['light', 'dark']
const WIDTH = 1440
const HEIGHT = 900

// The page is ready once the main area has rendered and nothing says it's still loading.
const READY = `(() => {
  const main = document.querySelector('main')
  return !!main && main.innerText.length > 0 && !/Loading|Asking/.test(main.innerText)
    && document.fonts.status === 'loaded'
})()`

const CANDIDATES = [
  process.env.BRINE_CHROME,
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  process.env.LOCALAPPDATA && join(process.env.LOCALAPPDATA, 'Google\\Chrome\\Application\\chrome.exe'),
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  '/usr/bin/google-chrome',
  '/usr/bin/google-chrome-stable',
  '/usr/bin/chromium',
  '/usr/bin/chromium-browser',
]

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

function findBrowser() {
  const found = CANDIDATES.find((c) => c && existsSync(c))
  if (!found) throw new Error('No Chrome/Chromium/Edge found; set BRINE_CHROME to the browser binary.')
  return found
}

async function waitFor(what, check, timeoutMs) {
  const deadline = Date.now() + timeoutMs
  for (;;) {
    try {
      const value = await check()
      if (value) return value
    } catch {
      // not ready yet
    }
    if (Date.now() > deadline) throw new Error(`timed out waiting for ${what}`)
    await sleep(250)
  }
}

/** Minimal DevTools-protocol client over one page target. */
async function connect(wsUrl) {
  const ws = new WebSocket(wsUrl)
  await new Promise((ok, fail) => {
    ws.onopen = ok
    ws.onerror = () => fail(new Error(`can't connect to ${wsUrl}`))
  })
  let nextId = 0
  const pending = new Map()
  ws.onmessage = (msg) => {
    const data = JSON.parse(msg.data)
    if (data.id && pending.has(data.id)) {
      const { ok, fail } = pending.get(data.id)
      pending.delete(data.id)
      if (data.error) fail(new Error(data.error.message))
      else ok(data.result)
    }
  }
  const send = (method, params = {}) =>
    new Promise((ok, fail) => {
      const id = ++nextId
      pending.set(id, { ok, fail })
      ws.send(JSON.stringify({ id, method, params }))
    })
  return { send, close: () => ws.close() }
}

async function capture(port, url, theme, out) {
  const target = await (await fetch(`http://127.0.0.1:${port}/json/new?about:blank`, { method: 'PUT' })).json()
  const page = await connect(target.webSocketDebuggerUrl)
  try {
    await page.send('Emulation.setDeviceMetricsOverride', {
      width: WIDTH,
      height: HEIGHT,
      deviceScaleFactor: 1,
      mobile: false,
    })
    await page.send('Emulation.setEmulatedMedia', {
      features: [{ name: 'prefers-color-scheme', value: theme }],
    })
    await page.send('Page.navigate', { url })
    await waitFor(`${url} to load`, async () => {
      const { result } = await page.send('Runtime.evaluate', { expression: READY, returnByValue: true })
      return result.value === true
    }, 40_000)
    await sleep(800) // let transitions and streamed content settle
    const { data } = await page.send('Page.captureScreenshot', { format: 'png' })
    writeFileSync(out, Buffer.from(data, 'base64'))
  } finally {
    page.close()
    await fetch(`http://127.0.0.1:${port}/json/close/${target.id}`).catch(() => {})
  }
}

function compose(...args) {
  const result = spawnSync('docker', ['compose', '-f', join(REPO, 'docker-compose.demo.yml'), ...args], {
    stdio: 'pipe',
  })
  if (result.status !== 0) throw new Error(`docker compose ${args.join(' ')} failed: ${result.stderr}`)
}

async function statusOf(base, minion) {
  const fleet = await (await fetch(`${base}/api/fleet`)).json()
  return fleet.minions.find((m) => m.id === minion)?.status
}

async function main() {
  const { values } = parseArgs({
    options: {
      base: { type: 'string', default: 'http://127.0.0.1:8000' },
      'stop-minion': { type: 'string' },
      port: { type: 'string', default: '9333' },
    },
  })
  const { base, port } = values
  const stop = values['stop-minion']

  mkdirSync(OUT, { recursive: true })
  const profile = mkdtempSync(join(tmpdir(), 'brine-shots-'))
  const browser = spawn(
    findBrowser(),
    [
      '--headless=new',
      '--disable-gpu',
      '--hide-scrollbars',
      '--no-first-run',
      `--remote-debugging-port=${port}`,
      `--user-data-dir=${profile}`,
      `--window-size=${WIDTH},${HEIGHT}`,
      'about:blank',
    ],
    { stdio: 'ignore' },
  )

  try {
    await waitFor('the browser', async () => (await fetch(`http://127.0.0.1:${port}/json/version`)).ok, 20_000)
    if (stop) {
      compose('stop', stop)
      await waitFor(`${stop} to show offline`, async () => (await statusOf(base, stop)) === 'offline', 90_000)
    }
    for (const [name, page] of PAGES) {
      const path = typeof page === 'function' ? await page(base) : page
      for (const theme of THEMES) {
        const out = join(OUT, `${name}-${theme}.png`)
        await capture(port, base + path, theme, out)
        console.log(`wrote ${out.slice(REPO.length + 1)}`)
      }
    }
  } finally {
    if (stop) compose('start', stop)
    browser.kill()
    await sleep(500)
    rmSync(profile, { recursive: true, force: true })
  }
}

main().catch((err) => {
  console.error(err.message)
  process.exit(1)
})
