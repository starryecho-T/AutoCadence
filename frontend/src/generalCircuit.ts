import type { GeneralCircuit } from './types'

export const COMPONENT_LABELS: Record<string, string> = { resistor: '电阻', capacitor: '电容', inductor: '电感', diode: '二极管', voltage_source: '电压源', current_source: '电流源', ideal_opamp: '理想运放', wire: '导线' }
export const PIN_LABELS: Record<string, string> = { p: '正端 / 端点 1', n: '负端 / 端点 2', a: '阳极', k: '阴极', plus: '同相端 +', minus: '反相端 −', out: '输出端' }
export const ANALYSIS_LABELS: Record<string, string> = { op: '直流工作点', ac: '交流扫频', tran: '瞬态响应', dc: '直流扫描' }
export const FIELDS: Record<string, [string, string]> = {
  resistance_ohm: ['阻值', 'Ω'], capacitance_f: ['电容', 'F'], inductance_h: ['电感', 'H'],
  initial_voltage_v: ['初始电压', 'V'], initial_current_a: ['初始电流', 'A'],
  dc: ['直流值', ''], ac_magnitude: ['交流幅值', ''], ac_phase_deg: ['交流相位', '°'],
  start_hz: ['起始频率', 'Hz'], stop_hz: ['终止频率', 'Hz'], points_per_decade: ['每十倍频点数', ''],
  stop_s: ['仿真时长', 's'], max_step_s: ['最大步长', 's'], source: ['扫描电源', ''], start: ['起始值', ''], stop: ['结束值', ''], step: ['步长', ''],
  use_initial_conditions: ['使用初始条件', ''], initial_condition_resistance_ohm: ['初值辅助电阻', 'Ω'],
  offset: ['偏置', ''], amplitude: ['幅度', ''], frequency_hz: ['频率', 'Hz'], phase_deg: ['相位', '°'], delay_s: ['延迟', 's'],
  low: ['低电平', ''], high: ['高电平', ''], period_s: ['周期', 's'], width_s: ['脉宽', 's'], rise_s: ['上升时间', 's'], fall_s: ['下降时间', 's'], model: ['二极管模型', ''],
}
const PREFIX: Record<string, number> = { p: 1e-12, n: 1e-9, u: 1e-6, 'µ': 1e-6, 'μ': 1e-6, m: 1e-3, k: 1e3, K: 1e3, M: 1e6, meg: 1e6, G: 1e9 }
export function parseEngineering(raw: string): number | string {
  const match = raw.trim().match(/^([+-]?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?)\s*(meg|[pnuµμmkKMG])?$/i)
  if (!match) return raw
  const scale = match[2] ? PREFIX[match[2]] : 1
  const value = Number(match[1]) * scale
  return Number.isFinite(value) ? Number(value.toPrecision(15)) : raw
}
export function formatEngineering(value: unknown): string {
  if (typeof value !== 'number') return value === null ? '' : typeof value === 'string' ? value : JSON.stringify(value) ?? ''
  if (value === 0) return '0'
  const prefix = Object.entries(PREFIX).filter(([p]) => !['K', 'µ', 'μ', 'meg'].includes(p)).reverse().find(([, scale]) => Math.abs(value) >= scale && (scale >= 1e3 || Math.abs(value) < 1))
  return prefix ? `${Number((value / prefix[1]).toPrecision(12))}${prefix[0]}` : String(Number(value.toPrecision(12)))
}
// This guard only protects the editor. The backend is the authority for circuit validity.
export function editableCircuit(raw: string): GeneralCircuit | null {
  try {
    const c = JSON.parse(raw)
    const objects = (x: unknown) => !!x && typeof x === 'object' && !Array.isArray(x)
    if (!objects(c) || typeof c.title !== 'string' || !Array.isArray(c.components) || c.components.length > 100 ||
      !c.components.every((x: any) => objects(x) && typeof x.id === 'string' && typeof x.type === 'string' && objects(x.pins) && Object.values(x.pins).every(n => typeof n === 'string')) ||
      !Array.isArray(c.analyses) || c.analyses.length > 4 || !c.analyses.every((x: any) => objects(x) && typeof x.type === 'string') ||
      !Array.isArray(c.signals) || c.signals.length > 16 || !c.signals.every((x: any) => objects(x) && typeof x.type === 'string' && typeof x.id === 'string')) return null
    return c
  } catch { return null }
}
