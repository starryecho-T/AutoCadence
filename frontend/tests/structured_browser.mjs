import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { mkdirSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { createInterface } from 'node:readline'
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE ? pathToFileURL(process.env.PLAYWRIGHT_MODULE).href : 'playwright')
const output=resolve(process.env.VAI_BROWSER_OUTPUT || '../work/structured-browser');mkdirSync(output,{recursive:true})
const server=spawn(process.env.VAI_TEST_PYTHON || resolve('../backend/.venv-local/Scripts/python.exe'),['-X','utf8','tests/general_workflow_server.py'],{windowsHide:true,stdio:['pipe','pipe','pipe']})
let errors='',browser
server.stderr.on('data',d=>{errors+=d})
try {
  const info=await new Promise((ok,bad)=>{const timer=setTimeout(()=>bad(new Error(errors||'server timeout')),15000);createInterface({input:server.stdout}).once('line',line=>{clearTimeout(timer);try{ok(JSON.parse(line))}catch(e){bad(e)}});server.once('error',bad)})
  browser=await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_CHANNEL || 'msedge'})
  const page=await browser.newPage({viewport:{width:1280,height:900}})
  const pageErrors=[],submissions=[],modelRequests=[];page.on('pageerror',e=>pageErrors.push(e.message));page.on('request',r=>{if(r.method()==='POST'&&r.url().endsWith('/api/v2/runs'))submissions.push(r.postDataJSON())})
  await page.goto(info.url);await page.getByText('后端在线',{exact:true}).waitFor()
  await page.evaluate(()=>localStorage.setItem('ocr-config-v1',JSON.stringify({baseUrl:'https://fixture-model.test/v1',apiKey:'test-only',model:'fixture'})))
  const connection='V1 vin 0 DC 5\nR1 vin out 1k\nR2 out 0 2k\n.op\n.save V(out) I(R1)'
  let reply={text:connection,summary:'直流分压电路，观察输出电压与电阻电流。',issues:['请确认 R2 阻值。']}, delayed=false, release
  await page.route('https://fixture-model.test/**',async route=>{modelRequests.push(route.request().postDataJSON());if(delayed)await new Promise(r=>{release=r});await route.fulfill({json:{choices:[{message:{content:JSON.stringify(reply)}}]}}).catch(()=>{})})
  await page.getByRole('button',{name:'通用电路',exact:true}).click()
  await page.getByRole('button',{name:'试试文字示例'}).click()
  const originalQuestion=await page.getByLabel('题目描述',{exact:true}).inputValue()
  await page.evaluate(()=>window.scrollTo(0,0))
  await page.screenshot({path:resolve(output,'text-input.png'),fullPage:true,animations:'disabled'})
  await page.getByRole('button',{name:'整理为电路',exact:true}).click()
  await page.getByLabel('问题 1 的补充').waitFor()
  assert.equal(await page.getByLabel('题目描述',{exact:true}).inputValue(),originalQuestion)
  assert.ok(await page.getByRole('button',{name:'解析并检查电路'}).isDisabled())
  await page.getByLabel('问题 1 的补充').fill('R2 为 2 kΩ。')
  await page.getByLabel('已根据此补充修正下方电路描述').check()
  // Any edit invalidates previous confirmations.
  await page.getByLabel('电路连接描述',{exact:true}).fill(connection+'\n')
  assert.ok(await page.getByRole('button',{name:'解析并检查电路'}).isDisabled())
  await page.getByLabel('已根据此补充修正下方电路描述').check()
  await page.evaluate(()=>window.scrollTo(0,0))
  await page.screenshot({path:resolve(output,'review-issues.png'),fullPage:true,animations:'disabled'})
  await page.getByRole('button',{name:'解析并检查电路'}).click();await page.getByRole('heading',{name:'核对元件与连接'}).waitFor()
  assert.equal(submissions.length,0)
  await page.getByLabel('R1 阻值',{exact:true}).fill('4.7k')
  assert.ok(await page.getByRole('button',{name:'确认并开始仿真'}).isDisabled())
  await page.getByRole('button',{name:'重新检查修改'}).click()
  await page.getByText('准备就绪，等待你的确认',{exact:true}).waitFor()
  await page.getByRole('button',{name:'返回修改',exact:true}).click()
  const edited=JSON.parse(await page.getByLabel('电路连接描述',{exact:true}).inputValue())
  assert.equal(edited.components.find(c=>c.id==='R1').resistance_ohm,4700)
  assert.equal(await page.getByLabel('问题 1 的补充').inputValue(),'R2 为 2 kΩ。')
  await page.getByRole('button',{name:'解析并检查电路'}).click();await page.getByRole('heading',{name:'核对元件与连接'}).waitFor()
  await page.getByLabel('R1 负端 / 端点 2',{exact:true}).fill('missing')
  await page.getByRole('button',{name:'重新检查修改'}).click()
  // A floating node might be valid; use an unknown observed node for a deterministic preflight rejection.
  await page.getByLabel('s1 正节点',{exact:true}).fill('does_not_exist')
  await page.getByRole('button',{name:'重新检查修改'}).click()
  await page.getByRole('alert').waitFor();assert.ok(await page.getByRole('button',{name:'确认并开始仿真'}).isDisabled())
  await page.getByLabel('s1 正节点',{exact:true}).fill('out')
  await page.getByLabel('R1 负端 / 端点 2',{exact:true}).fill('out')
  await page.getByRole('button',{name:'重新检查修改'}).click();await page.getByText('准备就绪，等待你的确认',{exact:true}).waitFor()
  await page.evaluate(()=>window.scrollTo(0,0))
  await page.screenshot({path:resolve(output,'confirmation.png'),fullPage:true,animations:'disabled'})
  for(const width of [760,390]){await page.setViewportSize({width,height:900});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`review overflow ${width}`)}
  await page.evaluate(()=>window.scrollTo(0,0))
  await page.screenshot({path:resolve(output,'confirmation-mobile.png'),fullPage:true,animations:'disabled'})
  await page.setViewportSize({width:1280,height:900})
  await page.getByRole('button',{name:'确认并开始仿真'}).click();await page.getByRole('heading',{name:'仿真失败',exact:true}).waitFor()
  assert.equal(submissions.length,1);assert.equal(submissions[0].components.find(c=>c.id==='R1').resistance_ohm,4700);assert.ok(submissions[0].question.includes(originalQuestion));assert.match(submissions[0].question,/R2 为 2 kΩ/)
  await page.getByRole('button',{name:'新建仿真',exact:true}).first().click();await page.getByRole('button',{name:'通用电路',exact:true}).click()
  await page.getByRole('button',{name:'电路截图',exact:true}).click()
  await page.getByLabel('通用电路截图',{exact:true}).setInputFiles({name:'circuit.png',mimeType:'image/png',buffer:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a8WQAAAAASUVORK5CYII=','base64')})
  await page.getByLabel('补充题目与分析要求',{exact:true}).fill('求分压工作点，观察 out 电压和 R1 电流。')
  reply={text:connection,summary:'图文共同识别的分压电路（自动化测试替身）。',issues:[]}
  await page.getByRole('button',{name:'识别元件与连接',exact:true}).click();await page.getByLabel('电路连接描述',{exact:true}).waitFor()
  assert.ok(modelRequests.at(-1).messages[1].content.some(c=>c.type==='image_url'));assert.match(modelRequests.at(-1).messages[1].content[0].text,/分压工作点/)
  // Cancel then let a late reply arrive: it must not overwrite the retained draft.
  delayed=true;reply={text:'late invalid output',issues:[]}
  await page.getByRole('button',{name:'根据补充重新整理'}).click()
  await page.waitForFunction(()=>!!document.querySelector('button') && document.body.innerText.includes('取消处理'))
  while(!release) await new Promise(r=>setTimeout(r,10))
  await page.getByRole('button',{name:'取消处理'}).click();release();await page.waitForTimeout(120)
  assert.equal(await page.getByLabel('电路连接描述',{exact:true}).inputValue(),connection)
  await page.getByRole('button',{name:'解析并检查电路'}).click();await page.getByRole('heading',{name:'核对元件与连接'}).waitFor()
  await page.getByText('对照原题与图片',{exact:true}).click();await page.getByRole('button',{name:'放大原图',exact:true}).click();await page.getByRole('dialog',{name:'电路原图'}).waitFor();await page.keyboard.press('Escape')
  assert.equal(submissions.length,1)
  assert.deepEqual(pageErrors,[])
  const result={status:'PASS',model_service:'mocked; no external provider called',backend_preview:'real local v2 validation',submissions:1,checks:['text extraction','individual issues','source preservation','form edits','backend rejection','return preserves edits','image plus question','cancel ignores late reply','390 and 760px layouts'],browser_errors:pageErrors}
  writeFileSync(resolve(output,'verification.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result))
}finally{await browser?.close();server.stdin.end('\n');setTimeout(()=>server.kill(),2000).unref()}
