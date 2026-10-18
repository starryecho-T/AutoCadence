// API 层：与 FastAPI 后端通信 + 演示模式兜底
//
// 设计要点（对应 FRONTEND_HANDOFF.md）：
// - 同源相对路径请求，开发期由 vite 代理到 127.0.0.1:8765
// - 只有 status === 'succeeded' 才视为成功；failed 展示 error.code/stage/message
// - artifacts[].url 是相对后端地址；演示模式下用页面内生成的资源（随参数变化）
// - 后端字段可能存在大小写/别名差异，统一经 as* 函数规范化
// - 题目截图以 image_b64 字段随 parse 请求发送（契约扩展，后端可忽略）

import type {
  Artifact, HealthInfo, Metrics, ParseResult, RunRecord, RunStatus, StageInfo, TaskSpec
} from './types'

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
  return s === 'queued' || s === 'running' || s === 'succeeded' || s === 'failed' ? s : 'queued'
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
  const out: Metrics = {}
  for (const [k, val] of Object.entries(r)) {
    if (typeof val === 'number' || typeof val === 'string' || val === null) out[k] = val
  }
  return Object.keys(out).length ? out : undefined
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
      mime: asString(r.mime ?? r.mime_type ?? r.content_type)
    })
  }
  return out.length ? out : undefined
}

