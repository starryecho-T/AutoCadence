/** Explicit live acceptance: submits ONE real remote Cadence job after clicking
 * confirmation. Requires VAI_LIVE_URL and a separately running real backend. */
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { mkdirSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

if (!process.env.VAI_LIVE_URL) throw new Error('Set VAI_LIVE_URL explicitly; this test runs a real remote simulation.')
const base = process.env.VAI_LIVE_URL
const output = resolve(process.env.VAI_BROWSER_OUTPUT || '../work/live-verification')
mkdirSync(output, { recursive: true })
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE ? pathToFileURL(process.env.PLAYWRIGHT_MODULE).href : 'playwright')
const browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {}) })
const page = await browser.newPage({ viewport: { width: 1360, height: 1000 } })
const errors = [], submissions = []
page.on('pageerror', (error) => errors.push(error.message))
page.on('request', (request) => {
  if (request.method() === 'POST' && request.url().endsWith('/api/v1/runs')) submissions.push(request.postDataJSON())
})
try {
  await page.goto(base)
  await page.getByText(/后端在线/).waitFor()
  await page.getByRole('button', { name: '填入示例题目' }).click()
  await page.getByRole('button', { name: '解析题目', exact: true }).click()
  await page.getByText(/参数预检通过/).waitFor()
  assert.equal(submissions.length, 0)
  assert.equal(await page.locator('#param-r_ohm').inputValue(), '16')
  assert.equal(Number(await page.locator('#param-c_farad').inputValue()), 10)
  await page.locator('.card').first().screenshot({ path: resolve(output, 'confirmation.png'), animations: 'disabled' })
  const submitted = page.waitForResponse((response) => response.request().method() === 'POST' && response.url().endsWith('/api/v1/runs'))
  await page.getByRole('button', { name: '确认并开始仿真' }).click()
  const response = await submitted
  assert.equal(response.status(), 202)
  const initial = await response.json()
  console.log('Real browser submission: ' + initial.run_id)
  await page.getByRole('heading', { name: /仿真完成|仿真失败/ }).waitFor({ timeout: 180000 })
  const run = await (await page.request.get(new URL(`/api/v1/runs/${initial.run_id}`, base).href)).json()
  assert.equal(run.status, 'succeeded', JSON.stringify(run.error))
  assert.equal(run.metrics.validation_status, 'PASS')
  assert.equal(run.stages.filter((s) => s.status === 'succeeded').length, 13)
  assert.equal(submissions.length, 1)
  assert.deepEqual(run.task.pulse, submissions[0].pulse)
  assert.ok(Math.abs(run.metrics.fc_hz / 1000 - 1) < .02)
  await page.waitForFunction(() => [...document.querySelectorAll('.shots img')].length === 2 && [...document.querySelectorAll('.shots img')].every((img) => img.complete && img.naturalWidth > 0))
  const required = ['schematic_window.png', 'waveform_window.png', 'report.html', 'report.md', 'metrics.json', 'input.scs', 'image_validation.json', 'protection.json']
  const artifacts = []
  for (const filename of required) {
    const artifact = run.artifacts.find((a) => a.filename === filename)
    assert.ok(artifact, filename)
    assert.ok(artifact.url.startsWith(`/api/v1/runs/${run.run_id}/artifacts/`))
    const downloaded = await page.request.get(new URL(artifact.url, base).href)
    assert.equal(downloaded.status(), 200)
    const bytes = await downloaded.body()
    assert.equal(bytes.length, artifact.bytes)
    assert.equal(createHash('sha256').update(bytes).digest('hex'), artifact.sha256)
    writeFileSync(resolve(output, filename), bytes)
    artifacts.push({ filename, sha256: artifact.sha256, bytes: artifact.bytes })
    if (filename === 'metrics.json') assert.deepEqual(JSON.parse(bytes.toString('utf8')), run.metrics)
    if (filename === 'image_validation.json') assert.equal(JSON.parse(bytes.toString('utf8')).ok, true)
    if (filename === 'protection.json') assert.equal(JSON.parse(bytes.toString('utf8')).unchanged, true)
  }
  await page.locator('.card').first().screenshot({ path: resolve(output, 'result.png'), animations: 'disabled' })
  await page.getByRole('tab', { name: '数值指标', exact: true }).click()
  await page.getByText(/数值验收明细/).click()
  assert.ok((await page.locator('body').innerText()).includes('18/18 通过'))
  const history = await (await page.request.get(new URL('/api/v1/runs', base).href)).json()
  const failure = history.runs.find((r) => r.error?.code === 'ENVIRONMENT_MISSING')
  assert.ok(failure, 'Run failure_regression.py before live browser acceptance')
  await page.locator(`button.history-item[data-run-id="${failure.run_id}"]`).click()
  await page.getByRole('heading', { name: /仿真失败/ }).waitFor()
  await page.getByText('错误详情', { exact: true }).click()
  await page.getByText('ENVIRONMENT_MISSING', { exact: true }).waitFor()
  await page.getByText(/诊断文件/).click()
  assert.ok(await page.getByRole('link', { name: /api-worker.log/ }).count())
  await page.locator('.card').first().screenshot({ path: resolve(output, 'real-failure.png'), animations: 'disabled' })
  assert.deepEqual(errors, [])
  const summary = { verdict: 'PASS', mode: 'real_browser_and_remote_cadence', checked_at: new Date().toISOString(),
    run_id: run.run_id, status: run.status, confirmation: 'browser_click_after_parameter_review',
    submissions: submissions.length, task: run.task, stages_passed: 13, numeric_checks_passed: run.metrics.checks.length,
    fc_hz: run.metrics.fc_hz, fc_theory_hz: run.metrics.fc_theory_hz, fc_relative_error_pct: run.metrics.fc_relative_error_pct,
    failure_case_run_id: failure.run_id, artifact_downloads: artifacts, browser_errors: errors }
  writeFileSync(resolve(output, 'live-summary.json'), JSON.stringify(summary, null, 2))
  console.log(JSON.stringify(summary))
} catch (error) {
  await page.screenshot({ path: resolve(output, 'acceptance-failure.png'), fullPage: true, animations: 'disabled' })
  console.error('Browser errors: ' + JSON.stringify(errors))
  throw error
} finally {
  await browser.close()
}
