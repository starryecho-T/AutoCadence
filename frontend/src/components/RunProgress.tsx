import type { RunRecord, StageInfo } from '../types'
import Icon from './Icon'
interface Props { run: RunRecord }
const LABELS: Record<string, string> = {
  upload: '上传任务', preflight: '检查运行环境', build: '建立原理图', probe: '检查电路',
  netlist: '生成网表', netlist_validation: '核对网表参数', spectre: '运行仿真',
  export: '导出数据', capture: '获取原始截图', download: '回传结果',
  image_validation: '校验截图', validation: '校验数值', equivalent:'搭建并验证 Y 参数等效电路', report: '生成报告'
}
const GROUPS = [
  { label: '准备电路', names: ['upload', 'preflight', 'build', 'probe', 'netlist', 'netlist_validation'] },
  { label: '运行仿真', names: ['spectre'] },
  { label: '整理结果', names: ['export', 'capture', 'download'] },
  { label: '验证与报告', names: ['image_validation', 'validation', 'equivalent', 'report'] },
]
export default function RunProgress({ run }: Props) {
  const stages: StageInfo[] = run.stages ?? []
  const current = stages.find(stage => stage.status === 'running')
  const done = stages.filter(stage => stage.status === 'done').length
  return <div className="card progress-card fade-in">
    <div className="progress-summary"><span className="progress-orbit"><span className="spinner" /></span><div><h2>{run.status === 'queued' ? '已提交，等待仿真' : '仿真进行中'}</h2><p className="muted">{current ? LABELS[current.name] ?? current.name : '正在等待服务更新进度'}{stages.length > 1 ? ` · 已完成 ${done} / ${stages.length} 个步骤` : ''}</p></div></div>
    <ol className="progress-groups">{GROUPS.map((group, i) => {
      const matched = stages.filter(stage => group.names.includes(stage.name))
      const state = matched.some(stage => stage.status === 'failed') ? 'failed' : matched.some(stage => stage.status === 'running') ? 'running' : matched.length && matched.every(stage => stage.status === 'done') ? 'done' : 'pending'
      return <li className={state} key={group.label}><span>{state === 'done' ? <Icon name="check" /> : i + 1}</span><strong>{group.label}</strong><small>{state === 'done' ? '已完成' : state === 'running' ? '进行中' : state === 'failed' ? '需要处理' : '等待中'}</small></li>
    })}</ol>
    <details className="detail-section"><summary>查看详细步骤</summary><ul className="stages">{stages.map((stage, i) => <li key={i} className={stage.status}><span className="stage-dot">{stage.status === 'done' ? <Icon name="check" /> : stage.status === 'running' ? <span className="spinner" /> : null}</span>{LABELS[stage.name] ?? stage.name}<small>{stage.status === 'failed' ? '失败' : ''}</small></li>)}</ul><p className="small muted">任务编号：<code>{run.run_id}</code></p></details>
    {run.demo && <div className="note warn">正在演示流程，不会启动真实仿真。</div>}
  </div>
}
