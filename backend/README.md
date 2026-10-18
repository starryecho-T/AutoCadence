# vai_backend — Virtuoso (Cadence) 自动化后端

把"读题 → 建原理图 → 网表 → Spectre 仿真 → 数值校验 → 真实截图 → 证据报告"整条 RC 低通滤波器实验流水线做成可编程调用的 HTTP 服务。本地 FastAPI 负责任务编排与验收，远程 Linux 服务器上的 Cadence IC617 / MMSIM151 完成真实 EDA 执行；全程不产生任何合成数据，所有数值与截图均可溯源到当次运行的 Spectre 输出。后端无 key、纯确定性；产品应用内由用户自配 API 的 agent 通过 `skill/` 工具库驱动全流程。

## 里程碑状态

| 里程碑 | 内容 | 状态 | 证据 |
|---|---|---|---|
| M1 | 固定 RC 电路端到端跑通 | ✅ | runs/vai_20261018_141418_21e24c15 |
| M2 | 可靠参数化（两组参数、完整周期、重复稳定、失败判定） | ✅ | [docs/M2_验收报告.md](docs/M2_验收报告.md) |
| M3 | 执行接口（TaskSpec → 任务 → Result 统一状态/日志/工件） | ✅ 后端侧达成（API v1.0 冻结 + skill 工具库；前端联调 B 侧） | contracts/ + skill/ |
| M4 | 题目到报告（读题→推导确认→执行→同次证据作答） | ✅ | [docs/M4_验收报告.md](docs/M4_验收报告.md) |
| M5 | 演示验收（回归 + 冻结） | 材料就绪 | [docs/M5_回归与冻结.md](docs/M5_回归与冻结.md)（v1.0.0） |

## 架构

```
产品应用（B 侧前端 + 用户自配 API 的 agent）        本地 Windows / 远程 Linux 服务器
┌──────────────────────────────┐   skill/     ┌─────────────────────────────────┐
│ 题目输入 → agent(SKILL.md)    │ ───────────▶ │ FastAPI (127.0.0.1:8765, 单worker)│
│  parse / derive / 确认 / 作答 │  vai_client  │  ├─ POST /runs → queued/running  │
└──────────────────────────────┘              │  └─ runs/<run_id>/ 持久化+工件索引 │
                                              │        │ SSH tar.gz + NDJSON 阶段流 │
                                              │        ▼                          │
                                              │ worker/run.py (Py2.6, 服务器执行)  │
                                              │  preflight(保护哈希)→build/probe   │
                                              │  →netlist(参数核对)→spectre→export │
                                              │  →capture(Xvfb 真实截图)           │
                                              │        │ 证据 tar 回传              │
                                              │        ▼                          │
                                              │ 本地校验 images/analysis(18项)    │
                                              │ →reporting report.html/md         │
                                              └─────────────────────────────────┘
```

13 个阶段（capabilities 端点可查）：`upload → preflight → build → probe → netlist → netlist_validation → spectre → export → capture → download → image_validation → validation → report`。

## 目录结构

```
vai_backend/
├── vai_backend/          # 本地服务包
│   ├── api.py            # FastAPI 应用（/health、/api/v1/*）
│   ├── manager.py        # RunManager：单 worker 队列、run.json 持久化、工件索引
│   ├── models.py         # TaskSpec / RunResult / Stage / Artifact (Pydantic 严格模型)
│   ├── pipeline.py       # SSH 上传/执行/证据回传 + 本地校验编排
│   ├── analysis.py       # 18 项确定性数值验收（fc、脉冲沿、精确 RC 递推等）
│   ├── images.py         # XWD 无损解码 + 截图画布彩色像素验证
│   ├── reporting.py      # HTML/Markdown 证据报告
│   ├── parsing.py        # 有界规则的题目文本解析（/api/v1/parse）
│   └── config.py         # Settings（环境变量）+ load_worker_config（VAI_CONFIG）
├── skill/                # ★ 应用内 agent 的工具库（用户自配 API 接入件）
│   ├── SKILL.md          # 硬性规则、五步工作流、设计规则、失败码处置
│   └── vai_client.py     # 纯标准库客户端 + derive_rc_from_cutoff + precheck_spec
├── worker/               # 远程执行器（Python 2.6 兼容）+ templates/*.il (SKILL)
├── contracts/            # task.schema.json / result.schema.json / openapi.json（v1.0 冻结）
├── examples/             # rc_1k / rc_m2_a / rc_m2_b / config_env_missing
├── tests/                # pytest：API 全链路(fixture)、图像验证、真实证据回归（19 项）
├── tools/                # m2_regression.py（M2/M5 回归）、m4_demo.py（M4 参考 agent）
├── docs/                 # FRONTEND_HANDOFF.md、M2/M4 验收报告、M5 冻结记录、汇总 JSON
├── runs/                 # 每次运行一个目录：run.json、evidence/、artifact_index.json
├── serve.py              # 服务入口（uvicorn）
├── run_task.py           # CLI 单任务入口
├── config.local.json     # 真实服务器配置（勿提交）
└── requirements*.txt
```

## 快速开始

