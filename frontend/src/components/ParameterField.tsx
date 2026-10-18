import { useState } from 'react'
import { PARAMETERS, chooseUnit, displayInUnit, toSI } from '../units'
import { PARAM_LABELS } from '../circuit'
export default function ParameterField({ name, value, recommended, disabled, onChange }: {
  name: string; value: number | string; recommended: boolean; disabled: boolean; onChange: (name: string, value: number | string) => void
}) {
  const definition = PARAMETERS[name]
  const [unit, setUnit] = useState(() => chooseUnit(value, definition?.units ?? []))
  const [raw, setRaw] = useState(() => displayInUnit(value, unit.scale))
  const numeric = !!definition || typeof value === 'number'
  const label = definition?.label ?? PARAM_LABELS[name] ?? name
  return <div className="param-item">
    <label htmlFor={`param-${name}`}>{label}{recommended && <span className="default-label">推荐</span>}</label>
    <div className="field-control">
      <input id={`param-${name}`} type={numeric ? 'number' : 'text'} step="any" disabled={disabled} value={raw}
        onChange={(event) => { setRaw(event.target.value); onChange(name, numeric ? toSI(event.target.value, unit.scale) : event.target.value) }} />
      {!!definition?.units.length && <select aria-label={`${label}单位`} value={unit.scale} disabled={disabled}
        onChange={(event) => { const next = definition.units.find(item => item.scale === Number(event.target.value))!; setRaw(displayInUnit(value, next.scale)); setUnit(next) }}>
        {definition.units.map(item => <option key={item.label} value={item.scale}>{item.label}</option>)}
      </select>}
    </div>
  </div>
}
