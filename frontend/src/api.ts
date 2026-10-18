// API 层：与 FastAPI 后端通信 + 演示模式兜底
//
// 设计要点（对应 FRONTEND_HANDOFF.md）：
// - 同源相对路径请求，开发期由 vite 代理到 127.0.0.1:8765
// - 只有 status === 'succeeded' 才视为成功；failed 展示 error.code/stage/message
// - artifacts[].url 是相对后端地址；演示模式下用页面内生成的资源（随参数变化）
// - 按冻结的 API v1.0 转换任务、解析提示与工件元信息
// - 截图先转文字；/parse 仅接收 text

import type {
  Artifact, HealthInfo, Metrics, ParseResult, RunRecord, RunStatus, StageInfo, TaskSpec
} from './types'
import { escapeHtml, formatNumber, rcValues, validateTask } from './circuit'
import { fromBackendTask, toBackendTask, validateBackendTask, type BackendTask } from './contract'
import { planQuestion } from './planning'
import { circuitTitle } from './generalCircuit'
import type { GeneralCircuit, CircuitPreview } from './types'

export const API_BASE = '' // 同源；若前端独立部署，可改为 'http://127.0.0.1:8765'

export class ApiError extends Error {
  constructor(message: string, public status?: number, public code?: string, public stage?: string) {
    super(message)
  }
}

/* ---------------- 响应规范化帮助函数 ---------------- */

function asRecord(v: unknown): Record<string, unknown> {
  return v && typeof v === 'object' ? (v as Record<string, unknown>) : {}
}

function asString(v: unknown): string | undefined {
  return typeof v === 'string' && v.length > 0 ? v : undefined
}

function asNumber(v: unknown): number | undefined {
  return typeof v === 'number' && Number.isFinite(v) ? v : undefined
}

function asRunStatus(v: unknown): RunStatus {
  const s = typeof v === 'string' ? v.toLowerCase() : ''
  if (s === 'queued' || s === 'running' || s === 'succeeded' || s === 'failed') return s
  throw new ApiError('后端返回了未知任务状态，请检查接口契约')
}

/** 兼容 {name,status} 对象数组与纯字符串数组两种 stage 表示 */
function asStages(v: unknown): StageInfo[] | undefined {
  if (!Array.isArray(v)) return undefined
  const out: StageInfo[] = []
  for (const item of v) {
    if (typeof item === 'string') { out.push({ name: item, status: 'unknown' }); continue }
    const r = asRecord(item)
    const name = asString(r.name ?? r.stage ?? r.title ?? r.label)
    if (!name) continue
    const st = asString(r.status)?.toLowerCase()
    const status: StageInfo['status'] =
      st === 'pending' || st === 'waiting' ? 'pending'
      : st === 'running' || st === 'active' ? 'running'
      : st === 'done' || st === 'ok' || st === 'succeeded' ? 'done'
      : st === 'failed' || st === 'error' ? 'failed'
      : 'unknown'
    out.push({ name, status })
  }
  return out.length ? out : undefined
}

function asMetrics(v: unknown): Metrics | undefined {
  const r = asRecord(v)
  if (!Object.keys(r).length) return undefined
  return r as Metrics
}

function asArtifacts(v: unknown): Artifact[] | undefined {
  if (!Array.isArray(v)) return undefined
  const out: Artifact[] = []
  for (const item of v) {
    const r = asRecord(item)
    out.push({
      id: asString(r.id ?? r.artifact_id ?? r.name) ?? `artifact-${out.length}`,
      kind: asString(r.kind ?? r.type ?? r.category) ?? 'other',
      label: asString(r.label ?? r.title ?? r.filename),
      url: asString(r.url ?? r.path ?? r.href),
      mime: asString(r.media_type ?? r.mime ?? r.mime_type ?? r.content_type),
      filename: asString(r.filename), sha256: asString(r.sha256), bytes: asNumber(r.bytes)
    })
  }
  return out.length ? out : undefined
}

