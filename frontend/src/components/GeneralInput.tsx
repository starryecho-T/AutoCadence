import { useEffect, useRef, useState } from 'react'
import type { ParseResult, TaskDraft } from '../types'
import { circuitCapabilities, isDemoMode, parseCircuit, type CircuitCapabilities } from '../api'
import { extractCircuit, loadOcrConfig } from '../ocr'
import { circuitTitle } from '../generalCircuit'
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
const TEXT_EXAMPLE = '帮我设计一个截止频率约 1 kHz 的低通滤波器，看看方波经过它后有什么变化。元件值和仿真设置请先给我建议。'

export default function GeneralInput({ draft, onDraftChange, disabled, onParsed, onOpenOcrSettings, onBusyChange }: Props) {
  const [examples, setExamples] = useState<{ id: string; label: string; text: string }[]>([])
  const [capabilities, setCapabilities] = useState<CircuitCapabilities | null>(null)
  const [capabilityError, setCapabilityError] = useState('')
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [elapsed, setElapsed] = useState(0)
  const [zoom, setZoom] = useState(false)
  const controller = useRef<AbortController | null>(null)
  const reader = useRef<FileReader | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const general = draft.general ?? { input: 'text' as const }
  const connections = general.connections ?? ''
  const selectedExample = examples.find(x => x.id === general.exampleId && x.text === connections)?.id ?? ''
  const issues = general.issues ?? []
  const proposals = general.proposals ?? []
  const pending = issues.filter(x => !x.confirmed || !x.answer.trim()).length + proposals.filter(x => x.decision !== 'yes').length
  const rejected = proposals.some(x => x.decision === 'no')
  const offline = isDemoMode()
  const manual = general.input === 'connections'
  const hasCandidate = general.connections !== undefined
  const mosDefault = capabilities !== null && !!(capabilities as { default_models?: { nmos?: string; pmos?: string } }).default_models
  const locked = !!busy
  useEffect(() => {
    let active = true
    const capabilityAbort = new AbortController()
    if (!disabled && !isDemoMode()) void circuitCapabilities(capabilityAbort.signal).then(x => { if (active) { setCapabilities(x); setExamples(x.examples); setCapabilityError('') } }).catch(() => { if (active) setCapabilityError('暂时无法读取通用后端能力，可先准备题目；预检需要新版后端。') })
    return () => { active = false; capabilityAbort.abort(); controller.current?.abort(); reader.current?.abort() }
  }, [disabled])
  useEffect(() => {
    setElapsed(0)
    if (!busy) return
    const started = Date.now()
    const timer = setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000)
    return () => clearInterval(timer)
  }, [busy])
  useEffect(() => { onBusyChange(locked); return () => onBusyChange(false) }, [locked, onBusyChange])
  function change(next: Partial<NonNullable<TaskDraft['general']>>) { onDraftChange({ ...draft, general: { ...general, ...next } }); setError('') }
  function cancel() { controller.current?.abort(); reader.current?.abort(); setBusy(''); setError('已取消，本次输入已保留。') }
  async function recognize() {
    const cfg = loadOcrConfig()
    if (!cfg) { setError('请先在 AI 识别设置中配置服务，也可以直接填写连接描述。'); return }
    const abort = new AbortController(); controller.current = abort
    setBusy('正在整理元件、连接与分析目标…'); setError('')
    try {
      const clarification = [...proposals.map(x => `${x.title}：${x.detail}\n用户决定：${x.decision === 'yes' ? '接受，保持此条件' : x.decision === 'no' ? '否决，请提出不同方案' : '尚未确认'}`), ...issues.map(x => `${x.question}\n回答：${x.answer || '请你提出合理建议，供我判断是或否'}`)].join('\n')
      const result = await extractCircuit(cfg, { text: draft.text, imageDataUrl: general.input === 'image' ? draft.image?.dataUrl : undefined, clarification, capabilities: capabilities ? { components: capabilities.components, analyses: capabilities.analyses, studies: capabilities.studies, limits: capabilities.limits, model_types: capabilities.model_types, cmn018: capabilities.cmn018 } : undefined, previousCandidate: connections, validationError: error || undefined }, abort.signal)
      if (abort.signal.aborted) return
      onDraftChange({ ...draft, general: { ...general, connections: result.text, title: result.title, summary: result.summary, proposals: (result.proposals?.length ? result.proposals : result.text.trim() ? [{ id: 'candidate', title: '按这份候选方案继续，可以吗？', detail: result.summary || 'AI 已整理候选电路，下一步可查看元件、连接与参数。', reason: '请核对是否符合原意；缺失条件的建议仍需通过后端预检。' }] : []).map(p => ({ ...p, decision: 'pending' as const })), issues: result.issues.map(question => ({ question, answer: '', confirmed: false })), stale: false } })
    } catch (e) { if (!abort.signal.aborted) setError(e instanceof Error ? e.message : String(e)) }
    finally { if (controller.current === abort) { controller.current = null; setBusy('') } }
  }
  async function parse() {
    if (pending || (!manual && general.stale)) return
    const abort = new AbortController(); controller.current = abort
    setBusy('正在检查连接、参数与分析设置…'); setError('')
    try {
      const parsed = await parseCircuit(connections, abort.signal)
      const source = [draft.text, ...proposals.map(x => `已接受的建议：${x.title}\n${x.detail}\n依据：${x.reason}`), ...issues.map(x => `待确认：${x.question}\n补充：${x.answer}`)].filter(Boolean).join('\n\n')
      const preview = { ...parsed, task: { ...parsed.task, title: manual && connections.trim().startsWith('{') ? circuitTitle(parsed.task) : general.title?.trim() || circuitTitle(parsed.task), ...(source ? { question: source.slice(0, 50000) } : {}) } }
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
    {offline && <div className="note warn">后端暂未连接。你可以先准备题目，连接后端后再检查电路并运行仿真。</div>}
    <div className="card input-card">
      <div className="section-heading"><div><h2>把电路问题交给工作台</h2><p className="sub">用自己的话说想做什么。AI 补出候选方案，你来判断是否采用。</p></div><span className="subtle-tag">AI 建议 · 你来决定</span></div>
      {mosDefault && /M\d|nmos|pmos|nch|pch/i.test((draft.text || '') + ' ' + connections) && <div className="note info">NMOS/PMOS 题目默认使用 CMN018 工艺模型（{String((capabilities as { default_models?: { nmos?: string } }).default_models?.nmos)}/{String((capabilities as { default_models?: { pmos?: string } }).default_models?.pmos)}）。请先在「仿真服务器 → 高级设置」配置 CMN018 主模型文件路径，未配置时仿真预检会失败；教学近似可显式指定 generic_nmos / generic_pmos。</div>}
      <div className="input-methods" aria-label="输入方式">{([['text', '文字描述', 'file'], ['image', '电路截图', 'image'], ['connections', '连接描述', 'circuit']] as const).map(([id, label, icon]) => <button key={id} aria-pressed={general.input === id} disabled={locked} onClick={() => change({ input: id, stale: id !== general.input && id !== 'connections' && hasCandidate ? true : general.stale })}><Icon name={icon} />{label}</button>)}</div>
      {!manual && <>
        {general.input === 'image' && <div className="source-upload">
          <input ref={fileInput} type="file" aria-label="通用电路截图" accept="image/png,image/jpeg" hidden disabled={locked} onChange={e => { pickFile(e.target.files?.[0]); e.target.value = '' }} />
          {draft.image ? <div className="source-attachment"><button className="source-thumb" aria-label="放大原图" onClick={() => setZoom(true)}><img src={draft.image.dataUrl} alt="电路原图" /></button><div><strong>{draft.image.name}</strong><p className="muted small">点击图片放大，核对标注与连线。</p><div className="btnrow"><button className="text-button" disabled={locked} onClick={() => fileInput.current?.click()}>更换图片</button><button className="text-button" disabled={locked} onClick={() => onDraftChange({ ...draft, image: undefined, general: { ...general, stale: hasCandidate } })}>移除图片</button></div></div></div> : <button className="upload-area" disabled={locked} onClick={() => fileInput.current?.click()}><Icon name="image" /><strong>选择电路图或题目截图</strong><span>PNG / JPEG，最大 8 MB</span></button>}
        </div>}
        <label className="field-label" htmlFor="general-question">{general.input === 'image' ? '补充题目与分析要求' : '题目描述'}</label>
        <textarea id="general-question" className="question-editor" value={draft.text} disabled={locked} placeholder={TEXT_EXAMPLE} onChange={e => onDraftChange({ ...draft, text: e.target.value, general: { ...general, stale: hasCandidate } })} />
        <div className="composer-footer"><button className="text-button" disabled={locked} onClick={() => onDraftChange({ ...draft, text: TEXT_EXAMPLE, general: { ...general, stale: hasCandidate } })}>试试文字示例</button><span>不必填写节点名或连接表</span></div>
        <div className="recognize-row"><button className="btn" disabled={locked || (general.input === 'image' ? !draft.image : !draft.text.trim())} onClick={recognize}>{hasCandidate ? rejected ? '换一个方案' : '根据补充重新整理' : general.input === 'image' ? '识别元件与连接' : '生成建议方案'}</button><button className="btn ghost" disabled={locked} onClick={onOpenOcrSettings}><Icon name="settings" />AI 识别设置</button></div>
        <p className="muted small">识别会将题目{general.input === 'image' ? '和图片' : ''}发送给你配置的 AI 服务。结果需要核对。</p>
      </>}
      {manual && <div className="manual-intro"><p className="sub">已有连接描述或完整电路 JSON，可以直接检查；也可以从示例开始。</p><label className="field-label">电路示例 <select aria-label="通用电路示例" disabled={locked} value={selectedExample} onChange={e => { const x = examples.find(x => x.id === e.target.value); if (x) onDraftChange({ text: '', mode: 'general', general: { input: 'connections', title: x.label, connections: x.text, exampleId: x.id } }) }}><option value="" disabled>选择一个示例</option>{examples.map(x => <option key={x.id} value={x.id}>{x.label}</option>)}</select></label></div>}
    </div>
    {(hasCandidate || manual) && <div className="card extraction-card">
      <div className="section-heading"><h2>候选电路方案</h2><span className={`subtle-tag ${pending ? 'amber' : ''}`}>{pending ? `${pending} 项待确认` : '等待预检'}</span></div>
      {general.summary && <p className="sub">{general.summary}</p>}
      {general.stale && !manual && <div className="note warn">原题或输入方式已修改，请重新整理电路后继续。</div>}
      {!!proposals.length && <div className="proposal-list"><h3>这些建议符合你的意思吗？</h3><p className="muted small">推测的连接与参数已放入候选方案。全部确认后，才进入电路核对。</p>{proposals.map((proposal, i) => <article className={`proposal-card ${proposal.decision}`} key={proposal.id}><div className="issue-title"><span>{i + 1}</span><strong>{proposal.title}</strong></div><p>{proposal.detail}</p>{proposal.reason && <p className="proposal-reason">建议依据：{proposal.reason}</p>}<div className="proposal-actions" role="group" aria-label={proposal.title}><button className="btn ghost" aria-pressed={proposal.decision === 'yes'} disabled={locked} onClick={() => change({ proposals: proposals.map((x, n) => n === i ? { ...x, decision: 'yes' } : x) })}>是，采用</button><button className="btn ghost" aria-pressed={proposal.decision === 'no'} disabled={locked} onClick={() => change({ proposals: proposals.map((x, n) => n === i ? { ...x, decision: 'no' } : x) })}>否，换个方案</button></div></article>)}</div>}
      {rejected && <div className="note info">你已否决部分建议。可以补充一句想法，或直接让 AI 换个方案。<button className="btn ghost" disabled={locked} onClick={recognize}>重新提出方案</button></div>}
      {!!issues.length && <div className="issue-list"><h3>还需要了解的情况</h3><p className="muted small">可以用普通语言补充，也可以让 AI 提出具体建议，不需要你改写连接表。</p>{issues.map((issue, i) => <div className="issue-item" key={i}><div className="issue-title"><span>{i + 1}</span><strong>{issue.question}</strong></div><input aria-label={`问题 ${i + 1} 的补充`} placeholder="可选：补充一句你的想法，或让 AI 先给建议" disabled={locked} value={issue.answer} onChange={e => change({ issues: issues.map((x, n) => n === i ? { ...x, answer: e.target.value, confirmed: false } : x) })} />{manual && <label className="issue-check"><input type="checkbox" disabled={locked || !issue.answer.trim()} checked={issue.confirmed} onChange={e => change({ issues: issues.map((x, n) => n === i ? { ...x, confirmed: e.target.checked } : x) })} />已手动修正连接描述</label>}</div>)}<button className="btn ghost" disabled={locked} onClick={recognize}>请 AI 补全并提出建议</button></div>}
      <details className="candidate-code" open={manual || undefined}><summary>高级：查看或手动编辑连接描述</summary>
      <label className="field-label" htmlFor="connection-description">元件连接与分析设置</label><textarea id="connection-description" aria-label="电路连接描述" className="general-editor" disabled={locked} value={connections} onChange={e => change({ connections: e.target.value, exampleId: undefined, title: undefined, issues: issues.map(x => ({ ...x, confirmed: false })), proposals: proposals.map(x => ({ ...x, decision: 'pending' })) })} placeholder={'V1 vin 0 DC 5\nR1 vin out 1k\nR2 out 0 2k\n.op\n.save V(out) I(R1)'} />
      <details className="format-help"><summary>查看连接描述格式</summary><p>每行一个元件：R / C / L 编号后依次填写两个节点及数值；D 填阳极、阴极；U 填同相、反相、输出；W 填相连节点。受控开关：S1 通路正端 通路负端 控制正端 控制负端 [断开阈值 闭合阈值 断开电阻 闭合电阻]。例如 S1 out 0 clk 0 0.2 0.8 1e12 1m；周期 100 ns 的 PULSE 电压源可驱动 10 MHz 开关。地写 0，数值可用 k、m、u、n、p 前缀。</p><p>晶体管：Q1 集电极 基极 发射极 generic_npn（或 generic_pnp）；M1 漏极 栅极 源极 衬底 w=10u l=0.18u（NMOS/PMOS 缺省用 CMN018 工艺模型 nch/pch，需在服务器高级设置配置模型文件；教学近似可显式写 generic_nmos/generic_pmos）。CMN018 模型先用 .model mn cmn018 nch 声明，再在 M1 行使用 mn；.corner tt 可选 tt、ss、ff。运行 CMN018 前须在仿真服务器高级设置中填写模型文件路径。</p><p>受控源：G / E 编号后填写输出正、输出负、控制正、控制负、增益；F / H 后填写输出正、输出负、控制电压源编号、增益。</p><p>电源：V1 正节点 负节点 DC 值；或 SINE 偏置 幅度 频率；或 PULSE 低 高 延迟 上升 下降 脉宽 周期。电流源以 I 开头，末尾可加 AC 幅度 相位。</p><p>分析：.op；.ac 起始Hz 终止Hz 每十倍频点数；.tran 终点秒 最大步长秒；.dc 源编号 起始 终止 步长。保存：.save V(out) I(Q1,c) P(Q1,region)。扫描：.step VG dc -1 -2 -3。二端口：.twoport V1 V2 1k。完整设置也可使用 JSON；示例涵盖转移分析和曲线比较。</p></details></details>
    </div>}
    {capabilityError && <div className="note warn">{capabilityError}</div>}{error && <div className="note err" role="alert">{error}{hasCandidate && !manual && <button className="btn ghost" disabled={locked} onClick={recognize}>让 AI 修正方案</button>}</div>}
    <footer className="actionbar"><span className="action-status" role="status">{(busy ? `${busy} 已等待 ${elapsed} 秒${elapsed >= 30 ? '，模型仍在处理，可取消并保留输入' : ''}` : '') || (pending ? `请先处理 ${pending} 项待确认问题` : '预检通过后，仍需确认才会运行仿真')}</span><div className="actions">{locked && <button className="btn ghost" onClick={cancel}>取消处理</button>}<button className="btn" disabled={disabled || offline || locked || !connections.trim() || !!pending || (!manual && general.stale)} onClick={parse}>{manual ? '解析并检查电路' : '采用方案并核对'}<Icon name="arrow" /></button></div></footer>
    {zoom && draft.image && <Modal title="电路原图" onClose={() => setZoom(false)} wide><img className="zoom-image" src={draft.image.dataUrl} alt="电路原图" /></Modal>}
  </section>
}
