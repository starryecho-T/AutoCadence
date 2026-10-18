import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { mkdirSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { createInterface } from 'node:readline'

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE ? pathToFileURL(process.env.PLAYWRIGHT_MODULE).href : 'playwright')
const server=spawn(process.env.VAI_TEST_PYTHON || resolve('../backend/.venv-local/Scripts/python.exe'),['-X','utf8','tests/general_workflow_server.py'],{windowsHide:true,stdio:['pipe','pipe','pipe']})
let errors='', browser
server.stderr.on('data',d=>{errors+=d})
try {
  const info=await new Promise((ok,bad)=>{
    const timer=setTimeout(()=>bad(new Error(errors||'server timeout')),15000)
    createInterface({input:server.stdout}).once('line',line=>{clearTimeout(timer);try{ok(JSON.parse(line))}catch(e){bad(e)}})
    server.once('error',bad)
  })
  browser=await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_CHANNEL || 'msedge'})
  const page=await browser.newPage({viewport:{width:1280,height:900}})
  const pageErrors=[], submissions=[]
  page.on('pageerror',e=>pageErrors.push(e.message))
  page.on('request',r=>{if(r.method()==='POST'&&r.url().endsWith('/api/v2/runs'))submissions.push(r.postDataJSON())})
  await page.goto(info.url)
  await page.getByText('后端在线',{exact:true}).waitFor()
  await page.getByRole('button',{name:'通用电路',exact:true}).click()
  await page.getByRole('button',{name:'连接描述',exact:true}).click()
  await page.getByLabel('通用电路示例').selectOption('rc_highpass')
  await page.getByRole('button',{name:'解析并检查电路'}).click()
  await page.getByRole('heading',{name:'核对元件与连接'}).waitFor()
  assert.equal(submissions.length,0)
  const output=resolve(process.env.VAI_BROWSER_OUTPUT || '../work/general-browser');mkdirSync(output,{recursive:true})
  await page.evaluate(()=>window.scrollTo(0,0))
  await page.screenshot({path:resolve(output,'confirmation.png'),fullPage:true,animations:'disabled'})
  await page.getByRole('button',{name:'确认并开始仿真'}).click()
  await page.getByRole('heading',{name:'仿真失败',exact:true}).waitFor()
  assert.equal(submissions.length,1)
  assert.equal(submissions[0].template_id,'general_circuit')
  await page.getByRole('button',{name:'修改参数并重试'}).click()
  await page.getByRole('heading',{name:'核对元件与连接'}).waitFor()
  if(info.historical_id){
    await page.locator(`button.history-item[data-run-id="${info.historical_id}"]`).first().click()
    await page.getByRole('heading',{name:'仿真完成',exact:true}).waitFor()
    await page.getByRole('heading',{name:'节点与支路结果'}).waitFor()
    await page.locator('.individual-curve').first().waitFor()
    const count=await page.locator('.individual-curve').count();assert.ok(count>=2)
    assert.ok(await page.locator('.overview-curve').count()>=1)
    await page.getByLabel('AC 分量').selectOption('phase')
    await page.locator('.individual-curve').first().getByRole('img').waitFor()
    await page.locator('.individual-curve').first().getByRole('button').click()
    await page.getByRole('dialog').waitFor();await page.keyboard.press('Escape')
    await page.evaluate(()=>window.scrollTo(0,0))
  await page.screenshot({path:resolve(output,'result.png'),fullPage:true,animations:'disabled'})
  }
  await page.setViewportSize({width:390,height:844})
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),'mobile overflow')
  assert.deepEqual(pageErrors,[])
  const result={status:'PASS',submissions:submissions.length,historical_id:info.historical_id,individual_curves:await page.locator('.individual-curve').count(),browser_errors:pageErrors};writeFileSync(resolve(output,'verification.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result))
}finally{await browser?.close();server.stdin.end('\n');setTimeout(()=>server.kill(),2000).unref()}
