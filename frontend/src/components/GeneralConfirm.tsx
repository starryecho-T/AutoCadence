import { useEffect, useRef, useState } from 'react'
import type { CircuitPreview, GeneralCircuit, TaskDraft, TaskSpec } from '../types'
import { previewCircuit } from '../api'
import { ANALYSIS_LABELS, COMPONENT_LABELS, editableCircuit, FIELDS, formatEngineering, parseEngineering, PIN_LABELS } from '../generalCircuit'
import ConnectionMap from './ConnectionMap'
import Modal from './Modal'

interface Props {
  preview: CircuitPreview
  draft?: TaskDraft
  busy: boolean
  onConfirm: (task: TaskSpec) => void
  onBack: () => void
  onTaskChange: (task: TaskSpec) => void
  onCircuitEdit?: (raw: string) => void
  onPreviewChange?: (preview: CircuitPreview) => void
}
function ValueField({ label, value, unit = '', numeric = true, disabled, onChange }: { label: string; value: unknown; unit?: string; numeric?: boolean; disabled: boolean; onChange: (value: unknown) => void }) {
  const [raw, setRaw] = useState(numeric ? formatEngineering(value) : String(value ?? ''))
  if (typeof value === 'boolean') return <label className="issue-check"><input type="checkbox" checked={value} disabled={disabled} onChange={e => onChange(e.target.checked)} />{label}</label>
  return <label className="general-field"><span>{label}</span><div className="general-field-control"><input aria-label={label} value={raw} disabled={disabled} onChange={e => { setRaw(e.target.value); onChange(numeric ? parseEngineering(e.target.value) : e.target.value) }} /><span>{unit}</span></div></label>
}