function asTask(v: unknown): TaskSpec | undefined {
  const r = asRecord(v)
  if (!Object.keys(r).length) return undefined
  if (r.template_id === 'rc_lowpass' && 'r_ohm' in r && 'c_f' in r) return fromBackendTask(r as unknown as BackendTask)
  if (r.template_id === 'general_circuit') return { kind: 'general_circuit', title: circuitTitle(r as unknown as GeneralCircuit), circuit: r as unknown as GeneralCircuit }
  const params = asRecord(r.params ?? r.parameters ?? r.defaults)
  return {
    kind: asString(r.kind ?? r.type),
    source_text: asString(r.source_text ?? r.text),
    params: Object.keys(params).length ? (params as Record<string, number | string>) : undefined
  }
}

function normalizeRun(v: unknown, demo = false): RunRecord {
  const r = asRecord(v)
  const err = asRecord(r.error)
  const id = asString(r.run_id ?? r.id)
  if (!id) throw new ApiError('后端未返回任务 ID')
  const artifacts = asArtifacts(r.artifacts ?? r.files ?? r.outputs)
  if (r.schema_version === '1.0') {
    for (const artifact of artifacts ?? []) {
      if (artifact.url !== `/api/v1/runs/${encodeURIComponent(id)}/artifacts/${encodeURIComponent(artifact.id)}`) {
        throw new ApiError('工件地址与本次任务不一致，已停止展示以避免混用运行证据')
      }
    }
  }
  return {
    run_id: id,
    status: asRunStatus(r.status ?? r.state),
    created_at: asString(r.created_at ?? r.created ?? r.timestamp),
    task: asTask(r.task ?? r.task_spec ?? r.spec),
    stages: asStages(r.stages ?? r.stage_list ?? r.progress),
    metrics: asMetrics(r.metrics ?? r.results ?? r.values),
    artifacts,
    warnings: Array.isArray(r.warnings) ? r.warnings.map(String) : [],
    error: Object.keys(err).length ? {
      code: asString(err.code), stage: asString(err.stage), message: asString(err.message ?? err.detail)
    } : undefined,
    demo
  }
}

/* ---------------- 演示模式 ---------------- */

let demoMode = false
export function isDemoMode(): boolean { return demoMode }

/** 元件值人性化：1000→"1kΩ"，2.2e-6→"2.2µF" */
function fmtComp(v: number, unit: string): string {
  const t = (n: number): string => String(Math.round(n * 100) / 100)
  const a = Math.abs(v)
  if (a >= 1e6) return t(v / 1e6) + 'M' + unit
  if (a >= 1e3) return t(v / 1e3) + 'k' + unit
  if (a >= 1) return t(v) + unit
  if (a >= 1e-3) return t(v * 1e3) + 'm' + unit
  if (a >= 1e-6) return t(v * 1e6) + 'µ' + unit
  if (a >= 1e-9) return t(v * 1e9) + 'n' + unit
  return t(v * 1e12) + 'p' + unit
}

/** 演示 parse：题干抓 R/C，抓不到用默认值并在 missing 里提示
 *  兼容 "R=2kΩ / R=2k / R = 2 kΩ / 2.2k ohm" 与 "C=0.1µF / 100nF / 1uF"（µ 为 U+00B5 或 U+03BC） */
