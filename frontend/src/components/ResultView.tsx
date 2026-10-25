import { useState } from 'react'
import type { Artifact, JsonValue, RunRecord } from '../types'
import { artifactUrl } from '../api'
import GeneralWaveforms from './GeneralWaveforms'
import GeneralStudyResults from './GeneralStudyResults'
import { formatNumber, METRIC_LABELS } from '../circuit'
import { engineering } from '../units'
import { imageLabel, resultImages } from '../resultArtifacts'
import Icon from './Icon'
import Modal from './Modal'
import ResultChat from './ResultChat'
import ErrorBoundary from './ErrorBoundary'

interface Props { run: RunRecord; onRestart: () => void; onEdit?: () => void }
function fmtVal(value: JsonValue | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'number') return formatNumber(value)
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (value === 'PASS') return '通过'
  if (value === 'FAIL') return '未通过'
  return typeof value === 'string' ? value : JSON.stringify(value)
}
function Shot({ artifact, label }: { artifact: Artifact; label: string }) {
  const [zoom, setZoom] = useState(false)
  const [failed, setFailed] = useState(false)
  return <div className="shot"><div className="shot-head"><Icon name="image" /><strong>{label}</strong><span>点击放大</span></div>
    {failed ? <div className="shot-empty">截图暂时无法加载。<a href={artifactUrl(artifact)} target="_blank" rel="noreferrer">打开原始文件</a></div>
      : <button className="image-button" aria-label={`放大${label}`} onClick={() => setZoom(true)}><img src={artifactUrl(artifact)} alt={label} onError={() => setFailed(true)} /></button>}
    {zoom && <Modal title={label} onClose={() => setZoom(false)} wide><img className="zoom-image" src={artifactUrl(artifact)} alt={label} /></Modal>}
  </div>
}
function FileLinks({ files, runId }: { files: Artifact[]; runId: string }) {
  const desktop = new URLSearchParams(window.location.search).get('desktop') === '1'
  return <div className="report-links">{files.filter(a => a.url).map(a => {
    const report = a.kind.startsWith('report')
    return <a key={a.id} href={artifactUrl(a)} target={desktop && report ? undefined : '_blank'} rel="noreferrer"
      download={desktop && report ? `AutoCadence-${runId}.${a.kind === 'report_html' ? 'html' : 'md'}` : undefined}>
      <Icon name={report ? 'download' : 'file'} /><span>{report ? `${desktop ? '保存' : '查看'}${a.kind === 'report_html' ? '网页版报告' : 'Markdown 报告'}` : a.filename || a.label || a.id}</span>
    </a>
  })}</div>
}
function MetricTable({ rows }: { rows: [string, JsonValue | undefined][] }) {
  return <div className="table-scroll"><table className="tbl"><thead><tr><th>指标</th><th>数值</th><th>单位</th></tr></thead><tbody>{rows.map(([key, value]) => {
    let display = fmtVal(value), unit = METRIC_LABELS[key]?.[1] ?? '—'
    if (typeof value === 'number' && ['tau_s', 'tran_end_s'].includes(key)) { const t = engineering(value, 'time'); display = t.value; unit = t.unit }
    return <tr key={key}><td>{METRIC_LABELS[key]?.[0] ?? key}</td><td className="num">{display}</td><td>{unit}</td></tr>
  })}</tbody></table></div>
}

