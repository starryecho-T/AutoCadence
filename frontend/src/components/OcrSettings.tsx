import { useEffect, useState } from 'react'
import { OCR_PRESETS, loadOcrConfig, saveOcrConfig, testOcrConfig } from '../ocr'

interface Props {
  onClose: () => void
}

/** OCR 设置弹窗：服务商预设 + base URL / API key / 模型；key 只存 localStorage */
export default function OcrSettings({ onClose }: Props) {
  const [baseUrl, setBaseUrl] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [model, setModel] = useState('')
  const [testing, setTesting] = useState(false)
  const [result, setResult] = useState<{ ok: boolean; msg: string } | null>(null)

  useEffect(() => {
    const saved = loadOcrConfig()
    if (saved) { setBaseUrl(saved.baseUrl); setApiKey(saved.apiKey); setModel(saved.model) }
    else { const p = OCR_PRESETS[0]; setBaseUrl(p.baseUrl); setModel(p.model) }
  }, [])

  function applyPreset(i: number) {
    const p = OCR_PRESETS[i]
    if (p.baseUrl) setBaseUrl(p.baseUrl)
    if (p.model) setModel(p.model)
    setResult(null)
  }

  async function doTest() {
    if (!baseUrl || !apiKey || !model) { setResult({ ok: false, msg: '请先填完 Base URL、API Key 和模型名' }); return }
    setTesting(true); setResult(null)
    try {
      const reply = await testOcrConfig({ baseUrl, apiKey, model })
      setResult({ ok: true, msg: `连通正常（模型回复：${reply.slice(0, 40)}）` })
    } catch (e) {
      setResult({ ok: false, msg: e instanceof Error ? e.message : String(e) })
    } finally { setTesting(false) }
  }

  function doSave() {
    if (!baseUrl || !apiKey || !model) { setResult({ ok: false, msg: '请先填完三项再保存' }); return }
    try {
      const url = new URL(baseUrl)
      if (!['http:', 'https:'].includes(url.protocol)) throw new Error('请输入 HTTP 或 HTTPS 服务地址')
      saveOcrConfig({ baseUrl, apiKey, model })
      onClose()
    } catch (error) {
      setResult({ ok: false, msg: error instanceof Error ? error.message : '无法保存设置，请检查浏览器存储权限' })
    }
  }

  return (
    <div className="lightbox" style={{ background: 'rgba(50,55,62,0.45)' }} onClick={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className="card fade-in" role="dialog" aria-modal="true" aria-label="AI 识别设置" style={{ width: 520, maxWidth: '92vw', margin: 0, boxShadow: '0 12px 40px rgba(60,70,85,0.25)', cursor: 'default' }}>
        <h2>AI 识别设置</h2>
        <div className="sub">用于把题目截图自动转录为文字。API Key 仅保存在本机浏览器（localStorage），请求直接发往你配置的服务商。</div>

        <div className="btnrow" style={{ marginTop: 0, marginBottom: 14, flexWrap: 'wrap' }}>
          {OCR_PRESETS.map((p, i) => (
            <button key={p.name} className="btn ghost" style={{ fontSize: 12.5, padding: '4px 12px' }} onClick={() => applyPreset(i)}>
              {p.name}
            </button>
          ))}
        </div>

        <div className="param-item" style={{ marginBottom: 10 }}>
          <label>Base URL（OpenAI 兼容接口根地址）</label>
          <input type="text" value={baseUrl} placeholder="https://open.bigmodel.cn/api/paas/v4"
            onChange={(e) => setBaseUrl(e.target.value.trim())} />
        </div>
        <div className="param-item" style={{ marginBottom: 10 }}>
          <label>API Key</label>
          <input type="password" value={apiKey} placeholder="sk-..."
            onChange={(e) => setApiKey(e.target.value.trim())} />
        </div>
        <div className="param-item" style={{ marginBottom: 6 }}>
          <label>模型名（需支持图片输入）</label>
          <input type="text" value={model} placeholder="glm-4v-plus-0111"
            onChange={(e) => setModel(e.target.value.trim())} />
        </div>

        {result && (
          <div className={`note ${result.ok ? 'info' : 'err'}`} style={{ marginTop: 10, wordBreak: 'break-all' }}>
            {result.ok ? '✓ ' : '✗ '}{result.msg}
          </div>
        )}

        <div className="btnrow">
          <button className="btn" disabled={testing} onClick={doTest}>{testing ? '测试中…' : '测试连通'}</button>
          <button className="btn" onClick={doSave}>保存</button>
          <button className="btn ghost" onClick={onClose}>取消</button>
        </div>
      </div>
    </div>
  )
}