function asTask(v: unknown): TaskSpec | undefined {
  const r = asRecord(v)
  if (!Object.keys(r).length) return undefined
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
  return {
    run_id: asString(r.run_id ?? r.id) ?? 'unknown-run',
    status: asRunStatus(r.status ?? r.state),
    created_at: asString(r.created_at ?? r.created ?? r.timestamp),
    task: asTask(r.task ?? r.task_spec ?? r.spec),
    stages: asStages(r.stages ?? r.stage_list ?? r.progress),
    metrics: asMetrics(r.metrics ?? r.results ?? r.values),
    artifacts: asArtifacts(r.artifacts ?? r.files ?? r.outputs),
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

/** 演示 parse：题干抓 R/C，抓不到用默认值并在 missing 里提示 */
export function demoParse(text: string, hasImage = false): ParseResult {
  const rMatch = text.match(/(\d+(?:\.\d+)?)\s*k?\s*(?:Ω|ohm|欧)/i)
  const cMatch = text.match(/(\d+(?:\.\d+)?)\s*[uμn]\s*[Ff]/)
  const rVal = rMatch ? parseFloat(rMatch[1]) * (/k/i.test(rMatch[0]) ? 1000 : 1) : 1000
  const cVal = cMatch ? parseFloat(cMatch[1]) * (/[μu]/i.test(cMatch[0]) ? 1e-6 : 1e-9) : 1e-6
  const hints = ['演示模式：后端未连接，以下为界面流程演示，数值由前端按一阶 RC 公式推算']
  if (hasImage) hints.push('已收到题目截图；真实后端上线后将以 image_b64 字段一并发送解析')
  const missing: string[] = []
  if (!rMatch) missing.push('电阻 R（默认 1 kΩ）')
  if (!cMatch) missing.push('电容 C（默认 1 µF）')
  return {
    ok: true,
    task: { kind: 'rc_lowpass', source_text: text, params: { r_ohm: rVal, c_farad: cVal } },
    missing,
    defaults: {},
    hints
  }
}

/* 演示 run：按 run_id 记住确认参数与起始时间 */
const demoRuns = new Map<string, { task?: TaskSpec; startedAt: number }>()

export function demoRunStart(task?: TaskSpec): string {
  const id = 'demo-run-' + Math.random().toString(36).slice(2, 10)
  demoRuns.set(id, { task, startedAt: Date.now() })
  return id
}

/** 演示原理图 SVG（标注随参数） */
function demoSchematic(r: number, c: number): string {
  const svg =
`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 300">
<rect width="640" height="300" fill="#fdfdfc"/>
<g stroke="#4a5568" stroke-width="1.6" fill="none">
<path d="M80 60 h120 M80 240 h120"/>
<circle cx="70" cy="150" r="10"/>
<path d="M70 140 v-80 M70 160 v80"/>
<path d="M200 60 v60 M200 180 v60"/>
<path d="M340 110 v-30 M340 160 v30"/>
<path d="M200 110 h100 M340 110 h100 M200 160 h100 M340 160 h100"/>
<path d="M440 60 v170"/>
</g>
<g font-family="Georgia, serif" font-size="15" fill="#2d3748">
<text x="50" y="150" text-anchor="middle">V1</text>
<text x="150" y="50">~</text>
<text x="170" y="140" font-size="13">R1</text>
<text x="330" y="150" font-size="13">C1</text>
<text x="170" y="158" font-size="12">${fmtComp(r, 'Ω')}</text>
<text x="305" y="100" font-size="12">${fmtComp(c, 'F')}</text>
<text x="448" y="150" font-size="13">OUT</text>
</g>
<g fill="#718096">
<circle cx="340" cy="110" r="2.5"/><circle cx="340" cy="160" r="2.5"/><circle cx="440" cy="60" r="2.5"/>
</g>
<text x="320" y="285" text-anchor="middle" font-family="sans-serif" font-size="12" fill="#a0aec0">RC 低通滤波器 · 原理图（演示，按确认参数绘制）</text>
</svg>`
  return 'data:image/svg+xml;utf8,' + encodeURIComponent(svg)
}

/** 演示幅频曲线 SVG（fc 位置随参数） */
function demoWaveform(fc: number, r: number, c: number): string {
  const fMin = Math.max(1, Math.floor(fc / 1000))
  const fMax = Math.ceil(fc * 100)
  const decades = Math.log10(fMax / fMin)
  const pts: string[] = []
  for (let i = 0; i <= 140; i++) {
    const f = fMin * Math.pow(10, (i / 140) * decades)
    const mag = Math.max(-80, -20 * Math.log10(Math.sqrt(1 + (f / fc) ** 2)))
    const x = 40 + (i / 140) * 560
    const y = 240 - ((mag + 80) / 80) * 190
    pts.push(x.toFixed(1) + ',' + y.toFixed(1))
  }
  const fcX = 40 + (Math.log10(fc / fMin) / decades) * 560
  const fmtF = (f: number): string => f >= 1000 ? (Math.round(f / 100) / 10) + 'kHz' : Math.round(f) + 'Hz'
  const svg =
`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 300">
<rect width="640" height="300" fill="#fdfdfc"/>
<g stroke="#e2e8f0" stroke-width="1">
<path d="M40 50 h560 M40 97.5 h560 M40 145 h560 M40 192.5 h560 M40 240 h560"/>
</g>
<path d="M${fcX.toFixed(1)} 40 v200" stroke="#cbd5e0" stroke-width="1" stroke-dasharray="4 4"/>
<polyline points="${pts.join(' ')}" fill="none" stroke="#5a7d9a" stroke-width="2.2"/>
<g font-family="sans-serif" font-size="11" fill="#718096">
<text x="36" y="54" text-anchor="end">0dB</text>
<text x="36" y="244" text-anchor="end">-80</text>
<text x="45" y="258">${fmtF(fMin)}</text>
<text x="320" y="258">${fmtF(Math.round(Math.sqrt(fMin * fMax)))}</text>
<text x="590" y="258">${fmtF(fMax)}</text>
<text x="${(fcX - 6).toFixed(1)}" y="38" fill="#5a7d9a" text-anchor="end">fc ≈ ${fc >= 1000 ? (Math.round(fc / 10) / 100) + ' kHz' : (Math.round(fc * 10) / 10) + ' Hz'}</text>
</g>
<text x="320" y="288" text-anchor="middle" font-family="sans-serif" font-size="12" fill="#a0aec0">AC 扫描 · 幅频特性（演示，R=${fmtComp(r, 'Ω')} C=${fmtComp(c, 'F')}）</text>
</svg>`
  return 'data:image/svg+xml;utf8,' + encodeURIComponent(svg)
}

/** 演示报告：可真实打开的 HTML Blob（含指标表与两张图） */
function demoReport(r: number, c: number, fc: number): string {
  const sch = encodeURIComponent(demoSchematic(r, c).split(',')[1] ?? '')
  const wav = encodeURIComponent(demoWaveform(fc, r, c).split(',')[1] ?? '')
  const html = `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>RC 低通仿真报告（演示）</title>
<style>body{font-family:"Segoe UI","Microsoft YaHei",sans-serif;color:#3d4754;max-width:760px;margin:32px auto;padding:0 20px;line-height:1.7}
h1{font-size:20px}h2{font-size:16px}table{border-collapse:collapse;font-size:14px;margin:8px 0 16px}
td,th{border:1px solid #e5e2db;padding:6px 14px;text-align:left}
img{max-width:100%;border:1px solid #e5e2db;border-radius:8px;background:#fdfdfc}
.warn{background:#f7f3e8;color:#85734e;padding:10px 14px;border-radius:8px;font-size:13px}</style></head><body>
<h1>RC 低通滤波器仿真报告</h1>
<p class="warn">⚠ 演示数据：后端未连接，本报告由前端按一阶 RC 公式推算，仅供流程演示。</p>
<h2>参数</h2><table><tr><th>R</th><td>${fmtComp(r, 'Ω')}</td></tr><tr><th>C</th><td>${fmtComp(c, 'F')}</td></tr></table>
<h2>数值指标</h2><table>
<tr><th>截止频率 fc = 1/(2πRC)</th><td>${Math.round(fc * 100) / 100} Hz</td></tr>
<tr><th>fc 处增益</th><td>${(1 / Math.sqrt(2)).toFixed(4)}（−3 dB）</td></tr>
<tr><th>fc 处相移</th><td>−45°</td></tr>
<tr><th>时间常数 τ = RC</th><td>${Math.round(r * c * 1e6) / 100} ms</td></tr></table>
<h2>原理图</h2><img src="data:image/svg+xml;utf8,${sch === '' ? '' : decodeURIComponent(sch)}" alt="schematic">
<h2>幅频特性</h2><img src="data:image/svg+xml;utf8,${wav === '' ? '' : decodeURIComponent(wav)}" alt="waveform">
</body></html>`
  return URL.createObjectURL(new Blob([html], { type: 'text/html' }))
}

export function demoRunGet(runId: string, elapsedMs?: number): RunRecord {
  const rec = demoRuns.get(runId)
  const task = rec?.task
  const elapsed = elapsedMs ?? (rec ? Date.now() - rec.startedAt : Infinity)
  const p = task?.params ?? {}
  const r = typeof p.r_ohm === 'number' && p.r_ohm > 0 ? p.r_ohm : 1000
  const c = typeof p.c_farad === 'number' && p.c_farad > 0 ? p.c_farad : 1e-6
  const fc = 1 / (2 * Math.PI * r * c)

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
        { id: 'wav', kind: 'waveform', label: `仿真波形（演示 · fc≈${Math.round(fc * 10) / 10}Hz）`, url: demoWaveform(fc, r, c) },
        { id: 'rep', kind: 'report_html', label: '实验报告（演示）', url: demoReport(r, c, fc) }
      ]
    : undefined

  return {
    run_id: runId,
    status,
    created_at: new Date().toISOString(),
    task,
    stages,
    metrics: status === 'succeeded'
      ? {
          r_ohm: r,
          c_farad: c,
          cutoff_hz: Math.round(fc * 1000) / 1000,
          gain_at_dc: 0.9998,
          phase_at_cutoff_deg: -45.0,
          tau_ms: Math.round(r * c * 1e6) / 100
        }
      : undefined,
    artifacts,
    demo: true
  }
}

/* ---------------- 真实 API ---------------- */

async function req<T>(path: string, method: string, body?: unknown): Promise<T> {
  const res = await fetch(API_BASE + path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body)
  })
  if (!res.ok) {
    let detail = 'HTTP ' + res.status
    try {
      const j = await res.json()
      detail = asString(asRecord(j).detail) ?? asString(asRecord(j).message) ?? JSON.stringify(j).slice(0, 200)
    } catch { /* 保留 HTTP 状态码信息 */ }
    if (res.status === 422) throw new ApiError(`输入不合法（422）：${detail}`, 422)
    throw new ApiError(detail, res.status)
  }
  return (await res.json()) as T
}

