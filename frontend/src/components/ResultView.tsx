import { useMemo, useState } from 'react'
import type { Artifact, JsonValue, RunRecord } from '../types'
import { artifactUrl } from '../api'
import { formatNumber, METRIC_LABELS } from '../circuit'

interface Props {
  run: RunRecord
  onRestart: () => void
}

function fmtVal(v: JsonValue | undefined): string {
  if (v === null || v === undefined || v === '') return '—'
  if (typeof v === 'number') {
    return formatNumber(v)
  }
  return typeof v === 'string' ? v : JSON.stringify(v)
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
      <button className="image-button" aria-label={`放大${a.label || kindLabel(a.kind)}`} onClick={() => setZoom(true)}><img src={imgSrc(a)} alt={a.label || kindLabel(a.kind)} /></button>
      {zoom && (
        <div className="lightbox" role="dialog" aria-label="图片预览" aria-modal="true" onClick={() => setZoom(false)}>
          <button className="btn lightbox-close" autoFocus onClick={() => setZoom(false)} onKeyDown={(e) => { if (e.key === 'Escape') setZoom(false) }}>关闭预览</button>
          <img src={imgSrc(a)} alt={a.label || kindLabel(a.kind)} />
        </div>
      )}
    </div>
  )
}

/** 第 4 步：结果 = 原理图截图 + 仿真结果截图 + 指标 + 报告链接；失败时展示错误与日志 */
export default function ResultView({ run, onRestart }: Props) {
  const desktop = new URLSearchParams(window.location.search).get('desktop') === '1'
  const arts = run.artifacts ?? []
  const sch = arts.find((a) => a.filename === 'schematic_window.png') ?? arts.find((a) => a.kind === 'schematic')
  const wav = arts.find((a) => a.filename === 'waveform_window.png') ?? arts.find((a) => a.kind === 'waveform')
  const reports = arts.filter((a) => a.kind.startsWith('report'))
  const others = arts.filter((a) => !a.kind.startsWith('report') && !['schematic', 'waveform'].includes(a.kind) && a.url)
  const metrics = useMemo(() => Object.entries(run.metrics ?? {}).filter(([, value]) => value === null || typeof value !== 'object'), [run.metrics])
  const checks = Array.isArray(run.metrics?.checks) ? run.metrics.checks.filter((c) => c && typeof c === 'object' && !Array.isArray(c)) as Record<string, JsonValue>[] : []

  if (run.status !== 'succeeded' && run.status !== 'failed') return null

  return (
    <div className="card fade-in">
      {!!run.warnings?.length && <div className="note warn">运行警告：{run.warnings.join('；')}</div>}
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

          {!run.demo && typeof run.metrics?.fc_hz === 'number' && <div className="note info">
            本次 Spectre 实测截止频率为 {formatNumber(run.metrics.fc_hz)} Hz。
            {typeof run.metrics.fc_relative_error_pct === 'number' && ` 相对元件理论值误差为 ${formatNumber(run.metrics.fc_relative_error_pct)}%。`}
            {typeof run.metrics.tau_s === 'number' && ` 时间常数为 ${formatNumber(run.metrics.tau_s)} s。`}
            本页指标、截图和报告均属于任务 <code>{run.run_id}</code>。
          </div>}

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
                <thead><tr><th>指标</th><th>数值</th><th>单位</th></tr></thead>
                <tbody>
                  {metrics.map(([k, v]) => (
                    <tr key={k}><td>{METRIC_LABELS[k]?.[0] ?? k}</td><td className="num">{fmtVal(v)}</td><td>{METRIC_LABELS[k]?.[1] ?? '—'}</td></tr>
                  ))}
                </tbody>
              </table>
            </>
          )}

          {checks.length > 0 && <details style={{ marginTop: 16 }}>
            <summary>数值验收明细（{checks.filter((c) => c.status === 'PASS').length}/{checks.length} 通过）</summary>
            <div style={{ overflowX: 'auto' }}><table className="tbl">
              <thead><tr><th>检查项</th><th>状态</th><th>实测</th><th>预期</th><th>容差</th></tr></thead>
              <tbody>{checks.map((check, index) => <tr key={index}>
                <td>{fmtVal(check.name)}</td><td>{fmtVal(check.status)}</td><td>{fmtVal(check.actual)}</td><td>{fmtVal(check.expected)}</td><td>{fmtVal(check.tolerance)}</td>
              </tr>)}</tbody>
            </table></div>
          </details>}

          {(reports.length > 0 || others.length > 0) && (
            <>
              <h2 style={{ margin: '22px 0 10px' }}>报告与文件</h2>
              <div className="report-links">
                {reports.map((a) => (
                  <a key={a.id} href={artifactUrl(a)} target={desktop ? undefined : '_blank'} rel="noreferrer" download={desktop ? `RC-${run.run_id}.${a.kind === 'report_html' ? 'html' : 'md'}` : undefined}>
                    📄 {desktop ? '保存 ' : ''}{a.label || (a.kind === 'report_html' ? 'HTML 报告' : 'Markdown 报告')}
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
          {arts.length > 0 && (
            <div className="report-links" style={{ marginTop: 12 }}>
              {arts.map((a) => <a key={a.id} href={artifactUrl(a)} target="_blank" rel="noreferrer">📋 {a.label || a.filename || a.id}</a>)}
            </div>
          )}
          <div className="btnrow">
            <button className="btn ghost" onClick={onRestart}>返回重试</button>
          </div>
        </>
      )}
      {arts.some((a) => a.sha256) && <details style={{ marginTop: 16 }}>
        <summary>运行证据索引 · {run.run_id}</summary>
        <div style={{ overflowX: 'auto' }}><table className="tbl">
          <thead><tr><th>文件</th><th>字节数</th><th>SHA-256</th></tr></thead>
          <tbody>{arts.map((a) => <tr key={a.id}><td>{a.filename ?? a.label ?? a.id}</td><td>{a.bytes ?? '—'}</td><td><code>{a.sha256 ?? '—'}</code></td></tr>)}</tbody>
        </table></div>
      </details>}
    </div>
  )
}
