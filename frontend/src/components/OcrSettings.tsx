import { useEffect, useState } from 'react'
import Modal from './Modal'
import { OCR_PRESETS, chatUrl, loadOcrConfig, saveOcrConfig, testOcrConfig, testVisionConfig } from '../ocr'

interface Props {
  onClose: () => void
}

/** OCR 设置弹窗：服务商预设 + base URL / API key / 模型；key 只存 localStorage */
export default function OcrSettings({ onClose }: Props) {
  const [baseUrl, setBaseUrl] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [model, setModel] = useState('')
  const [visionModel, setVisionModel] = useState('')
  const [timeoutSeconds, setTimeoutSeconds] = useState(180)
  const [deepThinking, setDeepThinking] = useState(false)
  const [testing, setTesting] = useState(false)
  const [result, setResult] = useState<{ ok: boolean; msg: string } | null>(null)

  useEffect(() => {
    const saved = loadOcrConfig()
    if (saved) { setBaseUrl(saved.baseUrl); setApiKey(saved.apiKey); setModel(saved.model); setVisionModel(saved.visionModel || ''); setTimeoutSeconds(saved.timeoutSeconds || 180); setDeepThinking(saved.deepThinking || false) }
    else { const p = OCR_PRESETS[0]; setBaseUrl(p.baseUrl); setModel(p.model) }
  }, [])

  function applyPreset(i: number) {
    const p = OCR_PRESETS[i]
    if (p.baseUrl) setBaseUrl(p.baseUrl)
    if (p.model) setModel(p.model)
    setVisionModel('')
    setResult(null)
  }

  async function doTest(vision = false) {
    if (!baseUrl || !apiKey || !model) { setResult({ ok: false, msg: '请先填完 Base URL、API Key 和模型名' }); return }
    setTesting(true); setResult(null)
    try {
      const cfg = { baseUrl, apiKey, model, visionModel, timeoutSeconds, deepThinking }
      const reply = vision ? await testVisionConfig(cfg) : await testOcrConfig(cfg)
      setResult({ ok: true, msg: vision ? reply : `文字连通正常（${reply.slice(0, 40)}）；图片能力请点击“测试图片识别”。` })
    } catch (e) {
      setResult({ ok: false, msg: e instanceof Error ? e.message : String(e) })
    } finally { setTesting(false) }
  }

  function doSave() {
    if (!baseUrl || !apiKey || !model) { setResult({ ok: false, msg: '请先填完三项再保存' }); return }
    try {
      chatUrl(baseUrl)
      if (!Number.isFinite(timeoutSeconds) || timeoutSeconds < 30 || timeoutSeconds > 300) throw new Error('等待时间请设为 30～300 秒')
      saveOcrConfig({ baseUrl, apiKey, model, visionModel, timeoutSeconds, deepThinking })
      onClose()
    } catch (error) {
      setResult({ ok: false, msg: error instanceof Error ? error.message : '无法保存设置，请检查浏览器存储权限' })
    }
  }

  return (
    <Modal title="AI 服务设置" onClose={onClose}>
        <div className="sub">识别电路与结果问答共用此配置。识别时发送题目和所选图片；结果页提问时发送当前电路、数值摘要及相关日志。均使用你配置的服务商，密钥保存在本机。</div>

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

        <div className="param-item">
          <label htmlFor="ocr-vision-model">图片模型（可选，留空使用上面的模型）</label>
          <input id="ocr-vision-model" disabled={testing} value={visionModel} onChange={e => { setVisionModel(e.target.value.trim()); setResult(null) }} placeholder="服务商提供的视觉模型名称" />
        </div>
        <div className="param-item">
          <label htmlFor="ocr-timeout">识别最长等待时间（秒）</label>
          <input id="ocr-timeout" type="number" min={30} max={300} disabled={testing} value={timeoutSeconds} onChange={e => setTimeoutSeconds(Number(e.target.value))} />
        </div>
        <label className="issue-check"><input type="checkbox" checked={deepThinking} disabled={testing} onChange={e => setDeepThinking(e.target.checked)} />启用 GLM 深度思考（耗时更长，默认关闭）</label>
        <p className="muted small">文字测试不能证明模型能读图。图片测试只发送自动生成的数字图片；不会发送你的电路图。</p>

        {result && (
          <div className={`note ${result.ok ? 'info' : 'err'}`} style={{ marginTop: 10, wordBreak: 'break-all' }}>
            {result.ok ? '✓ ' : '✗ '}{result.msg}
          </div>
        )}

        <div className="btnrow">
          <button className="btn ghost" disabled={testing} onClick={() => doTest()}>{testing ? '测试中…' : '测试连通'}</button>
          <button className="btn ghost" disabled={testing} onClick={() => doTest(true)}>测试图片识别</button>
          <button className="btn" disabled={testing} onClick={doSave}>保存设置</button>
          <button className="btn ghost" onClick={onClose}>取消</button>
        </div>
    </Modal>
  )
}