```powershell
# 1) 虚拟环境（已就绪）
python -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt

# 2) 配置：config.local.json 指定 ssh_host、remote_base、virtuoso_bin、
#    spectre_bin、protected_files、stage/run 超时；参考 config.example.json

# 3) 启动服务（默认 127.0.0.1:8765）
.venv\Scripts\python serve.py
#    环境变量：VAI_PORT / VAI_HOST / VAI_API_TOKEN / VAI_RUNS_DIR / VAI_CORS_ORIGINS

# 4) agent / 工具库方式（产品应用内用户自配 API 的 agent 即这样接入）
.venv\Scripts\python -c "from skill import VaiClient; print(VaiClient().health())"
#    行为类题目全流程演示（自带后端线程，或 VAI_BASE 指向已运行服务）：
.venv\Scripts\python tools\m4_demo.py

# 5) 提交一个任务（原始 HTTP）
$body = Get-Content examples\rc_m2_a.json -Raw
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/api/v1/runs `
  -ContentType 'application/json' -Body $body
# 然后轮询 GET /api/v1/runs/{run_id} 至 succeeded/failed

# 6) CLI 单任务（不经 HTTP）
.venv\Scripts\python run_task.py examples\rc_m2_a.json

# 7) M2/M5 全量回归（前台单进程：服务线程 + 3 次真实运行 + 断言）
.venv\Scripts\python tools\m2_regression.py

# 8) 失败判定演示（环境缺失注入）
$env:VAI_CONFIG = "$PWD\examples\config_env_missing.json"
.venv\Scripts\python run_task.py examples\rc_m2_a.json --run-id vai_m2_envfail_probe

# 9) 测试
.venv\Scripts\python -m pytest tests -q
```

> 注意：在 TRAE/沙箱环境内请以**前台**方式运行以上命令——沙箱会阻止后台/服务进程在 `runs/` 下新建目录（WinError 5），前台进程不受影响。`tools/m2_regression.py`、`tools/m4_demo.py` 即为此设计（服务跑在同进程线程内）。

## HTTP API（v1.0，已冻结对接前端）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /health | 服务与队列状态（无需鉴权） |
| GET | /api/v1/capabilities | 模板、默认参数、工件清单、阶段列表、限额 |
| POST | /api/v1/parse | 题目文本 → TaskSpec 草案（requires_confirmation） |
| POST | /api/v1/runs | 提交 TaskSpec → 202 + RunResult（status=queued） |
| GET | /api/v1/runs | 运行列表（新→旧，limit ≤ 200） |
| GET | /api/v1/runs/{id} | 轮询至终态 queued/running/succeeded/failed |
| GET | /api/v1/runs/{id}/artifacts/{artifact_id} | 下载工件（带 SHA-256 索引；HTML 带 CSP sandbox） |

- 状态机固定：`queued → running → succeeded | failed`（失败含 `error.code/stage/message`，如 `ENVIRONMENT_MISSING`、`NETLIST_MISMATCH`、`SPECTRE_ERRORS`）。
- 队列上限 20，单 worker 串行；不支持并发写同一 cell（每次运行在远程独立 `db/<run_id>` 建图）。
- 鉴权：设置 `VAI_API_TOKEN` 后需 `Authorization: Bearer <token>`；CORS 白名单见 `VAI_CORS_ORIGINS`。
- 契约文件：`contracts/`（JSON Schema + OpenAPI）；对接说明：[docs/FRONTEND_HANDOFF.md](docs/FRONTEND_HANDOFF.md)；agent 工作流：[skill/SKILL.md](skill/SKILL.md)。

## TaskSpec 要点（models.py 强制校验）

- `r_ohm` 10–1e6，`c_f` 1e-12–1e-3；脉冲/AC/瞬态子模型各有物理约束。
- AC 范围必须覆盖理论截止频率两侧各 5 倍；瞬态必须覆盖 `delay + 2.05×period`（保证 ≥2 个完整脉冲周期）；`max_step_s ≤ min(τ/20, period/200, width/20)`；点数预算受限（AC ≤1500 点，瞬态 ≤60000 点）。
- 行为类题目（只给 fc）：agent 用 `skill.vai_client.derive_rc_from_cutoff()` 选 E24 标准值并 `precheck_spec()` 预检，经用户确认后提交。

## 安全与可溯源性

- **保护机制**：`protected_files`（课程 cds.lib、EElearn cell、历史基线）每次运行前后 SHA-256 对比，任何变化即判 `PROTECTED_FILE_CHANGED` 失败。
- **路径白名单**：SSH 主机与全部远程路径走严格正则校验；证据 tar 解包拒绝 `..`/软硬链接；工件下载经 `artifact_index.json` 二次寻址。
- **真实截图**：Xvfb 私有显示（:180–239 原子抢占）+ xauth + xwd 无损抓取 Cadence 窗口，另附 Cadence 原生导出图；`images.py` 校验画布彩色像素分布，杜绝空白/占位图。
- **零合成数据**：指标全部来自当次 Spectre 导出的数值文本；报告内嵌全部工件的 SHA-256。后端不持有也不请求任何用户的模型 API key。

## 测试与证据

- `pytest tests -q`：19 项（API 全链路、鉴权、CORS、重启恢复、路径安全、坏任务拒绝、图像验证、真实 M1 证据回归）。
- 运行证据目录 `runs/<run_id>/`：`run.json`（RunResult 持久化）、`evidence/`（stages.json、metrics.json、input.scs、spectre.out、截图、报告、protection.json 等）、`artifact_index.json`。
- M2 验收：[docs/M2_验收报告.md](docs/M2_验收报告.md) + [docs/m2_regression_summary.json](docs/m2_regression_summary.json)。
- M4 验收：[docs/M4_验收报告.md](docs/M4_验收报告.md) + [docs/m4_demo_summary.json](docs/m4_demo_summary.json)。
- M5 冻结：[docs/M5_回归与冻结.md](docs/M5_回归与冻结.md)（v1.0.0，契约与证据哈希）。
