import type { RunRecord, StageInfo } from '../types'

interface Props {
  run: RunRecord
}

const LABELS: Record<string, string> = {
  upload: '上传任务', preflight: '环境预检', build: '建立原理图', probe: '检查电路',
  netlist: '生成网表', netlist_validation: '核对网表参数', spectre: 'Spectre 仿真',
  export: '导出数据', capture: '获取真实截图', download: '回传证据',
  image_validation: '校验截图', validation: '校验数值', report: '生成报告'
}

/** 第 3 步：仿真进行中，展示后端返回的 stages 与状态 */
export default function RunProgress({ run }: Props) {
  const stages: StageInfo[] = run.stages?.length
    ? run.stages
    : [{ name: '排队等待中', status: run.status === 'queued' ? 'pending' : 'running' }]

  return (
    <div className="card fade-in">
      <h2>
        <span className="stepno">3</span> 仿真进行中
        <span style={{ fontWeight: 400, fontSize: 13, color: 'var(--ink-soft)' }}>
          run_id: <code style={{ fontSize: 12 }}>{run.run_id}</code>
        </span>
      </h2>
      <div className="sub">页面每 1.5 秒查询一次进度，完成后自动展示结果</div>

      <ul className="stages">
        {stages.map((s, i) => (
          <li key={i} className={s.status}>
            <span className="dot">
              {s.status === 'running' && <span className="spinner" style={{ width: 10, height: 10 }} />}
            </span>
            {LABELS[s.name] ?? s.name}
            {s.status === 'failed' && <span style={{ color: 'var(--err)', fontSize: 12.5 }}>（失败）</span>}
          </li>
        ))}
      </ul>
    </div>
  )
}