export function demoParse(text: string, hasImage = false): ParseResult {
  if (!text.trim()) throw new ApiError('请先识别图片或输入题目文字，演示模式不能直接解析截图')
  const number = '[+-]?(?:\\d+(?:\\.\\d*)?|\\.\\d+)(?:[eE][+-]?\\d+)?'
  // 先匹配带元件标记的值，再匹配明确的单位；kHz 不会作为 kΩ。
  const rMatch = text.match(new RegExp(`(?:\\bR(?:\\d+)?\\b|电阻)\\s*[:：=＝]?\\s*(${number})\\s*([kKMm]?)\\s*(?:Ω|ohms?|欧姆?)?(?![A-Za-z0-9.])`, 'i'))
    ?? text.match(new RegExp(`(${number})\\s*([kKMm]?)\\s*(?:Ω|ohms?|欧姆?)`, 'i'))
  const cMatch = text.match(new RegExp(`(${number})\\s*([uµμnpm]?)\\s*[Ff](?![A-Za-z])`))
  const rScale: Record<string, number> = { k: 1e3, K: 1e3, M: 1e6, m: 1e-3, '': 1 }
  const cScale: Record<string, number> = { u: 1e-6, 'µ': 1e-6, 'μ': 1e-6, n: 1e-9, p: 1e-12, m: 1e-3, '': 1 }
  const rVal = rMatch ? Number(rMatch[1]) * rScale[rMatch[2]] : 1000
  const cVal = cMatch ? Number(cMatch[1]) * cScale[cMatch[2]] : 1e-6
  const params: Record<string, number | string> = { r_ohm: rVal, c_farad: cVal }
  const range = text.match(new RegExp(`(${number})\\s*([kKMm]?)\\s*Hz\\s*(?:~|～|至|到|—|–|-)\\s*(${number})\\s*([kKMm]?)\\s*Hz`, 'i'))
  if (range) {
    params.freq_min_hz = Number(range[1]) * rScale[range[2]]
    params.freq_max_hz = Number(range[3]) * rScale[range[4]]
  }
  const hints = ['演示模式：后端未连接，以下为界面流程演示，数值由前端按一阶 RC 公式推算']
  if (hasImage) hints.push('截图仅供对照；解析使用输入框中已识别并核对的文字。')
  const missing: string[] = []
  if (!rMatch) missing.push('电阻 R（默认 1 kΩ）')
  if (!cMatch) missing.push('电容 C（默认 1 µF）')
  return {
    ok: true,
    task: { kind: 'rc_lowpass', source_text: text, params },
    missing,
    defaults: { ...(!rMatch ? { r_ohm: 1000 } : {}), ...(!cMatch ? { c_farad: 1e-6 } : {}) },
    hints
  }
}

/* 演示 run：按 run_id 记住确认参数与起始时间 */
const demoRuns = new Map<string, { task: TaskSpec; startedAt: number; completed?: RunRecord }>()

export function demoRunStart(task: TaskSpec): string {
  const error = validateTask(task)
  if (error) throw new ApiError(error)
  if (task.kind && task.kind !== 'rc_lowpass') throw new ApiError('演示模式仅支持 RC 低通电路')
  rcValues(task)
  const id = 'demo-run-' + crypto.randomUUID()
  demoRuns.set(id, { task: { ...task, params: { ...task.params } }, startedAt: Date.now() })
  return id
}

/** 演示原理图 SVG（标注随参数） */
function demoSchematic(r: number, c: number): string {
  const svg =
`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 300">
<rect width="640" height="300" fill="#fdfdfc"/>
<g stroke="#4a5568" stroke-width="1.6" fill="none">
<circle cx="110" cy="150" r="28"/>
<path d="M110 122 V80 H240 M310 80 H510 M110 178 V230 H510 M410 80 V140 M385 140 H435 M385 154 H435 M410 154 V230"/>
<rect x="240" y="69" width="70" height="22"/>
<path d="M96 150 q7 -18 14 0 t14 0 M280 230 v14 M264 244 h32 M270 251 h20 M276 258 h8"/>
</g>
<g font-family="Georgia, serif" font-size="15" fill="#2d3748">
<text x="57" y="154">V1</text>
<text x="265" y="53" font-size="13">R1</text>
<text x="445" y="145" font-size="13">C1</text>
<text x="252" y="114" font-size="12">${fmtComp(r, 'Ω')}</text>
<text x="445" y="165" font-size="12">${fmtComp(c, 'F')}</text>
<text x="515" y="84" font-size="13">OUT</text>
</g>
<g fill="#718096">
<circle cx="410" cy="80" r="3"/><circle cx="410" cy="230" r="3"/><circle cx="280" cy="230" r="3"/>
</g>
<text x="320" y="285" text-anchor="middle" font-family="sans-serif" font-size="12" fill="#a0aec0">RC 低通滤波器 · 原理图（演示，按确认参数绘制）</text>
</svg>`
  return 'data:image/svg+xml;utf8,' + encodeURIComponent(svg)
}

