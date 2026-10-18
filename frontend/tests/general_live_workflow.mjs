// Explicit real browser -> v2 API -> Cadence/Spectre -> browser regression.
import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { mkdirSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { createInterface } from 'node:readline'

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE ? pathToFileURL(process.env.PLAYWRIGHT_MODULE).href : 'playwright')
const server=spawn(resolve('../backend/.venv-local/Scripts/python.exe'),['-X','utf8','tests/general_workflow_server.py','--live'],{windowsHide:true,stdio:['pipe','pipe','pipe']})
let errors='',browser
server.stderr.on('data',d=>{errors+=d})
try {
  const info=await new Promise((ok,bad)=>{
    const timer=setTimeout(()=>bad(new Error(errors||'server timeout')),15000)
    createInterface({input:server.stdout}).once('line',line=>{clearTimeout(timer);try{ok(JSON.parse(line))}catch(e){bad(e)}})
    server.once('error',bad)
  })
  assert.equal(info.mode,'live')
  browser=await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_CHANNEL || 'msedge'})
  const page=await browser.newPage({viewport:{width:1280,height:900}})
  const pageErrors=[],submissions=[]
  page.on('pageerror',e=>pageErrors.push(e.message))
  page.on('request',r=>{if(r.method()==='POST'&&r.url().endsWith('/api/v2/runs'))submissions.push(r.postDataJSON())})
  await page.goto(info.url)
  await page.getByText('后端在线',{exact:true}).waitFor()
  await page.getByRole('button',{name:'通用电路',exact:true}).click()
  await page.getByRole('button',{name:'连接描述',exact:true}).click()
  await page.getByLabel('通用电路示例').selectOption('divider')
  await page.getByRole('button',{name:'解析并检查电路'}).click()
  await page.getByRole('heading',{name:'核对元件与连接'}).waitFor()
  await page.getByText('高级：完整电路、模型与测量指标',{exact:true}).click()
  const editor=page.getByLabel('通用电路 JSON')
  const task=JSON.parse(await editor.inputValue())
  task.measurements=[{id:'output_5v',analysis:'op',signal:'s1',operation:'final',minimum:4.9999,maximum:5.0001}]
  await editor.fill('{')
  assert.equal(await page.getByRole('button',{name:'确认并开始仿真'}).isDisabled(),true)
  await page.getByRole('button',{name:'重新检查修改'}).click()
  await page.getByRole('alert').waitFor()
  assert.equal(submissions.length,0)
  await editor.fill(JSON.stringify(task,null,2))
  await page.getByRole('button',{name:'重新检查修改'}).click()
  await page.getByText('准备就绪，等待你的确认',{exact:true}).waitFor()
  assert.equal(submissions.length,0)
  const accepted=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/api/v2/runs'))
  await page.getByRole('button',{name:'确认并开始仿真'}).click()
  const initial=await (await accepted).json()
  console.log(JSON.stringify({stage:'submitted',run_id:initial.run_id,data_dir:info.data_dir}))
  await page.getByRole('heading',{name:'仿真完成',exact:true}).waitFor({timeout:180000})
  await page.getByRole('heading',{name:'节点与支路结果'}).waitFor()
  await page.locator('.operating-values strong').first().waitFor()
  const run=await (await fetch(`${info.url}/api/v2/runs/${initial.run_id}`)).json()
  assert.equal(run.status,'succeeded')
  assert.equal(run.task.template_id,'general_circuit')
  assert.equal(run.metrics.requirements_status,'PASS')
  assert.ok(Math.abs(run.metrics.signals['op.s1'].final_real-5)<1e-4)
  assert.ok(run.stages.every(s=>s.status==='succeeded'))
  assert.equal(submissions.length,1)
  assert.deepEqual(pageErrors,[])
  const output=resolve('../work/general-live-browser');mkdirSync(output,{recursive:true})
  await page.screenshot({path:resolve(output,'result.png'),fullPage:true,animations:'disabled'})
  const result={status:'PASS',mode:'real_browser_to_v2_to_remote_eda',remote_simulation:true,run_id:run.run_id,data_dir:info.data_dir,measurement:run.metrics.measurements[0],stages:run.stages.length,browser_errors:pageErrors}
  writeFileSync(resolve(output,'result.json'),JSON.stringify(result,null,2)+'\n')
  console.log(JSON.stringify(result))
}finally{await browser?.close();server.stdin.end('\n');setTimeout(()=>server.kill(),3000).unref()}
