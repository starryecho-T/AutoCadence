import { useEffect, useState } from 'react'
import type { RunRecord } from '../types'
import { artifactUrl } from '../api'
import { ANALYSIS_LABELS } from '../generalCircuit'
import { groupWaveforms, parseNumericWave, validateWaveforms, waveBounds, waveUnit, waveValue, type WaveMode, type WaveSeries } from '../waveforms'
import Icon from './Icon'
import Modal from './Modal'
const COLORS = ['#3976d6', '#d17b32', '#0c917e', '#9b63cd', '#ca566e', '#688438', '#a06031', '#647ba2']
const number = (v: number) => Number(v.toPrecision(4)).toString()

function Plot({ series, mode, label, colorIndex, scanUnit }: { series: WaveSeries[]; mode: WaveMode; label: string; colorIndex: (signal: string) => number; scanUnit: string }) {
  const { xmin, xmax, low, high } = waveBounds(series, mode)
  const x = (v: number) => xmin === xmax ? 400 : 76 + (v - xmin) / (xmax - xmin) * 686
  const y = (v: number) => 235 - (v - low) / (high - low) * 205
  const analysis = series[0].analysis
  return <svg className="wave-plot" viewBox="0 0 800 300" role="img" aria-label={label}>
    {[0, 1, 2, 3, 4].map(i => { const yy = 30 + i * 205 / 4, xx = 76 + i * 686 / 4, coordinate = xmin + (xmax - xmin) * i / 4; return <g key={i}><path d={`M76 ${yy} H762 M${xx} 30 V235`} stroke="#e8edf4" fill="none" /><text x="66" y={yy + 4} textAnchor="end">{number(high - (high - low) * i / 4)}</text><text x={xx} y="257" textAnchor="middle">{number(analysis === 'ac' ? 10 ** coordinate : coordinate)}</text></g> })}
    <text x="76" y="17">{waveUnit(series[0], mode)}</text><path d="M76 30V235H762" fill="none" stroke="#a4b2c4" />
    {series.map(s => <g key={s.signal}>{s.rows.length === 1 ? <circle cx={x(s.analysis === 'ac' ? Math.log10(s.rows[0][0]) : s.rows[0][0])} cy={y(waveValue(s.rows[0], mode))} r="4" fill={COLORS[colorIndex(s.signal) % COLORS.length]} /> : <polyline points={s.rows.map(r => `${x(s.analysis === 'ac' ? Math.log10(r[0]) : r[0])},${y(waveValue(r, mode))}`).join(' ')} fill="none" stroke={COLORS[colorIndex(s.signal) % COLORS.length]} strokeWidth="2" strokeDasharray={colorIndex(s.signal) >= COLORS.length ? '7 3' : undefined} />}</g>)}
    <text x="419" y="287" textAnchor="middle">{analysis === 'tran' ? '时间 (s)' : analysis === 'ac' ? '频率 (Hz，对数坐标)' : `电源扫描值${scanUnit ? ` (${scanUnit})` : ''}`}</text>
  </svg>
}
export default function GeneralWaveforms({ run }: { run: RunRecord }) {
  const [series, setSeries] = useState<WaveSeries[]>([])
  const [mode, setMode] = useState<WaveMode>('magnitude')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [zoom, setZoom] = useState<{ series: WaveSeries[]; title: string } | null>(null)
  const artifact = run.artifacts?.find(a => a.filename === 'waveforms.json')
  const url = artifact ? artifactUrl(artifact) : ''
  const rcFiles = (run.artifacts ?? []).filter(a => ['tran_in.txt', 'tran_out.txt', 'ac_vdb_in.txt', 'ac_vdb_out.txt'].includes(a.filename ?? ''))
  const rcKey = rcFiles.map(a => artifactUrl(a)).join('|')
  useEffect(() => {
    setSeries([]); setError(''); setLoading(true); setZoom(null)
    const abort = new AbortController()
    async function load() {
      try {
        let data: WaveSeries[] = []
        if (url) {
          const response = await fetch(url, { signal: abort.signal })
          if (!response.ok) throw new Error(`HTTP ${response.status}`)
          data = validateWaveforms(await response.json())
        } else {
          data = await Promise.all(rcFiles.map(async file => {
            const response = await fetch(artifactUrl(file), { signal: abort.signal })
            if (!response.ok) throw new Error(`${file.filename}：HTTP ${response.status}`)
            const ac = file.filename!.startsWith('ac_')
            return parseNumericWave(await response.text(), ac ? 'ac' : 'tran', file.filename!.includes('_out') ? 'out' : 'in', ac ? 'dB' : 'V')
          }))
        }
        if (!abort.signal.aborted) setSeries(data)
      } catch (e) { if (!abort.signal.aborted) setError(e instanceof Error ? e.message : String(e)) }
      finally { if (!abort.signal.aborted) setLoading(false) }
    }
    void load()
    return () => abort.abort()
  }, [url, rcKey])
  function signalLabel(id: string) {
    const s = run.task?.circuit?.signals.find(s => s.id === id)
    return s?.type === 'voltage' ? `V(${s.p}${s.n && s.n !== '0' ? `,${s.n}` : ''})` : s?.type === 'current' ? `I(${s.component})` : id === 'in' ? '输入电压' : id === 'out' ? '输出电压' : id
  }
  const signalIds = [...new Set(series.map(s => s.signal))]
  const colorIndex = (signal: string) => signalIds.indexOf(signal)
  const dc = run.task?.circuit?.analyses.find(a => a.type === 'dc')
  const source = run.task?.circuit?.components.find(c => c.id === dc?.source)
  const scanUnit = source?.type === 'current_source' ? 'A' : source?.type === 'voltage_source' ? 'V' : ''
  const groups = groupWaveforms(series)
  const curves = series.filter(s => s.analysis !== 'op')
  const measurements = Array.isArray(run.metrics?.measurements) ? run.metrics.measurements as Record<string, unknown>[] : []
  function plotCard(items: WaveSeries[], title: string, individual: boolean) {
    return <article className={`wave-card ${individual ? 'individual-curve' : 'overview-curve'}`} key={`${items[0].analysis}.${items[0].unit}.${individual ? items[0].signal : 'all'}`}><div className="section-heading"><h4>{title}</h4><button className="icon-button" aria-label={`放大${title}`} onClick={() => setZoom({ series: items, title })}><Icon name="expand" /></button></div><Plot series={items} mode={mode} colorIndex={colorIndex} scanUnit={scanUnit} label={title + ' 仿真波形'} /><div className="wave-legend">{items.map(s => <span key={s.signal}><i style={{ backgroundColor: COLORS[colorIndex(s.signal) % COLORS.length], borderBottom: colorIndex(s.signal) >= COLORS.length ? '2px dashed white' : undefined }} />{signalLabel(s.signal)}{items.length === 1 ? ` · ${s.rows.length} / ${s.original_samples} 点` : ''}</span>)}</div></article>
  }
  return <div className="card general-waves">
    <div className="section-heading"><div><h2>{run.task?.circuit ? '节点与支路结果' : '信号曲线'}</h2><p className="sub">同类信号对比查看，每条曲线也有独立图和独立纵轴。</p></div>{series.some(s => s.analysis === 'ac' && s.rows[0]?.length === 3) && <label className="wave-mode">交流显示 <select aria-label="AC 分量" value={mode} onChange={e => setMode(e.target.value as WaveMode)}><option value="magnitude">幅值</option><option value="phase">相位（度）</option><option value="real">实部</option><option value="imag">虚部</option></select></label>}</div>
    {loading && <p role="status">正在加载仿真曲线…</p>}{error && <p className="note err" role="alert">波形加载失败：{error}</p>}{!loading && !error && !series.length && <p className="muted">本次运行没有可显示的数值波形，请查看报告与文件。</p>}
    {!!series.filter(s => s.analysis === 'op').length && <div className="operating-values">{series.filter(s => s.analysis === 'op').map(s => <div key={s.signal}><span>{signalLabel(s.signal)} · 直流工作点</span><strong>{number(s.rows[0][1])} <small>{s.unit}</small></strong></div>)}</div>}
    {groups.some(g => g.length > 1) && <section className="wave-section"><h3>曲线对比</h3><p className="muted small">按分析类型与单位分组，共用坐标便于比较。</p>{groups.filter(g => g.length > 1).map(g => plotCard(g, `${ANALYSIS_LABELS[g[0].analysis]} · ${g[0].analysis === 'ac' && mode === 'phase' ? `${g[0].unit === 'V' ? '电压' : g[0].unit === 'A' ? '电流' : g[0].unit}相位 (°)` : g[0].unit} 对比`, false))}</section>}
    {!!curves.length && <section className="wave-section"><h3>独立曲线 <span className="muted small">{curves.length} 张</span></h3><div className="individual-waves">{curves.map(s => plotCard([s], `${ANALYSIS_LABELS[s.analysis]} · ${signalLabel(s.signal)}`, true))}</div></section>}
    {!!curves.length && <p className="muted small">曲线来自本次仿真的数值数据。绘图可能经过抽样，指标使用完整数据；原始数据可在“报告与文件”中查看。</p>}
    {!!measurements.length && <div className="table-scroll"><table className="tbl"><thead><tr><th>指标</th><th>数值</th><th>判定</th></tr></thead><tbody>{measurements.map(m => <tr key={String(m.id)}><td>{String(m.id)}</td><td>{typeof m.value === 'number' ? m.value.toPrecision(7) : String(m.value)}</td><td>{m.status === 'PASS' ? '通过' : m.status === 'FAIL' ? '未通过' : '已测量'}</td></tr>)}</tbody></table></div>}
    {zoom && <Modal title={zoom.title} onClose={() => setZoom(null)} wide><Plot series={zoom.series} mode={mode} colorIndex={colorIndex} scanUnit={scanUnit} label={zoom.title + ' 放大波形'} /><div className="wave-legend">{zoom.series.map(s => <span key={s.signal}><i style={{ backgroundColor: COLORS[colorIndex(s.signal) % COLORS.length] }} />{signalLabel(s.signal)}</span>)}</div></Modal>}
  </div>
}
