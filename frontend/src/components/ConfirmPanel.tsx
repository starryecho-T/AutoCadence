import { useMemo, useState } from 'react'
import type { ParseResult, TaskSpec } from '../types'
import { isDemoMode } from '../api'

interface Props {
  parse: ParseResult
  sourceText: string
  busy: boolean
  onConfirm: (task: TaskSpec) => void
  onBack: () => void
}

/** 第 2 步：确认解析结果，可编辑参数；绝不自动提交 */
export default function ConfirmPanel({ parse, sourceText, busy, onConfirm, onBack }: Props) {
  const task0 = parse.task
  const [params, setParams] = useState<Record<string, number | string>>(() => ({ ...(task0?.params ?? {}) }))
  const [err, setErr] = useState<string | null>(null)

  const missing = parse.missing ?? []
  const defaults = parse.defaults ?? {}

  const paramList = useMemo(
    () => Object.entries(params).map(([k, v]) => ({ key: k, value: v })),
    [params]
  )

  function setParam(key: string, raw: string) {
    setParams((p) => {
      const n = Number(raw)
      const next = { ...p, [key]: raw === '' ? '' : Number.isFinite(n) && raw.trim() !== '' ? n : raw }
      return next
    })
  }

  function confirm() {
    if (!paramList.length) { setErr('没有可提交的参数'); return }
    const cleaned: Record<string, number | string> = {}
    for (const { key, value } of paramList) {
      if (value === '' || value === null || value === undefined) { setErr(`参数 ${key} 未填写`); return }
      cleaned[key] = value
    }
    setErr(null)
    onConfirm({ kind: task0?.kind ?? 'rc_lowpass', source_text: sourceText, params: cleaned })
  }

  return (
    <div className="card fade-in">
      <h2><span className="stepno">2</span> 确认参数</h2>
      <div className="sub">
        请核对从题目解析出的参数，可直接修改。确认无误后才会提交仿真（不会自动开始）。
        {isDemoMode() && '（当前为演示模式，参数不会被真实仿真）'}
      </div>

      {missing.length > 0 && (
        <div className="note warn">
          ⚠️ 题目中缺少：{missing.join('、')} —— 已按默认值填入，可修改
        </div>
      )}

      <div className="params-grid" style={{ marginTop: missing.length ? 14 : 0 }}>
        {paramList.map(({ key, value }) => {
          const isNum = typeof value === 'number'
          return (
            <div className="param-item" key={key}>
              <label>{key}{defaults[key] !== undefined && <span style={{ color: '#b8a27a' }}> · 默认</span>}</label>
              {isNum ? (
                <input
                  type="number"
                  step="any"
                  value={String(value)}
                  onChange={(e) => setParam(key, e.target.value)}
                />
              ) : (
                <input type="text" value={String(value)} onChange={(e) => setParam(key, e.target.value)} />
              )}
            </div>
          )
        })}
      </div>

      {Object.keys(defaults).length > 0 && (
        <div className="note info" style={{ marginTop: 14 }}>
          默认项说明：{Object.entries(defaults).map(([k, v]) => `${k}：${String(v)}`).join('；')}
        </div>
      )}

      {(parse.hints?.length ?? 0) > 0 && (
        <div className="note info" style={{ marginTop: 10 }}>
          {parse.hints!.join('；')}
        </div>
      )}

      {err && <div className="note err" style={{ marginTop: 12 }}>{err}</div>}

      <div className="btnrow">
        <button className="btn" disabled={busy} onClick={confirm}>
          {busy ? '提交中…' : '确认并开始仿真'}
        </button>
        <button className="btn ghost" disabled={busy} onClick={onBack}>← 返回修改题目</button>
      </div>
    </div>
  )
}
