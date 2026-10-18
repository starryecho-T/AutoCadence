import designerSkill from './skills/circuit-designer.skill.json'
// AI OCR 模块：调用 OpenAI 兼容的多模态接口（GLM-4V / qwen-vl / gpt-4o 等）
// 从题目截图中提取电路仿真题干的文字内容。
//
// 设计要点：
// - OpenAI 兼容协议：POST {base}/chat/completions，messages 带 image_url(base64 data URL)
// - API key 只存 localStorage，仅浏览器 → 用户自己的 API 服务，不经过任何中间服务器
// - 模型只生成待审核的连接描述；本地后端预检通过并由用户确认后才提交仿真

export interface OcrConfig {
  baseUrl: string   // 形如 https://open.bigmodel.cn/api/paas/v4
  apiKey: string
  model: string     // 形如 glm-4v-plus
}

export interface OcrResult {
  text: string      // 识别出的题目文字
  raw?: string      // 模型原始返回（调试用）
}

const LS_KEY = 'ocr-config-v1'

/** 预置服务商（都可后续手改） */
export const OCR_PRESETS: { name: string; baseUrl: string; model: string; keyUrl: string }[] = [
  { name: '智谱 GLM', baseUrl: 'https://open.bigmodel.cn/api/paas/v4', model: 'glm-4v-plus-0111', keyUrl: 'https://open.bigmodel.cn/usercenter/apikeys' },
  { name: '阿里通义', baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1', model: 'qwen-vl-max', keyUrl: 'https://bailian.console.aliyun.com/' },
  { name: 'OpenAI', baseUrl: 'https://api.openai.com/v1', model: 'gpt-4o', keyUrl: 'https://platform.openai.com/api-keys' },
  { name: '自定义/中转', baseUrl: '', model: '', keyUrl: '' }
]

export function loadOcrConfig(): OcrConfig | null {
  try {
    const s = localStorage.getItem(LS_KEY)
    if (!s) return null
    const j = JSON.parse(s) as OcrConfig
    if (j.baseUrl && j.apiKey && j.model) return j
    return null
  } catch { return null }
}

export function saveOcrConfig(cfg: OcrConfig): void {
  localStorage.setItem(LS_KEY, JSON.stringify(cfg))
}

function chatUrl(baseUrl: string): string {
  return baseUrl.replace(/\/+$/, '') + '/chat/completions'
}

/** 发送一次多模态请求；timeoutMs 毫秒无响应则报错 */
async function chat(cfg: OcrConfig, messages: unknown[], timeoutMs = 60_000, signal?: AbortSignal): Promise<string> {
  const ctrl = new AbortController()
  const abort = () => ctrl.abort()
  if (signal?.aborted) ctrl.abort()
  signal?.addEventListener('abort', abort, { once: true })
  const timer = setTimeout(() => ctrl.abort(), timeoutMs)
  try {
    const res = await fetch(chatUrl(cfg.baseUrl), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${cfg.apiKey}` },
      body: JSON.stringify({ model: cfg.model, messages, temperature: 0.1 }),
      signal: ctrl.signal
    })
    if (!res.ok) {
      let detail = `HTTP ${res.status}`
      try {
        const j = await res.json()
        detail += '：' + (j?.error?.message ?? j?.message ?? JSON.stringify(j).slice(0, 150))
      } catch { /* ignore */ }
      throw new Error(detail)
    }
    const j = await res.json()
    const content = j?.choices?.[0]?.message?.content
    if (typeof content !== 'string' || !content) throw new Error('返回结构异常：没有 choices[0].message.content')
    return content
  } catch (error) {
    if (ctrl.signal.aborted && !signal?.aborted) throw new Error('识别服务响应超时，请稍后重试')
    throw error
  } finally {
    clearTimeout(timer)
    signal?.removeEventListener('abort', abort)
  }
}

const OCR_PROMPT = `你是一个电路题目识别助手。请把图片中的电路仿真作业题目的全部文字内容准确转录出来。
要求：
1. 只输出题目文字本身，不要任何解释、前言或总结
2. 保持原有数值、单位、符号（Ω、µF、kHz、下标等）完全不变
3. 公式用普通文本近似表示即可（如 f = 1/(2πRC)）
4. 如果图中有电路图而文字很少，请把能看到的元件标注（如 R1=1kΩ、C1=100nF、V1=5V）也列出来
5. 全文用题目的语言（中文/英文）输出`

/** OCR 主入口：把题目截图（data URL）转成文字 */
export async function ocrImage(cfg: OcrConfig, imageDataUrl: string, signal?: AbortSignal): Promise<OcrResult> {
  const content = await chat(cfg, [
    { role: 'user', content: [
      { type: 'image_url', image_url: { url: imageDataUrl } },
      { type: 'text', text: OCR_PROMPT }
    ] }
  ], 90_000, signal)
  return { text: content.trim(), raw: content }
}

/** 设置面板的连通性测试：发一个最小文本请求 */
export async function testOcrConfig(cfg: OcrConfig): Promise<string> {
  return chat(cfg, [
    { role: 'user', content: [{ type: 'text', text: '请只回复：ok' }] }
  ], 20_000)
}

export interface CircuitProposal { id: string; title: string; detail: string; reason: string }
export interface CircuitExtraction { text: string; summary: string; issues: string[]; proposals?: CircuitProposal[] }

export function parseCircuitExtraction(raw: string): CircuitExtraction {
  let value: unknown
  try { value = JSON.parse(raw.trim().replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/, '')) }
  catch { throw new Error('识别服务没有返回有效的电路结果，请重试，无需改写题目格式') }
  const result = value as Partial<CircuitExtraction> | null
  if (!result || typeof result.text !== 'string' || result.text.length > 50000 ||
      !Array.isArray(result.issues) || result.issues.length > 100 ||
      !result.issues.every(x => typeof x === 'string' && x.trim() && x.length <= 2000) ||
      (result.summary !== undefined && (typeof result.summary !== 'string' || result.summary.length > 2000))) {
    throw new Error('识别结果缺少有效的电路描述或待确认问题列表')
  }
  if (!result.text.trim() && !result.issues.length) throw new Error('未识别到电路，请补充元件、连接和分析目标')
  if (result.proposals !== undefined && (!Array.isArray(result.proposals) || result.proposals.length > 20 ||
    !result.proposals.every(p => p && ['id', 'title', 'detail', 'reason'].every(k => typeof (p as unknown as Record<string, unknown>)[k] === 'string') && p.id.trim() && p.id.length <= 80 && p.title.trim() && p.title.length <= 300 && p.detail.trim() && p.detail.length <= 3000 && p.reason.length <= 2000) ||
    new Set(result.proposals.map(p => p.id)).size !== result.proposals.length)) throw new Error('建议卡片格式异常，请让 AI 重新整理')
  return { text: result.text.trim(), summary: result.summary?.trim() ?? '', issues: result.issues, ...(result.proposals ? { proposals: result.proposals } : {}) }
}

const CIRCUIT_PROMPT = JSON.stringify(designerSkill)

export async function extractCircuit(cfg: OcrConfig, input: { text: string; imageDataUrl?: string; clarification?: string; capabilities?: unknown; previousCandidate?: string; validationError?: string }, signal?: AbortSignal): Promise<CircuitExtraction> {
  const content: unknown[] = [{ type: 'text', text: `题目：\n${input.text || '见附图'}${input.clarification ? '\n用户补充与上次待核对内容：\n' + input.clarification : ''}` }]
  if (input.imageDataUrl) content.push({ type: 'image_url', image_url: { url: input.imageDataUrl } })
  return parseCircuitExtraction(await chat(cfg, [
    { role: 'system', content: CIRCUIT_PROMPT + '\n当前后端能力：' + JSON.stringify(input.capabilities ?? { components: ['resistor', 'capacitor', 'inductor', 'diode', 'voltage_source', 'current_source', 'ideal_opamp', 'wire'], analyses: ['op', 'dc', 'ac', 'tran'], note: '能力未读取，先限制为基础元件' }) },
    ...(input.previousCandidate ? [{ role: 'user', content: '上次候选（仅作修改参考）：\n' + input.previousCandidate }] : []),
    ...(input.validationError ? [{ role: 'user', content: '请修正后端预检指出的问题：\n' + input.validationError }] : []),
    { role: 'user', content }
  ], 90_000, signal))
}

export async function recognizeCircuit(cfg: OcrConfig, imageDataUrl: string, signal?: AbortSignal): Promise<CircuitExtraction> {
  return extractCircuit(cfg, { text: '', imageDataUrl }, signal)
}
