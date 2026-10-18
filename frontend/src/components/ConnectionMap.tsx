import { useState } from 'react'
import type { GeneralCircuit } from '../types'
import { COMPONENT_LABELS, PIN_LABELS } from '../generalCircuit'

export default function ConnectionMap({ circuit }: { circuit: GeneralCircuit }) {
  const nodes = [...new Set(circuit.components.flatMap(c => Object.values(c.pins)))].sort((a, b) => a === '0' ? -1 : b === '0' ? 1 : a.localeCompare(b))
  const [selected, setSelected] = useState(nodes.find(n => n !== '0') ?? '0')
  const node = nodes.includes(selected) ? selected : nodes[0]
  const connections = circuit.components.flatMap(c => Object.entries(c.pins).filter(([, n]) => n === node).map(([pin]) => ({ component: c, pin })))
  const height = Math.max(150, connections.length * 68 + 28)
  return <div className="connection-map"><div className="section-heading"><h3>节点连接图</h3><span className="muted small">{nodes.length} 个节点</span></div><p className="muted small">选择节点查看直接相连的引脚；此图表示连接关系。</p>
    <div className="node-buttons" aria-label="选择电路节点">{nodes.map(n => <button key={n} aria-pressed={node === n} onClick={() => setSelected(n)}>{n === '0' ? '0 · 参考地' : n}</button>)}</div>
    <div className="connection-scroll"><svg viewBox={`0 0 560 ${height}`} role="img" aria-label={`节点 ${node} 的连接关系`}>
      <rect x="16" y={height / 2 - 22} width="130" height="44" rx="12" fill="#e9f1ff" stroke="#9bbbea" /><text x="81" y={height / 2 + 5} textAnchor="middle">{node === '0' ? '0 · 参考地' : node}</text>
      {connections.map(({ component: c, pin }, i) => { const y = i * 68 + 24; return <g key={`${c.id}.${pin}.${i}`}><path d={`M146 ${height / 2} H180 V${y + 20} H250`} stroke="#9bbbea" fill="none" /><circle cx="250" cy={y + 20} r="3" fill="#487abc" /><rect x="254" y={y} width="290" height="44" rx="8" fill="#fff" stroke="#dce4ef" /><text x="268" y={y + 18}>{c.id} · {COMPONENT_LABELS[c.type] ?? c.type}</text><text className="pin-label" x="268" y={y + 34}>{PIN_LABELS[pin] ?? pin}</text></g> })}
    </svg></div>
  </div>
}
