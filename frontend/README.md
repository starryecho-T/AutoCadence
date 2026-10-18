# 电路仿真助手 · 前端

RC 低通电路仿真作业的前端界面：题目输入（文字 + 图片）→ 参数确认 → 提交仿真 → 轮询进度 → 结果展示（原理图截图 + 仿真结果截图 + 指标 + 报告）。

- 技术栈：Vite 5 + React 18 + TypeScript（零 UI 库依赖）
- 后端约定：见 `../FRONTEND_HANDOFF.md`（FastAPI，默认 `http://127.0.0.1:8765`）
- 低饱和度柔和配色 / 浅色主题

## 快速开始

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
```

开发期 Vite 把 `/api`、`/health`、`/openapi.json` 代理到 `http://127.0.0.1:8765`（见 `vite.config.ts`），后端 CORS 也默认放行 5173/3000。

## 构建与集成

```bash
npm run build      # 产出静态文件到 dist/
```

**推荐：由 FastAPI 直接托管 dist/**（同源、零 CORS、零额外进程）：

```python
# main.py 里加
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

app.mount("/ui", StaticFiles(directory="frontend/dist", html=True), name="ui")

@app.get("/ui/{path:path}")
async def ui_spa(path: str):
    return FileResponse("frontend/dist/index.html")  # SPA 路由回退
```

然后访问 `http://127.0.0.1:8765/ui/`。

**打包为 Windows EXE（PyInstaller + 静态前端）**：

1. `cd frontend && npm run build`
2. 后端入口加载 `frontend/dist`（如上）；PyInstaller 打包时把 dist 作为 data 打进去：
   `pyinstaller --add-data "frontend/dist;frontend/dist" --onefile main.py`
3. 启动后自动打开浏览器访问 `http://127.0.0.1:8765/ui/`（或在 main 里 `webbrowser.open`）。

备选：Tauri/PyWebview 把页面套成本机窗口，但服务器方案最简单，推荐先用 FastAPI 托管 + webbrowser 弹窗。

## AI 识别（题目截图 → 文字）

上传题目截图后点击"🤖 识别图片题目"，由**视觉大模型**把截图转录成文字并回填输入框（原文保留，可继续编辑再解析）。电路题的 Ω/µF/kHz 符号、公式、下标识别质量远好于传统 OCR。

- **设置**：输入页 → 上传图片 → "AI 识别设置"，预置智谱 GLM / 阿里通义 / OpenAI，也可填自定义 OpenAI 兼容中转
- **协议**：标准 OpenAI `/chat/completions` + `image_url`（base64），任何兼容服务都能用
- **隐私**：API Key 只存浏览器 localStorage；请求从你的浏览器**直连**所选服务商，不经过本项目后端
- 识别失败不影响主流程：图片仍以 `image_b64` 随 parse 请求发给后端

## 演示模式

后端未启动（`/health` 不可达）时前端自动进入演示模式，顶栏显示黄色“演示模式”徽标：

- parse/提交/轮询/结果全流程可走通
- 原理图、波形（Bode 曲线）为页面内 SVG，**随确认的 R/C 参数实时变化**（fc = 1/(2πRC)）
- “实验报告”为可真实打开的 HTML Blob
- 所有演示产物都带“演示”标注，不冒充实时结果（契约约定 fixture 不冒充真实结果）

## 与后端的契约对接

| 页面行为 | 接口 |
|---|---|
| 启动健康检查 | `GET /health`（失败 → 演示模式） |
| 解析题目 | `POST /api/v1/parse`，body `{ text, image_b64? }`；`image_b64` 为题目截图 base64（不带 data: 前缀），是本前端的**契约扩展字段**，后端可忽略 |
| 提交仿真（用户确认后，绝不自动） | `POST /api/v1/runs`（TaskSpec），202 → run_id |
| 进度轮询 | `GET /api/v1/runs/{run_id}`，1.5 s 一次，终态停止 |
| 截图/报告 | `GET artifacts[].url`（相对后端）；`kind=schematic` 原理图、`kind=waveform` 仿真结果、`kind=report_html/report_markdown` 报告 |
| 历史 | `GET /api/v1/runs`（最近 20 条） |

- 只有 `status=succeeded` 视为成功；`failed` 展示 `error.code/stage/message` 并保留日志链接
- 所有响应经防御性解析（字段别名兼容：`run_id/id`、`stages/progress`、`artifacts/files` 等），字段命名以后端 openapi.json 为准，可随时对齐
- 参数命名暂用 `r_ohm`/`c_farad`（SI 单位），如后端契约不同改 `src/api.ts` 顶部即可

## 目录结构

```
frontend/
├── src/
│   ├── api.ts              # API 封装 + 演示模式（含 SVG 生成）
│   ├── types.ts            # 契约类型
│   ├── styles.css          # 低饱和度柔和样式
│   ├── App.tsx             # 流程编排（输入→确认→轮询→结果）
│   └── components/
│       ├── TaskInput.tsx   # 1 题目输入（文字+图片）
│       ├── ConfirmPanel.tsx# 2 参数确认/编辑
│       ├── RunProgress.tsx # 3 进度（阶段状态）
│       └── ResultView.tsx  # 4 结果（截图+指标+报告）
├── vite.config.ts          # dev 代理 5173 → 8765
└── package.json
```

## 开发约定（与后端协作）

- 契约文件共同维护：`contracts/task.schema.json`、`result.schema.json` 变更需同步本前端
- 请求示例：`examples/rc_1k.json`
- `GET /docs` 有交互式接口文档，字段对不齐时以后端 openapi.json 为准
