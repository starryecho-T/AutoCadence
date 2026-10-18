import type { Metrics } from '../types'
const format = (v: unknown) => typeof v === 'number' ? Number(v.toPrecision(7)).toString() : String(v ?? '—')
const status = (s: unknown) => s === 'PASS' ? '通过' : s === 'FAIL' ? '未通过' : '待验证'
interface Check { id?: string; signal?: string; port?: number; status: string; max_absolute_error: number; rmse: number; max_tolerance_ratio: number }
interface Transfer { case: string; max_absolute_error_v: number; rmse_v: number; theory_saturation_boundary_v: number; regions: { region: string; start_v: number; stop_v: number }[] }
interface TwoPort { reference_hz: number; reference_matrix: { real: number; imag: number }[][]; status: string; equivalent_requested: boolean; equivalence?: { status: string; reason?: string; checks?: Check[] }; linearity_checks: Check[] }
const regions: Record<string,string> = { cutoff:'截止', forward_active:'正向放大', reverse_active:'反向放大', saturation:'饱和', breakdown:'击穿' }
function ComparisonTable({ checks }: { checks: Check[] }) {
  return <div className="table-scroll"><table className="tbl"><thead><tr><th>比较项</th><th>最大绝对误差</th><th>均方根误差</th><th>最大容差比</th><th>判定</th></tr></thead><tbody>{checks.map((c,i) => <tr key={i}><td>{c.id ?? c.signal ?? `端口 ${c.port}`}</td><td>{format(c.max_absolute_error)}</td><td>{format(c.rmse)}</td><td>{format(c.max_tolerance_ratio)}</td><td>{status(c.status)}</td></tr>)}</tbody></table></div>
}
export default function GeneralStudyResults({ metrics }: { metrics: Metrics }) {
  const tp = metrics.two_port as unknown as TwoPort | undefined
  const transfer = metrics.bjt_transfer as unknown as Transfer[] | undefined
  const comparisons = metrics.comparisons as unknown as Check[] | undefined
  if (!tp && !transfer?.length && !comparisons?.length) return null
  return <div className="card study-results"><h2>分析与比较</h2>
    {tp && <section><h3>二端口 Y 参数 · {format(tp.reference_hz)} Hz</h3><p className="sub">I = YV，电流正方向为流入被测网络，单位 S。保持原直流偏置，按交流小信号提取。</p><div className="table-scroll"><table className="tbl"><thead><tr><th></th><th>V₁</th><th>V₂</th></tr></thead><tbody>{tp.reference_matrix.map((r,i) => <tr key={i}><th>I{i+1}</th>{r.map((z,j) => <td className="num" key={j}>{format(z.real)} {z.imag < 0 ? '−' : '+'} j{format(Math.abs(z.imag))}</td>)}</tr>)}</tbody></table></div>
      <p>联合端口激励校验：{status(tp.linearity_checks.every(c => c.status === 'PASS') ? 'PASS' : 'FAIL')}。两路输入同时施加 1∠0° V 和 0.37∠37° V。</p>
      {tp.equivalent_requested && <><h4>独立搭建等效电路：{status(tp.equivalence?.status)}</h4><p className="muted small">用参考频率的实数 Y 系数构成四个压控电流源，再进行实际仿真，比较整个指定频段的复数端口电流。</p>{tp.equivalence?.reason && <p className="note warn">{tp.equivalence.reason}</p>}{tp.equivalence?.checks && <ComparisonTable checks={tp.equivalence.checks} />}</>}
      <details className="detail-section"><summary>参数提取后的联合激励校验</summary><ComparisonTable checks={tp.linearity_checks} /></details>
    </section>}
    {!!transfer?.length && <section><h3>NPN 共射转移分析</h3><p className="sub">工作区来自仿真器；叠加曲线使用固定 VBE 与 VCEsat 的分段近似，误差反映两种模型的差异。</p>{transfer.map(t => <div key={t.case}><h4>{t.case}</h4><p>输出最大误差 {format(t.max_absolute_error_v)} V；均方根误差 {format(t.rmse_v)} V；理论饱和边界 Vin ≈ {format(t.theory_saturation_boundary_v)} V。</p><div className="table-scroll"><table className="tbl"><thead><tr><th>工作区</th><th>输入电压范围 (V)</th></tr></thead><tbody>{t.regions.map((r,i) => <tr key={i}><td>{regions[r.region] ?? r.region}</td><td>{format(r.start_v)} ～ {format(r.stop_v)}</td></tr>)}</tbody></table></div></div>)}<p className="muted small">RB 限制基极电流；去掉 RB 后，理想电压源直接驱动 BE 结，此处的分段公式不再适用。</p></section>}
    {!!comparisons?.length && <section><h3>配置的曲线比较</h3><ComparisonTable checks={comparisons} /></section>}
    <p className="muted small">容差判据：|误差| ≤ 绝对容差 + 相对容差 × |参考值|；容差比不超过 1 为通过。原始矩阵、比较结果和各组网表可在报告与文件中查看。</p>
  </div>
}
