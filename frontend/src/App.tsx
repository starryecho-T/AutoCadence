import { useCallback, useEffect, useRef, useState } from 'react'
import type { HealthInfo, ParseResult, RunRecord, TaskDraft, TaskSpec } from './types'
import { getHealth, getRun, listRuns, postRun, demoRunGet, isDemoMode, retainDemoRuns } from './api'
import { formatNumber } from './circuit'
import { pollSequentially } from './polling'
import TaskInput from './components/TaskInput'
import ConfirmPanel from './components/ConfirmPanel'
import RunProgress from './components/RunProgress'
import ResultView from './components/ResultView'
import OcrSettings from './components/OcrSettings'

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
  const [parse, setParse] = useState<ParseResult | null>(null)
  const [draft, setDraft] = useState<TaskDraft>({ text: '' })
  const [run, setRun] = useState<RunRecord | null>(null)
  const [history, setHistory] = useState<RunRecord[]>([])
  const [notice, setNotice] = useState('')
  const [pollError, setPollError] = useState('')
  const [showOcrSettings, setShowOcrSettings] = useState(false)
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
    setParse(result)
    setPhase('confirm')
  }

  async function handleSubmit(task: TaskSpec) {
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
    stopPolling()
    setPollError('')
    setRun(null)
    setParse(null)
    setDraft({ text: '' })
    setNotice('')
    setPhase('input')
  }

  function selectRun(selected: RunRecord) {
    stopPolling()
    setPollError('')
    setNotice('')
    setRun(selected)
    if (selected.status === 'queued' || selected.status === 'running') {
      setPhase('running')
      startPolling(selected)
    } else setPhase('result')
  }

  const demo = health?.demo === true
  return (
    <div className="app">
      <header className="topbar">
        <div className="logo">⚡</div>
        <h1>电路仿真助手</h1>
        <span className="tagline">RC 低通 · 自动仿真与截图</span>
        <div className="spacer" />
        {health === null ? <span className="status-chip">连接后端中…</span>
          : demo ? <span className="status-chip demo">演示模式（后端未连接）</span>
          : <span className="status-chip ok">后端在线{health.version ? ` · ${health.version}` : ''}{health.queue !== undefined ? ` · 队列 ${health.queue}` : ''}</span>}
        {phase === 'input' && <button className="btn ghost" disabled={!health} onClick={() => setConnectionAttempt((value) => value + 1)}>重新连接</button>}
      </header>

      {notice && <div className="note err" role="alert">{notice}</div>}
      {phase === 'input' && <TaskInput draft={draft} onDraftChange={setDraft} disabled={!health} onParsed={handleParsed} onOpenOcrSettings={() => setShowOcrSettings(true)} />}
      {phase === 'confirm' && parse && <ConfirmPanel parse={parse} sourceText={draft.text} busy={submitting} onConfirm={handleSubmit} onBack={() => { setNotice(''); setPhase('input') }} />}
      {phase === 'running' && run && (
        <>
          <RunProgress run={run} />
          {pollError && <div className="note err" role="alert">
            进度查询中断：{pollError}。任务可能仍在后端运行。
            <div className="btnrow"><button className="btn" onClick={() => startPolling(run)}>重新查询进度</button></div>
          </div>}
          <div className="btnrow"><button className="btn ghost" onClick={restart}>返回输入新题目</button></div>
        </>
      )}
      {phase === 'result' && run && <ResultView run={run} onRestart={restart} />}

      {history.length > 0 && <div className="card">
        <h2>最近任务</h2>
        <div className="sub">点击查看进度或结果；演示任务保留在当前页面会话中</div>
        {history.map((item) => <button className="history-item" key={item.run_id} disabled={submitting || !health} onClick={() => selectRun(item)}>
          <span className={`badge ${item.status}`}>{STATUS_LABELS[item.status]}</span>
          <span className="rid">{item.demo ? '演示 · ' : ''}{item.run_id}</span>
          <span className="history-summary">{summarizeParams(item.task?.params)}</span>
          {item.created_at && <time dateTime={item.created_at}>{new Date(item.created_at).toLocaleString('zh-CN')}</time>}
        </button>)}
      </div>}
      {showOcrSettings && <OcrSettings onClose={() => setShowOcrSettings(false)} />}
    </div>
  )
}

function summarizeParams(params: TaskSpec['params']): string {
  if (!params) return ''
  return Object.entries(params).slice(0, 4).map(([key, value]) => `${key}=${typeof value === 'number' ? formatNumber(value) : value}`).join(' · ')
}
