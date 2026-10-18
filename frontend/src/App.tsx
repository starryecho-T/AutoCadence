import { useCallback, useEffect, useRef, useState } from 'react'
import type { HealthInfo, ParseResult, RunRecord, TaskSpec } from './types'
import { getHealth, getRun, listRuns, postRun, demoRunGet, isDemoMode } from './api'
import TaskInput from './components/TaskInput'
import ConfirmPanel from './components/ConfirmPanel'
import RunProgress from './components/RunProgress'
import ResultView from './components/ResultView'
import OcrSettings from './components/OcrSettings'

type Phase = 'input' | 'confirm' | 'running' | 'result'

interface HistoryEntry {
  run: RunRecord
  time: string
}

const POLL_MS = 1500

export default function App() {
  const [health, setHealth] = useState<HealthInfo | null>(null)
  const [phase, setPhase] = useState<Phase>('input')
  const [submitting, setSubmitting] = useState(false)
  const [parse, setParse] = useState<ParseResult | null>(null)
  const [sourceText, setSourceText] = useState('')
  const [run, setRun] = useState<RunRecord | null>(null)
  const [history, setHistory] = useState<HistoryEntry[]>([])
  const [showOcrSettings, setShowOcrSettings] = useState(false)
  const timerRef = useRef<number | null>(null)
  const demoStartRef = useRef<number>(0)

  /* 启动时健康检查 + 拉取历史 */
  useEffect(() => {
    getHealth().then(async (h) => {
      setHealth(h)
      if (!h.demo) setHistory((await listRuns()).map((r) => ({ run: r, time: r.created_at ?? '' })))
    })
  }, [])

  /* 轮询：终态停止 */
  const startPolling = useCallback((runId: string, demo: boolean) => {
    if (timerRef.current) window.clearInterval(timerRef.current)
    const started = demo ? demoStartRef.current : 0
    timerRef.current = window.setInterval(async () => {
      try {
        const r = demo
          ? demoRunGet(runId, Date.now() - started)
          : await getRun(runId)
        setRun(r)
        if (r.status === 'succeeded' || r.status === 'failed') {
          if (timerRef.current) window.clearInterval(timerRef.current)
          timerRef.current = null
          setPhase('result')
          // 计入本地历史；真实模式再从后端拉全量列表
          if (demo) {
            setHistory((h) => [{ run: r, time: r.created_at ?? '' }, ...h.filter((x) => x.run.run_id !== r.run_id)].slice(0, 10))
          } else {
            listRuns().then((runs) => setHistory(runs.map((x) => ({ run: x, time: x.created_at ?? '' })))).catch(() => {})
          }
        }
      } catch (e) {
        if (timerRef.current) window.clearInterval(timerRef.current)
        timerRef.current = null
        setRun({
          run_id: runId, status: 'failed',
          error: { code: 'POLL_ERROR', message: e instanceof Error ? e.message : String(e) }
        })
        setPhase('result')
      }
    }, POLL_MS)
  }, [])

  useEffect(() => () => { if (timerRef.current) window.clearInterval(timerRef.current) }, [])

  async function handleParsed(text: string, result: ParseResult) {
    setSourceText(text)
    setParse(result)
    setPhase('confirm')
  }

  async function handleSubmit(task: TaskSpec) {
    setSubmitting(true)
    try {
      const demo = isDemoMode()
      const runId = await postRun(task)
      demoStartRef.current = Date.now()
      const seedRun: RunRecord = {
        run_id: runId, status: 'queued',
        task, stages: [{ name: '已提交，排队中', status: 'pending' }], demo
      }
      setRun(seedRun)
      // 提交后立即计入历史（真实模式待轮询终态时再从后端刷新）
      setHistory((h) => [{ run: seedRun, time: new Date().toISOString() }, ...h.filter((x) => x.run.run_id !== runId)].slice(0, 10))
      setPhase('running')
      startPolling(runId, demo)
    } catch (e) {
      setRun({
        run_id: '—', status: 'failed',
        error: { code: 'SUBMIT_ERROR', message: e instanceof Error ? e.message : String(e) }
      })
      setPhase('result')
    } finally {
      setSubmitting(false)
    }
  }

  function restart() {
    if (timerRef.current) window.clearInterval(timerRef.current)
    timerRef.current = null
    setRun(null); setParse(null); setSourceText(''); setPhase('input')
  }

  const demo = health?.demo === true

  return (
    <div className="app">
      <header className="topbar">
        <div className="logo">⚡</div>
        <h1>电路仿真助手</h1>
        <span style={{ color: 'var(--ink-soft)', fontSize: 13 }}>RC 低通 · 自动仿真与截图</span>
        <div className="spacer" />
        {health === null
          ? <span className="status-chip">连接后端中…</span>
          : demo
            ? <span className="status-chip demo">演示模式（后端未连接）</span>
            : <span className="status-chip ok">后端在线{health.version ? ` · ${health.version}` : ''}{health.queue !== undefined ? ` · 队列 ${health.queue}` : ''}</span>}
      </header>

      {phase === 'input' && <TaskInput onParsed={handleParsed} onOpenOcrSettings={() => setShowOcrSettings(true)} />}

      {phase === 'confirm' && parse && (
        <ConfirmPanel parse={parse} sourceText={sourceText} busy={submitting} onConfirm={handleSubmit} onBack={() => setPhase('input')} />
      )}

      {phase === 'running' && run && <RunProgress run={run} />}

      {phase === 'result' && run && <ResultView run={run} onRestart={restart} />}

      {history.length > 0 && (
        <div className="card">
          <h2>最近任务</h2>
          <div className="sub">点击可查看该次运行的结果（仅 succeeded 的任务有截图）</div>
          {history.map(({ run: r }) => (
            <div className="history-item" key={r.run_id} onClick={() => { setRun(r); setPhase(r.status === 'succeeded' || r.status === 'failed' ? 'result' : 'running'); if (r.status === 'queued' || r.status === 'running') startPolling(r.run_id, r.demo === true) }}>
              <span className={`badge ${r.status}`}>{r.status}</span>
              <span className="rid">{r.run_id}</span>
              <span style={{ marginLeft: 'auto', fontSize: 12.5, color: 'var(--ink-soft)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 340 }}>
                {summarizeParams(r.task?.params)}
              </span>
            </div>
          ))}
        </div>
      )}
      {showOcrSettings && <OcrSettings onClose={() => setShowOcrSettings(false)} />}
    </div>
  )
}

/** 参数摘要：任意参数键值对 → "r_ohm=1k c_farad=100n"（最多 4 项，超出显示 +N） */
function summarizeParams(p: Record<string, number | string> | undefined): string {
  if (!p || Object.keys(p).length === 0) return ''
  const entries = Object.entries(p).slice(0, 4)
  const rest = Object.keys(p).length - entries.length
  const s = entries.map(([k, v]) => `${k}=${fmt(v)}`).join(' ')
  return rest > 0 ? s + ` +${rest}` : s
}

function fmt(v: number | string | undefined): string {
  if (v === undefined) return ''
  if (typeof v === 'string') return v
  if (Math.abs(v) >= 1e3 || (Math.abs(v) < 1e-2 && v !== 0)) return v.toExponential(2)
  return String(v)
}
