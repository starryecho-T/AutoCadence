export interface Unit { label: string; scale: number }
export interface ParameterDefinition { label: string; units: readonly Unit[] }
const resistance = [{ label: 'Ω', scale: 1 }, { label: 'kΩ', scale: 1e3 }, { label: 'MΩ', scale: 1e6 }]
const capacitance = [{ label: 'pF', scale: 1e-12 }, { label: 'nF', scale: 1e-9 }, { label: 'µF', scale: 1e-6 }, { label: 'F', scale: 1 }]
const time = [{ label: 'ns', scale: 1e-9 }, { label: 'µs', scale: 1e-6 }, { label: 'ms', scale: 1e-3 }, { label: 's', scale: 1 }]
const frequency = [{ label: 'Hz', scale: 1 }, { label: 'kHz', scale: 1e3 }, { label: 'MHz', scale: 1e6 }]
const voltage = [{ label: 'mV', scale: 1e-3 }, { label: 'V', scale: 1 }]
export const PARAMETERS: Record<string, ParameterDefinition> = {
  r_ohm: { label: '电阻 R', units: resistance }, c_farad: { label: '电容 C', units: capacitance },
  low_v: { label: '低电平', units: voltage }, high_v: { label: '高电平', units: voltage },
  period_s: { label: '周期', units: time }, width_s: { label: '脉宽', units: time },
  rise_s: { label: '上升时间', units: time }, fall_s: { label: '下降时间', units: time }, delay_s: { label: '延迟', units: time },
  freq_min_hz: { label: '扫描起始频率', units: frequency }, freq_max_hz: { label: '扫描结束频率', units: frequency },
  f_min_hz: { label: '扫描起始频率', units: frequency }, f_max_hz: { label: '扫描结束频率', units: frequency },
  points_per_decade: { label: '每十倍频点数', units: [] }, stop_s: { label: '仿真时长', units: time }, max_step_s: { label: '最大步长', units: time },
}
export function chooseUnit(value: number | string, units: readonly Unit[]): Unit {
  if (typeof value !== 'number' || !Number.isFinite(value) || value === 0) return units.find(u => u.scale === 1) ?? units[0] ?? { label: '', scale: 1 }
  return [...units].reverse().find(u => Math.abs(value) >= u.scale * (1 - 1e-12)) ?? units[0] ?? { label: '', scale: 1 }
}
export function displayInUnit(value: number | string, scale: number): string {
  return typeof value === 'number' ? String(Number((value / scale).toPrecision(15))) : value
}
// Keep API values in SI; remove binary multiplication noise without rounding the input display.
export function toSI(raw: string, scale: number): number | string {
  if (!raw.trim()) return ''
  const n = Number(raw) * scale
  return Number.isFinite(n) ? Number(n.toPrecision(15)) : raw
}
export function engineering(value: number, dimension: 'resistance' | 'capacitance' | 'time' | 'frequency'): { value: string; unit: string } {
  if (!Number.isFinite(value)) return { value: '—', unit: '' }
  const unit = chooseUnit(value, { resistance, capacitance, time, frequency }[dimension])
  return { value: Number((value / unit.scale).toPrecision(6)).toLocaleString('zh-CN', { maximumSignificantDigits: 6 }), unit: unit.label }
}
