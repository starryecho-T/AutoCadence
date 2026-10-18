import { useRef, useState } from 'react'
import type { ParseResult } from '../types'
import { postParse } from '../api'

interface Props {
  onParsed: (text: string, result: ParseResult) => void
}

const EXAMPLE =
  '设计一个 RC 低通滤波器：电阻 R = 1 kΩ，电容 C = 1 µF。' +
  '要求：输入正弦信号，进行 AC 频率扫描分析（1 Hz ~ 100 kHz），' +
  '测量 -3 dB 截止频率，并记录幅频特性曲线。'

/** 第 1 步：题目输入（文字粘贴 + 图片上传预览） */
export default function TaskInput({ onParsed }: Props) {
  const [text, setText] = useState('')
  const [img, setImg] = useState<{ name: string; dataUrl: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  function pickFile(f: File | undefined) {
    if (!f) return
    if (!f.type.startsWith('image/')) { setErr('请选择图片文件（PNG / JPG）'); return }
    if (f.size > 8 * 1024 * 1024) { setErr('图片超过 8 MB，请压缩后重试'); return }
    const reader = new FileReader()
    reader.onload = () => setImg({ name: f.name, dataUrl: String(reader.result) })
    reader.readAsDataURL(f)
    setErr(null)
  }

  async function doParse() {
    if (!text.trim() && !img) { setErr('请先粘贴题目文字，或上传题目截图'); return }
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
      <div className="sub">粘贴电路仿真作业的文字描述；如有题目截图可一并上传（当前版本仅支持文字 RC 低通题目）</div>

      <textarea
        value={text}
        placeholder={'例如：' + EXAMPLE}
        onChange={(e) => setText(e.target.value)}
        onDrop={(e) => { const f = e.dataTransfer.files?.[0]; if (f) { e.preventDefault(); pickFile(f) } }}
      />

      <div style={{ marginTop: 12 }}>
        <input
          ref={fileRef}
          type="file"
          accept="image/png,image/jpeg"
          style={{ display: 'none' }}
          onChange={(e) => pickFile(e.target.files?.[0])}
        />
        <div
          className="upload-zone"
          onClick={() => fileRef.current?.click()}
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

      {err && <div className="note err" style={{ marginTop: 12 }}>{err}</div>}

      <div className="btnrow">
        <button className="btn" disabled={busy} onClick={doParse}>
          {busy ? '解析中…' : '解析题目'}
        </button>
        <button className="btn ghost" onClick={() => setText(EXAMPLE)}>填入示例题目</button>
      </div>
    </div>
  )
}
