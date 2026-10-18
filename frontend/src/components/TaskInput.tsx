import { useEffect, useRef, useState } from 'react'
import type { ParseResult, TaskDraft } from '../types'
import { postParse } from '../api'
import { loadOcrConfig, ocrImage } from '../ocr'

interface Props {
  draft: TaskDraft
  onDraftChange: (draft: TaskDraft) => void
  disabled: boolean
  onParsed: (text: string, result: ParseResult) => void
  onOpenOcrSettings: () => void
}

const EXAMPLE =
  '设计一阶 RC 低通滤波器，要求截止频率约为 1 kHz。' +
  '使用 0 到 2 V、周期 4 ms、脉宽 2 ms 的脉冲激励验证其时域响应，' +
  '给出 -3 dB 截止频率与脉冲响应波形。'

/** 第 1 步：题目输入（文字粘贴 + 图片上传预览 + AI 识别回填） */
export default function TaskInput({ draft, onDraftChange, disabled, onParsed, onOpenOcrSettings }: Props) {
  const { text, image: img } = draft
  const [busy, setBusy] = useState(false)
  const [ocrBusy, setOcrBusy] = useState(false)
  const [ocrTip, setOcrTip] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const readerRef = useRef<FileReader | null>(null)
  const ocrController = useRef<AbortController | null>(null)
  const [reading, setReading] = useState(false)
  const locked = busy || ocrBusy || reading
  useEffect(() => () => { readerRef.current?.abort(); ocrController.current?.abort() }, [])

  function pickFile(f: File | undefined) {
    if (!f || locked) return
    if (!['image/png', 'image/jpeg'].includes(f.type)) { setErr('请选择图片文件（PNG / JPG）'); return }
    if (f.size > 8 * 1024 * 1024) { setErr('图片超过 8 MB，请压缩后重试'); return }
    const reader = new FileReader()
    readerRef.current = reader
    setReading(true)
    reader.onload = () => { onDraftChange({ ...draft, image: { name: f.name, dataUrl: String(reader.result) } }); setReading(false) }
    reader.onerror = () => { setErr('读取图片失败，请重新选择'); setReading(false) }
    reader.readAsDataURL(f)
    setErr(null); setOcrTip(null)
  }

  /** AI 识别：把截图转成文字并回填 textarea（原文保留，追加不覆盖有内容的输入框） */
  async function doOcr() {
    if (!img || locked) return
    const cfg = loadOcrConfig()
    if (!cfg) { setOcrTip('尚未配置 AI 识别服务'); return }
    setOcrBusy(true); setOcrTip('识别中…（约需十几秒）')
    const controller = new AbortController()
    ocrController.current = controller
    try {
      const { text: got } = await ocrImage(cfg, img.dataUrl, controller.signal)
      if (controller.signal.aborted) return
      if (got) {
        onDraftChange({ ...draft, text: text.trim() ? text + '\n---- 以下为图片识别结果 ----\n' + got : got })
        setOcrTip(`识别完成，已回填 ${got.length} 字，请检查后解析`)
      } else {
        setOcrTip('模型没有返回文字，请换一张更清晰的截图')
      }
    } catch (e) {
      if (!controller.signal.aborted) setOcrTip('识别失败：' + (e instanceof Error ? e.message : String(e)))
    } finally {
      setOcrBusy(false)
    }
  }

  async function doParse() {
    if (disabled || locked) return
    if (!text.trim()) { setErr('请先粘贴题目文字，或识别截图并核对文字后再解析'); return }
    setErr(null)
    setBusy(true)
    try {
      const result = await postParse(text.trim(), img?.dataUrl)
      onParsed(text.trim(), result)
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card fade-in">
      <h2><span className="stepno">1</span> 输入题目</h2>
      <div className="sub">粘贴电路仿真作业的文字描述，或上传截图后用 AI 识别自动转文字（当前版本仅支持文字 RC 低通题目）</div>

      <textarea
        aria-label="题目文字"
        disabled={locked}
        value={text}
        placeholder={'例如：' + EXAMPLE}
        onChange={(e) => onDraftChange({ ...draft, text: e.target.value })}
        onDrop={(e) => { const f = e.dataTransfer.files?.[0]; if (f) { e.preventDefault(); pickFile(f) } }}
      />

      <div style={{ marginTop: 12 }}>
        <input
          ref={fileRef}
          type="file"
          disabled={locked}
          accept="image/png,image/jpeg"
          style={{ display: 'none' }}
          onChange={(e) => { pickFile(e.target.files?.[0]); e.target.value = '' }}
        />
        <div
          className="upload-zone"
          role="button"
          tabIndex={locked ? -1 : 0}
          aria-label="上传题目截图"
          aria-disabled={locked}
          onKeyDown={(e) => { if (!locked && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); fileRef.current?.click() } }}
          onClick={() => { if (!locked) fileRef.current?.click() }}
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => { e.preventDefault(); pickFile(e.dataTransfer.files?.[0]) }}
        >
          {img ? (
            <>
              <div>📎 {img.name} —— 点击可更换</div>
              <img className="preview" src={img.dataUrl} alt="题目截图预览" />
            </>
          ) : (
            <>📷 上传题目截图（点击选择，或把图片拖到这里）· 可选</>
          )}
        </div>
      </div>

      {img && (
        <div className="btnrow" style={{ marginTop: 10 }}>
          <button className="btn" disabled={locked} onClick={doOcr}>
            {ocrBusy ? '识别中…' : '🤖 识别图片题目'}
          </button>
          <button className="btn ghost" onClick={onOpenOcrSettings}>AI 识别设置</button>
          <button className="btn ghost" disabled={locked} onClick={() => { onDraftChange({ text }); setOcrTip(null) }}>移除图片</button>
        </div>
      )}
      {ocrTip && <div className="note info" style={{ marginTop: 10, wordBreak: 'break-all' }}>{ocrTip}</div>}

      {err && <div className="note err" role="alert" style={{ marginTop: 12 }}>{err}</div>}

      <div className="btnrow">
        <button className="btn" disabled={disabled || locked} onClick={doParse}>
          {disabled ? '连接后端中…' : reading ? '读取图片中…' : busy ? '解析中…' : '解析题目'}
        </button>
        <button className="btn ghost" disabled={locked} onClick={() => onDraftChange({ ...draft, text: EXAMPLE })}>填入示例题目</button>
      </div>
    </div>
  )
}
