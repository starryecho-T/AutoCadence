import type { TaskSpec } from './types'

/** API v1.0 wire format. The editable UI uses flat fields; only this shape is sent. */
export interface BackendTask {
  schema_version: '1.0'
  template_id: 'rc_lowpass'
  title: string
  question: string | null
  r_ohm: number
  c_f: number
  pulse: { low_v: number; high_v: number; period_s: number; width_s: number; rise_s: number; fall_s: number; delay_s: number }
  ac: { start_hz: number; stop_hz: number; points_per_decade: number }
  transient: { stop_s: number; max_step_s: number }
}

export const ANALYSIS_DEFAULTS = {
  low_v: 0, high_v: 1, period_s: .002, width_s: .001,
  rise_s: 1e-9, fall_s: 1e-9, delay_s: 1e-6,
  freq_min_hz: 10, freq_max_hz: 1e6, points_per_decade: 50,
  stop_s: .004201, max_step_s: 1e-6
}

export function toBackendTask(task: TaskSpec): BackendTask {
  const p: Record<string, number | string> = { ...ANALYSIS_DEFAULTS, ...task.params }
  return {
    schema_version: '1.0', template_id: 'rc_lowpass',
    title: task.title ?? 'RC 低通仿真', question: task.source_text ?? null,
    r_ohm: p.r_ohm as number, c_f: p.c_farad as number,
    pulse: {
      low_v: p.low_v as number, high_v: p.high_v as number,
      period_s: p.period_s as number, width_s: p.width_s as number,
      rise_s: p.rise_s as number, fall_s: p.fall_s as number, delay_s: p.delay_s as number
    },
    ac: {
      start_hz: (task.params?.freq_min_hz ?? task.params?.f_min_hz ?? p.freq_min_hz) as number,
      stop_hz: (task.params?.freq_max_hz ?? task.params?.f_max_hz ?? p.freq_max_hz) as number,
      points_per_decade: p.points_per_decade as number
    },
    transient: { stop_s: p.stop_s as number, max_step_s: p.max_step_s as number }
  }
}

export function fromBackendTask(task: BackendTask): TaskSpec {
  return {
    contract: '1.0', kind: task.template_id, title: task.title,
    source_text: task.question ?? undefined,
    params: {
      r_ohm: task.r_ohm, c_farad: task.c_f, ...ANALYSIS_DEFAULTS,
      ...task.pulse,
      freq_min_hz: task.ac?.start_hz ?? ANALYSIS_DEFAULTS.freq_min_hz,
      freq_max_hz: task.ac?.stop_hz ?? ANALYSIS_DEFAULTS.freq_max_hz,
      points_per_decade: task.ac?.points_per_decade ?? ANALYSIS_DEFAULTS.points_per_decade,
      ...task.transient
    }
  }
}

/** Advisory checks mirror models.py. Server validation remains authoritative. */
export function validateBackendTask(task: TaskSpec): string | null {
  if (task.kind && task.kind !== 'rc_lowpass') return '当前仅支持一阶 RC 低通电路'
  if ((task.title?.length ?? 0) > 120) return '标题不能超过 120 字符'
  if ((task.source_text?.length ?? 0) > 10000) return '题目不能超过 10000 字符'
  const s = toBackendTask(task)
  const p = s.pulse, ac = s.ac, tr = s.transient
  const limits: [string, number, number, number, boolean?][] = [
    ['电阻 R（Ω）', s.r_ohm, 10, 1e6], ['电容 C（F）', s.c_f, 1e-12, 1e-3],
    ['低电平（V）', p.low_v, -10, 10], ['高电平（V）', p.high_v, -10, 10],
    ['周期（s）', p.period_s, 1e-5, .1], ['脉宽（s）', p.width_s, 0, .1, true],
    ['上升时间（s）', p.rise_s, 1e-10, .001], ['下降时间（s）', p.fall_s, 1e-10, .001],
    ['延迟（s）', p.delay_s, 0, .01],
    ['扫描起始频率（Hz）', ac.start_hz, 0, 1e8, true], ['扫描结束频率（Hz）', ac.stop_hz, 0, 1e9, true],
    ['每十倍频点数', ac.points_per_decade, 20, 100],
    ['瞬态终点（s）', tr.stop_s, 0, .5, true], ['最大步长（s）', tr.max_step_s, 1e-9, .001]
  ]
  for (const [label, value, min, max, exclusive] of limits) {
    if (typeof value !== 'number' || !Number.isFinite(value) || (exclusive ? value <= min : value < min) || value > max) {
      return `${label}必须在 ${exclusive ? '(' : '['}${min}, ${max}] 范围内`
    }
  }
  if (!Number.isInteger(ac.points_per_decade)) return '每十倍频点数必须是整数'
  if (p.high_v <= p.low_v) return '高电平必须大于低电平'
  if (p.rise_s + p.width_s + p.fall_s >= p.period_s) return '上升时间 + 脉宽 + 下降时间必须小于周期'
  const tau = s.r_ohm * s.c_f, fc = 1 / (2 * Math.PI * tau)
  if (ac.start_hz > fc / 5 || ac.stop_hz < fc * 5) return `扫描范围必须覆盖截止频率两侧至少 5 倍（起点 ≤ ${fc / 5} Hz，终点 ≥ ${fc * 5} Hz）`
  if (Math.log10(ac.stop_hz / ac.start_hz) * ac.points_per_decade > 1500) return 'AC 扫描点数预算不能超过 1500'
  if (tr.stop_s < p.delay_s + 2.05 * p.period_s) return `瞬态终点至少为 ${p.delay_s + 2.05 * p.period_s} s，以覆盖两个完整脉冲周期`
  if (tr.max_step_s > Math.min(tau / 20, p.period_s / 200, p.width_s / 20)) return '最大步长必须 ≤ min(τ/20, 周期/200, 脉宽/20)'
  if (tr.stop_s / tr.max_step_s > 60000) return '瞬态点数预算不能超过 60000，请调整终点或步长'
  return null
}
