import assert from 'node:assert/strict'
import { test, afterEach } from 'node:test'
import { build } from 'esbuild'
async function bundle(path) { const r = await build({ entryPoints: [path], bundle: true, write: false, platform: 'node', format: 'esm' }); return import('data:text/javascript;base64,' + Buffer.from(r.outputFiles[0].text).toString('base64')) }
const ocr = await bundle('src/ocr.ts'), wave = await bundle('src/waveforms.ts'), circuit = await bundle('src/generalCircuit.ts')
const originalFetch = globalThis.fetch
afterEach(() => { globalThis.fetch = originalFetch })

test('endpoint normalization accepts full endpoint and preserves provider paths', () => {
  assert.equal(ocr.chatUrl(' https://model.test/v1/chat/completions/ '),'https://model.test/v1/chat/completions')
  assert.equal(ocr.chatUrl('https://model.test/api/paas/v4'),'https://model.test/api/paas/v4/chat/completions')
  assert.throws(()=>ocr.chatUrl('https://model.test/v1?key=secret'))
})

test('vision uses selected model and GLM fast mode; content blocks and truncation are handled', async () => {
  let body
  globalThis.fetch = async (_url,opts) => {body=JSON.parse(opts.body);return Response.json({choices:[{finish_reason:'stop',message:{content:[{type:'text',text:'{"title":"RL 阶跃响应","text":"R1 n1 0 100","issues":[]}'}]}}]})}
  const result=await ocr.extractCircuit({baseUrl:'https://model.test/v1/chat/completions',apiKey:'fixture',model:'text-only',visionModel:'GLM-5.3-Flash'}, {text:'识别图',imageDataUrl:'data:image/png;base64,AA=='})
  assert.equal(body.model,'GLM-5.3-Flash');assert.equal(body.thinking.type,'disabled');assert.equal(result.title,'RL 阶跃响应')
  globalThis.fetch=async()=>Response.json({choices:[{finish_reason:'length',message:{content:'{"text":'}}]})
  await assert.rejects(()=>ocr.extractCircuit({baseUrl:'https://model.test',apiKey:'fixture',model:'fixture'},{text:'x'}),/截断/)
})

test('generic history gets descriptive fallback while custom titles remain intact', () => {
  const task={title:'通用电路仿真',components:[{type:'resistor'},{type:'inductor'}],analyses:[{type:'tran'}]}
  assert.equal(circuit.circuitTitle(task),'RL 电路 · 瞬态响应')
  assert.equal(circuit.circuitTitle({...task,title:'10mH 电感阶跃响应'}),'10mH 电感阶跃响应')
})

test('parameter cases remain distinct and reject duplicated or malformed case identities', () => {
  const s = {analysis:'dc',signal:'s1',unit:'A',original_samples:2,rows:[[0,0],[1,.001]]}
  const value = {series:[{...s,case:'base'},{...s,case:'s000',parameters:{'VG.dc':-1}}]}
  assert.equal(wave.validateWaveforms(value).length,2)
  assert.equal(wave.groupWaveforms(value.series)[0].length,2)
  assert.throws(()=>wave.validateWaveforms({series:[s,{...s,case:'base'}]}),/重复/)
  assert.throws(()=>wave.validateWaveforms({series:[{...s,case:'../bad'}]}),/编号/)
})
test('extraction rejects incomplete, oversized and malformed model replies', () => {
  for (const value of ['not json', 'null', '{}', '{"text":"x","issues":[2]}', '{"text":"","issues":[]}', JSON.stringify({text:'x'.repeat(50001),issues:[]})]) assert.throws(() => ocr.parseCircuitExtraction(value))
  assert.deepEqual(ocr.parseCircuitExtraction('```json\n{"text":"R1 a 0 1k", "issues":["缺少激励"], "summary":"电阻电路"}\n```'), {text:'R1 a 0 1k',issues:['缺少激励'],summary:'电阻电路'})
})
test('text and image recognition preserve the question and clarifications without creating runs', async () => {
  const calls = []
  globalThis.fetch = async (url, opts) => { calls.push([url,JSON.parse(opts.body)]); return Response.json({choices:[{message:{content:'{"text":"R1 a 0 1k","issues":["缺少电源"]}'}}]}) }
  const result = await ocr.extractCircuit({baseUrl:'https://model.test/v1/',apiKey:'fixture-key',model:'fixture'}, {text:'原始题目',imageDataUrl:'data:image/png;base64,AA==',clarification:'最大步长为 10 us'})
  assert.equal(calls.length,1); assert.equal(calls[0][0],'https://model.test/v1/chat/completions')
  const content = calls[0][1].messages[1].content
  assert.match(content[0].text,/原始题目/);assert.match(content[0].text,/10 us/)
  assert.equal(content[1].image_url.url,'data:image/png;base64,AA==');assert.equal(result.issues.length,1)
})
test('cancelled recognition aborts the provider request', async () => {
  const ctrl = new AbortController()
  globalThis.fetch = (_url, {signal}) => new Promise((_, reject) => signal.addEventListener('abort', () => reject(new DOMException('Cancelled','AbortError'))))
  const request = ocr.extractCircuit({baseUrl:'https://model.test',apiKey:'fixture',model:'fixture'},{text:'test'},ctrl.signal)
  ctrl.abort();await assert.rejects(request,{name:'AbortError'})
})

