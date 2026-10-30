import { useCallback, useEffect, useRef, useState } from 'react'
import type { HealthInfo, ParseResult, RunRecord, TaskDraft, TaskSpec } from './types'
import { getHealth, getRun, listRuns, postRun, demoRunGet, isDemoMode, retainDemoRuns, previewCircuit } from './api'
import { engineering } from './units'
import Icon from './components/Icon'
import Modal from './components/Modal'
import { pollSequentially } from './polling'
import TaskInput from './components/TaskInput'
import ConfirmPanel from './components/ConfirmPanel'
import RunProgress from './components/RunProgress'
import ResultView from './components/ResultView'
import OcrSettings from './components/OcrSettings'
import ConnectionSettings from './components/ConnectionSettings'

type Phase = 'input' | 'confirm' | 'running' | 'result'
const STATUS_LABELS = { queued: '排队中', running: '进行中', succeeded: '已完成', failed: '失败' }
const message = (error: unknown) => error instanceof Error ? error.message : String(error)

function mergeRuns(incoming: RunRecord[], current: RunRecord[]) {
  const ids = new Set(incoming.map((item) => item.run_id))
  return [...incoming, ...current.filter((item) => !ids.has(item.run_id))].slice(0, 20)
}

export default function App() {
  const [health, setHealth] = useState<HealthInfo | null>(null)
  const [connectionAttempt, setConnectionAttempt] = useState(0)
  const [phase, setPhase] = useState<Phase>('input')
  const [submitting, setSubmitting] = useState(false)
  const [inputBusy, setInputBusy] = useState(false)
  const [showHistory, setShowHistory] = useState(false)
  const [parse, setParse] = useState<ParseResult | null>(null)
  const [draft, setDraft] = useState<TaskDraft>({ text: '', mode: 'general' })
  const [run, setRun] = useState<RunRecord | null>(null)
  const [history, setHistory] = useState<RunRecord[]>([])
  const [notice, setNotice] = useState('')
  const [pollError, setPollError] = useState('')
  const [showOcrSettings, setShowOcrSettings] = useState(false)
  const [showConnectionSettings, setShowConnectionSettings] = useState(false)
  const editController = useRef<AbortController | null>(null)
  useEffect(() => () => editController.current?.abort(), [])
  const stopPollingRef = useRef<(() => void) | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    setHealth(null)
    setNotice('')
    void getHealth(controller.signal).then(async (info) => {
      if (controller.signal.aborted) return
      setHealth(info)
      if (!info.demo) {
        const runs = await listRuns(controller.signal)
        if (!controller.signal.aborted) setHistory((current) => mergeRuns(runs, current))
      }
    }).catch((error) => {
      if (!controller.signal.aborted) setNotice('加载历史任务失败：' + message(error))
    })
    return () => controller.abort()
  }, [connectionAttempt])

  const stopPolling = useCallback(() => {
    stopPollingRef.current?.()
    stopPollingRef.current = null
  }, [])
  useEffect(() => stopPolling, [stopPolling])

  const startPolling = useCallback((selected: RunRecord) => {
    stopPolling()
    setPollError('')
    stopPollingRef.current = pollSequentially({
      read: async (signal) => selected.demo ? demoRunGet(selected.run_id) : getRun(selected.run_id, signal),
      intervalMs: 1500,
      isDone: (value) => value.status === 'succeeded' || value.status === 'failed',
      onValue: (value) => {
        const latest = { ...value, task: value.task ?? selected.task, created_at: value.created_at ?? selected.created_at }
        setRun(latest)
        setHistory((current) => mergeRuns([latest], current))
        if (latest.status === 'succeeded' || latest.status === 'failed') setPhase('result')
      },
      onError: (error) => setPollError(message(error))
    })
  }, [stopPolling])

  useEffect(() => {
    retainDemoRuns([...history.filter((item) => item.demo).map((item) => item.run_id), ...(run?.demo ? [run.run_id] : [])])
  }, [history, run])

  function handleParsed(_text: string, result: ParseResult) {
    setInputBusy(false)
    setParse(result)
    setPhase('confirm')
  }

  async function handleSubmit(task: TaskSpec) {
    if (health?.connectionConfigured === false) { setShowConnectionSettings(true); return }
    setSubmitting(true)
    setNotice('')
    try {
      const demo = isDemoMode()
      const runId = await postRun(task)
      const selected: RunRecord = {
        run_id: runId, status: 'queued', task, demo,
        created_at: new Date().toISOString(), stages: [{ name: '已提交，排队中', status: 'pending' }]
      }
      setRun(selected)
      setHistory((current) => mergeRuns([selected], current))
      setPhase('running')
      startPolling(selected)
    } catch (error) {
      setNotice('提交失败：' + message(error) + '。参数已保留，可重试。')
    } finally {
      setSubmitting(false)
    }
  }

  function restart() {
    editController.current?.abort()
    stopPolling()
    setPollError('')
    setRun(null)
    setParse(null)
    setDraft({ text: '', mode: 'general' })
    setNotice('')
    setPhase('input')
  }

  function selectRun(selected: RunRecord) {
    editController.current?.abort()
    stopPolling()
    setPollError('')
    setNotice('')
    setRun(selected)
    setShowHistory(false)
    if (selected.status === 'queued' || selected.status === 'running') {
      setPhase('running')
      startPolling(selected)
    } else setPhase('result')
  }

  async function editRun() {
    if (!run?.task) return
    stopPolling()
    if (run.task.circuit) {
      editController.current?.abort()
      const abort = new AbortController(); editController.current = abort
      try {
        const circuitPreview = await previewCircuit(run.task.circuit, abort.signal)
        if (abort.signal.aborted) return
        setParse({ ok: true, task: run.task, circuitPreview })
        setDraft({ text: typeof run.task.circuit.question === 'string' ? run.task.circuit.question : '', mode: 'general', general: { input: 'connections', connections: JSON.stringify(run.task.circuit, null, 2) } })
        setNotice(''); setPhase('confirm')
      } catch (e) { if (!abort.signal.aborted) setNotice('加载电路失败：' + message(e)) }
      return
    }
    setParse({ ok: true, task: run.task })
    setDraft({ text: run.task.source_text ?? '', mode: 'general' })
    setNotice('')
    setPhase('confirm')
  }
  const demo = health?.demo === true
  const general = phase === 'input' || (phase === 'confirm' ? !!parse?.circuitPreview : !!run?.task?.circuit)
  const locked = submitting || inputBusy
  const currentStep = phase === 'input' ? 0 : phase === 'confirm' ? 1 : 2
  const headings = {
    input: ['从电路题目开始', '描述电路与验证目标，或添加一张题目截图。'],
    confirm: ['确认电路参数', '核对元件与输入信号，准备好后开始仿真。'],
    running: ['运行进度', '正在处理你的电路，完成后会自动展示结果。'],
    result: ['仿真结果', '先看关键结论，再查看截图、指标与原始文件。'],
  }
  function historyItems() {
    return history.length ? history.map(item => <button className={`history-item ${item.run_id === run?.run_id && (phase === 'result' || phase === 'running') ? 'selected' : ''}`}
      key={item.run_id} data-run-id={item.run_id} title={item.run_id} disabled={locked || !health} onClick={() => selectRun(item)}>
      <Icon name="history" /><span className="history-copy"><strong>{item.demo ? '演示 · ' : ''}{item.task?.title || 'RC 低通滤波器'}</strong>
        <span className="history-summary">{item.task?.circuit ? `${item.task.circuit.components.length} 个元件 · ${item.task.circuit.analyses.map(a => ({ op: '工作点', dc: '直流扫描', ac: '频响', tran: '瞬态' }[a.type] || a.type)).join(' / ')}` : summarizeParams(item.task?.params)}</span>
        <span className="history-meta"><span className={`status-text ${item.status}`}>{STATUS_LABELS[item.status]}</span>{item.created_at && <time dateTime={item.created_at}>{new Date(item.created_at).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</time>}</span>
      </span>
    </button>) : <p className="history-empty">完成第一次仿真后，<br />可以在这里再次查看。</p>
  }
  return <div className="app-shell">
    <aside className="sidebar" aria-label="工作台导航">
      <div className="brand"><div className="brand-mark"><Icon name="circuit" /></div><div>AutoCadence<small>电路设计与仿真</small></div></div>
      <button className="new-task" disabled={locked} onClick={restart}><Icon name="plus" />新建仿真</button>
      <div className="sidebar-label">最近任务 <span>{history.length || ''}</span></div>
      <div className="history-list">{historyItems()}</div>
      <div className="sidebar-footer"><button className="sidebar-action" disabled={locked || phase === 'running'} onClick={() => setShowConnectionSettings(true)}><Icon name="circuit" />仿真服务器</button><button className="sidebar-action" onClick={() => setShowOcrSettings(true)}><Icon name="settings" />AI 设置</button>
        <button className="sidebar-action" disabled={!health || phase === 'running' || locked} onClick={() => setConnectionAttempt(value => value + 1)}><Icon name="refresh" />重新连接</button>
        <span className="sidebar-caption">通用模拟电路 · AutoCadence 0.7.4</span>
      </div>
    </aside>
    <div className="app-main">
      <header className="topbar"><div className="breadcrumb"><span>工作台</span><span className="separator">/</span><strong>{general ? '通用电路' : 'RC 低通滤波器'}</strong></div>
        <div className="topbar-actions"><button className="icon-button mobile-only" aria-label="最近任务" onClick={() => setShowHistory(true)}><Icon name="history" /></button>
          <button className="icon-button mobile-only" aria-label="设置" onClick={() => setShowOcrSettings(true)}><Icon name="settings" /></button>
          <button className="icon-button mobile-only" aria-label="仿真服务器" disabled={locked || phase === 'running'} onClick={() => setShowConnectionSettings(true)}><Icon name="circuit" /></button>
          {health === null ? <span className="status-chip">连接中…</span> : demo ? <span className="status-chip demo">后端未连接</span> : <span className="status-chip ok" title={health.version ? `服务版本 ${health.version}` : undefined}>后端在线{Number(health.queue) > 0 ? ` · 排队 ${health.queue}` : ''}</span>}
        </div>
      </header>
      <main className="workspace"><header className="page-heading"><div><h1>{headings[phase][0]}</h1><p>{headings[phase][1]}</p></div><span className="type-badge">{general ? '通用电路 · 晶体管 · 二端口' : '一阶 RC 低通'}</span></header>
        {health?.connectionConfigured === false && <div className="note info connection-setup"><span>先连接你的仿真服务器，再开始运行电路。</span><button className="btn ghost" onClick={() => setShowConnectionSettings(true)}>配置服务器</button></div>}
        <nav className="steps" aria-label="仿真步骤">{['输入题目', '确认参数', '仿真与结果'].map((label, index) => <div key={label} className={`step ${index === currentStep ? 'active' : index < currentStep ? 'done' : ''}`} aria-current={index === currentStep ? 'step' : undefined}>
          <span className="step-number">{index < currentStep ? <Icon name="check" /> : index + 1}</span><span>{label}</span>{index < 2 && <span className="step-line" />}
        </div>)}</nav>
        {notice && <div className="note err" role="alert">{notice}</div>}
        {phase === 'input' && <TaskInput draft={draft} onDraftChange={setDraft} disabled={!health} onParsed={handleParsed} onOpenOcrSettings={() => setShowOcrSettings(true)} onBusyChange={setInputBusy} />}
        {phase === 'confirm' && parse && <ConfirmPanel parse={parse} draft={draft} sourceText={draft.text}
          onCircuitEdit={raw => setDraft(current => ({ ...current, general: { ...current.general, input: 'connections', connections: raw, stale: false } }))}
          onPreviewChange={preview => setParse(current => current ? { ...current, circuitPreview: preview } : current)} busy={submitting} onConfirm={handleSubmit}
          onTaskChange={task => setParse(current => current ? { ...current, task } : current)} onBack={() => { setNotice(''); setPhase('input') }} />}
        {phase === 'running' && run && <>
          <RunProgress run={run} />
          {pollError && <div className="note err" role="alert">暂时无法获取进度，正在自动重试（最多 3 次，间隔逐步加长）；若持续失败，请重新查询。任务可能仍在运行。<details><summary>查看连接详情</summary>{pollError}</details><button className="btn ghost" onClick={() => startPolling(run)}>重新查询进度</button></div>}
          <div className="actionbar"><span className="muted small">切换页面后，可从最近任务继续查看</span><button className="btn ghost" onClick={restart}>新建仿真</button></div>
        </>}
        {phase === 'result' && run && <ResultView key={run.run_id} run={run} onRestart={restart} onEdit={run.task ? editRun : undefined} />}
        {phase === 'input' && demo && <div className="note warn">本地仿真服务暂未连接，请重新打开 AutoCadence，或启动已有后端后重新连接。<button className="text-button mobile-only" onClick={() => setConnectionAttempt(value => value + 1)}>重新连接</button></div>}
      </main>
    </div>
    {showHistory && <Modal title="最近任务" onClose={() => setShowHistory(false)}><button className="btn ghost" disabled={locked} onClick={() => { setShowHistory(false); restart() }}><Icon name="plus" />新建仿真</button>{historyItems()}</Modal>}
    {showOcrSettings && <OcrSettings onClose={() => setShowOcrSettings(false)} />}
    {showConnectionSettings && <ConnectionSettings onClose={() => setShowConnectionSettings(false)} onSaved={() => setConnectionAttempt(value => value + 1)} />}
  </div>
}

function summarizeParams(params: TaskSpec['params']): string {
  if (!params) return '查看运行记录'
  return ([['r_ohm', 'resistance'], ['c_farad', 'capacitance']] as const).flatMap(([key, dimension]) => {
    const value = params[key]
    if (typeof value !== 'number') return []
    const formatted = engineering(value, dimension)
    return `${formatted.value} ${formatted.unit}`
  }).join(' · ')
}