/** 演示幅频曲线 SVG（fc 位置随参数；扫描范围可由确认参数指定） */
function demoWaveform(fc: number, r: number, c: number, fMin: number, fMax: number): string {
  const decades = Math.log10(fMax) - Math.log10(fMin)
  const pts: string[] = []
  for (let i = 0; i <= 140; i++) {
    const f = 10 ** (Math.log10(fMin) + (i / 140) * decades)
    const mag = Math.max(-80, -20 * Math.log10(Math.hypot(1, f / fc)))
    const x = 40 + (i / 140) * 560
    const y = 240 - ((mag + 80) / 80) * 190
    pts.push(x.toFixed(1) + ',' + y.toFixed(1))
  }
  const fcX = 40 + ((Math.log10(fc) - Math.log10(fMin)) / decades) * 560
  const inRange = fc >= fMin && fc <= fMax
  const fmtF = (f: number): string => f >= 1000 ? formatNumber(f / 1000) + 'kHz' : formatNumber(f) + 'Hz'
  const svg =
`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 300">
<rect width="640" height="300" fill="#fdfdfc"/>
<g stroke="#e2e8f0" stroke-width="1">
<path d="M40 50 h560 M40 97.5 h560 M40 145 h560 M40 192.5 h560 M40 240 h560"/>
</g>
${inRange ? `<path d="M${fcX.toFixed(1)} 40 v200" stroke="#cbd5e0" stroke-width="1" stroke-dasharray="4 4"/>` : ''}
<polyline points="${pts.join(' ')}" fill="none" stroke="#5a7d9a" stroke-width="2.2"/>
<g font-family="sans-serif" font-size="11" fill="#718096">
<text x="36" y="54" text-anchor="end">0dB</text>
<text x="36" y="244" text-anchor="end">-80</text>
<text x="45" y="258">${fmtF(fMin)}</text>
<text x="320" y="258" text-anchor="middle">${fmtF(10 ** ((Math.log10(fMin) + Math.log10(fMax)) / 2))}</text>
<text x="600" y="258" text-anchor="end">${fmtF(fMax)}</text>
<text x="40" y="30" fill="#5a7d9a">fc ≈ ${fmtF(fc)}${inRange ? '' : '（扫描范围外）'}</text>
</g>
<text x="320" y="288" text-anchor="middle" font-family="sans-serif" font-size="12" fill="#a0aec0">AC 扫描 · 幅频特性（演示，R=${fmtComp(r, 'Ω')} C=${fmtComp(c, 'F')}）</text>
</svg>`
  return 'data:image/svg+xml;utf8,' + encodeURIComponent(svg)
}

