import assert from 'node:assert/strict'
import { test } from 'node:test'
import { build } from 'esbuild'

async function loadModule(file) {
  const { outputFiles } = await build({ entryPoints: [file], bundle: true, write: false, platform: 'node', format: 'esm' })
  return import('data:text/javascript;base64,' + Buffer.from(outputFiles[0].text).toString('base64'))
}
const { pollSequentially } = await loadModule('src/polling.ts')
// Mocked timers only cover setTimeout; a real macrotask lets pending promise continuations settle between ticks.
const flush = () => new Promise((resolve) => setImmediate(resolve))
const advance = async (context, ms) => { context.mock.timers.tick(ms); await flush() }

test('failed polls back off 1.5s, 3s, 6s and stop after three retries', async (context) => {
  context.mock.timers.enable({ apis: ['setTimeout'] })
  let attempts = 0
  const errors = []
  const stop = pollSequentially({
    read: async () => { attempts++; throw new Error(`network ${attempts}`) },
    onValue: () => assert.fail('onValue must not fire while reads fail'),
    isDone: () => false,
    onError: (error) => errors.push(error.message),
    intervalMs: 100
  })
  await flush()
  assert.deepEqual(errors, ['network 1'])
  await advance(context, 1499)
  assert.equal(attempts, 1, 'first retry waits 1.5s')
  await advance(context, 1)
  assert.deepEqual(errors, ['network 1', 'network 2'])
  await advance(context, 2999)
  assert.equal(attempts, 2, 'second retry waits 3s')
  await advance(context, 1)
  assert.deepEqual(errors, ['network 1', 'network 2', 'network 3'])
  await advance(context, 6000)
  assert.deepEqual(errors, ['network 1', 'network 2', 'network 3', 'network 4'], 'third retry waits 6s and still reports the error')
  await advance(context, 600000)
  assert.equal(attempts, 4, 'polling stops after three retries and never schedules again')
  stop()
})

test('one successful poll resets the retry backoff counter', async (context) => {
  context.mock.timers.enable({ apis: ['setTimeout'] })
  let attempts = 0
  const values = [], errors = []
  const stop = pollSequentially({
    read: async () => { attempts++; if (attempts !== 3 && attempts !== 5) throw new Error(`flaky ${attempts}`); return attempts },
    onValue: (value) => values.push(value),
    isDone: (value) => value === 5,
    onError: (error) => errors.push(error.message),
    intervalMs: 100
  })
  await flush()
  await advance(context, 1500)
  assert.deepEqual(errors, ['flaky 1', 'flaky 2'])
  await advance(context, 3000)
  assert.deepEqual(values, [3], 'third attempt succeeds and resets the counter')
  await advance(context, 100)
  assert.deepEqual(errors, ['flaky 1', 'flaky 2', 'flaky 4'])
  await advance(context, 1500)
  assert.deepEqual(values, [3, 5], 'failure after a success retries after 1.5s again, not 3s')
  await advance(context, 60000)
  assert.equal(attempts, 5, 'terminal status still stops the loop')
  stop()
})

test('abort cancels scheduled retries and late failures stay ignored', async (context) => {
  context.mock.timers.enable({ apis: ['setTimeout'] })
  let attempts = 0, errors = 0
  let requestSignal = null
  const stop = pollSequentially({
    read: (signal) => { attempts++; requestSignal = signal; return Promise.reject(new Error('down')) },
    onValue: () => {}, isDone: () => false, onError: () => errors++, intervalMs: 1
  })
  await flush()
  assert.equal(attempts, 1); assert.equal(errors, 1)
  stop()
  await advance(context, 60000)
  assert.equal(attempts, 1, 'scheduled backoff retry is cleared on stop')
  assert.equal(requestSignal.aborted, true)

  let release
  const pending = new Promise((_resolve, reject) => { release = () => reject(new Error('late')) })
  let lateSignal = null
  const stop2 = pollSequentially({
    read: (signal) => { lateSignal = signal; return pending },
    onValue: () => {}, isDone: () => false, onError: () => errors++, intervalMs: 1
  })
  await flush()
  stop2(); release(); await flush()
  assert.equal(lateSignal.aborted, true)
  assert.equal(errors, 1, 'a failure landing after abort must not reach onError nor reschedule')
  await advance(context, 60000)
  assert.equal(errors, 1)
})

test('successful polling keeps the original sequential interval behaviour', async (context) => {
  context.mock.timers.enable({ apis: ['setTimeout'] })
  let attempts = 0
  const values = []
  const stop = pollSequentially({
    read: async (signal) => { attempts++; assert.equal(signal.aborted, false); return attempts },
    onValue: (value) => values.push(value),
    isDone: (value) => value >= 3,
    onError: () => assert.fail('no errors expected'),
    intervalMs: 1500
  })
  await flush()
  assert.deepEqual(values, [1])
  await advance(context, 1500)
  await flush()
  assert.deepEqual(values, [1, 2])
  await advance(context, 1500)
  await flush()
  assert.deepEqual(values, [1, 2, 3])
  await advance(context, 60000)
  assert.equal(attempts, 3, 'done status stops scheduling')
  stop()
})
