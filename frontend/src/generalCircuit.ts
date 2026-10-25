import type { GeneralCircuit } from './types'

export function circuitTitle(circuit: GeneralCircuit): string {
  if (circuit.title?.trim() && circuit.title !== '通用电路仿真') return circuit.title.trim()
  const kinds = new Set(circuit.components.map(c => c.type))
  const parts = [['resistor', 'R'], ['inductor', 'L'], ['capacitor', 'C']].filter(([k]) => kinds.has(k)).map(([, label]) => label).join('')
  const family = kinds.has('bjt') ? 'BJT 晶体管电路' : kinds.has('nmos') && kinds.has('pmos') ? 'CMOS 电路' : kinds.has('nmos') ? 'NMOS 电路' : kinds.has('pmos') ? 'PMOS 电路' : kinds.has('ideal_opamp') ? '运放电路' : kinds.has('diode') ? '二极管电路' : parts ? `${parts} 电路` : '电源与受控源电路'
  const study = circuit.two_port ? '二端口分析' : circuit.bjt_transfer ? '转移特性' : Array.isArray(circuit.parameter_sweeps) && circuit.parameter_sweeps.length ? '参数扫描' : circuit.analyses.map(a => ANALYSIS_LABELS[a.type] || a.type).join(' / ')
  return `${family} · ${study}`.slice(0, 120)
}

export const COMPONENT_LABELS: Record<string, string> = { resistor: '电阻', capacitor: '电容', inductor: '电感', diode: '二极管', voltage_source: '电压源', current_source: '电流源', ideal_opamp: '理想运放', wire: '导线', bjt:'双极型晶体管', pmos:'PMOS', nmos:'NMOS', vccs:'压控电流源', vcvs:'压控电压源', cccs:'流控电流源', ccvs:'流控电压源' }
export const PIN_LABELS: Record<string, string> = { p: '正端 / 端点 1', n: '负端 / 端点 2', a: '阳极', k: '阴极', plus: '同相端 +', minus: '反相端 −', out: '输出端', c:'集电极', b:'基极 / 衬底', e:'发射极', d:'漏极', g:'栅极', s:'源极', cp:'控制正端', cn:'控制负端' }
export const ANALYSIS_LABELS: Record<string, string> = { op: '直流工作点', ac: '交流扫频', tran: '瞬态响应', dc: '直流扫描' }
export const FIELDS: Record<string, [string, string]> = {
  resistance_ohm: ['阻值', 'Ω'], capacitance_f: ['电容', 'F'], inductance_h: ['电感', 'H'],
  initial_voltage_v: ['初始电压', 'V'], initial_current_a: ['初始电流', 'A'],
  dc: ['直流值', ''], ac_magnitude: ['交流幅值', ''], ac_phase_deg: ['交流相位', '°'],
  start_hz: ['起始频率', 'Hz'], stop_hz: ['终止频率', 'Hz'], points_per_decade: ['每十倍频点数', ''],
  stop_s: ['仿真时长', 's'], max_step_s: ['最大步长', 's'], source: ['扫描电源', ''], start: ['起始值', ''], stop: ['结束值', ''], step: ['步长', ''],
  use_initial_conditions: ['使用初始条件', ''], initial_condition_resistance_ohm: ['初值辅助电阻', 'Ω'],
  offset: ['偏置', ''], amplitude: ['幅度', ''], frequency_hz: ['频率', 'Hz'], phase_deg: ['相位', '°'], delay_s: ['延迟', 's'],
  low: ['低电平', ''], high: ['高电平', ''], period_s: ['周期', 's'], width_s: ['脉宽', 's'], rise_s: ['上升时间', 's'], fall_s: ['下降时间', 's'], model: ['器件模型', ''],
  width_m:['沟道宽度','m'], length_m:['沟道长度','m'], multiplicity:['并联倍数',''], area:['面积倍数',''], gain:['增益（G: S；E/F: 1；H: Ω）',''], control_source:['控制电流的电压源',''],
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
