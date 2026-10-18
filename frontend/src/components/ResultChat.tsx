import { useEffect, useRef, useState } from 'react'
import type { RunRecord } from '../types'
import { askSimulation, loadOcrConfig, type ResultMessage } from '../ocr'
import Icon from './Icon'
import OcrSettings from './OcrSettings'

interface Evidence { run_id: string; context: string; files_read: string[]; series_count: number; omitted: string[]; sampled: boolean }
const storageKey = (id: string) => `autocadence-result-chat:${id}`
function answerText(text: string) {
  return text.split(/(\*\*[^*\n]+\*\*|`[^`\n]+`)/g).map((part, index) => part.startsWith('**') ? <strong key={index}>{part.slice(2, -2)}</strong> : part.startsWith('`') ? <code key={index}>{part.slice(1, -1)}</code> : part)
}
function readHistory(id: string): ResultMessage[] {
  try {
    const value = JSON.parse(sessionStorage.getItem(storageKey(id)) || '[]')
    return Array.isArray(value) ? value.filter(m => ['user', 'assistant'].includes(m?.role) && typeof m.content === 'string').slice(-24) : []
  } catch { return [] }
}

export default function ResultChat({ run }: { run: RunRecord }) {
  const [messages, setMessages] = useState<ResultMessage[]>(() => readHistory(run.run_id))
  const [draft, setDraft] = useState('')
  const [phase, setPhase] = useState('')
  const [error, setError] = useState('')
  const [settings, setSettings] = useState(false)
  const [evidence, setEvidence] = useState<Evidence | null>(null)
  const controller = useRef<AbortController | null>(null)
  const conversation = useRef<HTMLDivElement>(null)
  useEffect(() => () => { controller.current?.abort() }, [])
  useEffect(() => {
    try { sessionStorage.setItem(storageKey(run.run_id), JSON.stringify(messages.slice(-24))) } catch { /* A full store must not interrupt the conversation. */ }
    if (conversation.current) conversation.current.scrollTop = conversation.current.scrollHeight
  }, [messages, run.run_id])

  async function send() {
    const question = draft.trim()
    if (!question || controller.current) return
    const cfg = loadOcrConfig()
    if (!cfg) { setSettings(true); setError('请先配置 AI 服务，问题已保留。'); return }
    const ctrl = new AbortController()
    controller.current = ctrl
    setError(''); setPhase('正在读取本次仿真数据…')
    let contextTimer: ReturnType<typeof setTimeout> | undefined
    try {
      let source = evidence
      if (!source) {
        if (run.demo) {
          source = { run_id: run.run_id, context: JSON.stringify({ ...run, artifacts: undefined, warning: '这是本地演示，仅为理论计算，绝非真实仿真。' }), files_read: [], series_count: 0, omitted: [], sampled: false }
        } else {
          const contextCtrl = new AbortController()
          const abortContext = () => contextCtrl.abort()
          ctrl.signal.addEventListener('abort', abortContext, { once: true })
          contextTimer = setTimeout(() => contextCtrl.abort(), 30000)
          try {
            const response = await fetch(`/api/v2/runs/${encodeURIComponent(run.run_id)}/ai-context`, { signal: contextCtrl.signal })
            if (!response.ok) throw new Error(response.status === 404 ? '后端暂不支持结果问答，请启动新版 AutoCadence 后端。' : '本次数据暂时无法读取，请稍后重试。')
            source = await response.json() as Evidence
            if (source?.run_id !== run.run_id || typeof source.context !== 'string' || !Array.isArray(source.files_read) || !Array.isArray(source.omitted)) throw new Error('返回的数据与当前任务不一致，已停止发送。')
          } catch (e) {
            if (contextCtrl.signal.aborted && !ctrl.signal.aborted) throw new Error('读取本次数据超时，请检查后端连接后重试。')
            throw e
          } finally {
            clearTimeout(contextTimer); ctrl.signal.removeEventListener('abort', abortContext)
          }
        }
        if (ctrl.signal.aborted) return
        setEvidence(source)
      }
      setPhase('AI 正在分析…')
      const answer = await askSimulation(cfg, source.context, messages, question, ctrl.signal)
      if (!ctrl.signal.aborted) {
        setMessages(previous => [...previous, { role: 'user', content: question }, { role: 'assistant', content: answer }].slice(-24) as ResultMessage[])
        setDraft('')
      }
    } catch (e) {
      if (!ctrl.signal.aborted) setError(e instanceof Error ? e.message : 'AI 回答失败，请重试。')
    } finally {
      clearTimeout(contextTimer)
      if (controller.current === ctrl) { controller.current = null; setPhase('') }
    }
  }

  return <section className="card result-chat" aria-labelledby="result-chat-heading">
    <div className="section-heading"><div><h3 id="result-chat-heading">与 AI 讨论本次结果</h3><p className="sub">从波形、参数到失败原因，直接用自己的话提问。</p></div><div className="actions"><button className="btn ghost" onClick={() => setSettings(true)} disabled={!!phase}><Icon name="settings" />AI 设置</button>{!!messages.length && <button className="btn ghost" onClick={() => { setMessages([]); setError('') }} disabled={!!phase}>清空对话</button>}</div></div>
    <div className="chat-suggestions">{[run.status === 'failed' ? '这次为什么失败，是器件不支持吗？' : '请解释本次仿真的主要结论', '哪些参数最值得调整？', '结果是否满足设计目标？'].map(question => <button key={question} disabled={!!phase} onClick={() => setDraft(question)}>{question}</button>)}</div>
    {!!messages.length && <div className="chat-messages" role="log" aria-label="本次结果对话" ref={conversation}>{messages.map((message, index) => <div className={`chat-message ${message.role}`} key={index}><span>{message.role === 'user' ? '你' : 'AI · 结果分析'}</span><div>{message.role === 'assistant' ? answerText(message.content) : message.content}</div></div>)}</div>}
    {evidence && <p className="chat-evidence">{run.demo ? '当前依据：本地演示数据' : `当前依据：电路与指标、${evidence.series_count} 组曲线统计、${evidence.files_read.length} 个数据与日志文件`}{evidence.sampled && '；长曲线仅发送抽样点及完整数值统计。'}</p>}
    {!!evidence?.omitted.length && <details className="chat-evidence"><summary>部分数据未提供给 AI</summary><ul>{evidence.omitted.map((item, index) => <li key={index}>{item}</li>)}</ul></details>}
    <form onSubmit={event => { event.preventDefault(); void send() }}>
      <label className="sr-only" htmlFor="result-question">询问本次仿真结果</label>
      <textarea id="result-question" value={draft} onChange={event => setDraft(event.target.value)} placeholder="例如：输出幅度为什么变小了？这个电阻改为 10 kΩ 会怎样？" maxLength={4000} rows={3} disabled={!!phase}
        onKeyDown={event => { if (event.key === 'Enter' && !event.nativeEvent.isComposing && (event.ctrlKey || event.metaKey)) { event.preventDefault(); void send() } }} />
      <div className="chat-compose-footer"><span className="small muted">发送时，将本次电路、数值摘要及相关日志交给你配置的 AI。回答供核对。</span>{phase ? <button key="stop" type="button" className="btn secondary" onClick={event => { event.preventDefault(); controller.current?.abort() }}>停止回答</button> : <button key="send" type="submit" className="btn primary" disabled={!draft.trim()}>发送问题<Icon name="arrow" /></button>}</div>
    </form>
    {phase && <p className="chat-evidence" role="status">{phase}</p>}
    {error && <p className="note err" role="alert">{error}</p>}
    {settings && <OcrSettings onClose={() => setSettings(false)} />}
  </section>
}
