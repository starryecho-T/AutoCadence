// Display historical real EDA evidence; this test does not submit simulations.
import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { mkdirSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { createInterface } from 'node:readline'
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE ? pathToFileURL(process.env.PLAYWRIGHT_MODULE).href : 'playwright')
const browser = await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_CHANNEL || 'msedge'})
const results=[], output=resolve('../work/studies-browser');mkdirSync(output,{recursive:true})
try {
  for (const example of ['common_base_y','pmos_families','bjt_transfer']) {
    const server=spawn(resolve('../backend/.venv-local/Scripts/python.exe'),['-X','utf8','tests/general_workflow_server.py','--history-example',example],{windowsHide:true,stdio:['pipe','pipe','pipe']})
    let error='';server.stderr.on('data',d=>error+=d)
    const page=await browser.newPage({viewport:{width:1280,height:900}}), pageErrors=[]
    page.on('pageerror',e=>pageErrors.push(e.message))
    try {
      const info=await new Promise((ok,bad)=>{const timer=setTimeout(()=>bad(new Error(error||'server timeout')),15000);createInterface({input:server.stdout}).once('line',line=>{clearTimeout(timer);ok(JSON.parse(line))})})
      assert.ok(info.historical_id)
      for (let i=0;i<100;i++) { try { const r=await fetch(info.url+'/health');if(r.ok)break } catch {} await new Promise(r=>setTimeout(r,100));if(i===99)throw new Error(error||'server did not start') }
      await page.goto(info.url)
      await page.locator(`button.history-item[data-run-id="${info.historical_id}"]`).first().click()
      await page.getByRole('heading',{name:'仿真完成',exact:true}).waitFor()
      await page.locator('.overview-curve polyline').first().waitFor({state:'attached'})
      if (example === 'common_base_y') {
        await page.getByRole('heading',{name:'分析与比较',exact:true}).waitFor()
        await page.getByLabel('扫描组',{exact:true}).selectOption('equivalent')
        assert.equal(await page.locator('.overview-curve polyline').count(),2)
        await page.getByLabel('AC 分量').selectOption('phase')
      } else if (example === 'pmos_families') {
        await page.getByLabel('扫描组',{exact:true}).selectOption('s003')
        assert.ok((await page.locator('.wave-legend').first().innerText()).includes('VG.dc=-2.5'))
        await page.getByLabel('扫描组',{exact:true}).selectOption('all')
      } else {
        await page.getByRole('heading',{name:'NPN 共射转移分析',exact:true}).waitFor()
        assert.ok((await page.locator('.study-results').innerText()).includes('饱和'))
      }
      await page.screenshot({path:resolve(output,example+'.png'),fullPage:true})
      await page.setViewportSize({width:390,height:844})
      const overflow=await page.evaluate(()=>({width:window.innerWidth,scroll:document.documentElement.scrollWidth,elements:[...document.querySelectorAll('body *')].filter(e=>e.getBoundingClientRect().right>window.innerWidth+1).map(e=>({tag:e.tagName,class:e.className,right:e.getBoundingClientRect().right,text:e.textContent?.slice(0,100)})).slice(0,16)}))
      assert.ok(overflow.scroll<=overflow.width,JSON.stringify(overflow))
      assert.deepEqual(pageErrors,[])
      results.push({example,status:'PASS',historical_id:info.historical_id,browser_errors:pageErrors})
    } finally { await page.close();server.stdin.end('\n');setTimeout(()=>server.kill(),2000).unref() }
  }
  writeFileSync(resolve(output,'result.json'),JSON.stringify(results,null,2)+'\n');console.log(JSON.stringify(results))
} finally { await browser.close() }
