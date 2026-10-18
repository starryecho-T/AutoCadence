// 后端契约类型 —— 与 contracts/ 中的 schema 对应
// 后端字段命名不完全确定时，解析层（api.ts 的 as* 帮助函数）会做兼容处理

export type RunStatus = 'queued' | 'running' | 'succeeded' | 'failed'

/** 阶段进度（stage 名称以后端实际返回为准，这里做宽松匹配） */
export interface StageInfo {
  name: string
  status: 'pending' | 'running' | 'done' | 'failed' | 'unknown'
}

/** 仿真数值指标，SI 单位，如 { cutoff_hz: 159.15, ... } */
export type Metrics = Record<string, number | string | null | undefined>

export interface Artifact {
  id: string
  /** schematic | waveform | report_html | report_markdown | data | log | other */
  kind: string
  /** 展示名，如 “原理图截图” */
  label?: string
  /** 相对后端的地址（演示模式下是 data: URL 或页面内占位） */
  url?: string
  /** 媒体类型，用于区分 图片/文本 */
  mime?: string
}

export interface RunError {
  code?: string
  stage?: string
  message?: string
}

export interface RunRecord {
  run_id: string
  status: RunStatus
  created_at?: string
  /** 参数摘要，用于历史列表 */
  task?: TaskSpec
  stages?: StageInfo[]
  metrics?: Metrics
  artifacts?: Artifact[]
  error?: RunError
  /** 前端本地补充 */
  demo?: boolean
}

/** 提交仿真的任务描述（parse 确认后） */
export interface TaskSpec {
  kind?: string
  source_text?: string
  params?: Record<string, number | string>
  /** parse 返回、用户在确认页可编辑的参数都放在 params 里 */
}

/** /api/v1/parse 的响应 */
export interface ParseResult {
  ok: boolean
  /** 候选任务（待用户确认，不自动提交） */
  task?: TaskSpec
  /** 缺失字段提示 */
  missing?: string[]
  /** 默认项说明 */
  defaults?: Record<string, unknown>
  /** 原样展示的提示信息 */
  hints?: string[]
}

export interface HealthInfo {
  ok: boolean
  /** 是否演示模式 */
  demo?: boolean
  version?: string
  queue?: number | string
  detail?: string
}
