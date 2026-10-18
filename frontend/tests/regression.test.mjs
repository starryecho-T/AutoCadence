import assert from 'node:assert/strict'
import { test, afterEach } from 'node:test'
import { build } from 'esbuild'

async function loadModule(file) {
  const { outputFiles } = await build({ entryPoints: [file], bundle: true, write: false, platform: 'node', format: 'esm' })
  return import('data:text/javascript;base64,' + Buffer.from(outputFiles[0].text).toString('base64'))
}
const api = await loadModule('src/api.ts')
const circuit = await loadModule('src/circuit.ts')
const { pollSequentially } = await loadModule('src/polling.ts')
const nativeFetch = globalThis.fetch
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))
const task = (params = {}) => ({ kind: 'rc_lowpass', params: { r_ohm: 1000, c_farad: 1e-6, ...params } })
const respond = (body, status = 200) => { globalThis.fetch = async () => new Response(JSON.stringify(body), { status }) }
afterEach(() => { globalThis.fetch = nativeFetch; api.retainDemoRuns([]) })

test('R/C units, scientific notation and frequency ranges parse correctly', () => {
  for (const [text, r, c] of [
    ['R=2kΩ C=100nF', 2000, 1e-7], ['R=4.7k C=0.1µF', 4700, 1e-7],
    ['电阻 1 MΩ，电容 1 F', 1e6, 1], ['330 ohm 1mF', 330, 1e-3],
    ['R=2.2e3 Ω C=1e-6 F', 2200, 1e-6], ['R=0 C=1uF', 0, 1e-6],
    ['R=-10Ω C=1μF', -10, 1e-6], ['R=1mΩ C=2pF', 0.001, 2e-12]
  ]) {
    const parsed = api.demoParse(text).task.params
    assert.ok(Math.abs(parsed.r_ohm - r) <= Math.abs(r) * 1e-12, text)
    assert.ok(Math.abs(parsed.c_farad - c) <= Math.abs(c) * 1e-12, text)
  }
  const parsed = api.demoParse('1 Hz ~ 100 kHz，C=1uF')
  assert.equal(parsed.task.params.r_ohm, 1000, 'kHz must not become resistance')
  assert.equal(parsed.defaults.r_ohm, 1000)
  assert.equal(parsed.task.params.freq_min_hz, 1)
  assert.equal(parsed.task.params.freq_max_hz, 100000)
  assert.throws(() => api.demoParse('', true), /先识别图片/)
})

test('invalid electrical parameters and frequency ranges cannot be submitted', async () => {
  for (const params of [
    { r_ohm: 0 }, { r_ohm: -1 }, { r_ohm: '1000' }, { c_farad: Infinity },
    { c_farad: NaN }, { c_farad: '' }, { freq_min_hz: 0 }, { freq_max_hz: -1 },
    { freq_min_hz: 100, freq_max_hz: 10 }, { f_min_hz: 100, f_max_hz: 100 },
    { freq_min_hz: 10, f_min_hz: 20 }, { r_ohm: 1e300, c_farad: 1e300 }
  ]) {
    assert.ok(circuit.validateTask(task(params)), JSON.stringify(params))
    assert.throws(() => api.demoRunStart(task(params)))
    await assert.rejects(api.postRun(task(params)))
  }
  assert.equal(circuit.validateTask(task({ note: 'custom input' })), null)
})

