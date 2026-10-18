import { useEffect, useState } from 'react'
import Modal from './Modal'
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
    <Modal title="AI 识别设置" onClose={onClose}>
        <div className="sub">用于整理题目文字和识别电路图片。点击识别时，题目、补充说明及所选图片会发送给你配置的服务商；密钥保存在本机。</div>

        <div className="preset-buttons" aria-label="识别服务商">
          {OCR_PRESETS.map((p, i) => (
            <button key={p.name} aria-pressed={baseUrl === p.baseUrl && model === p.model} disabled={testing} onClick={() => applyPreset(i)}>
              {p.name}
            </button>
          ))}
        </div>

        <div className="param-item" style={{ marginBottom: 10 }}>
          <label htmlFor="ocr-url">服务地址（OpenAI 兼容）</label>
          <input id="ocr-url" type="text" disabled={testing} value={baseUrl} placeholder="https://open.bigmodel.cn/api/paas/v4"
            onChange={(e) => { setBaseUrl(e.target.value.trim()); setResult(null) }} />
        </div>
        <div className="param-item" style={{ marginBottom: 10 }}>
          <label htmlFor="ocr-key">API 密钥</label>
          <input id="ocr-key" type="password" autoComplete="off" disabled={testing} value={apiKey} placeholder="sk-..."
            onChange={(e) => { setApiKey(e.target.value.trim()); setResult(null) }} />
        </div>
        <div className="param-item" style={{ marginBottom: 6 }}>
          <label htmlFor="ocr-model">模型名称（图片识别需支持视觉）</label>
          <input id="ocr-model" type="text" disabled={testing} value={model} placeholder="glm-4v-plus-0111"
            onChange={(e) => { setModel(e.target.value.trim()); setResult(null) }} />
        </div>

        {result && (
          <div className={`note ${result.ok ? 'info' : 'err'}`} style={{ marginTop: 10, wordBreak: 'break-all' }}>
            {result.ok ? '✓ ' : '✗ '}{result.msg}
          </div>
        )}

        <div className="btnrow">
          <button className="btn ghost" disabled={testing} onClick={doTest}>{testing ? '测试中…' : '测试连通'}</button>
          <button className="btn" disabled={testing} onClick={doSave}>保存设置</button>
          <button className="btn ghost" onClick={onClose}>取消</button>
        </div>
    </Modal>
  )
}