/** 演示报告：可真实打开的 HTML Blob（含指标表与两张图；额外参数如实列入） */
function demoReport(r: number, c: number, fc: number, fMin: number, fMax: number, extra?: Metrics): string {
  const sch = demoSchematic(r, c)
  const wav = demoWaveform(fc, r, c, fMin, fMax)
  const extraRows = Object.entries(extra ?? {})
    .map(([k, v]) => `<tr><th>${escapeHtml(k)}</th><td>${escapeHtml(v)}</td></tr>`).join('')
  const html = `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>RC 低通仿真报告（演示）</title>
<style>body{font-family:"Segoe UI","Microsoft YaHei",sans-serif;color:#3d4754;max-width:760px;margin:32px auto;padding:0 20px;line-height:1.7}
h1{font-size:20px}h2{font-size:16px}table{border-collapse:collapse;font-size:14px;margin:8px 0 16px}
td,th{border:1px solid #e5e2db;padding:6px 14px;text-align:left}
img{max-width:100%;border:1px solid #e5e2db;border-radius:8px;background:#fdfdfc}
.warn{background:#f7f3e8;color:#85734e;padding:10px 14px;border-radius:8px;font-size:13px}</style></head><body>
<h1>RC 低通滤波器仿真报告</h1>
<p class="warn">⚠ 演示数据：后端未连接，本报告由前端按一阶 RC 公式推算，仅供流程演示。</p>
<h2>参数</h2><table><tr><th>R</th><td>${fmtComp(r, 'Ω')}</td></tr><tr><th>C</th><td>${fmtComp(c, 'F')}</td></tr><tr><th>扫描范围</th><td>${formatNumber(fMin)}–${formatNumber(fMax)} Hz</td></tr></table>
<h2>数值指标</h2><table>
<tr><th>截止频率 fc = 1/(2πRC)</th><td>${formatNumber(fc)} Hz</td></tr>
<tr><th>fc 处增益</th><td>${(1 / Math.sqrt(2)).toFixed(4)}（−3 dB）</td></tr>
<tr><th>fc 处相移</th><td>−45°</td></tr>
<tr><th>时间常数 τ = RC</th><td>${formatNumber(r * c * 1000)} ms</td></tr>${extraRows}</table>
<h2>原理图</h2><img src="${sch}" alt="schematic">
<h2>幅频特性</h2><img src="${wav}" alt="waveform">
</body></html>`
  return URL.createObjectURL(new Blob([html], { type: 'text/html' }))
}

export function demoRunGet(runId: string, elapsedMs?: number): RunRecord {
  const rec = demoRuns.get(runId)
  if (!rec) throw new ApiError('演示任务不存在或已清理，请重新提交')
  if (rec.completed) return rec.completed
  const task = rec.task
  const elapsed = elapsedMs ?? Date.now() - rec.startedAt
  const p = task?.params ?? {}
  const { r, c, fc, tauMs, fMin, fMax } = rcValues(task)
  // 其余确认参数全部透传进 metrics（不限于 R/C——演示引擎只算 R/C，其余如实展示）
  const extraMetrics: Metrics = {}
  for (const [k, v] of Object.entries(p)) {
    if (!['r_ohm', 'c_farad', 'freq_min_hz', 'freq_max_hz', 'f_min_hz', 'f_max_hz', 'source_kind'].includes(k)) {
      if (!['cutoff_hz', 'tau_ms', 'gain_at_dc', 'phase_at_cutoff_deg'].includes(k)) extraMetrics[k] = v
    }
  }

  const stages: StageInfo[] = [
    { name: '生成原理图', status: 'done' },
    { name: '网表编译', status: 'done' },
    { name: 'AC 扫描仿真', status: elapsed > 3000 ? 'done' : 'running' },
    { name: '数值计算', status: elapsed > 4500 ? 'done' : 'pending' },
    { name: '截图与报告', status: elapsed > 5500 ? 'done' : 'pending' }
  ]
  const status: RunStatus = elapsed > 6500 ? 'succeeded' : 'running'

  const artifacts: Artifact[] | undefined = status === 'succeeded'
    ? [
        { id: 'sch', kind: 'schematic', label: `原理图（演示 · R=${fmtComp(r, 'Ω')} C=${fmtComp(c, 'F')}）`, url: demoSchematic(r, c) },
        { id: 'wav', kind: 'waveform', label: `仿真波形（演示 · fc≈${Math.round(fc * 10) / 10}Hz）`, url: demoWaveform(fc, r, c, fMin, fMax) },
        { id: 'rep', kind: 'report_html', label: '实验报告（演示）', url: demoReport(r, c, fc, fMin, fMax, extraMetrics) }
      ]
    : undefined

  const result: RunRecord = {
    run_id: runId,
    status,
    created_at: new Date(rec.startedAt).toISOString(),
    task,
    stages,
    metrics: status === 'succeeded'
      ? {
          r_ohm: r,
          c_farad: c,
          cutoff_hz: fc,
          gain_at_dc: 1,
          phase_at_cutoff_deg: -45.0,
          tau_ms: tauMs,
          ...extraMetrics
        }
      : undefined,
    artifacts,
    demo: true
  }
  if (status === 'succeeded') rec.completed = result
  return result
}