test('RC metrics and report agree; repeated reads preserve results and timestamps', async () => {
  const id = api.demoRunStart(task())
  const initial = api.demoRunGet(id, 0)
  const completed = api.demoRunGet(id, 7000)
  assert.equal(completed.metrics.tau_ms, 1)
  assert.equal(completed.metrics.gain_at_dc, 1)
  assert.ok(Math.abs(completed.metrics.cutoff_hz - 159.15494309189535) < 1e-10)
  assert.equal(initial.created_at, completed.created_at)
  assert.equal(completed, api.demoRunGet(id, 0))
  const report = await (await nativeFetch(completed.artifacts.find((a) => a.kind === 'report_html').url)).text()
  assert.match(report, /时间常数 τ = RC<\/th><td>1 ms/)
  assert.match(report, /159\.155 Hz/)
  assert.match(report, /<img src="data:image\/svg\+xml;utf8,%3Csvg/)
  assert.throws(() => api.demoRunGet('missing-run'), /不存在/)
})

test('report escapes extra input and cannot overwrite computed metrics', async () => {
  const id = api.demoRunStart(task({ '<script>': '<img onerror=alert(1)>', tau_ms: 12345, cutoff_hz: 7 }))
  const result = api.demoRunGet(id, 7000)
  assert.equal(result.metrics.tau_ms, 1)
  const report = await (await nativeFetch(result.artifacts.find((a) => a.kind === 'report_html').url)).text()
  assert.doesNotMatch(report, /<script>|<img onerror/)
  assert.match(report, /&lt;script&gt;/)
})

test('low cutoff frequencies and custom scans produce finite plots', () => {
  for (const params of [{ r_ohm: 1e6, c_farad: 1 }, { freq_min_hz: 1000, freq_max_hz: 2000 }, { f_max_hz: 0.001 }]) {
    const result = api.demoRunGet(api.demoRunStart(task(params)), 7000)
    const svg = decodeURIComponent(result.artifacts.find((a) => a.kind === 'waveform').url.split(',')[1])
    assert.doesNotMatch(svg, /NaN|Infinity/)
    assert.doesNotMatch(svg, /polyline points=""/)
  }
})

test('real API rejects parse failures, unknown statuses, wrong IDs and malformed history', async () => {
  respond({ status: 'ok' })
  await api.getHealth()
  respond({ ok: false, message: '无法解析' })
  await assert.rejects(api.postParse('test'), /无法解析/)
  respond({ task: { kind: 'rc_lowpass' } })
  await assert.rejects(api.postParse('test'), /未解析到电路参数/)
  respond({ run_id: 'a', status: 'mystery' })
  await assert.rejects(api.getRun('a'), /未知任务状态/)
  respond({ run_id: 'other', status: 'succeeded' })
  await assert.rejects(api.getRun('a'), /不一致/)
  respond({ items: {} })
  await assert.rejects(api.listRuns(), /列表格式/)
  respond({ run_id: 'a', status: 'failed', error: { code: 'LICENSE', stage: 'simulate', message: 'Unavailable' }, artifacts: [{ kind: 'log', url: '/log' }] })
  const failed = await api.getRun('a')
  assert.equal(failed.error.code, 'LICENSE')
  assert.equal(failed.artifacts[0].url, '/log')
})

test('health failures use labelled demo mode; cancellation does not change modes', async () => {
  respond({ ok: false })
  assert.equal((await api.getHealth()).demo, true)
  respond({ status: 'active', version: '1' })
  assert.equal((await api.getHealth()).demo, undefined)
  const controller = new AbortController()
  controller.abort()
  globalThis.fetch = async (_url, { signal }) => { signal.throwIfAborted() }
  await assert.rejects(api.getHealth(controller.signal))
  assert.equal(api.isDemoMode(), false)
})

test('artifact URLs allow expected resources and reject executable protocols', () => {
  for (const url of ['javascript:alert(1)', 'file:///private', '//other.example/file']) assert.equal(api.artifactUrl({ url }), '')
  for (const url of ['/api/files/a', 'https://example.com/image.png', 'blob:test', 'data:image/svg+xml,example']) assert.equal(api.artifactUrl({ url }), url)
})

test('request deadlines abort stalled health and progress requests', async (context) => {
  context.mock.timers.enable({ apis: ['setTimeout'] })
  globalThis.fetch = async (_url, { signal }) => new Promise((_resolve, reject) => {
    signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true })
  })
  const health = api.getHealth()
  context.mock.timers.tick(5000)
  assert.equal((await health).demo, true)
  const pending = api.getRun('test-timeout')
  const rejected = assert.rejects(pending, /请求超时/)
  context.mock.timers.tick(15000)
  await rejected
})

test('polling never overlaps slow requests and stops at terminal status', async () => {
  let active = 0, maximum = 0, count = 0
  let finish
  const done = new Promise((resolve) => { finish = resolve })
  const stop = pollSequentially({
    read: async () => { active++; maximum = Math.max(maximum, active); await sleep(15); active--; return ++count },
    onValue: (value) => { if (value === 3) finish() }, isDone: (value) => value === 3,
    onError: (error) => { throw error }, intervalMs: 1
  })
  try { await done; await sleep(25); assert.equal(maximum, 1); assert.equal(count, 3) } finally { stop() }
})

test('switching tasks cancels the request and ignores its late result or failure', async () => {
  for (const fail of [false, true]) {
    let release, requestSignal, values = 0, errors = 0
    const pending = new Promise((resolve, reject) => { release = fail ? () => reject(new Error('late')) : () => resolve(1) })
    const stop = pollSequentially({ read: (signal) => { requestSignal = signal; return pending }, onValue: () => values++, isDone: () => false, onError: () => errors++, intervalMs: 1 })
    stop(); release(); await sleep(5)
    assert.equal(requestSignal.aborted, true)
    assert.equal(values, 0); assert.equal(errors, 0)
  }
})

test('history eviction revokes generated reports and removes abandoned demo runs', () => {
  const id = api.demoRunStart(task())
  const reportUrl = api.demoRunGet(id, 7000).artifacts.find((a) => a.kind === 'report_html').url
  const revoke = URL.revokeObjectURL
  const revoked = []
  URL.revokeObjectURL = (url) => { revoked.push(url); revoke(url) }
  try { api.retainDemoRuns([]); assert.deepEqual(revoked, [reportUrl]); assert.throws(() => api.demoRunGet(id)) }
  finally { URL.revokeObjectURL = revoke }
})
