import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { existsSync, mkdirSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { createInterface } from 'node:readline'

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE ? pathToFileURL(process.env.PLAYWRIGHT_MODULE).href : 'playwright')
const localPython = resolve('../backend/.venv-local/Scripts/python.exe')
const python = process.env.VAI_TEST_PYTHON || (existsSync(localPython) ? localPython : 'python')
const output = resolve(process.env.VAI_BROWSER_OUTPUT || '../work/browser-verification')
mkdirSync(output, { recursive: true })
const server = spawn(python, ['-X', 'utf8', 'tests/workflow_server.py'], { windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] })
let serverErrors = ''
server.stderr.on('data', (data) => { serverErrors += data.toString() })
let browser, page
const errors = [], submissions = [], networkFailures = []
try {
  const info = await new Promise((resolveInfo, reject) => {
    const timeout = setTimeout(() => reject(new Error('Browser test server startup timed out: ' + serverErrors)), 15000)
    createInterface({ input: server.stdout }).once('line', (line) => {
      clearTimeout(timeout)
      try { resolveInfo(JSON.parse(line)) } catch (error) { reject(error) }
    })
    server.once('error', (error) => { clearTimeout(timeout); reject(error) })
    server.once('exit', (code) => { clearTimeout(timeout); reject(new Error(`Test server exited ${code}: ${serverErrors}`)) })
  })
  for (let attempt = 0; attempt < 100; attempt++) {
    try { if ((await fetch(info.url + '/health')).ok) break } catch { /* startup */ }
    if (attempt === 99) throw new Error('Test server was not ready')
    await new Promise((resolveWait) => setTimeout(resolveWait, 100))
  }
  browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {}) })
  page = await browser.newPage({ viewport: { width: 1120, height: 820 } })
  page.on('pageerror', (error) => errors.push(error.message))
  page.on('console', (message) => { if (message.type() === 'error') errors.push(message.text()) })
  page.on('requestfailed', (request) => networkFailures.push({ url: request.url(), error: request.failure()?.errorText }))
  page.on('request', (request) => {
    if (request.method() === 'POST' && request.url().endsWith('/api/v1/runs')) submissions.push(request.postDataJSON())
  })
  await page.goto(info.url)
  await page.getByText(/后端在线/).waitFor()
  await page.getByRole('button', { name: '设置', exact: true }).filter({ visible: true }).click()
  await page.getByRole('dialog', { name: 'AI 识别设置' }).waitFor()
  await page.keyboard.press('Escape')
  assert.equal(await page.getByRole('dialog').count(), 0)
  await page.screenshot({ path: resolve(output, 'input.png'), fullPage: true, animations: 'disabled' })
  await page.locator('textarea').evaluate(el => {
    const clipboard = new DataTransfer()
    clipboard.items.add(new File([new Uint8Array([1, 2, 3])], 'clipboard.png', { type: 'image/png' }))
    el.dispatchEvent(new ClipboardEvent('paste', { clipboardData: clipboard, bubbles: true, cancelable: true }))
  })
  await page.getByText('clipboard.png', { exact: true }).waitFor()
  await page.getByRole('button', { name: '移除图片' }).click()
  await page.getByRole('button', { name: '填入示例题目' }).click()
  await page.getByRole('button', { name: '解析题目', exact: true }).click()
  await page.getByText(/参数预检通过/).waitFor()
  assert.equal(submissions.length, 0, 'parsing must not submit before user confirmation')
  assert.equal(await page.locator('#param-r_ohm').inputValue(), '16')
  assert.equal(await page.getByLabel('电阻 R单位').inputValue(), '1000')
  await page.getByLabel('电阻 R单位').selectOption('1')
  assert.equal(await page.locator('#param-r_ohm').inputValue(), '16000')
  await page.getByLabel('电阻 R单位').selectOption('1000')
  await page.locator('#param-r_ohm').fill('')
  assert.equal(await page.getByRole('button', { name: '确认并开始仿真' }).isDisabled(), true)
  assert.equal(await page.locator('#param-r_ohm').getAttribute('type'), 'number')
  await page.locator('#param-r_ohm').fill('16')
  assert.equal(Number(await page.locator('#param-c_farad').inputValue()), 10)
  await page.getByLabel('电容 C单位').selectOption('0.000001')
  assert.equal(Number(await page.locator('#param-c_farad').inputValue()), .01)
  await page.getByLabel('电容 C单位').selectOption('1e-9')
  assert.ok(await page.getByTestId('theory-cutoff').innerText() === '994.718')
  assert.equal(Number(await page.locator('#param-high_v').inputValue()), 2)
  await page.getByText('高级仿真设置', { exact: false }).click()
  await page.locator('#param-stop_s').fill('1')
  assert.equal(await page.getByRole('button', { name: '确认并开始仿真' }).isDisabled(), true)
  await page.locator('#param-stop_s').fill('8.3')
  await page.getByText(/参数预检通过/).waitFor()
  await page.getByText('高级仿真设置', { exact: false }).click()
  await page.screenshot({ path: resolve(output, 'confirmation.png'), fullPage: true, animations: 'disabled' })
  await page.getByRole('button', { name: '确认并开始仿真' }).click()
  await page.getByRole('heading', { name: /仿真失败/ }).waitFor()
  assert.equal(submissions.length, 1)
  assert.equal(submissions[0].c_f, 1e-8)
  assert.equal(submissions[0].params, undefined)
  await page.getByText('错误详情', { exact: true }).click()
  await page.getByText('ENVIRONMENT_MISSING', { exact: true }).waitFor()
  await page.getByText(/诊断文件/).click()
  assert.ok(await page.getByRole('link', { name: /api-worker.log/ }).count())
  await page.screenshot({ path: resolve(output, 'failure-fixture.png'), fullPage: true, animations: 'disabled' })
  await page.getByRole('button', { name: '修改参数并重试' }).click()
  assert.equal(await page.locator('#param-r_ohm').inputValue(), '16')
  await page.getByText('高级仿真设置', { exact: false }).click()
  assert.equal(await page.locator('#param-stop_s').inputValue(), '8.3', 'failed run keeps edited analysis parameters')
  assert.equal(submissions.length, 1)

  let evidenceResult = 'not_bundled'
  if (info.historical_id) {
    await page.locator(`button.history-item[data-run-id="${info.historical_id}"]`).click()
    await page.getByRole('heading', { name: /仿真完成/ }).waitFor()
    await page.waitForFunction(() => [...document.querySelectorAll('.shots img')].length === 2 && [...document.querySelectorAll('.shots img')].every((img) => img.complete && img.naturalWidth > 0))
    await page.locator('.metric-card').getByText('实测截止频率', { exact: true }).waitFor()
    await page.locator('.individual-curve').nth(3).waitFor()
    assert.equal(await page.locator('.individual-curve').count(),4)
    await page.evaluate(()=>window.scrollTo(0,0))
    await page.screenshot({ path: resolve(output, 'historical-overview.png'), fullPage: true, animations: 'disabled' })
    await page.getByRole('button', { name: '放大仿真波形' }).click()
    await page.getByRole('dialog', { name: '仿真波形' }).waitFor()
    await page.keyboard.press('Escape')
    assert.equal(await page.getByRole('button', { name: '放大仿真波形' }).evaluate(el => document.activeElement === el), true)
    await page.getByRole('tab', { name: '报告与文件' }).click()
    const report = page.getByRole('link', { name: '查看网页版报告' })
    assert.equal((await page.request.get(new URL(await report.getAttribute('href'), info.url).href)).status(), 200)
    await page.getByText(/运行证据索引/).click()
    await page.getByRole('tab', { name: '数值指标', exact: true }).click()
    await page.getByText(/数值验收明细/).click()
    await page.screenshot({ path: resolve(output, 'historical-result.png'), fullPage: true, animations: 'disabled' })
    evidenceResult = 'historical_evidence_rendered'
  }
  await page.getByRole('button', { name: /调整参数再运行|修改参数并重试/ }).click()
  assert.equal(await page.locator('#param-r_ohm').inputValue(), '16')
  assert.equal(submissions.length, 1, 'editing a previous run must not submit automatically')
  for (const viewport of [{ width: 760, height: 560 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport)
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'no horizontal page overflow')
    await page.screenshot({ path: resolve(output, `confirmation-${viewport.width}.png`), fullPage: true, animations: 'disabled' })
  }
  await page.getByRole('button', { name: '最近任务', exact: true }).click()
  await page.getByRole('dialog', { name: '最近任务' }).waitFor()
  await page.keyboard.press('Escape')
  assert.deepEqual(errors, [])
  const summary = { status: 'PASS', mode: 'isolated_browser_test', remote_simulation: false,
    confirmation_required: true, rejected_invalid_parameters: true, submissions: submissions.length,
    failure_fixture: 'ENVIRONMENT_MISSING', evidence: evidenceResult, historical_run_id: info.historical_id,
    browser_errors: errors, checked_at: new Date().toISOString() }
  writeFileSync(resolve(output, 'browser-summary.json'), JSON.stringify(summary, null, 2))
  console.log(JSON.stringify(summary))
} catch (error) {
  if (page) {
    await page.screenshot({ path: resolve(output, 'test-failure.png'), fullPage: true })
    console.error(JSON.stringify({ page_errors: errors, networkFailures, body: (await page.locator('body').innerText()).slice(0, 4000), serverErrors }))
  }
  throw error
} finally {
  await browser?.close()
  server.stdin.end('\n')
  await new Promise((done) => {
    if (server.exitCode !== null) { done(); return }
    const timer = setTimeout(() => { server.kill(); done() }, 5000)
    server.once('exit', () => { clearTimeout(timer); done() })
  })
}
