import type { TaskSpec } from './types'
import { validateBackendTask } from './contract'

export const PARAM_LABELS: Record<string, string> = {
  r_ohm: '电阻 R（Ω）', c_farad: '电容 C（F）',
  freq_min_hz: '扫描起始频率（Hz）', freq_max_hz: '扫描结束频率（Hz）',
  f_min_hz: '扫描起始频率（Hz）', f_max_hz: '扫描结束频率（Hz）',
  source_kind: '激励类型',
  low_v: '脉冲低电平（V）', high_v: '脉冲高电平（V）',
  period_s: '脉冲周期（s）', width_s: '脉冲宽度（s）',
  rise_s: '上升时间（s）', fall_s: '下降时间（s）', delay_s: '延迟（s）',
  points_per_decade: '每十倍频点数', stop_s: '瞬态终点（s）', max_step_s: '最大步长（s）'
}

export const METRIC_LABELS: Record<string, [string, string]> = {
  r_ohm: ['电阻 R', 'Ω'], c_farad: ['电容 C', 'F'],
  cutoff_hz: ['截止频率', 'Hz'], gain_at_dc: ['直流增益', '倍'],
  phase_at_cutoff_deg: ['截止频率处相位', '°'], tau_ms: ['时间常数 τ', 'ms'],
  c_f: ['电容 C', 'F'], fc_hz: ['实测截止频率', 'Hz'], fc_theory_hz: ['理论截止频率', 'Hz'],
  fc_relative_error_pct: ['截止频率相对误差', '%'], tau_s: ['时间常数 τ', 's'],
  vout_at_tau: ['τ 时刻输出电压', 'V'], vout_at_100us: ['100 µs 时刻输出电压', 'V'],
  tran_points: ['瞬态数据点数', '点'], ac_points: ['AC 数据点数', '点'],
  tran_end_s: ['瞬态终点', 's'], transient_max_relative_error: ['瞬态最大相对误差', '倍'],
  ac_input_output_aligned: ['频域输入与输出对齐', '—'], tran_input_output_aligned: ['时域输入与输出对齐', '—'],
  max_ac_gain_error_db: ['幅频最大误差', 'dB'], transient_max_abs_error_v: ['瞬态最大电压误差', 'V'],
  vout_at_end: ['结束时输出电压', 'V'], validation_status: ['数值验收结果', '—']
}

export function validateTask(task: TaskSpec): string | null {
  if (task.kind === 'general_circuit') return task.circuit ? null : '缺少通用电路描述'
  const p = task.params ?? {}
  if (!Object.keys(p).length) return '没有可提交的参数'
  for (const [key, value] of Object.entries(p)) {
    if (typeof value === 'string' && !value.trim()) return `请填写${PARAM_LABELS[key] ?? key}`
    if (typeof value === 'number' && !Number.isFinite(value)) return `参数 ${key} 必须是有限数值`
  }
  if (task.kind === 'rc_lowpass' || task.kind === undefined) {
    for (const key of ['r_ohm', 'c_farad']) {
      if (typeof p[key] !== 'number' || !Number.isFinite(p[key]) || p[key] <= 0) {
        return `${PARAM_LABELS[key]}必须是大于 0 的数值`
      }
    }
    const rc = Number(p.r_ohm) * Number(p.c_farad)
    const fc = 1 / (2 * Math.PI * rc)
    if (!Number.isFinite(fc) || fc <= 0 || !Number.isFinite(rc * 1000) || fc / 1000 <= 0 || !Number.isFinite(fc * 100)) {
      return 'R、C 的组合超出可计算范围，请调整参数'
    }
  }
  for (const key of ['freq_min_hz', 'freq_max_hz', 'f_min_hz', 'f_max_hz']) {
    if (p[key] !== undefined && (typeof p[key] !== 'number' || !Number.isFinite(p[key]) || p[key] <= 0)) {
      return `${PARAM_LABELS[key]}必须是大于 0 的数值`
    }
  }
  for (const [primary, alias] of [['freq_min_hz', 'f_min_hz'], ['freq_max_hz', 'f_max_hz']]) {
    if (p[primary] !== undefined && p[alias] !== undefined && p[primary] !== p[alias]) return '频率参数别名存在冲突，请统一数值'
  }
  const min = p.freq_min_hz ?? p.f_min_hz
  const max = p.freq_max_hz ?? p.f_max_hz
  if (typeof min === 'number' && typeof max === 'number' && max <= min) return '扫描结束频率必须大于起始频率'
  return task.contract === '1.0' ? validateBackendTask(task) : null
}

export function rcValues(task: TaskSpec) {
  const error = validateTask(task)
  if (error) throw new Error(error)
  const p = task.params!
  const r = Number(p.r_ohm)
  const c = Number(p.c_farad)
  const fc = 1 / (2 * Math.PI * r * c)
  const min = Number(p.freq_min_hz ?? p.f_min_hz ?? Math.min(fc / 1000, Number(p.freq_max_hz ?? p.f_max_hz ?? Infinity) / 1000))
  const max = Number(p.freq_max_hz ?? p.f_max_hz ?? Math.max(fc * 100, min * 100))
  if (!(min > 0 && max > min && Number.isFinite(max) && Number.isFinite(Math.log10(max) - Math.log10(min)))) {
    throw new Error('扫描频率范围超出可计算范围')
  }
  return { r, c, fc, tauMs: r * c * 1000, fMin: min, fMax: max }
}

export function formatNumber(value: number): string {
  return Number(value.toPrecision(6)).toString()
}

export function escapeHtml(value: unknown): string {
  return String(value).replace(/[&<>"']/g, (s) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[s]!)
}