export default function GeneralConfirm({ preview, draft, busy, onConfirm, onBack, onTaskChange, onCircuitEdit, onPreviewChange }: Props) {
  const [raw, setRaw] = useState(() => JSON.stringify(preview.task, null, 2))
  const [checked, setChecked] = useState(preview)
  const [dirty, setDirty] = useState(false)
  const [checking, setChecking] = useState(false)
  const [revision, setRevision] = useState(0)
  const [error, setError] = useState('')
  const [zoom, setZoom] = useState(false)
  const controller = useRef<AbortController | null>(null)
  useEffect(() => () => controller.current?.abort(), [])
  const circuit = editableCircuit(raw)
  const locked = busy || checking
  const wrapped = (p: CircuitPreview): TaskSpec => ({ kind: 'general_circuit', title: p.task.title, circuit: p.task })
  function edit(text: string) { setRaw(text); setDirty(true); setError(''); onTaskChange({ kind: 'general_circuit' }); onCircuitEdit?.(text) }
  function update(next: GeneralCircuit) { edit(JSON.stringify(next, null, 2)) }
  async function check() {
    const abort = new AbortController(); controller.current = abort
    setChecking(true); setError('')
    try {
      const p = await previewCircuit(JSON.parse(raw), abort.signal)
      if (abort.signal.aborted) return
      setChecked(p); setRaw(JSON.stringify(p.task, null, 2)); setDirty(false); setRevision(r => r + 1)
      onTaskChange(wrapped(p)); onPreviewChange?.(p); onCircuitEdit?.(JSON.stringify(p.task, null, 2))
    } catch (e) { if (!abort.signal.aborted) setError(e instanceof Error ? e.message : String(e)) }
    finally { if (!abort.signal.aborted) setChecking(false) }
  }
  function fields(record: Record<string, unknown>, prefix: string, onChange: (key: string, value: unknown) => void, sourceUnit = '') {
    return <div className="general-fields">{Object.entries(record).filter(([k, v]) => FIELDS[k] && v !== null && typeof v !== 'object').map(([key, value]) => <ValueField key={`${revision}.${prefix}.${key}`} label={`${prefix} ${FIELDS[key][0]}`} unit={FIELDS[key][1] || (['dc', 'ac_magnitude', 'offset', 'amplitude', 'low', 'high', 'start', 'stop', 'step'].includes(key) ? sourceUnit : '')} value={value} numeric={!['source', 'model', 'control_source'].includes(key)} disabled={locked} onChange={v => onChange(key, v)} />)}</div>
  }
  const sourceText = draft?.text || (typeof checked.task.question === 'string' ? checked.task.question : '')
  return <section className="fade-in general-review">
    <div className="card review-intro"><div className="section-heading"><div><h2>核对元件与连接</h2><p className="sub">确认每个端点、数值和观察目标。修改后重新检查，才可提交仿真。</p></div><span className={`subtle-tag ${dirty ? 'amber' : ''}`}>{dirty ? '有待检查的修改' : '连接预检通过'}</span></div>
      {!!draft?.general?.proposals?.length && <details className="detail-section"><summary>已确认的 AI 建议 · {draft.general.proposals.length} 项</summary>{draft.general.proposals.map(p => <p key={p.id}><strong>{p.title}</strong><br />{p.detail}<br /><span className="muted small">{p.reason}</span></p>)}</details>}
      <div className="circuit-summary"><span><strong>{circuit?.components.length ?? '—'}</strong> 个元件</span><span><strong>{circuit?.signals.length ?? '—'}</strong> 个观察量</span><span>{circuit?.analyses.map(a => ANALYSIS_LABELS[a.type] ?? a.type).join(' · ')}</span></div>
      {Array.isArray(circuit?.parameter_sweeps) && circuit.parameter_sweeps.length > 0 && <p className="note">参数扫描：{circuit.parameter_sweeps.map((s: any) => `${s.component}.${s.parameter} = ${s.values.join(', ')}`).join('；')}。另保留原参数基准组。</p>}
      {!!circuit?.two_port && <p className="note">提取二端口 Y 参数，并在原直流偏置下验证交流小信号等效。参考频率的复数 Y 无法用实数受控源表达时，会在结果中说明。</p>}
      {!!circuit?.bjt_transfer && <p className="note">包含 NPN 工作区、分段理论曲线和与仿真的误差分析。</p>}
      {(sourceText || draft?.image) && <details className="detail-section"><summary>对照原题与图片</summary><p className="source-question">{sourceText}</p>{draft?.image && <button className="source-thumb" aria-label="放大原图" onClick={() => setZoom(true)}><img src={draft.image.dataUrl} alt="电路原图" /></button>}{!!draft?.general?.issues?.length && <ul>{draft.general.issues.map((x, i) => <li key={i}>{x.question}：{x.answer}</li>)}</ul>}</details>}
    </div>
    {circuit ? <>
      <div className="card"><ConnectionMap circuit={circuit} /></div>
      <div className="card"><div className="section-heading"><h3>元件与参数</h3><span className="muted small">数值可输入 1k、100n、2m 等工程前缀</span></div>
        <div className="component-list">{circuit.components.map((c, index) => <article className="component-editor" key={`${revision}.${index}.${c.id}`}><div className="component-heading"><strong>{c.id}</strong><span>{COMPONENT_LABELS[c.type] ?? c.type}</span></div>
          <div className="general-fields pin-fields">{Object.entries(c.pins).map(([pin, node]) => <ValueField key={`${revision}.${pin}`} label={`${c.id} ${PIN_LABELS[pin] ?? pin}`} value={node} numeric={false} disabled={locked} onChange={value => update({ ...circuit, components: circuit.components.map((x, i) => i === index ? { ...x, pins: { ...x.pins, [pin]: String(value) } } : x) })} />)}</div>
          {fields(c, c.id, (key, value) => update({ ...circuit, components: circuit.components.map((x, i) => i === index ? { ...x, [key]: value } : x) }), c.type === 'current_source' ? 'A' : 'V')}
          {c.waveform && typeof c.waveform === 'object' && !Array.isArray(c.waveform) ? <div className="waveform-settings"><p className="muted small">输入波形 · {String((c.waveform as Record<string, unknown>).type)}</p>{fields(c.waveform as Record<string, unknown>, `${c.id} 波形`, (key, value) => update({ ...circuit, components: circuit.components.map((x, i) => i === index ? { ...x, waveform: { ...(c.waveform as object), [key]: value } } : x) }), c.type === 'current_source' ? 'A' : 'V')}{'points' in c.waveform && <p className="muted small">分段线性波形的点值可在完整电路编辑器中修改。</p>}</div> : null}
        </article>)}</div>
      </div>
      <div className="review-two-columns"><div className="card"><h3>分析设置</h3>{circuit.analyses.map((a, index) => <div className="analysis-editor" key={`${revision}.${index}`}><h4>{ANALYSIS_LABELS[a.type] ?? a.type}</h4>{a.type === 'op' && <p className="muted small">求取稳态节点电压和支路电流。</p>}{fields(a, ANALYSIS_LABELS[a.type] ?? a.type, (key, value) => update({ ...circuit, analyses: circuit.analyses.map((x, i) => i === index ? { ...x, [key]: value } : x) }), circuit.components.find(c => c.id === a.source)?.type === 'current_source' ? 'A' : 'V')}</div>)}</div>
      <div className="card"><h3>观察量</h3><p className="muted small">每个观察量都会保留独立结果；多个信号可分别查看曲线。</p>{circuit.signals.map((s, index) => <div className="signal-editor" key={`${revision}.${index}`}><h4>{s.id} · {s.type === 'voltage' ? '节点电压' : s.type === 'device_parameter' ? '器件工作参数' : '支路电流'}</h4><div className="general-fields">{(s.type === 'voltage' ? ['p', 'n'] : s.type === 'device_parameter' ? ['component', 'parameter'] : ['component']).map(key => <ValueField key={`${revision}.${key}`} label={`${s.id} ${key === 'p' ? '正节点' : key === 'n' ? '参考节点' : key === 'parameter' ? '参数名称' : '元件编号'}`} value={s[key] ?? '0'} numeric={false} disabled={locked} onChange={value => update({ ...circuit, signals: circuit.signals.map((x, i) => i === index ? { ...x, [key]: value } : x) })} />)}</div></div>)}</div></div>
    </> : <div className="note warn">完整电路内容尚不能显示为表单，请在下方修正后重新检查。</div>}
    <div className="card review-details">
      {!!checked.warnings.length && <div className="note warn">{dirty ? '上次预检提示：' : ''}{checked.warnings.join('；')}</div>}
      <details><summary>高级：完整电路、模型与测量指标</summary><textarea aria-label="通用电路 JSON" className="general-editor" disabled={locked} value={raw} onChange={e => { edit(e.target.value); setRevision(r => r + 1) }} /></details>
      <details className="detail-section"><summary>上次预检的节点归并与网表</summary>{dirty && <p className="note warn">修改尚未检查，下方仍是上次预检结果。</p>}<pre>{JSON.stringify(checked.normalized.aliases, null, 2)}</pre><pre>{checked.netlist}</pre></details>
      <p className="muted small">二极管使用所选模型；理想运放无电源轨限幅。预检用于检查连接和参数，实际收敛情况以仿真结果为准。</p>
    </div>
    {error && <div className="note err" role="alert">{error}</div>}
    <footer className="actionbar"><span className="action-status" role="status">{checking ? '正在重新检查电路…' : dirty ? '修改已保留，请重新检查' : '准备就绪，等待你的确认'}</span><div className="actions"><button className="btn ghost" disabled={locked} onClick={onBack}>返回修改</button>{dirty && <button className="btn" disabled={locked} onClick={check}>重新检查修改</button>}<button className="btn" disabled={locked || dirty} onClick={() => onConfirm(wrapped(checked))}>{busy ? '提交中…' : '确认并开始仿真'}</button></div></footer>
    {zoom && draft?.image && <Modal title="电路原图" onClose={() => setZoom(false)} wide><img className="zoom-image" src={draft.image.dataUrl} alt="电路原图" /></Modal>}
  </section>
}
