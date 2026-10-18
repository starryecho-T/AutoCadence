// 后端契约类型 —— 与 contracts/ 中的 schema 对应
// API v1.0 的传输结构见 contract.ts；这里保留界面使用的扁平参数。

export type RunStatus = 'queued' | 'running' | 'succeeded' | 'failed'

export interface TaskDraft {
  text: string
  mode?: 'rc' | 'general'
  image?: { name: string; dataUrl: string }
  general?: {
    input: 'text' | 'image' | 'connections'
    connections?: string
    summary?: string
    title?: string
    issues?: { question: string; answer: string; confirmed: boolean }[]
    proposals?: { id: string; title: string; detail: string; reason: string; decision: 'pending' | 'yes' | 'no' }[]
    stale?: boolean
  }
}

/** 阶段进度（stage 名称以后端实际返回为准，这里做宽松匹配） */
export interface StageInfo {
  name: string
  status: 'pending' | 'running' | 'done' | 'failed' | 'unknown'
}

/** 仿真数值指标，SI 单位，如 { cutoff_hz: 159.15, ... } */
export type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue }
export type Metrics = Record<string, JsonValue | undefined>

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
  filename?: string
  sha256?: string
  bytes?: number
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
  warnings?: string[]
  /** 前端本地补充 */
  demo?: boolean
}

/** 提交仿真的任务描述（parse 确认后） */
export interface TaskSpec {
  circuit?: GeneralCircuit
  contract?: '1.0'
  title?: string
  kind?: string
  source_text?: string
  params?: Record<string, number | string>
  /** parse 返回、用户在确认页可编辑的参数都放在 params 里 */
}

/** /api/v1/parse 的响应 */
export interface ParseResult {
  circuitPreview?: CircuitPreview
  ok: boolean
  /** 候选任务（待用户确认，不自动提交） */
  task?: TaskSpec
  /** 缺失字段提示 */
  missing?: string[]
  /** 默认项说明 */
  defaults?: Record<string, unknown>
  defaultNotes?: string[]
  derivation?: { target_hz: number; achieved_hz: number; error_pct: number }
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
  connectionConfigured?: boolean
}

export interface GeneralCircuit {
  schema_version: '2.0'
  template_id: 'general_circuit'
  title: string
  components: { id: string; type: string; pins: Record<string, string>; [key: string]: unknown }[]
  analyses: { type: string; [key: string]: unknown }[]
  signals: { id: string; type: string; [key: string]: unknown }[]
  [key: string]: unknown
}

export interface CircuitPreview {
  task: GeneralCircuit
  normalized: { components: GeneralCircuit['components']; aliases: Record<string, string>; node_map: Record<string, string> }
  warnings: string[]
  netlist: string
  requires_confirmation: true
}
