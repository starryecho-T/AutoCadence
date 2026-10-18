import { useState } from 'react'
import type { ParseResult, TaskSpec } from '../types'
import { isDemoMode } from '../api'
import { formatNumber, PARAM_LABELS, validateTask } from '../circuit'
import { engineering, PARAMETERS } from '../units'
import Icon from './Icon'
import ParameterField from './ParameterField'

interface Props {
  parse: ParseResult; sourceText: string; busy: boolean
  onConfirm: (task: TaskSpec) => void; onBack: () => void; onTaskChange: (task: TaskSpec) => void
}
const COMPONENTS = ['r_ohm', 'c_farad']
const SIGNAL = ['low_v', 'high_v', 'period_s', 'width_s']

export default function ConfirmPanel({ parse, sourceText, busy, onConfirm, onBack, onTaskChange }: Props) {
  const [params, setParams] = useState(() => ({ ...parse.task?.params }))
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const task = { ...parse.task, kind: parse.task?.kind ?? 'rc_lowpass', source_text: sourceText, params }
  const validation = validateTask(task)
  const defaults = parse.defaults ?? {}
  const advanced = Object.keys(params).filter(key => !COMPONENTS.includes(key) && !SIGNAL.includes(key))
  const r = Number(params.r_ohm), c = Number(params.c_farad), tau = r * c, fc = 1 / (2 * Math.PI * tau)
  const preview = r > 0 && c > 0 && Number.isFinite(fc) && fc > 0 && Number.isFinite(tau)
  const cutoff = preview ? engineering(fc, 'frequency') : null
  const resistance = engineering(r, 'resistance'), capacitance = engineering(c, 'capacitance')
  const timeConstant = engineering(tau, 'time')
  const target = parse.derivation?.target_hz
  const recommended = Object.keys(params).filter(key => defaults[key] !== undefined).length

  function changeParam(name: string, value: number | string) {
    const next = { ...params, [name]: value }
    setParams(next)
    onTaskChange({ ...task, params: next })
  }
  function fields(keys: string[]) {
    return <div className="params-grid">{keys.filter(key => key in params).map(key => <ParameterField key={key} name={key} value={params[key]}
      recommended={defaults[key] !== undefined} disabled={busy} onChange={changeParam} />)}</div>
  }

  return <section className="fade-in">
    {isDemoMode() && <div className="note warn">演示模式：本次只预览界面流程，不运行真实仿真。</div>}
    {!!parse.missing?.length && <div className="note warn">请补全或核对：{parse.missing.map(key => PARAMETERS[key]?.label ?? PARAM_LABELS[key] ?? key).join('、')}。</div>}
    <div className="confirm-layout">
      <div className="card parameter-card">
        <section className="form-section"><div className="section-heading"><h2>电路元件</h2><span className="muted small">一阶 RC 低通</span></div>{fields(COMPONENTS)}</section>
        {SIGNAL.some(key => key in params) && <section className="form-section"><div className="section-heading"><h2>输入信号</h2><span className="muted small">脉冲激励</span></div>{fields(SIGNAL)}</section>}
        <p className="recognition"><Icon name="check" />{recommended ? `${recommended} 项参数采用推荐值，可展开核对` : '参数可编辑，修改后实时检查'}</p>
        {!!advanced.length && <details className="advanced" open={advancedOpen} onToggle={event => setAdvancedOpen(event.currentTarget.open)}>
          <summary>高级仿真设置 <span>扫描范围、步长等 · {advanced.length} 项</span></summary>{fields(advanced)}
        </details>}
        {(!!parse.hints?.length || !!parse.defaultNotes?.length || !!Object.keys(defaults).length) && <details className="parse-details">
          <summary>参数来源与解析说明</summary>
          {!!Object.keys(defaults).length && <p>推荐项：{Object.keys(defaults).map(key => PARAMETERS[key]?.label ?? PARAM_LABELS[key] ?? key).join('、')}。提交值以上方输入为准。</p>}
          {parse.derivation && <p>根据目标频率匹配标准元件，初始方案为 {formatNumber(parse.derivation.achieved_hz)} Hz。</p>}
          <ul>{[...(parse.hints ?? []), ...(parse.defaultNotes ?? [])].map((note, index) => <li key={index}>{note}</li>)}</ul>
        </details>}
      </div>
      <aside className="preview-aside"><div className="card theory-preview">
        <div className="section-heading"><h2>电路预览</h2><Icon name="circuit" /></div>
        <svg className="circuit-diagram" viewBox="0 0 230 108" role="img" aria-label="电阻串联、电容对地的 RC 低通电路">
          <g fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round"><path d="M17 35h34l5-6 8 12 8-12 8 12 8-12 5 6h110M149 35v29m-13 0h26m-26 7h26m-13 0v20m-11 0h22m-18 5h14m-10 5h6" /><circle cx="17" cy="35" r="3" fill="white" /><circle cx="203" cy="35" r="3" fill="white" /><circle cx="149" cy="35" r="2" fill="currentColor" /></g>
          <text x="7" y="58">Vin</text><text x="192" y="58">Vout</text><text x="52" y="16">{r > 0 ? `${resistance.value} ${resistance.unit}` : 'R'}</text><text x="172" y="72">{c > 0 ? `${capacitance.value} ${capacitance.unit}` : 'C'}</text>
        </svg>
        <span className="muted small">理论截止频率</span>
        <div className="preview-number"><output data-testid="theory-cutoff">{cutoff?.value ?? '—'}</output><span>{cutoff?.unit}</span></div>
        <p className="formula">f<sub>c</sub> = 1 / (2πRC)</p>
        {target !== undefined && <><div className="target-row"><span>题目目标</span><strong>{engineering(target, 'frequency').value} {engineering(target, 'frequency').unit}</strong></div>
          {preview && <div className="preview-delta"><Icon name="info" />与目标偏差 {Number((Math.abs(fc / target - 1) * 100).toPrecision(3))}%</div>}</>}
        <p className="preview-foot">时间常数 τ <strong>{preview ? `${timeConstant.value} ${timeConstant.unit}` : '—'}</strong><br />按当前元件值计算，供仿真前核对。</p>
      </div></aside>
    </div>
    {validation && <div className="note err validation-message" role="alert"><Icon name="info" /><div>{validation}{!!advanced.length && !advancedOpen && <button className="text-button" onClick={() => setAdvancedOpen(true)}>展开高级设置</button>}</div></div>}
    <footer className="actionbar"><div className={`action-status ${validation ? 'muted' : 'success'}`} role="status"><Icon name={validation ? 'info' : 'check'} />{validation ? '请先修正参数，再开始仿真' : '参数预检通过，等待你确认'}</div><div className="actions">
      <button className="btn ghost" disabled={busy} onClick={onBack}>返回修改题目</button>
      <button className="btn" disabled={busy || !!validation} onClick={() => { if (!validateTask(task)) onConfirm(task) }}>{busy ? '提交中…' : '确认并开始仿真'}<Icon name="arrow" /></button>
    </div></footer>
  </section>
}
