import assert from 'node:assert/strict'
import { test, afterEach } from 'node:test'
import { build } from 'esbuild'

const { outputFiles } = await build({ entryPoints:['src/api.ts'], bundle:true, write:false, platform:'node', format:'esm' })
const api = await import('data:text/javascript;base64,'+Buffer.from(outputFiles[0].text).toString('base64'))
const original = globalThis.fetch
afterEach(() => { globalThis.fetch = original })
const circuit = { schema_version:'2.0', template_id:'general_circuit', title:'divider', components:[], analyses:[], signals:[] }

test('generic parsing never submits a run and submission sends v2 circuit unchanged', async () => {
  const calls = []
  globalThis.fetch = async (url, options) => {
    calls.push([url,options?.body && JSON.parse(options.body)])
    return Response.json(url.endsWith('/parse') ? { task:circuit, requires_confirmation:true } : { run_id:'vai_generic_test' })
  }
  const result = await api.parseCircuit('V1 a 0 DC 5')
  assert.equal(result.requires_confirmation,true)
  assert.equal(calls.length,1)
  assert.equal(calls[0][0],'/api/v2/parse')
  assert.equal(await api.postRun({kind:'general_circuit',circuit}),'vai_generic_test')
  assert.deepEqual(calls[1],['/api/v2/runs',circuit])
})

test('generic history retains circuit topology and exposes parse errors', async () => {
  globalThis.fetch = async () => Response.json({run_id:'vai_generic_test',status:'succeeded',task:circuit})
  const run = await api.getRun('vai_generic_test')
  assert.deepEqual(run.task.circuit,circuit)
  globalThis.fetch = async () => Response.json({error:{code:'CIRCUIT_INVALID',message:'missing reference ground'}},{status:422})
  await assert.rejects(api.parseCircuit('bad'), /missing reference ground/)
})

test('generic tasks are never calculated by the offline RC demonstration', async () => {
  globalThis.fetch = async () => { throw new Error('offline') }
  await api.getHealth()
  await assert.rejects(api.parseCircuit('V1 a 0 DC 5'), /需要连接后端/)
  await assert.rejects(api.postRun({kind:'general_circuit',circuit}), /需要连接真实仿真后端/)
})