/** 历史之外的演示任务释放报告资源；当前结果由调用方一并保留。 */
export function retainDemoRuns(runIds: string[]): void {
  const keep = new Set(runIds)
  for (const [id, rec] of demoRuns) {
    if (keep.has(id)) continue
    for (const artifact of rec.completed?.artifacts ?? []) {
      if (artifact.url?.startsWith('blob:')) URL.revokeObjectURL(artifact.url)
    }
    demoRuns.delete(id)
  }
}

/* ---------------- 真实 API ---------------- */

async function req<T>(path: string, method: string, body?: unknown, signal?: AbortSignal, timeoutMs = 15_000): Promise<T> {
  const controller = new AbortController()
  const abort = () => controller.abort()
  if (signal?.aborted) controller.abort()
  signal?.addEventListener('abort', abort, { once: true })
  const timer = setTimeout(abort, timeoutMs)
  try {
    const res = await fetch(API_BASE + path, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal
    })
    if (!res.ok) {
      let detail = 'HTTP ' + res.status
      let code: string | undefined, stage: string | undefined
      try {
        const j = asRecord(await res.json()), error = asRecord(j.error)
        code = asString(error.code); stage = asString(error.stage)
        detail = asString(error.message) ?? asString(j.detail) ?? asString(j.message) ?? JSON.stringify(j).slice(0, 200)
        if (Array.isArray(error.details)) detail += '：' + error.details.map((item) => {
          const d = asRecord(item)
          return `${Array.isArray(d.location) ? d.location.join('.') : ''} ${asString(d.message) ?? ''}`
        }).join('；')
      } catch { /* 保留 HTTP 状态码信息 */ }
      if (res.status === 422) throw new ApiError(`输入不合法（422）：${detail}`, 422, code, stage)
      throw new ApiError(detail, res.status, code, stage)
    }
    return (await res.json()) as T
  } catch (error) {
    if (controller.signal.aborted && !signal?.aborted) throw new ApiError('请求超时，请检查后端连接后重试')
    throw error
  } finally {
    clearTimeout(timer)
    signal?.removeEventListener('abort', abort)
  }
}

export async function getHealth(signal?: AbortSignal): Promise<HealthInfo> {
  try {
    const r = asRecord(await req<unknown>('/health', 'GET', undefined, signal, 5000))
    if (r.ok === false || r.healthy === false || ['error', 'failed', 'unhealthy', 'offline'].includes(String(r.status).toLowerCase())) throw new ApiError('后端健康检查未通过')
    demoMode = false
    return {
      ok: true,
      version: asString(r.version),
      queue: asNumber(asRecord(r.queue).queued ?? r.queue ?? r.queued) ?? asString(r.queue),
      detail: asString(r.status) === 'ok' || asString(r.status) === 'active' ? undefined : asString(r.status)
    }
  } catch (error) {
    if (signal?.aborted) throw error
    demoMode = true // 后端不可达 → 自动进入演示模式
    return { ok: false, demo: true, detail: '后端 127.0.0.1:8765 未响应，已切换演示模式' }
  }
}

