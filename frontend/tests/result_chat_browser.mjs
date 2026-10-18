// Read-only against existing runs. Provider replies are fixtures; no simulation is submitted.
import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const origin = process.env.RESULT_CHAT_URL || 'http://127.0.0.1:18766'
const output = resolve(process.env.RESULT_CHAT_OUTPUT || '../work/result-chat-browser')
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ headless: true, channel: 'msedge' })
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1050 } })
  const failures = [], requests = [], submissions = []
  page.on('pageerror', e => failures.push(e.message))
  page.on('request', r => { if (r.method() === 'POST' && /\/api\/v[12]\/runs$/.test(r.url())) submissions.push(r.url()) })
  const runs = (await (await fetch(origin + '/api/v2/runs')).json()).runs
  const failed = runs.find(r => r.status === 'failed'), success = runs.find(r => r.status === 'succeeded')
  assert.ok(failed && success, 'Requires one historical failed run and one successful run')
  let delayed = false, release, bad = false
  await page.route('https://result-test.invalid/**', async route => {
    requests.push(route.request().postDataJSON())
    if (delayed) await new Promise(r => { release = r })
    await route.fulfill(bad ? { status: 429, json: { error: { message: '请稍后重试' } } } : { json: { choices: [{ message: { content: '这是问答界面测试回复：本次数据来自原始导出文件，具体结论应结合单位与连接判断。' } }] } }).catch(() => {})
  })
  await page.goto(origin)
  await page.getByText('后端在线', { exact: true }).waitFor()
  assert.equal(await page.title(), 'AutoCadence')
  await page.evaluate(() => localStorage.setItem('ocr-config-v1', JSON.stringify({ baseUrl: 'https://result-test.invalid/v1', apiKey: 'fixture-key', model: 'fixture' })))
  const choose = async id => { await page.locator(`[data-run-id="${id}"]`).click(); await page.getByRole('heading', { name: '与 AI 讨论本次结果' }).waitFor() }
  const input = page.getByLabel('询问本次仿真结果')
  const send = page.getByRole('button', { name: '发送问题' })
  await choose(failed.run_id)
  await page.getByRole('button', { name: '这次为什么失败，是器件不支持吗？', exact: true }).click()
  await send.click()
  await page.locator('.chat-message.assistant').waitFor()
  assert.match(requests[0].messages[1].content, new RegExp(failed.run_id))
  assert.ok(!JSON.stringify(requests[0]).includes('fixture-key'))
  await input.fill('应该优先检查哪个参数？'); await send.click()
  await page.waitForFunction(() => document.querySelectorAll('.chat-message.assistant').length === 2)
  assert.equal(requests[1].messages.length, 5)
  await choose(success.run_id)
  assert.equal(await page.locator('.chat-message').count(), 0)
  await page.getByRole('button', { name: '请解释本次仿真的主要结论', exact: true }).click(); await send.click()
  await page.locator('.chat-message.assistant').waitFor()
  assert.ok(!requests.at(-1).messages[1].content.includes(failed.run_id))
  await page.locator('.result-chat').scrollIntoViewIfNeeded()
  await page.screenshot({ path: resolve(output, 'result-chat.png'), animations: 'disabled' })
  for (const width of [760, 390]) {
    await page.setViewportSize({ width, height: 900 })
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `overflow at ${width}`)
  }
  await page.setViewportSize({ width: 1440, height: 1050 })
  bad = true
  await input.fill('失败时保留这条问题'); await send.click()
  await page.getByRole('alert').filter({ hasText: 'HTTP 429' }).waitFor()
  assert.equal(await input.inputValue(), '失败时保留这条问题')
  assert.equal(await page.locator('.chat-message.assistant').count(), 1)
  bad = false; delayed = true
  const pending = page.waitForRequest('https://result-test.invalid/v1/chat/completions')
  await send.click(); await pending
  await page.getByRole('button', { name: '停止回答' }).click()
  release?.()
  await send.waitFor(); assert.equal(await input.inputValue(), '失败时保留这条问题')
  delayed = false
  await choose(failed.run_id)
  assert.equal(await page.locator('.chat-message.assistant').count(), 2)
  await page.getByRole('button', { name: '清空对话' }).click()
  assert.equal(await page.locator('.chat-message').count(), 0)
  assert.deepEqual(failures, []); assert.deepEqual(submissions, [])
  const result = { status: 'PASS', current_run_context: true, separate_history: true, multiturn: true, cancellation: true, error_preserves_input: true, responsive: [390, 760, 1440], no_simulation_submission: true }
  await writeFile(resolve(output, 'verification.json'), JSON.stringify(result, null, 2))
  console.log(JSON.stringify(result))
} finally { await browser.close() }
