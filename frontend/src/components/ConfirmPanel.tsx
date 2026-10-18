import { useMemo, useState } from 'react'
import type { ParseResult, TaskSpec } from '../types'
import { isDemoMode } from '../api'
import { formatNumber, PARAM_LABELS, rcValues, validateTask } from '../circuit'

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
  const task = { ...task0, kind: task0?.kind ?? 'rc_lowpass', source_text: sourceText, params }
  const validation = validateTask(task)
  let preview: ReturnType<typeof rcValues> | null = null
  if (task.kind === 'rc_lowpass' && !validation) {
    try { preview = rcValues(task) } catch { /* 确认时展示具体错误 */ }
  }

  function setParam(key: string, raw: string) {
    setParams((p) => {
      const n = Number(raw)
      const next = { ...p, [key]: raw === '' ? '' : Number.isFinite(n) && raw.trim() !== '' ? n : raw }
      return next
    })
  }

  function confirm() {
    const error = validateTask(task)
    if (error) { setErr(error); return }
    if (task.kind === 'rc_lowpass') {
      try { rcValues(task) } catch (error) { setErr(error instanceof Error ? error.message : String(error)); return }
    }
    setErr(null)
    onConfirm(task)
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
          ⚠️ 题目中缺少：{missing.join('、')}。请核对默认项，并补全必要参数。
        </div>
      )}

      <div className="params-grid" style={{ marginTop: missing.length ? 14 : 0 }}>
        {paramList.map(({ key, value }) => {
          const isNum = typeof value === 'number'
          return (
            <div className="param-item" key={key}>
              <label htmlFor={`param-${key}`}>{PARAM_LABELS[key] ?? key}{defaults[key] !== undefined && <span style={{ color: '#b8a27a' }}> · 默认</span>}</label>
              {isNum ? (
                <input
                  type="number"
                  id={`param-${key}`}
                  step="any"
                  disabled={busy}
                  value={String(value)}
                  onChange={(e) => setParam(key, e.target.value)}
                />
              ) : (
                <input id={`param-${key}`} type="text" disabled={busy} value={String(value)} onChange={(e) => setParam(key, e.target.value)} />
              )}
            </div>
          )
        })}
      </div>

      {preview && <div className="note info">理论截止频率 ≈ {formatNumber(preview.fc)} Hz；时间常数 τ = {formatNumber(preview.tauMs)} ms。参数采用 SI 单位，例如 1 kΩ 填 1000，1 µF 填 0.000001。</div>}

      {parse.derivation && <div className="note info">
        目标截止频率：{formatNumber(parse.derivation.target_hz)} Hz；
        初始标准值方案：{formatNumber(parse.derivation.achieved_hz)} Hz，舍入误差 {formatNumber(parse.derivation.error_pct)}%。
        {preview && ` 当前参数与目标偏差 ${formatNumber(Math.abs(preview.fc / parse.derivation.target_hz - 1) * 100)}%。`}
      </div>}

      {task.contract && <div className={`note ${validation ? 'warn' : 'info'}`} role="status">
        {validation ? `预检待处理：${validation}` : '参数预检通过：扫描覆盖、完整脉冲周期、步长和点数预算满足要求。'}
      </div>}

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

      {!!parse.defaultNotes?.length && <details style={{ marginTop: 10 }}>
        <summary>查看后端原始默认项说明（提交值以上方参数为准）</summary>
        <ul>{parse.defaultNotes.map((note, index) => <li key={index}>{note}</li>)}</ul>
      </details>}

      {err && <div className="note err" style={{ marginTop: 12 }}>{err}</div>}

      <div className="btnrow">
        <button className="btn" disabled={busy || !!validation} onClick={confirm}>
          {busy ? '提交中…' : '确认并开始仿真'}
        </button>
        <button className="btn ghost" disabled={busy} onClick={onBack}>← 返回修改题目</button>
      </div>
    </div>
  )
}