/** API v1.0 accepts only text. OCR happens before parsing, in the input page. */
export async function postParse(text: string, imageDataUrl?: string): Promise<ParseResult> {
  if (!text.trim()) throw new ApiError('请先识别图片或输入完整题目文字，后端仅支持文字解析')
  if (demoMode) return demoParse(text, !!imageDataUrl)
  const r = asRecord(await req<unknown>('/api/v1/parse', 'POST', { text }))
  if (r.ok === false) throw new ApiError(asString(r.message ?? r.detail) ?? '题目解析失败，请补充题目后重试')
  if (r.supported === false) throw new ApiError(Array.isArray(r.warnings) ? r.warnings.join('；') : '当前仅支持一阶 RC 低通题目')
  const task = asTask(r.task ?? (Array.isArray(r.candidates) ? r.candidates[0] : undefined))
  if (!task?.params && r.supported !== true) throw new ApiError('未解析到电路参数，请补充 R、C 和单位')
  const result: ParseResult = {
    ok: r.ok === true || r.ok === undefined,
    task,
    missing: Array.isArray(r.missing_fields) ? r.missing_fields.map(String) : Array.isArray(r.missing) ? r.missing.map(String) : [],
    defaults: asRecord(r.defaults),
    defaultNotes: Array.isArray(r.defaults_applied) ? r.defaults_applied.map(String) : [],
    hints: Array.isArray(r.warnings) ? r.warnings.map(String) : Array.isArray(r.hints) ? r.hints.map(String) : []
  }
  return r.supported === true ? planQuestion(text, result) : result
}

export async function postRun(task: TaskSpec): Promise<string> {
  if (task.circuit) {
    if (demoMode) throw new ApiError('通用电路需要连接真实仿真后端')
    const run = await req<{ run_id: string }>('/api/v2/runs', 'POST', task.circuit)
    return run.run_id
  }
  const error = validateTask(task)
  if (error) throw new ApiError(error)
  if (demoMode) return demoRunStart(task)
  const contractError = validateBackendTask(task)
  if (contractError) throw new ApiError(contractError)
  const r = asRecord(await req<unknown>('/api/v1/runs', 'POST', toBackendTask(task)))
  const id = asString(r.run_id ?? r.id)
  if (!id) throw new ApiError('后端未返回 run_id')
  return id
}

export async function getRun(runId: string, signal?: AbortSignal): Promise<RunRecord> {
  const run = normalizeRun(await req<unknown>(`/api/v1/runs/${encodeURIComponent(runId)}`, 'GET', undefined, signal))
  if (run.run_id !== runId) throw new ApiError('后端返回的任务 ID 与当前任务不一致')
  return run
}

export async function parseCircuit(text: string, signal?: AbortSignal): Promise<CircuitPreview> {
  if (demoMode) throw new ApiError('通用电路需要连接后端；离线演示仅支持 RC 低通')
  return req('/api/v2/parse', 'POST', { text }, signal)
}

export async function previewCircuit(task: unknown, signal?: AbortSignal): Promise<CircuitPreview> {
  return req('/api/v2/preview', 'POST', task, signal)
}

export interface CircuitCapabilities { schema_version: string; components: string[]; analyses: string[]; studies?: string[]; examples: { id: string; label: string; text: string }[]; [key: string]: unknown }
export async function circuitCapabilities(signal?: AbortSignal): Promise<CircuitCapabilities> {
  const result = await req<CircuitCapabilities>('/api/v2/capabilities', 'GET', undefined, signal)
  if (!Array.isArray(result.components) || !Array.isArray(result.examples)) throw new ApiError('后端未提供通用电路能力，请更新并重新连接后端')
  return result
}
export async function circuitExamples(): Promise<{ id: string; label: string; text: string }[]> {
  return (await circuitCapabilities()).examples
}

export async function listRuns(signal?: AbortSignal): Promise<RunRecord[]> {
  if (demoMode) return []
  const j = await req<unknown>('/api/v1/runs', 'GET', undefined, signal)
  const arr = Array.isArray(j) ? j : asRecord(j).items ?? asRecord(j).runs
  if (!Array.isArray(arr)) throw new ApiError('后端任务列表格式不正确')
  return arr.map((x) => normalizeRun(x)).slice(0, 20)
}

/** 相对 url 拼成可访问地址；data:/blob: 原样返回 */
export function artifactUrl(a: Artifact): string {
  if (!a.url) return ''
  if (a.url.startsWith('data:') || a.url.startsWith('blob:')) return a.url
  if (/^https?:/i.test(a.url)) return a.url
  if (/^[a-z][a-z\d+.-]*:/i.test(a.url) || a.url.startsWith('//')) return ''
  return API_BASE + a.url
}
