import assert from 'node:assert/strict'
import { test, afterEach } from 'node:test'
import { build } from 'esbuild'
import { execFileSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { resolve } from 'node:path'

async function load(file) {
  const { outputFiles } = await build({ entryPoints: [file], bundle: true, write: false, platform: 'node', format: 'esm' })
  return import('data:text/javascript;base64,' + Buffer.from(outputFiles[0].text).toString('base64'))
}
const api = await load('src/api.ts')
const { toBackendTask, fromBackendTask, validateBackendTask } = await load('src/contract.ts')
const { planQuestion } = await load('src/planning.ts')
const nativeFetch = globalThis.fetch
afterEach(() => { globalThis.fetch = nativeFetch })
const question = '用一阶 RC 低通滤波器设计一个音频抗混叠前置滤波器，要求截止频率约为 1 kHz。使用 0 到 2 V、周期 4 ms、脉宽 2 ms 的脉冲激励验证其时域响应，并给出 -3 dB 截止频率与脉冲响应波形。'
const empty = { ok: true, missing: ['r_ohm', 'c_f'] }

test('M4 derives a standard RC pair, preserves pulse requirements and passes all limits', () => {
  const plan = planQuestion(question, empty)
  assert.equal(plan.task.params.r_ohm, 16000)
  assert.equal(plan.task.params.c_farad, 1e-8)
  assert.equal(plan.task.params.high_v, 2)
  assert.equal(plan.task.params.period_s, .004)
  assert.equal(plan.task.params.width_s, .002)
  assert.ok(plan.task.params.stop_s >= plan.task.params.delay_s + 2.05 * .004)
  assert.ok(plan.derivation.error_pct < 1)
  assert.equal(validateBackendTask(plan.task), null)
  assert.deepEqual(plan.missing, [])
  assert.equal(plan.defaults.high_v, undefined)
})

test('missing or conflicting components require editing; explicit analysis limits are preserved', () => {
  for (const text of ['RC 低通 R=1kΩ', 'RC 低通 R=1kΩ R=2kΩ，截止频率约为 1 kHz']) {
    const plan = planQuestion(text, empty)
    assert.equal(plan.task.params.c_farad, '')
    assert.ok(validateBackendTask(plan.task))
    assert.equal(plan.derivation, undefined)
  }
  const plan = planQuestion(question + ' 瞬态终点 1 ms，最大步长 1 ms，扫描 1000 Hz ~ 2000 Hz。', empty)
  assert.equal(plan.task.params.stop_s, .001)
  assert.equal(plan.task.params.max_step_s, .001)
  assert.equal(plan.task.params.freq_min_hz, 1000)
  assert.ok(validateBackendTask(plan.task))
  const conflictingPulse = planQuestion(question + ' 高电平为 3 V。', empty)
  assert.equal(conflictingPulse.task.params.high_v, '')
  assert.ok(validateBackendTask(conflictingPulse.task))
})

test('v1.0 prechecks reject incomplete cycles, excessive step and budgets, and noninteger AC counts', () => {
  const task = planQuestion(question, empty).task
  for (const change of [
    { r_ohm: 9 }, { c_farad: 1e-13 }, { high_v: 0 }, { width_s: .004 },
    { stop_s: .001 }, { max_step_s: .001 }, { max_step_s: 1e-9 },
    { points_per_decade: 50.5 }, { freq_min_hz: 1e-30, points_per_decade: 100 },
    { rise_s: '1e-9' }, { low_v: NaN }, { delay_s: -.001 }
  ]) assert.ok(validateBackendTask({ ...task, params: { ...task.params, ...change } }), JSON.stringify(change))
  assert.deepEqual(toBackendTask(fromBackendTask(toBackendTask(task))), toBackendTask(task))
})

test('real parse maps warnings/defaults; screenshots never add forbidden image_b64 to v1.0', async () => {
  const requests = []
  globalThis.fetch = async (url, options) => {
    requests.push({ url, body: options.body && JSON.parse(options.body) })
    return Response.json(url === '/health' ? { status: 'ok', queue: { queued: 2 } } : {
      supported: true, task: null, missing_fields: ['r_ohm', 'c_f'],
      defaults_applied: ['backend default note'], warnings: ['backend warning'], requires_confirmation: true
    })
  }
  assert.equal((await api.getHealth()).queue, 2)
  const result = await api.postParse(question, 'data:image/png;base64,fixture')
  assert.deepEqual(requests[1].body, { text: question })
  assert.equal(requests.length, 2, 'parsing must never submit a run')
  assert.ok(result.hints.includes('backend warning'))
  assert.deepEqual(result.defaultNotes, ['backend default note'])
  assert.equal(result.task.params.r_ohm, 16000)
})

test('unsupported circuits and structured HTTP errors are surfaced', async () => {
  globalThis.fetch = async () => Response.json({ supported: false, warnings: ['仅支持 RC 低通'] })
  await assert.rejects(api.postParse('高通'), /仅支持 RC 低通/)
  globalThis.fetch = async () => Response.json({ error: { code: 'VALIDATION_ERROR', message: 'invalid', details: [{ location: ['body', 'pulse', 'period_s'], message: 'too short' }] } }, { status: 422 })
  await assert.rejects(api.postParse(question), (error) => error.code === 'VALIDATION_ERROR' && /pulse.period_s.*too short/.test(error.message))
})

test('M3 preserves nested checks, warnings and hashes and rejects evidence from another run', async () => {
  const id = 'vai_contract_test', artifactId = '0123456789abcdefabcd'
  const run = {
    schema_version: '1.0', run_id: id, status: 'succeeded',
    task: toBackendTask(planQuestion(question, empty).task),
    metrics: { fc_hz: 994.6, checks: [{ name: 'pulse_edges', status: 'PASS', actual: { rising: [3], falling: [2] } }] },
    warnings: ['fixture warning'],
    artifacts: [{ id: artifactId, kind: 'waveform', filename: 'waveform_window.png', media_type: 'image/png', bytes: 123, sha256: 'a'.repeat(64), url: `/api/v1/runs/${id}/artifacts/${artifactId}` }]
  }
  globalThis.fetch = async () => Response.json(run)
  const result = await api.getRun(id)
  assert.equal(result.task.params.c_farad, 1e-8)
  assert.deepEqual(result.metrics.checks, run.metrics.checks)
  assert.equal(result.artifacts[0].mime, 'image/png')
  assert.equal(result.artifacts[0].sha256, 'a'.repeat(64))
  assert.deepEqual(result.warnings, ['fixture warning'])
  run.artifacts[0].url = `/api/v1/runs/vai_other/artifacts/${artifactId}`
  await assert.rejects(api.getRun(id), /本次任务不一致/)
})

// Cross-language integration: use the real FastAPI parser and Pydantic model,
// not a JavaScript copy of their expected responses. No remote simulation.
test('M3/M4 frontend payloads are accepted by the actual Python backend contract', async () => {
  const localPython = resolve('../backend/.venv-local/Scripts/python.exe')
  const python = process.env.VAI_TEST_PYTHON || (existsSync(localPython) ? localPython : 'python')
  const backend = (operation, payload) => JSON.parse(execFileSync(python, ['-X', 'utf8', '-c', `
import json, sys
from fastapi.testclient import TestClient
from vai_backend.api import create_app
from vai_backend.config import Settings
from vai_backend.manager import RunManager
from vai_backend.models import TaskSpec
from tempfile import TemporaryDirectory
from pathlib import Path
payload = json.load(sys.stdin)
if '${operation}' == 'parse':
    with TemporaryDirectory() as root:
        app = create_app(Settings(data_dir=Path(root)), RunManager(Path(root)))
        with TestClient(app) as client:
            response = client.post('/api/v1/parse', json=payload)
            response.raise_for_status()
            print(json.dumps(response.json()))
else:
    print(TaskSpec.model_validate(payload).model_dump_json())
`], { cwd: resolve('../backend'), input: JSON.stringify(payload), encoding: 'utf8' }))
  for (const text of [question, 'RC 低通 R=1kΩ C=100nF，0 到 3.3 V，周期 1 ms，脉宽 0.5 ms。']) {
    const parsed = backend('parse', { text })
    globalThis.fetch = async (url) => Response.json(url === '/health' ? { status: 'ok' } : parsed)
    await api.getHealth()
    const plan = await api.postParse(text)
    let submitted
    globalThis.fetch = async (_url, options) => {
      submitted = JSON.parse(options.body)
      backend('validate', submitted)
      return Response.json({ run_id: 'vai_contract_test', status: 'queued' }, { status: 202 })
    }
    assert.equal(await api.postRun(plan.task), 'vai_contract_test')
    assert.ok(submitted.c_f > 0)
    assert.equal(submitted.params, undefined)
    assert.equal(submitted.question, text)
  }
})