export async function getHealth(): Promise<HealthInfo> {
  try {
    const r = asRecord(await req<unknown>('/health', 'GET'))
    demoMode = false
    return {
      ok: true,
      version: asString(r.version),
      queue: asNumber(r.queue ?? r.queued) ?? asString(r.queue),
      detail: asString(r.status) === 'ok' || asString(r.status) === 'active' ? undefined : asString(r.status)
    }
  } catch {
    demoMode = true // 后端不可达 → 自动进入演示模式
    return { ok: false, demo: true, detail: '后端 127.0.0.1:8765 未响应，已切换演示模式' }
  }
}

/** 解析题目；题目截图（data:image/...;base64,xx）以 image_b64 字段一并发送 */
export async function postParse(text: string, imageDataUrl?: string): Promise<ParseResult> {
  const imageB64 = imageDataUrl && imageDataUrl.includes(',') ? imageDataUrl.split(',')[1] : undefined
  if (demoMode) return demoParse(text, !!imageB64)
  const r = asRecord(await req<unknown>('/api/v1/parse', 'POST', { text, ...(imageB64 ? { image_b64: imageB64 } : {}) }))
  return {
    ok: r.ok === true || r.ok === undefined,
    task: asTask(r.task ?? (Array.isArray(r.candidates) ? r.candidates[0] : undefined)),
    missing: Array.isArray(r.missing) ? r.missing.map(String) : [],
    defaults: asRecord(r.defaults),
    hints: Array.isArray(r.hints) ? r.hints.map(String) : []
  }
}

export async function postRun(task: TaskSpec): Promise<string> {
  if (demoMode) return demoRunStart(task)
  const r = asRecord(await req<unknown>('/api/v1/runs', 'POST', task))
  const id = asString(r.run_id ?? r.id)
  if (!id) throw new ApiError('后端未返回 run_id')
  return id
}

export async function getRun(runId: string): Promise<RunRecord> {
  if (demoMode) throw new Error('demo run 应使用 demoRunGet')
  return normalizeRun(await req<unknown>(`/api/v1/runs/${encodeURIComponent(runId)}`, 'GET'))
}

export async function listRuns(): Promise<RunRecord[]> {
  if (demoMode) return []
  try {
    const j = await req<unknown>('/api/v1/runs', 'GET')
    const arr = Array.isArray(j) ? j : asRecord(j).items ?? asRecord(j).runs ?? []
    return (arr as unknown[]).map((x) => normalizeRun(x)).slice(0, 20)
  } catch { return [] }
}

/** 相对 url 拼成可访问地址；data:/blob: 原样返回 */
export function artifactUrl(a: Artifact): string {
  if (!a.url) return ''
  if (a.url.startsWith('data:') || a.url.startsWith('blob:')) return a.url
  if (/^https?:/i.test(a.url)) return a.url
  return API_BASE + a.url
}
