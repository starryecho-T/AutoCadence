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
  await page.route('**/health', async route => {
    const response=await route.fetch()
    const health=await response.json()
    await route.fulfill({response,json:{...health,connection_configured:true}})
  })
  await page.goto(info.url)
  await page.getByText('后端在线',{exact:true}).waitFor()
  await page.getByRole('button',{name:'仿真服务器'}).click()
  const settings=page.getByRole('dialog',{name:'仿真服务器'})
  await settings.getByText('高级设置 · 环境路径与兼容选项').click()
  await settings.getByLabel('CMN018 主模型文件').waitFor()
  await settings.getByRole('button',{name:'关闭仿真服务器'}).click()

  await page.getByRole('button',{name:'连接描述',exact:true}).click()
  await page.getByLabel('通用电路示例').selectOption('rc_highpass')
  assert.equal(await page.getByLabel('通用电路示例').inputValue(),'rc_highpass')
  const exampleText=await page.getByLabel('电路连接描述').inputValue()
  await page.getByLabel('电路连接描述').fill(`${exampleText}\nR9 extra 0 1k`)
  assert.equal(await page.getByLabel('通用电路示例').inputValue(),'')
  await page.getByLabel('通用电路示例').selectOption('rc_highpass')
  assert.equal(await page.getByLabel('通用电路示例').inputValue(),'rc_highpass')
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
    const historical=await (await page.request.get(`${info.url}/api/v2/runs/${info.historical_id}`)).json()
    const imageNames=historical.artifacts.filter(a=>/\.(png|jpe?g|gif|webp|svg|avif)$/i.test(a.filename)).map(a=>a.filename)
    assert.equal(await page.locator('.shots .shot').count(),imageNames.length)
    for(const [filename,label] of [['waveform_window.png','ViVA 波形窗口截图'],['waveform_native.png','Cadence 波形原生导出']]){
      if(!imageNames.includes(filename))continue
      await page.locator('.shots').getByText(label,{exact:true}).waitFor()
      const shot=page.locator('.shots .shot').filter({hasText:label})
      assert.ok(await shot.locator('img').evaluate(async img=>{await img.decode();return img.naturalWidth>0}),`${filename} should load`)
      await shot.getByRole('button',{name:`放大${label}`}).click()
      await page.getByRole('dialog').waitFor()
      await page.keyboard.press('Escape')
      await page.getByRole('dialog').waitFor({state:'hidden'})
    }
    assert.ok(!(await page.locator('.shots').innerText()).includes('.xwd'))
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
  if(!info.historical_id){
    const image=await page.evaluate(()=>{
      const canvas=document.createElement('canvas');canvas.width=640;canvas.height=320
      const context=canvas.getContext('2d');context.fillStyle='#fff';context.fillRect(0,0,640,320)
      context.strokeStyle='#2162ae';context.lineWidth=4;context.beginPath()
      for(let x=0;x<640;x+=8){const y=160+Math.sin(x/45)*70;if(x===0)context.moveTo(x,y);else context.lineTo(x,y)}
      context.stroke();return canvas.toDataURL('image/png')
    })
    const imageNames=['schematic_window.png','waveform_window.png','schematic_native.png','waveform_native.png']
    const mock={run_id:'vai_browser_images',status:'succeeded',created_at:new Date().toISOString(),metrics:{validation_status:'PASS'},artifacts:[
      ...imageNames.map((filename,index)=>({id:`png${index}`,kind:filename.startsWith('schematic')?'schematic':'waveform',filename,media_type:'image/png',url:image})),
      {id:'xwd',kind:'data',filename:'waveform_window.xwd',media_type:'image/x-xwindowdump',url:'data:application/octet-stream;base64,AA==' }
    ]}
    await page.route('**/api/v1/runs',route=>route.request().method()==='GET'?route.fulfill({json:{runs:[mock]}}):route.continue())
    await page.reload()
    await page.locator('button.history-item[data-run-id="vai_browser_images"]').click()
    await page.getByRole('heading',{name:'仿真完成',exact:true}).waitFor()
    assert.equal(await page.locator('.shots .shot').count(),4)
    for(const filename of imageNames){
      const label=filename==='waveform_window.png'?'ViVA 波形窗口截图':filename==='waveform_native.png'?'Cadence 波形原生导出':filename==='schematic_window.png'?'Virtuoso 原理图窗口截图':'Cadence 原理图原生导出'
      const shot=page.locator('.shots .shot').filter({hasText:label})
      assert.ok(await shot.locator('img').evaluate(async img=>{await img.decode();return img.naturalWidth>0}),`${filename} should load`)
    }
    assert.ok(!(await page.locator('.shots').innerText()).includes('.xwd'))
    await page.getByRole('button',{name:'放大Cadence 波形原生导出'}).click()
    await page.getByRole('dialog').waitFor()
    await page.keyboard.press('Escape')
    await page.screenshot({path:resolve(output,'result-multiple-images.png'),fullPage:true,animations:'disabled'})
  }
  await page.getByRole('button',{name:'新建仿真'}).first().click()
  await page.getByRole('button',{name:'连接描述',exact:true}).click()
  assert.equal(await page.getByLabel('通用电路示例').inputValue(),'')
  await page.setViewportSize({width:390,height:844})
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),'mobile overflow')
  assert.deepEqual(pageErrors,[])
  const result={status:'PASS',submissions:submissions.length,historical_id:info.historical_id,preview_images:info.historical_id?undefined:4,individual_curves:await page.locator('.individual-curve').count(),browser_errors:pageErrors};writeFileSync(resolve(output,'verification.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result))
}finally{await browser?.close();server.stdin.end('\n');setTimeout(()=>server.kill(),2000).unref()}
