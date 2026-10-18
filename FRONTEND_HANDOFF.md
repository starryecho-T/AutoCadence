# 前端接口约定 v1.0

后端：Python + FastAPI。本机默认 http://127.0.0.1:8765；前端可选 Vite + React + TypeScript，任何 HTTP 客户端都可用。所有数值使用 SI 单位。

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | /health | 活跃、队列与版本；不等同于授权可用 |
| GET | /api/v1/capabilities | 模板、默认参数与限制 |
| POST | /api/v1/parse | text 字段输入题目；返回候选 task、缺失字段、默认项，需确认 |
| POST | /api/v1/runs | TaskSpec，202 返回 run_id 和 queued；非法输入返回 422 |
| GET | /api/v1/runs | 最近任务 |
| GET | /api/v1/runs/{run_id} | 轮询状态，每 1–2 秒一次 |
| GET | /api/v1/runs/{run_id}/artifacts/{artifact_id} | 图、数据、日志、HTML/Markdown 报告 |
| GET | /openapi.json | 机器可读接口 |
| GET | /docs | 交互式接口文档 |

请求见 examples/rc_1k.json；契约见 contracts/task.schema.json 和 result.schema.json。状态固定 queued/running/succeeded/failed。只有 succeeded 表示仿真、数值、截图和报告全部通过。失败展示 error.code、error.stage、error.message，同时保留日志链接。

页面最小流程：

1. 题目输入 → POST parse；显示 R/C、默认激励、分析范围和待确认项。只支持文字 RC 低通题目。
2. 用户确认并可编辑参数 → POST runs；不要因 parse 返回候选对象就自动启动。
3. GET run 显示 stages；终态停止轮询。
4. 显示 metrics、kind=schematic/waveform 的图片及 kind=report_html/report_markdown 的报告链接；artifacts[].url 是相对后端地址。
5. 使用同一 run_id 的数值和图片；fixture 只用于开发，不冒充实时结果。

CORS 默认支持 localhost/127.0.0.1 的 5173 和 3000 端口。另一台电脑的连接方式见 README，不共享私钥。后端负责 worker/ 与 vai_backend/；前端独立目录开发，共同维护 contracts/。
