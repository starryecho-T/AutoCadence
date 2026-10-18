// AI OCR 模块：调用 OpenAI 兼容的多模态接口（GLM-4V / qwen-vl / gpt-4o 等）
// 从题目截图中提取电路仿真题干的文字内容。
//
// 设计要点：
// - OpenAI 兼容协议：POST {base}/chat/completions，messages 带 image_url(base64 data URL)
// - API key 只存 localStorage，仅浏览器 → 用户自己的 API 服务，不经过任何中间服务器
// - 识别失败不影响主流程（图片仍随 parse 请求发给后端 image_b64）

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
