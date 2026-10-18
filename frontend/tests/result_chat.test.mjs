import assert from 'node:assert/strict'
import { test, afterEach } from 'node:test'
import { build } from 'esbuild'

const { outputFiles } = await build({ entryPoints: ['src/ocr.ts'], bundle: true, write: false, platform: 'node', format: 'esm' })
const { askSimulation } = await import('data:text/javascript;base64,' + Buffer.from(outputFiles[0].text).toString('base64'))
const original = globalThis.fetch
afterEach(() => { globalThis.fetch = original })
const cfg = { baseUrl: 'https://user-provider.test/v1', apiKey: 'private-test-key', model: 'glm-5.3-flash' }

test('result chat sends grounded evidence and conversation only to the configured model', async () => {
  globalThis.fetch = async (url, options) => {
    assert.equal(url, 'https://user-provider.test/v1/chat/completions')
    assert.equal(options.headers.Authorization, 'Bearer private-test-key')
    assert.ok(!options.body.includes('private-test-key'))
    const body = JSON.parse(options.body)
    assert.equal(body.model, cfg.model)
    assert.equal(body.thinking.type, 'disabled')
    assert.match(body.messages[1].content, /run_a.*419mV/)
    assert.deepEqual(body.messages.slice(-3), [{ role: 'user', content: '上次的问题' }, { role: 'assistant', content: '上次的答复' }, { role: 'user', content: '为什么失败' }])
    return Response.json({ choices: [{ message: { content: '求解成功，截图校验失败。' } }] })
  }
  assert.equal(await askSimulation(cfg, 'run_a 419mV', [{ role: 'user', content: '上次的问题' }, { role: 'assistant', content: '上次的答复' }], '为什么失败'), '求解成功，截图校验失败。')
})

test('cancelling result chat aborts the provider request', async () => {
  const ctrl = new AbortController()
  globalThis.fetch = async (_url, { signal }) => new Promise((_resolve, reject) => {
    signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
    ctrl.abort()
  })
  await assert.rejects(askSimulation(cfg, 'run_a', [], '问题', ctrl.signal), { name: 'AbortError' })
})

test('provider failures remain actionable without pretending an answer was returned', async () => {
  globalThis.fetch = async () => Response.json({ error: { message: 'invalid model' } }, { status: 400 })
  await assert.rejects(askSimulation(cfg, 'run_a', [], '问题'), /HTTP 400.*invalid model/)
})