test('proposal cards reject missing fields and ambiguous identities', () => {
  const proposal = {id:'topology',title:'采用低通吗？',detail:'R=1kΩ，C=159nF 接地。',reason:'目标截止频率约 1kHz。'}
  const reply = proposals => JSON.stringify({text:'R1 in out 1k',summary:'候选方案',issues:[],proposals})
  assert.deepEqual(ocr.parseCircuitExtraction(reply([proposal])).proposals,[proposal])
  for (const proposals of [[proposal,proposal],[{...proposal,id:''}],[{...proposal,detail:null}],[null],{}]) assert.throws(()=>ocr.parseCircuitExtraction(reply(proposals)),/建议卡片/)
})

test('design skill receives current capabilities, decisions and preflight feedback in one request', async () => {
  let body
  globalThis.fetch = async (_url,opts) => {body=JSON.parse(opts.body);return Response.json({choices:[{message:{content:'{"text":"R1 a 0 1k","issues":[]}'}}]})}
  await ocr.extractCircuit({baseUrl:'https://model.test',apiKey:'fixture',model:'fixture'}, {text:'设计一个放大器',capabilities:{components:['bjt'],studies:['bjt_transfer']},previousCandidate:'Q1 c b 0 generic_npn',clarification:'否决原阻值，保持电源电压',validationError:'浮空节点'})
  assert.match(body.messages[0].content,/circuit-design-assistant/)
  assert.match(body.messages[0].content,/bjt_transfer/)
  assert.match(JSON.stringify(body.messages),/否决原阻值/)
  assert.match(JSON.stringify(body.messages),/浮空节点/)
  assert.match(JSON.stringify(body.messages),/Q1 c b 0/)
})
test('engineering input preserves real circuit values and rejects empty or nonfinite input', () => {
  assert.equal(circuit.parseEngineering('1k'),1000);assert.equal(circuit.parseEngineering('100n'),1e-7)
  assert.equal(circuit.parseEngineering('2.5e-3'),.0025);assert.equal(circuit.parseEngineering('2M'),2e6)
  for (const v of [1e-12,1e-9,1e-6,.002,1,300,1e3,1e6,-.001]) assert.equal(circuit.parseEngineering(circuit.formatEngineering(v)),v)
  assert.equal(circuit.parseEngineering(''),'');assert.equal(circuit.parseEngineering('Infinity'),'Infinity')
  assert.equal(circuit.editableCircuit('{"title":"x","components":[null],"analyses":[],"signals":[]}'),null)
})
const series = (analysis, signal, unit, rows) => ({analysis,signal,unit,rows,original_samples:rows.length})
test('comparison groups keep units and analysis types separate; individual ranges preserve small curves', () => {
  const list = [series('tran','v1','V',[[0,0],[1,10]]),series('tran','v2','V',[[0,0],[1,.001]]),series('tran','i1','A',[[0,0],[1,.01]]),series('ac','v1','V',[[1,1,0],[10,0,1]])]
  assert.equal(wave.groupWaveforms(list).length,3)
  const all = wave.waveBounds(list.slice(0,2),'real'), individual = wave.waveBounds([list[1]],'real')
  assert.ok(all.high>10);assert.ok(individual.high<.002)
  assert.equal(wave.waveValue([1,0,1],'phase'),90);assert.equal(wave.waveValue([1,3,4],'magnitude'),5)
  assert.equal(wave.waveUnit(list[3],'phase'),'°')
})
test('bad waveform data is reported instead of drawing a plausible plot', () => {
  for (const rows of [[[0,1,0]], [[1,Infinity,0]], [[1,2,0],[1,3,0]], [[1,2,0],[3,3,0],[2,4,0]]]) assert.throws(() => wave.validateWaveforms({series:[series('ac','s1','V',rows)]}))
  assert.equal(wave.validateWaveforms({series:[series('dc','s1','A',[[2,2],[1,1],[0,0]])]}).length,1)
  const equal = wave.waveBounds([series('tran','s1','V',[[0,0],[1,0]])],'real');assert.ok(equal.high>equal.low)
})
test('legacy RC numeric files produce separate input/output curves and preserve sampled peaks', () => {
  assert.equal(wave.parseNumericWave('0 0\n1 2\n','tran','out','V').rows[1][1],2)
  assert.throws(() => wave.parseNumericWave('0 bad','tran','out','V'))
  const rows = Array.from({length:10000},(_,i)=>[i,i===3333?100:0])
  const sampled = wave.sampleWave(rows);assert.ok(sampled.some(r=>r[1]===100));assert.deepEqual(sampled[0],rows[0]);assert.deepEqual(sampled.at(-1),rows.at(-1))
})
