import { useEffect, useRef, useState } from 'react'
import type { ParseResult, TaskDraft } from '../types'
import { postParse } from '../api'
import { loadOcrConfig, ocrImage } from '../ocr'
import Icon from './Icon'
import GeneralInput from './GeneralInput'

interface Props {
  draft: TaskDraft
  onDraftChange: (draft: TaskDraft) => void
  disabled: boolean
  onParsed: (text: string, result: ParseResult) => void
  onOpenOcrSettings: () => void
  onBusyChange: (busy: boolean) => void
}

const EXAMPLE =
  '设计一阶 RC 低通滤波器，要求截止频率约为 1 kHz。' +
  '使用 0 到 2 V、周期 4 ms、脉宽 2 ms 的脉冲激励验证其时域响应，' +
  '给出 -3 dB 截止频率与脉冲响应波形。'

/** 第 1 步：题目输入（文字粘贴 + 图片上传预览 + AI 识别回填） */
export default function TaskInput({ draft, onDraftChange, disabled, onParsed, onOpenOcrSettings, onBusyChange }: Props) {
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
  useEffect(() => { onBusyChange(locked); return () => onBusyChange(false) }, [locked, onBusyChange])
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

  if (draft.mode === 'general') return <GeneralInput draft={draft} onDraftChange={onDraftChange} disabled={disabled} onParsed={onParsed} onOpenOcrSettings={onOpenOcrSettings} onBusyChange={onBusyChange} />

  return <section className="fade-in">
    <div className="btnrow" style={{ marginBottom: 12 }}><button className="btn" disabled>RC 低通题目</button><button className="btn ghost" disabled={locked} onClick={() => onDraftChange({ ...draft, mode: 'general' })}>通用电路</button></div>
    <div className="card input-card" onPaste={event => {
      const file = [...event.clipboardData.items].find(item => item.type.startsWith('image/'))?.getAsFile()
      if (file && !locked) { event.preventDefault(); pickFile(file) }
    }} onDragOver={event => event.preventDefault()} onDrop={event => { if (event.dataTransfer.files.length) { event.preventDefault(); pickFile(event.dataTransfer.files[0]) } }}>
      <div className="section-heading"><h2>描述你想验证的电路</h2><Icon name="circuit" /></div>
      <p className="sub">写下电路类型、元件参数或目标频率，以及需要观察的现象。</p>
      <div className="composer">
        <textarea aria-label="题目文字" disabled={locked} value={text} placeholder={'例如：' + EXAMPLE}
          onChange={event => onDraftChange({ ...draft, text: event.target.value })}
          onKeyDown={event => { if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') { event.preventDefault(); void doParse() } }} />
        <div className="composer-toolbar"><button className="text-button" disabled={locked} onClick={() => fileRef.current?.click()}><Icon name="image" />添加题目截图</button><span>支持拖入或粘贴图片 · PNG / JPG · 最大 8 MB</span></div>
      </div>
      <input ref={fileRef} type="file" disabled={locked} accept="image/png,image/jpeg" hidden onChange={event => { pickFile(event.target.files?.[0]); event.target.value = '' }} />
      {img && <div className="attachment"><img src={img.dataUrl} alt="题目截图预览" /><div className="attachment-body"><strong>{img.name}</strong><p className="muted small">识别后请核对文字，再解析题目。</p><div className="btnrow">
        <button className="btn ghost" disabled={locked} onClick={doOcr}>{ocrBusy ? '识别中…' : '识别图片题目'}</button>
        <button className="text-button" onClick={onOpenOcrSettings}>AI 识别设置</button>
      </div></div><button className="icon-button" aria-label="移除图片" disabled={locked} onClick={() => { onDraftChange({ text }); setOcrTip(null) }}><Icon name="close" /></button></div>}
      {ocrTip && <div className="note info" role="status">{ocrTip}</div>}
      {err && <div className="note err" role="alert">{err}</div>}
      <div className="example-row"><span>试试示例</span><button className="example-chip" aria-label="填入示例题目" disabled={locked} onClick={() => onDraftChange({ ...draft, text: EXAMPLE })}>1 kHz 低通滤波器<Icon name="arrow" /></button></div>
    </div>
    <footer className="actionbar"><span className="action-status muted">支持一阶 RC 低通电路 · Ctrl + Enter 解析</span><button className="btn" disabled={disabled || locked} onClick={doParse}>{disabled ? '连接后端中…' : reading ? '读取图片中…' : busy ? '解析中…' : '解析题目'}<Icon name="arrow" /></button></footer>
  </section>
}
