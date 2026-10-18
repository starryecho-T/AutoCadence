import { useEffect, useRef, useState } from 'react'
import type { ParseResult, TaskDraft } from '../types'
import { circuitExamples, isDemoMode, parseCircuit, previewCircuit } from '../api'
import { extractCircuit, loadOcrConfig } from '../ocr'
import Icon from './Icon'
import Modal from './Modal'

interface Props {
  draft: TaskDraft
  onDraftChange: (draft: TaskDraft) => void
  disabled: boolean
  onParsed: (text: string, result: ParseResult) => void
  onOpenOcrSettings: () => void
  onBusyChange: (busy: boolean) => void
}
const TEXT_EXAMPLE = '一个直流分压电路：5 V 电压源 V1 的正端接 vin，负端接地。R1 为 1 kΩ，连接 vin 与 out；R2 为 2 kΩ，连接 out 与地。求直流工作点，观察 out 对地电压与 R1 电流。'

export default function GeneralInput({ draft, onDraftChange, disabled, onParsed, onOpenOcrSettings, onBusyChange }: Props) {
  const [examples, setExamples] = useState<{ id: string; label: string; text: string }[]>([])
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [zoom, setZoom] = useState(false)
  const controller = useRef<AbortController | null>(null)
  const reader = useRef<FileReader | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const general = draft.general ?? { input: 'text' as const }
  const connections = general.connections ?? ''
  const issues = general.issues ?? []
  const pending = issues.filter(x => !x.confirmed || !x.answer.trim()).length
  const offline = isDemoMode()
  const manual = general.input === 'connections'
  const hasCandidate = general.connections !== undefined
  const locked = !!busy
  useEffect(() => {
    let active = true
    if (!isDemoMode()) void circuitExamples().then(x => { if (active) setExamples(x) }).catch(() => { /* Manual input remains available. */ })
    return () => { active = false; controller.current?.abort(); reader.current?.abort() }
  }, [])
  useEffect(() => { onBusyChange(locked); return () => onBusyChange(false) }, [locked, onBusyChange])
  function change(next: Partial<NonNullable<TaskDraft['general']>>) { onDraftChange({ ...draft, general: { ...general, ...next } }); setError('') }
  function cancel() { controller.current?.abort(); reader.current?.abort(); setBusy(''); setError('已取消，本次输入已保留。') }
  async function recognize() {
    const cfg = loadOcrConfig()
    if (!cfg) { setError('请先在 AI 识别设置中配置服务，也可以直接填写连接描述。'); return }
    const abort = new AbortController(); controller.current = abort
    setBusy('正在整理元件、连接与分析目标…'); setError('')
    try {
      const clarification = issues.map(x => `${x.question}\n回答：${x.answer || '尚未补充'}`).join('\n')
      const result = await extractCircuit(cfg, { text: draft.text, imageDataUrl: general.input === 'image' ? draft.image?.dataUrl : undefined, clarification }, abort.signal)
      if (abort.signal.aborted) return
      onDraftChange({ ...draft, general: { ...general, connections: result.text, summary: result.summary, issues: result.issues.map(question => ({ question, answer: '', confirmed: false })), stale: false } })
    } catch (e) { if (!abort.signal.aborted) setError(e instanceof Error ? e.message : String(e)) }
    finally { if (controller.current === abort) { controller.current = null; setBusy('') } }
  }
  async function parse() {
    if (pending || (!manual && general.stale)) return
    const abort = new AbortController(); controller.current = abort
    setBusy('正在检查连接、参数与分析设置…'); setError('')
    try {
      const parsed = await parseCircuit(connections, abort.signal)
      const source = [draft.text, ...issues.map(x => `待确认：${x.question}\n补充：${x.answer}`)].filter(Boolean).join('\n\n')
      const preview = source ? await previewCircuit({ ...parsed.task, question: source }, abort.signal) : parsed
      if (!abort.signal.aborted) onParsed(draft.text, { ok: true, task: { kind: 'general_circuit', title: preview.task.title, circuit: preview.task }, circuitPreview: preview })
    } catch (e) { if (!abort.signal.aborted) setError(e instanceof Error ? e.message : String(e)) }
    finally { if (controller.current === abort) { controller.current = null; setBusy('') } }
  }
  function pickFile(file?: File) {
    if (!file) return
    if (!['image/png', 'image/jpeg'].includes(file.type) || file.size > 8 * 1024 * 1024) { setError('请选择不超过 8 MB 的 PNG / JPEG 图片'); return }
    const r = new FileReader(); reader.current = r; setBusy('正在读取图片…'); setError('')
    r.onload = () => { onDraftChange({ ...draft, image: { name: file.name, dataUrl: String(r.result) }, general: { ...general, input: 'image', stale: hasCandidate } }); setBusy('') }
    r.onerror = () => { setError('图片读取失败，请重试'); setBusy('') }
    r.readAsDataURL(file)
  }
  return <section className="fade-in general-input">
    <div className="mode-switch" aria-label="电路模式"><button disabled={locked} onClick={() => onDraftChange({ ...draft, mode: 'rc' })}>RC 低通题目</button><button aria-pressed="true" disabled={locked}>通用电路</button></div>
    {offline && <div className="note warn">通用电路预检和仿真需要连接后端。你可以先准备题目，或切换到 RC 低通体验演示。</div>}
    <div className="card input-card">
      <div className="section-heading"><div><h2>把电路问题交给工作台</h2><p className="sub">描述已知条件，核对整理出的电路，再开始仿真。</p></div><span className="subtle-tag">先理解 · 后确认</span></div>
      <div className="input-methods" aria-label="输入方式">{([['text', '文字描述', 'file'], ['image', '电路截图', 'image'], ['connections', '连接描述', 'circuit']] as const).map(([id, label, icon]) => <button key={id} aria-pressed={general.input === id} disabled={locked} onClick={() => change({ input: id, stale: id !== general.input && id !== 'connections' && hasCandidate ? true : general.stale })}><Icon name={icon} />{label}</button>)}</div>
      {!manual && <>
        {general.input === 'image' && <div className="source-upload">
          <input ref={fileInput} type="file" aria-label="通用电路截图" accept="image/png,image/jpeg" hidden disabled={locked} onChange={e => { pickFile(e.target.files?.[0]); e.target.value = '' }} />
          {draft.image ? <div className="source-attachment"><button className="source-thumb" aria-label="放大原图" onClick={() => setZoom(true)}><img src={draft.image.dataUrl} alt="电路原图" /></button><div><strong>{draft.image.name}</strong><p className="muted small">点击图片放大，核对标注与连线。</p><div className="btnrow"><button className="text-button" disabled={locked} onClick={() => fileInput.current?.click()}>更换图片</button><button className="text-button" disabled={locked} onClick={() => onDraftChange({ ...draft, image: undefined, general: { ...general, stale: hasCandidate } })}>移除图片</button></div></div></div> : <button className="upload-area" disabled={locked} onClick={() => fileInput.current?.click()}><Icon name="image" /><strong>选择电路图或题目截图</strong><span>PNG / JPEG，最大 8 MB</span></button>}
        </div>}
        <label className="field-label" htmlFor="general-question">{general.input === 'image' ? '补充题目与分析要求' : '题目描述'}</label>
        <textarea id="general-question" className="question-editor" value={draft.text} disabled={locked} placeholder={TEXT_EXAMPLE} onChange={e => onDraftChange({ ...draft, text: e.target.value, general: { ...general, stale: hasCandidate } })} />
        <div className="composer-footer"><button className="text-button" disabled={locked} onClick={() => onDraftChange({ ...draft, text: TEXT_EXAMPLE, general: { ...general, stale: hasCandidate } })}>试试文字示例</button><span>写明元件、连接、激励和想观察的量</span></div>
        <div className="recognize-row"><button className="btn" disabled={locked || (general.input === 'image' ? !draft.image : !draft.text.trim())} onClick={recognize}>{hasCandidate ? '根据补充重新整理' : general.input === 'image' ? '识别元件与连接' : '整理为电路'}</button><button className="btn ghost" disabled={locked} onClick={onOpenOcrSettings}><Icon name="settings" />AI 识别设置</button></div>
        <p className="muted small">识别会将题目{general.input === 'image' ? '和图片' : ''}发送给你配置的 AI 服务。结果需要核对。</p>
      </>}
      {manual && <div className="manual-intro"><p className="sub">已有连接描述或完整电路 JSON，可以直接检查；也可以从示例开始。</p><label className="field-label">电路示例 <select aria-label="通用电路示例" disabled={locked} value="" onChange={e => { const x = examples.find(x => x.id === e.target.value); if (x) onDraftChange({ text: '', mode: 'general', general: { input: 'connections', connections: x.text } }) }}><option value="" disabled>选择一个示例</option>{examples.map(x => <option key={x.id} value={x.id}>{x.label}</option>)}</select></label></div>}
    </div>
    {(hasCandidate || manual) && <div className="card extraction-card">
      <div className="section-heading"><h2>待核对的电路描述</h2><span className={`subtle-tag ${pending ? 'amber' : ''}`}>{pending ? `${pending} 项待确认` : '等待预检'}</span></div>
      {general.summary && <p className="sub">{general.summary}</p>}
      {general.stale && !manual && <div className="note warn">原题或输入方式已修改，请重新整理电路后继续。</div>}
      {!!issues.length && <div className="issue-list"><h3>把不确定的地方说明白</h3><p className="muted small">补充答案后可重新整理；也可手动修正下方连接描述，再逐项确认。</p>{issues.map((issue, i) => <div className={`issue-item ${issue.confirmed ? 'resolved' : ''}`} key={i}><div className="issue-title"><span>{i + 1}</span><strong>{issue.question}</strong></div><input aria-label={`问题 ${i + 1} 的补充`} placeholder="填写明确的值、连接或分析要求" disabled={locked} value={issue.answer} onChange={e => change({ issues: issues.map((x, n) => n === i ? { ...x, answer: e.target.value, confirmed: false } : x) })} /><label className="issue-check"><input type="checkbox" disabled={locked || !issue.answer.trim()} checked={issue.confirmed} onChange={e => change({ issues: issues.map((x, n) => n === i ? { ...x, confirmed: e.target.checked } : x) })} />已根据此补充修正下方电路描述</label></div>)}</div>}
      <label className="field-label" htmlFor="connection-description">元件连接与分析设置</label><textarea id="connection-description" aria-label="电路连接描述" className="general-editor" disabled={locked} value={connections} onChange={e => change({ connections: e.target.value, issues: issues.map(x => ({ ...x, confirmed: false })) })} placeholder={'V1 vin 0 DC 5\nR1 vin out 1k\nR2 out 0 2k\n.op\n.save V(out) I(R1)'} />
      <details className="format-help"><summary>查看连接描述格式</summary><p>每行一个元件：R / C / L 编号后依次填写两个节点及数值；D 填阳极、阴极；U 填同相、反相、输出；W 填相连节点。地写 0，数值可用 k、m、u、n、p 前缀。</p><p>电源：V1 正节点 负节点 DC 值；或 SINE 偏置 幅度 频率；或 PULSE 低 高 延迟 上升 下降 脉宽 周期。电流源以 I 开头，末尾可加 AC 幅度 相位。</p><p>分析：.op；.ac 起始Hz 终止Hz 每十倍频点数；.tran 终点秒 最大步长秒；.dc 源编号 起始 终止 步长。保存：.save V(out) I(R1)。也可填写完整电路 JSON。</p></details>
    </div>}
    {error && <div className="note err" role="alert">{error}</div>}
    <footer className="actionbar"><span className="action-status" role="status">{busy || (pending ? `请先处理 ${pending} 项待确认问题` : '预检通过后，仍需确认才会运行仿真')}</span><div className="actions">{locked && <button className="btn ghost" onClick={cancel}>取消处理</button>}<button className="btn" disabled={disabled || offline || locked || !connections.trim() || !!pending || (!manual && general.stale)} onClick={parse}>解析并检查电路<Icon name="arrow" /></button></div></footer>
    {zoom && draft.image && <Modal title="电路原图" onClose={() => setZoom(false)} wide><img className="zoom-image" src={draft.image.dataUrl} alt="电路原图" /></Modal>}
  </section>
}