export default function ResultView({ run, onRestart, onEdit }: Props) {
  const [tab, setTab] = useState('shots')
  // ErrorBoundary 重置：递增 key 只重挂出错的卡片（指标卡 / 波形卡），不影响其他区域
  const [metricAttempt, setMetricAttempt] = useState(0)
  const [waveAttempt, setWaveAttempt] = useState(0)
  const arts = run.artifacts ?? []
  const { images, schematic: sch, waveform: wav, shots } = resultImages(arts)
  const reports = arts.filter(a => a.kind.startsWith('report'))
  const logs = arts.filter(a => a.kind === 'log' || /(?:^logs\/|\.log$)/i.test(a.filename ?? ''))
  const data = arts.filter(a => !reports.includes(a) && !logs.includes(a) && !images.includes(a))
  const metrics = Object.entries(run.metrics ?? {}).filter(([, value]) => value === null || typeof value !== 'object')
  const knownMetrics = metrics.filter(([key]) => key in METRIC_LABELS)
  const technicalMetrics = metrics.filter(([key]) => !(key in METRIC_LABELS))
  const checks = Array.isArray(run.metrics?.checks) ? run.metrics.checks.filter(c => c && typeof c === 'object' && !Array.isArray(c)) as Record<string, JsonValue>[] : []
  const m = run.metrics ?? {}
  const cutoffValue = typeof m.fc_hz === 'number' ? m.fc_hz : m.cutoff_hz
  const cutoff = typeof cutoffValue === 'number' ? engineering(cutoffValue, 'frequency') : null
  const timeValue = typeof m.tau_s === 'number' ? m.tau_s : typeof m.tau_ms === 'number' ? m.tau_ms / 1000 : undefined
  const time = timeValue !== undefined ? engineering(timeValue, 'time') : null
  const tabs = [['shots', '仿真截图'], ['metrics', '数值指标'], ['files', '报告与文件']]
  const warnings = !!run.warnings?.length && <details className="note warn"><summary>运行提示 · {run.warnings!.length} 条</summary><ul>{run.warnings!.map((warning, i) => <li key={i}>{warning}</li>)}</ul></details>
  if (run.status !== 'succeeded' && run.status !== 'failed') return null

  return <section className="result-view fade-in">
    {run.demo && <div className="note warn">演示数据：仅展示界面流程与理论计算，不是真实仿真结果。</div>}
    {run.status === 'succeeded' ? <>
      <div className="result-heading"><h2><span className="result-mark"><Icon name="check" /></span>仿真完成</h2><span className="small muted">{run.demo ? '本地演示' : '指标与文件来自本次仿真'}</span></div>
      {run.task?.circuit ? <><ErrorBoundary key={`metrics-${metricAttempt}`} onReset={() => setMetricAttempt(n => n + 1)}><div className="metric-cards"><div className="card metric-card"><span>仿真元件</span><div className="metric-number">{String(m.component_count ?? '—')}</div></div><div className="card metric-card"><span>数据校验</span><div className="metric-number">{m.validation_status === 'PASS' ? '通过' : String(m.validation_status ?? '—')}</div></div><div className="card metric-card"><span>目标指标</span><div className="metric-number">{m.requirements_status === 'NOT_SPECIFIED' ? '未指定' : m.requirements_status === 'PASS' ? '通过' : m.requirements_status === 'FAIL' ? '未通过' : String(m.requirements_status ?? '—')}</div></div></div></ErrorBoundary><ErrorBoundary key={`waves-${waveAttempt}`} onReset={() => setWaveAttempt(n => n + 1)}><GeneralWaveforms run={run} /></ErrorBoundary></> : <ErrorBoundary key={`metrics-${metricAttempt}`} onReset={() => setMetricAttempt(n => n + 1)}><div className="metric-cards">
        <div className="card metric-card"><span>{run.demo ? '理论截止频率 · 演示' : '实测截止频率'}</span><div className="metric-number">{cutoff?.value ?? '—'}<small>{cutoff?.unit}</small></div><p>{typeof m.fc_theory_hz === 'number' ? `理论值 ${formatNumber(m.fc_theory_hz)} Hz` : '一阶 RC 低通滤波器'}</p></div>
        <div className="card metric-card"><span>{typeof m.fc_relative_error_pct === 'number' ? '相对理论误差' : '数值验收'}</span><div className="metric-number">{typeof m.fc_relative_error_pct === 'number' ? Number(m.fc_relative_error_pct.toPrecision(3)).toString() : fmtVal(m.validation_status)}<small>{typeof m.fc_relative_error_pct === 'number' ? '%' : ''}</small></div><p>{checks.length ? `${checks.filter(c => c.status === 'PASS').length} / ${checks.length} 项检查通过` : run.demo ? '演示不执行数值验收' : '查看数值指标了解详情'}</p></div>
        <div className="card metric-card"><span>时间常数 τ</span><div className="metric-number">{time?.value ?? '—'}<small>{time?.unit}</small></div><p>由元件值 R × C 计算</p></div>
      </div></ErrorBoundary>
      }
      {warnings}
      {run.task?.circuit && <GeneralStudyResults metrics={m} />}
      {!run.task?.circuit && arts.some(a => ['waveforms.json', 'tran_in.txt', 'tran_out.txt', 'ac_vdb_in.txt', 'ac_vdb_out.txt'].includes(a.filename ?? '')) && <ErrorBoundary key={`waves-${waveAttempt}`} onReset={() => setWaveAttempt(n => n + 1)}><GeneralWaveforms run={run} /></ErrorBoundary>}
      <div className="card result-card">
        <div className="tabs" role="tablist" aria-label="结果内容">{tabs.map(([id, label], index) => <button key={id} role="tab" id={`tab-${id}`} aria-controls={`panel-${id}`} aria-selected={tab === id} tabIndex={tab === id ? 0 : -1} className={tab === id ? 'active' : ''}
          onClick={() => setTab(id)} onKeyDown={event => {
            const next = event.key === 'ArrowRight' ? (index + 1) % tabs.length : event.key === 'ArrowLeft' ? (index + tabs.length - 1) % tabs.length : event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : -1
            if (next >= 0) { event.preventDefault(); setTab(tabs[next][0]); document.getElementById(`tab-${tabs[next][0]}`)?.focus() }
          }}>{label}</button>)}</div>
        <div role="tabpanel" id="panel-shots" aria-labelledby="tab-shots" hidden={tab !== 'shots'}>
          <div className="shots">{sch ? null : <div className="shot-empty">暂无电路原理图</div>}{wav ? null : <div className="shot-empty">暂无仿真波形截图</div>}{shots.map(a => <Shot key={a.id} artifact={a} label={imageLabel(a)} />)}</div>
          <p className="artifact-caption">{run.demo ? '当前图形为公式生成的演示示意。' : '窗口截图及原生导出均来自本次仿真，点击图片可放大核对。'}</p>
        </div>
        <div role="tabpanel" id="panel-metrics" aria-labelledby="tab-metrics" hidden={tab !== 'metrics'}>
          {knownMetrics.length ? <MetricTable rows={knownMetrics} /> : <p className="empty-state">暂无数值指标</p>}
          {checks.length > 0 && <details className="detail-section"><summary>数值验收明细（{checks.filter(c => c.status === 'PASS').length}/{checks.length} 通过）</summary><div className="table-scroll"><table className="tbl"><thead><tr><th>检查项</th><th>状态</th><th>实测</th><th>预期</th><th>容差</th></tr></thead><tbody>{checks.map((check, i) => <tr key={i}><td>{fmtVal(check.name)}</td><td>{fmtVal(check.status)}</td><td>{fmtVal(check.actual)}</td><td>{fmtVal(check.expected)}</td><td>{fmtVal(check.tolerance)}</td></tr>)}</tbody></table></div></details>}
          {!!technicalMetrics.length && <details className="detail-section"><summary>技术指标与数据来源（{technicalMetrics.length}）</summary><MetricTable rows={technicalMetrics} /></details>}
        </div>
        <div role="tabpanel" id="panel-files" aria-labelledby="tab-files" hidden={tab !== 'files'}>
          <h3>仿真报告</h3>{reports.length ? <FileLinks files={reports} runId={run.run_id} /> : <p className="muted">本次没有生成报告。</p>}
          <details className="detail-section"><summary>图像文件（{shots.length}）</summary><FileLinks files={shots} runId={run.run_id} /></details>
          {!!data.length && <details className="detail-section"><summary>数值数据与电路文件（{data.length}）</summary><FileLinks files={data} runId={run.run_id} /></details>}
          {!!logs.length && <details className="detail-section"><summary>诊断日志（{logs.length}）</summary><FileLinks files={logs} runId={run.run_id} /></details>}
          {arts.some(a => a.sha256) && <details className="detail-section"><summary>运行证据索引</summary><div className="table-scroll"><table className="tbl"><thead><tr><th>文件</th><th>字节数</th><th>SHA-256</th></tr></thead><tbody>{arts.map(a => <tr key={a.id}><td>{a.filename ?? a.label ?? a.id}</td><td>{a.bytes ?? '—'}</td><td><code>{a.sha256 ?? '—'}</code></td></tr>)}</tbody></table></div></details>}
        </div>
      </div>
    </> : <div className="card failure-card">
      <h2><span className="result-mark failed"><Icon name="info" /></span>仿真失败</h2>
      <p className="failure-title">{run.error?.code === 'ENVIRONMENT_MISSING' ? '仿真环境暂不可用' : run.error?.code === 'CMN018_NOT_CONFIGURED' ? '还差一步：配置 CMN018 模型文件' : '本次仿真未能完成'}</p>
      <p className="muted">{run.error?.code === 'ENVIRONMENT_MISSING' ? '请检查仿真服务与运行环境，准备好后可以使用当前参数重试。' : run.error?.code === 'CMN018_NOT_CONFIGURED' ? 'NMOS/PMOS 题目默认使用 CMN018 工艺模型。打开「仿真服务器 → 高级设置」，在 CMN018 主模型文件填写服务器上的绝对路径并连接保存，然后重新运行即可。' : '参数已保留。你可以查看错误详情，调整参数后重新提交。'}</p>
      <details className="detail-section error-details"><summary>错误详情</summary><p>错误码：<code>{run.error?.code || '—'}</code> · 阶段：<code>{run.error?.stage || '—'}</code></p><p>{run.error?.message || '服务未提供错误详情'}</p></details>
      {warnings}
      {!!arts.length && <details className="detail-section"><summary>诊断文件（{arts.length}）</summary><FileLinks files={arts} runId={run.run_id} /></details>}
    </div>}
    <ResultChat key={run.run_id} run={run} />
    <footer className="actionbar"><details className="run-identity"><summary>任务信息</summary><div><code>{run.run_id}</code>{run.created_at && <p>{new Date(run.created_at).toLocaleString('zh-CN')}</p>}</div></details><div className="actions"><button className="btn ghost" onClick={onRestart}>新建仿真</button>{onEdit && <button className="btn" onClick={onEdit}>{run.status === 'failed' ? '修改参数并重试' : '调整参数再运行'}<Icon name="arrow" /></button>}</div></footer>
  </section>
}
