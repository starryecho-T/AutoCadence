import { useMemo, useState } from 'react'
import type { Artifact, RunRecord } from '../types'
import { artifactUrl } from '../api'

interface Props {
  run: RunRecord
  onRestart: () => void
}

function fmtVal(v: number | string | null | undefined): string {
  if (v === null || v === undefined || v === '') return '—'
  if (typeof v === 'number') {
    if (Math.abs(v) >= 1e4 || (Math.abs(v) < 1e-2 && v !== 0)) return v.toExponential(3)
    return String(Math.round(v * 10000) / 10000)
  }
  return v
}

function imgSrc(a: Artifact): string {
  return artifactUrl(a)
}

function kindLabel(kind: string): string {
  if (kind === 'schematic') return '原理图截图'
  if (kind === 'waveform') return '仿真结果截图'
  return '图片'
}

/** 展示单张截图（含点击放大） */
function Shot({ a }: { a: Artifact }) {
  const [zoom, setZoom] = useState(false)
  return (
    <div className="shot">
      <div className="shot-head">
        🖼 {a.label || kindLabel(a.kind)}
        <span style={{ marginLeft: 'auto', fontWeight: 400, fontSize: 12, color: 'var(--ink-soft)' }}>点击放大</span>
      </div>
      <img src={imgSrc(a)} alt={a.label || kindLabel(a.kind)} onClick={() => setZoom(true)} />
      {zoom && (
        <div className="lightbox" onClick={() => setZoom(false)}>
          <img src={imgSrc(a)} alt={a.label || kindLabel(a.kind)} />
        </div>
      )}
    </div>
  )
}

/** 第 4 步：结果 = 原理图截图 + 仿真结果截图 + 指标 + 报告链接；失败时展示错误与日志 */
export default function ResultView({ run, onRestart }: Props) {
  const arts = run.artifacts ?? []
  const sch = arts.find((a) => a.kind === 'schematic')
  const wav = arts.find((a) => a.kind === 'waveform')
  const reports = arts.filter((a) => a.kind.startsWith('report'))
  const others = arts.filter((a) => ['data', 'log', 'other'].includes(a.kind) && a.url)
  const log = arts.find((a) => a.kind === 'log' && a.url)
  const metrics = useMemo(() => Object.entries(run.metrics ?? {}), [run.metrics])

  if (run.status !== 'succeeded' && run.status !== 'failed') return null

  return (
    <div className="card fade-in">
      {run.status === 'succeeded' ? (
        <>
          <h2>
            <span className="stepno" style={{ background: 'var(--ok-bg)', color: 'var(--ok)' }}>✓</span>
            仿真完成 · 成果截图
          </h2>
          <div className="sub">
            run_id: <code>{run.run_id}</code>
            {run.demo && <span style={{ color: '#b8a27a' }}> · 演示数据（后端未连接，仅展示界面流程）</span>}
          </div>

          <div className="shots">
            {sch ? <Shot a={sch} /> : (
              <div className="shot"><div className="shot-head">🖼 原理图截图</div><div className="shot-empty">后端未返回原理图（schematic）产物</div></div>
            )}
            {wav ? <Shot a={wav} /> : (
              <div className="shot"><div className="shot-head">🖼 仿真结果截图</div><div className="shot-empty">后端未返回仿真波形（waveform）产物</div></div>
            )}
          </div>

          {metrics.length > 0 && (
            <>
              <h2 style={{ margin: '22px 0 10px' }}>数值指标</h2>
              <table className="tbl">
                <thead><tr><th>指标</th><th>数值（SI 单位）</th></tr></thead>
                <tbody>
                  {metrics.map(([k, v]) => (
                    <tr key={k}><td>{k}</td><td className="num">{fmtVal(v)}</td></tr>
                  ))}
                </tbody>
              </table>
            </>
          )}

          {(reports.length > 0 || others.length > 0) && (
            <>
              <h2 style={{ margin: '22px 0 10px' }}>报告与文件</h2>
              <div className="report-links">
                {reports.map((a) => (
                  <a key={a.id} href={artifactUrl(a)} target="_blank" rel="noreferrer">
                    📄 {a.label || (a.kind === 'report_html' ? 'HTML 报告' : 'Markdown 报告')}
                  </a>
                ))}
                {others.map((a) => (
                  <a key={a.id} href={artifactUrl(a)} target="_blank" rel="noreferrer">
                    📎 {a.label || a.id}
                  </a>
                ))}
              </div>
            </>
          )}

          <div className="btnrow">
            <button className="btn ghost" onClick={onRestart}>再跑一题</button>
          </div>
        </>
      ) : (
        <>
          <h2><span className="stepno" style={{ background: 'var(--err-bg)', color: 'var(--err)' }}>!</span> 仿真失败</h2>
          <div className="sub">run_id: <code>{run.run_id}</code></div>
          <div className="err-box">
            <div>错误码：<code>{run.error?.code || '—'}</code> · 阶段：<code>{run.error?.stage || '—'}</code></div>
            <div style={{ marginTop: 6 }}>{run.error?.message || '后端未提供错误详情'}</div>
          </div>
          {log && (
            <div className="report-links" style={{ marginTop: 12 }}>
              <a href={artifactUrl(log)} target="_blank" rel="noreferrer">📋 查看运行日志</a>
            </div>
          )}
          <div className="btnrow">
            <button className="btn ghost" onClick={onRestart}>返回重试</button>
          </div>
        </>
      )}
    </div>
  )
}
